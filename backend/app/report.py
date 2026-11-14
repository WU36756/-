"""Report composition, citation checks and safety review."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .citations import citation_numbers, verify_citations
from .triage import Triage

DISCLAIMER = (
    "**免责声明**：本报告由自动化系统汇总公开权威资料与平台策展的中成药知识库生成，"
    "仅供健康信息参考，不构成诊断、处方或用药建议。中成药与西药均须按说明书使用；"
    "任何用药决定、剂量调整或症状持续加重，请咨询医生或药师。"
)

FORBIDDEN = ("包治", "无需就医", "不用看医生", "我可以给你开药", "保证治愈")


@dataclass
class Review:
    passed: bool
    findings: list[str] = field(default_factory=list)


def combined_sources(tcm: list[dict[str, Any]], evidence: list[dict[str, Any]],
                    western: list[dict[str, Any]] | None = None,
                    lifestyle: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """TCM entries first, then retrieved evidence, in one numbering space."""
    sources: list[dict[str, Any]] = []
    for item in tcm:
        detail = (
            f"辨证方向：{item.get('pattern', '')}；"
            f"主治：{'、'.join(item.get('indications', []))}；"
            f"用法（按说明书）：{item.get('dosage', '')}；"
            f"禁忌：{item.get('contraindications', '')}；"
            f"注意：{item.get('cautions', '')}；"
            f"参考价：{item.get('price_range', '')}"
        )
        sources.append({
            "source": item.get("source", "药品说明书"),
            "title": f"{item.get('name', '中成药')}（{item.get('otc', 'OTC')}）说明书",
            "url": "",
            "snippet": detail,
            "retrieved_at": item.get("source_note", ""),
        })
    for item in western or []:
        detail = (
            f"适应症：{'、'.join(item.get('indications', []))}；"
            f"用法（按说明书）：{item.get('dosage', '')}；"
            f"禁忌：{item.get('contraindications', '')}；"
            f"注意：{item.get('cautions', '')}；参考价：{item.get('price_range', '')}"
        )
        sources.append({
            "source": item.get("source", "说明书"),
            "title": f"{item['name']}（OTC 西药）说明书",
            "url": "",
            "snippet": detail,
            "retrieved_at": item.get("source_note", ""),
        })
    sources.extend(evidence)
    for item in (lifestyle or {}).get("sources", []):
        sources.append({
            "source": "权威指南",
            "title": item["title"],
            "url": item["url"],
            "snippet": item["zh"],
            "retrieved_at": "",
        })
    return sources


def sources_block(sources: list[dict[str, Any]]) -> str:
    lines = ["## 来源", ""]
    for index, item in enumerate(sources, start=1):
        title = item.get("title") or item.get("url")
        if item.get("url"):
            lines.append(f"[{index}] {title} — {item.get('source')} ({item.get('retrieved_at')}) {item.get('url')}")
        else:
            lines.append(f"[{index}] {title} — {item.get('source')}（{item.get('retrieved_at')}）")
    return "\n".join(lines)


def emergency_report(symptoms: str, triage: Triage, provider: str) -> dict[str, Any]:
    reasons = "、".join(triage.reasons)
    markdown = "\n\n".join([
        "# 健康建议报告",
        "## ⚠️ 请立即就医",
        f"你描述的情况包含需要立即医疗评估的信号：**{reasons}**。",
        "请立刻联系急救或前往最近的急诊；不要自行用药掩盖症状，也不要在等待期间驾驶。",
        f"原始描述：{symptoms}",
        DISCLAIMER,
    ])
    return {
        "symptoms": symptoms,
        "triage": {"urgent": True, "reasons": triage.reasons, "sensitive": triage.sensitive,
                   "high_fever": triage.high_fever},
        "tcm": [],
        "evidence": [],
        "sources": [],
        "differentiation": None,
        "followups": [],
        "report_markdown": markdown,
        "review": {"passed": True, "findings": []},
        "provider": provider,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _tcm_lines(item: dict[str, Any], index: int) -> list[str]:
    return [
        f"- [{index}] **{item['name']}**（{item['otc']}，{item['form']}，{item['price_range']}，"
        f"辨证方向：{item['pattern']}）",
        f"  - 适用：{'、'.join(item['indications'])}"
        + (f"（匹配：{'、'.join(item['matched'])}）" if item.get("matched") else ""),
        f"  - 用法（按说明书）：{item['dosage']}（见来源 [{index}]）",
        f"  - 禁忌：{item['contraindications']}",
        f"  - 注意：{item['cautions']}",
    ]


def template_report(
    symptoms: str,
    triage: Triage,
    evidence: list[dict[str, Any]],
    tcm: list[dict[str, Any]],
    english_terms: list[str],
    differentiation: dict[str, Any] | None = None,
    followups: list[dict[str, Any]] | None = None,
    western: list[dict[str, Any]] | None = None,
    medications: list[dict[str, Any]] | None = None,
    med_warnings: list[str] | None = None,
    lifestyle: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
    profile_warnings: list[str] | None = None,
    memory_notes: list[dict[str, Any]] | None = None,
) -> str:
    western_entries = western or []
    meds = medications or []
    warnings = med_warnings or []
    sources = combined_sources(tcm, evidence, western_entries, lifestyle)
    index_of = {item.get("id"): position for position, item in enumerate(tcm, start=1)}
    lines = ["# 健康建议报告", "", "## 一、症状与分诊", f"- 原始描述：{symptoms}"]
    if not evidence:
        lines.append("- 说明：本次使用平台内置演示知识库匹配，未检索到外部文献；"
                     "具体用药请咨询药师或医生。")
    if triage.reasons:
        lines += [f"- 红旗信号：{r}" for r in triage.reasons]
    else:
        lines += ["- 未识别到急诊红旗症状；以下为一般信息，如症状加重请及时就医。"]
    if triage.high_fever:
        lines += ["- ⚠️ 高热：请先就医评估；不要自行叠加中成药与退热西药。"]
    if triage.sensitive:
        lines += [f"- 需要特别注意的人群：{s}，用药请先咨询医生或药师。" for s in triage.sensitive]

    if meds:
        lines += ["", "## 正在用药（来自用药提醒记录）", ""]
        for med in meds:
            lines.append(f"- {med.get('name', '')} {med.get('dose', '')}".strip())
        for warning in warnings:
            lines.append(f"- ⚠️ {warning}")
        lines += ["", "> 如需服用新的药物，请先核对成分是否重复，或咨询药师。"]

    from . import safety as safety_module

    profile_bits = safety_module.summary(profile)
    if profile_bits or profile_warnings:
        lines += ["", "## 个人情况与用药安全", ""]
        if profile_bits:
            lines.append("- " + "；".join(profile_bits))
        for warning in (profile_warnings or []):
            lines.append(f"- ⚠️ {warning}")
        lines.append("- 相互作用检查覆盖：内置常见组合 + openFDA 说明书（仅西药）；"
                     "中药组合未全面覆盖，拿不准请咨询药师。")

    if memory_notes:
        lines += ["", "## 既往记录（来自历史对话）", ""]
        for note in memory_notes:
            lines.append(f"- {note.get('symptoms', '')} → {note.get('summary', '')}")

    decision = (differentiation or {}).get("decision")
    ambiguous = decision == "ambiguous" and bool(tcm)
    if ambiguous:
        lines += ["", "## 二、辨证分支（目前还分不清风寒/风热）", "",
                  "> 现有描述不足以可靠判断偏风寒还是偏风热。下面按两种可能分别列出，"
                  "请对照自己的情况选择；仍不确定时先咨询药师，不要同时服用两类药。"]
        for tag, title in (("风寒", "若偏风寒（怕冷明显、清涕、白痰、不出汗）"),
                           ("风热", "若偏风热（咽痛明显、黄痰、口渴、容易出汗）")):
            group = [item for item in tcm if item.get("pattern_tag") == tag]
            lines += ["", f"### {title}", ""]
            if not group:
                lines += ["- 本次知识库没有匹配到该方向的常用中成药。"]
                continue
            for item in group:
                lines += _tcm_lines(item, index_of.get(item.get("id"), 1))
        if followups:
            lines += ["", "### 回答下面几个问题，可以帮助判断", ""]
            for question in followups:
                options = "；".join(question["options"].keys())
                lines.append(f"- {question['question']}（可选：{options}）")
    else:
        base_title = "首选中药（按症状匹配）" if (differentiation or {}).get("decision") == "not_applicable" else "首选中药（常见、便宜）"
        title = f"{base_title} · 共 {len(tcm)} 个（中成药 + 中药材）"
        if not sources:
            lines += ["", "**证据不足**：没有匹配到可用的中成药、西药或权威指南，请咨询医生或药师。"]
        lines += ["", f"## 二、{title}", ""]
        if tcm:
            for item in tcm:
                lines += _tcm_lines(item, index_of.get(item.get("id"), 1))
            lines += ["", "以上包含 OTC 中成药与中药材（饮片）；中药材请在药师指导下按药典剂量使用，"
                        "孕妇、儿童、慢病或正在服其他药者，请先咨询药师。"]
            if differentiation and differentiation.get("reason"):
                lines += [f"- 判断依据：{differentiation['reason']}（仅供参考，不作为诊断）。"]
        else:
            lines += ["- 平台知识库中没有与当前症状匹配的常用中成药，因此不推荐中药。"]
        if triage.high_fever:
            lines += ["- 高热时先就医评估，不建议自行使用中成药退热。"]
        if followups:
            lines += ["", "### 还需要确认", ""]
            for question in followups:
                options = "；".join(question["options"].keys())
                lines.append(f"- {question['question']}（可选：{options}）")

    western_pairs = [
        (len(tcm) + offset, item)
        for offset, item in enumerate(western_entries, start=1)
    ]
    if not western_pairs:
        western_pairs = [
            (len(tcm) + len(western_entries) + offset, item)
            for offset, item in enumerate(evidence, start=1)
            if item.get("source") == "openfda"
        ]
    western = western_pairs
    guides = [
        (len(tcm) + len(western_entries) + offset, item)
        for offset, item in enumerate(evidence, start=1)
        if any(host in (item.get("url") or "") for host in ("nhs.uk", "who.int", "cdc.gov"))
    ]
    decision = (differentiation or {}).get("decision")
    sections: list[tuple[str, list[str]]] = []
    if western or decision != "not_applicable":
        body: list[str] = []
        if western:
            for number, item in western:
                if "indications" in item:
                    body.append(
                        f"- [{number}] **{item['name']}**（{item['price_range']}）："
                        f"{'、'.join(item['indications'])}；用法（按说明书）：{item['dosage']}（见来源 [{number}]）；"
                        f"禁忌：{item['contraindications']}；注意：{item['cautions']}"
                    )
                else:
                    body.append(f"- [{number}] {item['title']}：{item['snippet'][:400]}")
            body += ["", "西药请按说明书剂量与禁忌使用；高热、持续发热或特殊人群先就医。"]
        else:
            body.append("- 本次检索没有取得可用的西药说明书信息。")
        sections.append(("备选西药（中药不适用或需要快速退热/止痛时）", body))
    if guides:
        sections.append(("权威指南要点", [f"- [{number}] **{item['title']}**：{item['snippet'][:320]}"
                                      for number, item in guides]))
    plan = lifestyle or {}
    if plan.get("diet") or plan.get("exercise"):
        base = len(tcm) + len(western_entries) + len(evidence)
        source_numbers = {item["key"]: base + index + 1
                          for index, item in enumerate(plan.get("sources", []))}
        diet_refs = "".join(f"[{source_numbers[key]}]" for key in plan.get("diet_sources", [])
                            if key in source_numbers)
        exercise_refs = "".join(f"[{source_numbers[key]}]" for key in plan.get("exercise_sources", [])
                                if key in source_numbers)
        diet_marker = f" [{diet_refs[1:-1].split('][')[0]}]" if diet_refs else ""
        exercise_marker = f" [{exercise_refs[1:-1].split('][')[0]}]" if exercise_refs else ""
        diet_body = [f"- {line}" for line in plan.get("diet", [])]
        if plan.get("notes"):
            diet_body += ["", "根据你的情况：" + "；".join(plan["notes"])]
        exercise_body = [f"- {line}" for line in plan.get("exercise", [])]
        if plan.get("avoid"):
            exercise_body += ["", "需要注意：" + "；".join(plan["avoid"])]
        sections.insert(0, ("膳食建议（按当前身体状况）", diet_body))
        sections.insert(1, ("恢复训练计划", exercise_body))

    sections.append(("何时就医", [
        "- 症状加重、出现胸痛/呼吸困难/意识改变等红旗症状时立即就医。",
        "- 高热（≥38.5℃）、发热超过 3 天、症状反复或出现新症状时就医。",
        "- 特殊人群（儿童、孕妇、哺乳期、慢病、肝肾功能异常）请先就医。",
    ]))
    for number, (title, body_lines) in zip(("三", "四", "五", "六", "七", "八", "九"), sections):
        lines += ["", f"## {number}、{title}", ""] + body_lines

    lines += ["", DISCLAIMER, "", sources_block(sources),
              "", "> 本回答由 AI 生成，内容仅供参考，请仔细甄别。"]
    return "\n".join(lines)


def review_report(
    markdown: str,
    evidence: list[dict[str, Any]],
    triage: Triage,
    tcm: list[dict[str, Any]] | None = None,
    differentiation: dict[str, Any] | None = None,
    western: list[dict[str, Any]] | None = None,
    lifestyle: dict[str, Any] | None = None,
) -> Review:
    tcm = tcm or []
    total = len(evidence) + len(tcm) + len(western or []) + len((lifestyle or {}).get("sources", []))
    findings: list[str] = []
    if "免责声明" not in markdown:
        findings.append("缺少免责声明")
    nums = citation_numbers(markdown)
    if total == 0:
        if nums:
            findings.append("没有来源却出现引用编号")
        if "证据不足" not in markdown:
            findings.append("无来源时未声明证据不足")
    else:
        if not nums:
            findings.append("有来源但正文没有任何 [n] 引用")
        missing = {n for n in nums if n < 1 or n > total}
        if missing:
            findings.append(f"引用了不存在的来源编号: {sorted(missing)}")
    if tcm and not any(item["name"] in markdown for item in tcm):
        findings.append("未引用知识库中的中成药")
    findings.extend(verify_citations(markdown, combined_sources(tcm, evidence, western, lifestyle)))
    if (differentiation or {}).get("decision") == "ambiguous" and tcm:
        if "风寒" not in markdown or "风热" not in markdown:
            findings.append("辨证不明确时未做风寒/风热分类讨论")
    if triage.urgent and not any(word in markdown for word in ("立即就医", "急诊", "急救")):
        findings.append("红旗症状下未给出立即就医指引")
    if triage.high_fever and "就医" not in markdown:
        findings.append("高热情况下未提示就医")
    for word in FORBIDDEN:
        if word in markdown:
            findings.append(f"出现越界措辞: {word}")
    for match in re.finditer("确诊为", markdown):
        prefix = markdown[max(0, match.start() - 4):match.start()]
        if not any(word in prefix for word in ("不能", "无法", "不可", "未", "别")):
            findings.append("出现越界措辞: 确诊为")
            break
    in_med_section = False
    for line in markdown.splitlines():
        if line.startswith("## "):
            in_med_section = "正在用药" in line
            continue
        if in_med_section:
            continue
        stripped = line.strip()
        if stripped.startswith(("- 用法（按说明书）", "- 用法（照说明书）")):
            continue  # 知识库条目自带剂量与来源
        if "用法用量" in stripped or "用法（按说明书）" in stripped or "用法（照说明书）" in stripped:
            continue  # 表格里的用法行同样来自说明书条目
        if stripped.startswith("|") and "用法" in stripped:
            continue  # Markdown 表格的用法行
        drug_context = any(word in line for word in
                           ("剂量", "服药", "用药", "口服", "每次", "一日", "片", "粒", "袋"))
        mass_dose = re.search(r"\d+\s*(mg|毫克|μg|微克)\b", line, re.IGNORECASE)
        gram_dose = re.search(r"\d+\s*g\b", line, re.IGNORECASE) and drug_context
        if (mass_dose or gram_dose) and "[" not in line:
            findings.append(f"剂量信息缺少引用: {stripped[:60]}")
    return Review(passed=not findings, findings=findings)
