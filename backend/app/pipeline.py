"""M1 pipeline: triage → differentiation → TCM branches → evidence → report → review.

Every stage records a trace entry so the web panel can show what the agents did.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from .config import settings
from .differentiation import differentiate, format_questions, is_respiratory
from .llm import LLMClient, LLMUnavailable, parse_json_object
from .report import Review, combined_sources, emergency_report, review_report, template_report
from . import cache
from .sources import DEMO_DRUG_HINTS, english_terms, guide_pages
from .tcm import by_pattern, recommend, search_tcm
from .symptoms import DOMAINS, detect as detect_domains
from .symptoms import followups_for
from . import safety
from .western import for_terms as western_for_terms
from .lifestyle import select as lifestyle_select
from .personalize import apply as personalize_lifestyle
from .tools import TOOLS, fetch_url, openfda_label_search, pubmed_search
from .triage import triage as run_triage

AGENT_SYSTEM = """You are a medical evidence retrieval agent. Gather authoritative evidence for the
patient's symptoms. Budget: AT MOST 3 tool calls in total.
1) Call tcm_search once with the patient's Chinese symptom text (the platform prefers cheap OTC TCM).
2) Call pubmed_search at most twice with SHORT ENGLISH keywords (guidelines/reviews first).
3) Optionally call openfda_label_search once for an OTC western drug, or fetch_url once for a known
   NHS/WHO/CDC page. Do not repeat a search that already returned results.
Respond with ONLY a compact JSON object, either:
  {"action": "call_tool", "tool": "tcm_search", "arguments": {"symptoms": "发烧头痛"}}
or when you have enough evidence:
  {"action": "final"}
Do not write explanations outside the JSON."""

COMPOSE_SYSTEM = """You are a careful health-information writer. Write a Chinese Markdown report for a
layperson using ONLY the numbered sources provided. Rules:
- Prefer TCM: if the numbered sources include OTC Chinese patent medicines that fit the symptoms,
  recommend the cheapest and most common one(s) first, with pattern (辨证), usage per the package
  insert, contraindications, cautions and price range. Never invent a TCM product or dose.
- If the sources contain BOTH wind-cold (风寒) and wind-heat (风热) medicines and you cannot decide
  which pattern fits, do NOT pick one: present two branches ("若偏风寒…", "若偏风热…") and list the
  follow-up questions that would distinguish them.
- Western medicine is a fallback: use it only when TCM does not fit, or when the patient needs fast
  fever/pain relief. Include indications, key warnings and the official dosage text, with citations.
- If the patient reports high fever, say to seek medical assessment first and do not stack drugs.
- Cite every factual claim with its source number like [1]. Include a section "何时就医" with red-flag
  guidance and a short limitation note. Never diagnose, never prescribe.\n- 用户可能用口语、方言、比喻或错别字（如"脑袋要炸""嗓子像吞刀片""拉不出""腰像断了"）。先按最接近的常见症状理解并给出建议，不要因说法不标准而拒答；拿不准时给出 1–3 个追问，不要编造。
"""


def _timed(trace: list[dict[str, Any]], tool: str, arguments: dict[str, Any], fn: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    started = time.monotonic()
    try:
        result = fn()
    except Exception as error:  # noqa: BLE001 - degrade, never crash the report
        trace.append({
            "step": "tool", "tool": tool, "arguments": arguments, "status": "error",
            "error": str(error)[:140], "ms": int((time.monotonic() - started) * 1000),
        })
        return []
    trace.append({
        "step": "tool", "tool": tool, "arguments": arguments, "status": "ok",
        "count": len(result), "ms": int((time.monotonic() - started) * 1000),
    })
    return result


def mock_evidence(symptoms: str, trace: list[dict[str, Any]], sequential: bool = False,
                  prefer_cache: bool = False) -> list[dict[str, Any]]:
    """Parallel demo retrieval with an offline cache fallback."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if prefer_cache:
        cached = cache.load(symptoms)
        trace.append({"step": "cache", "status": "prefer", "count": len(cached or [])})
        return cached or []

    if cache.offline_only():
        cached = cache.load(symptoms)
        trace.append({"step": "cache", "status": "offline", "count": len(cached or [])})
        return cached or []

    terms = english_terms(symptoms)
    tasks: list[tuple[str, dict[str, Any], Callable[[], list[dict[str, Any]]]]] = []
    for term in terms[:2]:
        tasks.append(("pubmed_search", {"term": term}, lambda t=term: pubmed_search(t, retmax=2, timeout=10)))
        drug = DEMO_DRUG_HINTS.get(term)
        if drug:
            tasks.append(("openfda_label_search", {"drug": drug}, lambda d=drug: openfda_label_search(d, limit=1, timeout=10)))
    for url in guide_pages(symptoms):
        tasks.append(("fetch_url", {"url": url}, lambda u=url: fetch_url(u, timeout=15)))

    evidence: list[dict[str, Any]] = []
    if tasks:
        detail = (f"{len(tasks)} 个检索顺序执行" if sequential
                  else f"{len(tasks)} 个检索并行执行")
        trace.append({"step": "parallel", "detail": detail,
                      "tasks": [item[0] for item in tasks]})
        if sequential:
            for name, args, fn in tasks:
                evidence.extend(_timed(trace, name, args, fn))
        else:
            with ThreadPoolExecutor(max_workers=min(4, len(tasks))) as pool:
                futures = [pool.submit(_timed, trace, name, args, fn) for name, args, fn in tasks]
                for future in as_completed(futures):
                    try:
                        evidence.extend(future.result())
                    except Exception:  # noqa: BLE001 - degrade
                        pass

    if evidence:
        cache.save(symptoms, evidence)
        trace.append({"step": "cache", "status": "saved", "count": len(evidence)})
        return evidence

    cached = cache.load(symptoms)
    trace.append({"step": "cache", "status": "fallback" if cached else "miss", "count": len(cached or [])})
    return cached or []


def agent_evidence(symptoms: str, client: LLMClient, trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": f"症状：{symptoms}\n可用工具：{json.dumps({k: v['description'] for k, v in TOOLS.items()}, ensure_ascii=False)}"},
    ]
    evidence: list[dict[str, Any]] = []
    tool_calls = 0
    for _ in range(settings.max_tool_steps):
        reply = client.chat(messages)
        try:
            action = parse_json_object(reply)
        except ValueError:
            trace.append({"step": "agent", "status": "stopped", "detail": "unparseable model reply"})
            break
        if action.get("action") != "call_tool":
            trace.append({"step": "agent", "status": "final", "detail": "model decided it has enough evidence"})
            break
        name = action.get("tool")
        arguments = action.get("arguments") or {}
        tool_calls += 1
        if tool_calls > settings.max_tool_steps:
            break
        from .tools import run_tool
        started = time.monotonic()
        observation = run_tool(name, arguments)
        try:
            parsed = json.loads(observation)
        except json.JSONDecodeError:
            parsed = None
        count = len(parsed) if isinstance(parsed, list) else (0 if isinstance(parsed, dict) and "error" in parsed else 1)
        trace.append({
            "step": "tool", "tool": name, "arguments": arguments,
            "status": "ok" if count else "empty", "count": count,
            "ms": int((time.monotonic() - started) * 1000),
        })
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": f"观测结果：{observation[:1200]}"})
        if name == "tcm_search":
            continue
        if isinstance(parsed, list):
            evidence.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict) and "error" not in parsed:
            evidence.append(parsed)
    return evidence


def _numbered_sources(sources: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{index}] {item.get('title')}：{(str(item.get('snippet') or item.get('url') or ''))[:700]}"
        for index, item in enumerate(sources, start=1)
    )


def _ensure_disclaimer(markdown: str) -> str:
    if "免责声明" in markdown or "仅供参考" in markdown:
        return markdown
    return markdown.rstrip() + (
        "\n\n**免责声明**：以上信息仅供参考，不能替代医生诊断；"
        "症状加重或出现危险信号请及时就医。\n")


def compose(symptoms: str, evidence: list[dict[str, Any]], tcm: list[dict[str, Any]],
            client: LLMClient, differentiation: dict[str, Any] | None = None,
            western: list[dict[str, Any]] | None = None,
            lifestyle: dict[str, Any] | None = None,
            profile: dict[str, Any] | None = None,
            medications: list[dict[str, Any]] | None = None) -> str:
    sources = combined_sources(tcm, [item for item in evidence if isinstance(item, dict)], western)[:10]
    followups = (differentiation or {}).get("followups") or []
    extra = ""
    plan = lifestyle or {}
    if plan.get("diet"):
        extra += "\n膳食与运动建议（来自平台指南库，请写入报告）：\n- 膳食：" + "；".join(plan["diet"][:4]) + "\n- 运动：" + "；".join(plan.get("exercise", [])[:3]) + "\n"
    profile_bits = safety.summary(profile)
    if profile_bits:
        extra += "\n患者情况：" + "；".join(profile_bits) + "。请据此调整建议。\n"
    if medications:
        med_lines = "；".join(f"{m.get('name')} {m.get('dose', '')}".strip() for m in medications)
        extra += f"\n患者正在服用（用药记录）：{med_lines}。请考虑成分重复，不要推荐叠加使用。\n"
    if (differentiation or {}).get("decision") == "ambiguous":
        extra = (
            "\n注意：症状还分不清风寒与风热，请分两支讨论，不要只推荐一支；"
            "并在报告中列出以下追问问题：\n" + format_questions(followups)
        )
    return client.chat([
        {"role": "system", "content": COMPOSE_SYSTEM},
        {"role": "user", "content": f"症状：{symptoms}{extra}\n编号来源：\n{_numbered_sources(sources)[:14000]}"},
    ])


def _select_tcm(symptoms: str, differentiation: dict[str, Any], high_fever: bool) -> list[dict[str, Any]]:
    decision = differentiation.get("decision", "ambiguous")
    tags = differentiation.get("tags") or []
    domains = detect_domains(symptoms)
    if decision in ("cold", "heat"):
        return recommend(symptoms, decision, tag=tags[0] if tags else "风寒",
                         high_fever=high_fever, domains=domains)
    return recommend(symptoms, decision, high_fever=high_fever, domains=domains)


def _tcm_public(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {k: item.get(k) for k in ("id", "kind", "name", "otc", "form", "pattern", "pattern_tag",
                                  "price_range", "dosage", "contraindications", "cautions", "matched")}
        for item in items
    ]



def _med_warnings(medications: list[dict[str, Any]] | None,
                  western: list[dict[str, Any]],
                  tcm: list[dict[str, Any]]) -> list[str]:
    """Flag duplicate ingredients between the user's medication log and this advice."""
    warnings: list[str] = []
    meds = medications or []
    for med in meds:
        name = str(med.get("name") or "")
        for item in western:
            other = str(item.get("name") or "")
            if name and other and (name in other or other in name):
                if name == other:
                    warnings.append(f"你正在服用 {name}，请勿重复服用")
                else:
                    warnings.append(f"你正在服用 {name}，不要与 {other} 叠加（成分重复）")
        for item in tcm:
            other = str(item.get("name") or "")
            if name and other and (name in other or other in name):
                warnings.append(f"{other} 已在用药记录中，请勿重复服用")
    if any(("复方" in str(m.get("name")) or "感冒" in str(m.get("name"))) for m in meds):
        if any("对乙酰氨基酚" in str(item.get("name")) for item in western):
            warnings.append("正在服用复方感冒药时不要叠加对乙酰氨基酚，避免过量伤肝")
    return list(dict.fromkeys(warnings))


TERM_ZH = {
    "cough": "咳嗽", "fever": "发热", "sore throat": "咽痛", "headache": "头痛",
    "insomnia": "失眠", "constipation": "便秘", "diarrhea": "腹泻", "nausea": "恶心",
    "heartburn": "反酸烧心", "allergic rhinitis": "过敏性鼻炎", "acne": "痤疮",
    "hives": "荨麻疹", "neck pain": "颈肩痛", "back pain": "腰痛", "dry eyes": "眼睛干",
    "toothache": "牙痛", "motion sickness": "晕车", "menopause": "更年期",
    "tinnitus": "耳鸣", "bad breath": "口臭", "piles": "痔疮", "eczema": "湿疹",
    "itching": "瘙痒", "dysmenorrhea": "痛经", "bloating": "腹胀", "sore-throat": "咽痛",
}
DRUG_ZH = {
    "acetaminophen": "对乙酰氨基酚", "paracetamol": "对乙酰氨基酚", "ibuprofen": "布洛芬",
    "dextromethorphan": "右美沙芬", "guaifenesin": "愈创甘油醚", "pseudoephedrine": "伪麻黄碱",
    "loratadine": "氯雷他定", "cetirizine": "西替利嗪", "omeprazole": "奥美拉唑",
    "simethicone": "西甲硅油", "loperamide": "洛哌丁胺", "diosmectite": "蒙脱石散",
    "lactulose": "乳果糖", "minoxidil": "米诺地尔", "terbinafine": "特比萘芬",
    "diclofenac": "双氯芬酸", "chlorhexidine": "氯己定", "oryzanol": "谷维素",
    "dimenhydrinate": "茶苯海明", "hydrotalcite": "铝碳酸镁", "domperidone": "多潘立酮",
    "ambroxol": "氨溴索", "benzoyl peroxide": "过氧化苯甲酰", "hydrocortisone": "氢化可的松",
    "calamine": "炉甘石", "hyaluronate": "玻璃酸钠", "camphor": "樟脑",
}


def _readable_url(url: str) -> str:
    from urllib.parse import urlparse

    hosts = {"www.nhs.uk": "NHS", "nhs.uk": "NHS", "www.who.int": "WHO", "who.int": "WHO",
             "www.cdc.gov": "CDC", "cdc.gov": "CDC"}
    parsed = urlparse(url or "")
    host = hosts.get(parsed.netloc, parsed.netloc or "网页")
    slug = parsed.path.rstrip("/").split("/")[-1] if parsed.path else ""
    name = TERM_ZH.get(slug, slug.replace("-", " "))
    return f"{host} 的「{name}」页面" if name else f"{host} 页面"


def _enrich_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn pipeline events into plain-Chinese descriptions of who did what."""
    labels = {
        "triage": ("分诊 Agent", "先看有没有危险信号"),
        "differentiate": ("辨证 Agent", "判断是风寒还是风热"),
        "tcm_kb": ("中药知识库 Agent", "从知识库挑药"),
        "parallel": ("检索 Agent ×3", "同时去查资料"),
        "tool": ("检索 Agent", "查资料"),
        "agent": ("调度 Agent", "决定下一步"),
        "compose": ("报告撰写 Agent", "写报告"),
        "review": ("安全审查 Agent", "检查报告"),
        "repair": ("报告撰写 Agent", "按意见重写"),
        "fallback": ("安全审查 Agent", "改用模板"),
        "cache": ("检索 Agent", "保存证据"),
    }
    enriched = []
    for step in trace:
        kind = step.get("step", "step")
        agent, title = labels.get(kind, ("系统", kind))
        item = dict(step)
        item["agent"] = agent
        item["title"] = title
        ms = step.get("ms")
        seconds = f"，用时 {ms / 1000:.1f} 秒" if isinstance(ms, (int, float)) and ms else ""
        if kind == "triage":
            item["title"] = "先看有没有危险信号"
            item["summary"] = ("发现危险信号：" + "、".join(step.get("reasons") or [])) if step.get("reasons") else "没发现需要立即就医的危险信号"
        elif kind == "differentiate":
            decision = step.get("decision")
            item["title"] = "判断是风寒还是风热"
            item["summary"] = {
                "cold": "判断偏风寒",
                "heat": "判断偏风热",
                "ambiguous": "暂时分不清，按两种可能分别准备",
                "not_applicable": "这不是感冒类症状，跳过风寒/风热判断",
            }.get(decision, str(decision))
        elif kind == "tcm_kb":
            names = step.get("names") or []
            item["title"] = "从知识库挑出可用的药"
            item["summary"] = f"挑了 {len(names)} 个：{'、'.join(names[:6])}{'…' if len(names) > 6 else ''}"
        elif kind == "parallel":
            item["title"] = "同时去查资料"
            item["summary"] = "分三路同时查：医学文献、药品说明书、权威机构指南"
        elif kind == "tool":
            tool = step.get("tool")
            args = step.get("arguments") or {}
            count = step.get("count", 0)
            empty = "这次没取到内容（可能网络超时或页面无匹配）"
            if tool == "pubmed_search":
                term = args.get("term") or args.get("query") or "相关主题"
                term = TERM_ZH.get(str(term).lower(), term)
                item["title"] = "查医学文献"
                item["summary"] = (f"在 PubMed 搜「{term}」，拿到 {count} 条结果{seconds}"
                                   if count else f"在 PubMed 搜「{term}」，{empty}{seconds}")
            elif tool == "openfda_label_search":
                name = args.get("drug") or args.get("name") or "药品"
                name = DRUG_ZH.get(str(name).lower(), name)
                item["title"] = "查药品说明书"
                item["summary"] = (f"查 openFDA 上「{name}」的说明书，拿到 {count} 条{seconds}"
                                   if count else f"查 openFDA 上「{name}」的说明书，{empty}{seconds}")
            elif tool == "fetch_url":
                url = args.get("url") or ""
                item["title"] = "查权威机构指南"
                item["summary"] = (f"打开 {_readable_url(url)}，拿到 {count} 条{seconds}"
                                   if count else f"打开 {_readable_url(url)}，{empty}{seconds}")
            else:
                item["title"] = "查资料"
                item["summary"] = f"拿到 {count} 条结果{seconds}"
        elif kind == "agent":
            item["title"] = "决定下一步查什么"
            item["summary"] = {"start": "模型开始自己决定要查哪些资料",
                               "final": "模型认为资料够了，结束检索",
                               "stopped": "模型输出无法解析，改为固定流程"}.get(step.get("status"), str(step.get("status")))
        elif kind == "compose":
            item["title"] = "写出报告"
            item["summary"] = f"写出约 {step.get('chars', 0)} 字的报告（{step.get('provider')} 模型）"
        elif kind == "review":
            findings = step.get("findings") or []
            item["title"] = "检查报告是否安全、有依据"
            item["summary"] = "检查通过" if step.get("passed") else "没通过：" + "；".join(findings[:2])
        elif kind == "repair":
            item["title"] = "按审查意见重写"
            item["summary"] = f"第 {step.get('attempt', 1)} 轮重写"
        elif kind == "fallback":
            item["title"] = "改用模板写报告"
            item["summary"] = "审查没通过，改用固定模板生成，保证有来源和免责声明"
        elif kind == "cache":
            item["title"] = "把证据存起来"
            item["summary"] = f"保存 {step.get('count', 0)} 条证据，下次可以直接复用"
        enriched.append(item)
    return enriched


def analyze(
    symptoms: str,
    provider: str | None = None,
    api_key: str | None = None,
    answers: dict[str, str] | None = None,
    medications: list[dict[str, Any]] | None = None,
    skip_review: bool = False,
    skip_kb: bool = False,
    sequential: bool = False,
    profile: dict[str, Any] | None = None,
    memory_notes: list[dict[str, Any]] | None = None,
    api_base: str | None = None,
    api_model: str | None = None,
    api_models: list[str] | None = None,
    api_format: str = "openai",
    is_followup: bool = False,
) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    triage = run_triage(symptoms)
    trace.append({"step": "triage", "urgent": triage.urgent, "reasons": triage.reasons,
                  "sensitive": triage.sensitive, "high_fever": triage.high_fever})
    client = LLMClient(provider=provider, api_key=api_key, base_url=api_base,
                       model=api_model, models=api_models, api_format=api_format)
    if triage.urgent:
        return emergency_report(symptoms, triage, client.provider) | {"trace": _enrich_trace(trace)}

    if is_respiratory(symptoms):
        differentiation = differentiate(symptoms, answers)
    else:
        followups = followups_for(symptoms)
        differentiation = {"decision": "not_applicable", "scores": {"cold": 0, "heat": 0},
                           "tags": [], "followups": followups, "reason": None}
    if "pediatrics" in detect_domains(symptoms):
        child_questions = DOMAINS["pediatrics"]["followups"]
        child_ids = {question["id"] for question in child_questions}
        existing = [question for question in (differentiation.get("followups") or [])
                    if question.get("id") not in child_ids]
        differentiation["followups"] = (child_questions + existing)[:5]
    answered_ids = set((answers or {}).keys())
    differentiation["followups"] = [
        question for question in (differentiation.get("followups") or [])
        if question.get("id") not in answered_ids
    ]
    if is_followup and not answers:
        differentiation["followups"] = []
    followups = differentiation["followups"]
    trace.append({"step": "differentiate", "decision": differentiation["decision"],
                  "scores": differentiation["scores"], "reason": differentiation.get("reason")})
    tcm = [] if skip_kb else _select_tcm(symptoms, differentiation, triage.high_fever)
    western = ([] if (triage.high_fever or skip_kb)
               else western_for_terms(english_terms(symptoms)))
    med_warnings = _med_warnings(medications, western, tcm)
    checked = safety.apply(profile, tcm, western, medications)
    tcm, western = checked["tcm"], checked["western"]
    profile_warnings = checked["warnings"]
    if any(word in symptoms for word in ("血压高", "高压高", "低压高", "高血压")):
        warning = ("血压相关：先安静休息后测量血压；若 ≥180/120 mmHg，或伴胸痛、"
                   "剧烈头痛、视物模糊、肢体无力，请立即就医。")
        if warning not in profile_warnings:
            profile_warnings.append(warning)
    if any("儿童" in group or "婴幼儿" in group for group in triage.sensitive):
        warning = "儿童/婴幼儿：用药剂量需按年龄/体重，建议先咨询儿科医生或药师"
        if warning not in profile_warnings:
            profile_warnings.append(warning)
    lifestyle = personalize_lifestyle(lifestyle_select(symptoms, triage),
                                         profile, medications, triage)
    trace.append({"step": "tcm_kb", "candidates": len(tcm), "names": [item["name"] for item in tcm]})
    followups = differentiation.get("followups") or []

    def _review(*args, **kwargs):
        if skip_review:
            return Review(passed=True, findings=[])
        return review_report(*args, **kwargs)

    provider_used = client.provider if client.live else "mock"
    fallback_reason = None
    if client.live:
        try:
            trace.append({"step": "agent", "status": "start", "detail": "model-driven tool selection"})
            try:
                evidence = agent_evidence(symptoms, client, trace)
            except LLMUnavailable as agent_error:
                evidence = mock_evidence(symptoms, trace, sequential=sequential, prefer_cache=True)
                trace.append({"step": "agent", "status": "fallback",
                              "detail": f"tool-selection failed, using mock evidence: {agent_error}"})
            markdown = _ensure_disclaimer(compose(
                symptoms, evidence, tcm, client, differentiation, western, lifestyle,
                profile=profile, medications=medications))
            trace.append({"step": "compose", "provider": client.provider, "chars": len(markdown)})
            review = _review(markdown, evidence, triage, tcm, differentiation, western, lifestyle)
            trace.append({"step": "review", "passed": review.passed, "findings": review.findings})
            if not review.passed:
                sources = combined_sources(tcm, evidence, western, lifestyle)[:10]
                repair = client.chat([
                    {"role": "system", "content": COMPOSE_SYSTEM},
                    {"role": "user", "content": (
                        f"症状：{symptoms}\n编号来源：\n{_numbered_sources(sources)[:14000]}\n"
                        f"上一次报告未通过安全审查，问题：{review.findings}。请修正后重新输出完整报告。"
                    )},
                ])
                trace.append({"step": "repair", "attempt": 1})
                repair = _ensure_disclaimer(repair)
                review = _review(repair, evidence, triage, tcm, differentiation, western, lifestyle)
                trace.append({"step": "review", "passed": review.passed, "findings": review.findings})
                markdown = repair
            if not review.passed:
                try:
                    from pathlib import Path as _Path
                    _Path("out").mkdir(exist_ok=True)
                    _Path("out/review-failed.md").write_text(markdown, encoding="utf-8")
                except OSError:
                    pass
                provider_used = "mock-fallback"
                fallback_reason = f"review failed: {review.findings}"
                markdown = template_report(symptoms, triage, evidence, tcm, english_terms(symptoms),
                                           differentiation, followups, western, medications, med_warnings,
                                           lifestyle, profile, profile_warnings, memory_notes)
                review = _review(markdown, evidence, triage, tcm, differentiation, western, lifestyle)
                trace.append({"step": "fallback", "reason": fallback_reason})
        except LLMUnavailable as error:
            provider_used = "mock-fallback"
            fallback_reason = f"model unavailable: {error}"
            evidence = mock_evidence(symptoms, trace, sequential=sequential)
            markdown = template_report(symptoms, triage, evidence, tcm, english_terms(symptoms),
                                       differentiation, followups)
            review = _review(markdown, evidence, triage, tcm, differentiation, western, lifestyle)
            trace.append({"step": "fallback", "reason": fallback_reason})
    else:
        evidence = mock_evidence(symptoms, trace, sequential=sequential)
        markdown = template_report(symptoms, triage, evidence, tcm, english_terms(symptoms),
                                   differentiation, followups, western, medications, med_warnings,
                                           lifestyle, profile, profile_warnings, memory_notes)
        review = _review(markdown, evidence, triage, tcm, differentiation, western, lifestyle)
        trace.append({"step": "review", "passed": review.passed, "findings": review.findings})

    return {
        "symptoms": symptoms,
        "answers": answers or {},
        "triage": {"urgent": triage.urgent, "reasons": triage.reasons,
                   "sensitive": triage.sensitive, "high_fever": triage.high_fever},
        "differentiation": {
            "decision": differentiation.get("decision"),
            "scores": differentiation.get("scores"),
            "reason": differentiation.get("reason"),
        },
        "followups": [
            {"id": q["id"], "question": q["question"], "options": list(q["options"].keys())}
            for q in followups
        ],
        "tcm": _tcm_public(tcm),
        "evidence": evidence,
        "western": western,
        "medications": medications or [],
        "med_warnings": med_warnings,
        "profile": profile or {},
        "safety_warnings": profile_warnings,
        "safety_coverage": checked.get("coverage", ""),
        "memory_notes": memory_notes or [],
        "lifestyle": lifestyle,
        "sources": combined_sources(tcm, evidence, western, lifestyle),
        "report_markdown": markdown,
        "review": {"passed": review.passed, "findings": review.findings},
        "provider": provider_used,
        "fallback_reason": fallback_reason,
        "trace": _enrich_trace(trace),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
