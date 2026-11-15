"""FastAPI surface for the health agent platform (M1)."""

from __future__ import annotations

import json
import os

import httpx
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import ipaddress
import socket
import threading
import time
from urllib.parse import urlparse
from collections import defaultdict, deque

from . import cabinet, cache, chat_mode, chitchat, conversations, crisis, db, demo_reset, food, language, memory, meds, notify, plan, profile as profile_store, psych, push as push_store, resp_cache, router, sessions
from .config import settings
from .llm import LLMClient
from .meta import describe
from .pipeline import analyze

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

meds.init()
conversations.init()
profile_store.init()
memory.init()
plan.init()
notify.init()
notify.start()
cabinet.init()
resp_cache.init()
push_store.init()


def _migrate_user_databases() -> None:
    """Old browser spaces can predate columns added to the shared schema."""
    from . import db
    for db_file in sorted(db.USERS_DIR.glob("*.db")):
        token = db.CURRENT_USER.set(db_file.stem)
        try:
            profile_store.init()
            meds.init()
            plan.init()
            conversations.init()
            memory.init()
            notify.init()
            cabinet.init()
            resp_cache.init()
            push_store.init()
        except Exception:
            # One stale/corrupt user database must not stop the whole service.
            import logging
            logging.getLogger("health-agent").exception(
                "user database migration failed: %s", db_file.name)
        finally:
            db.CURRENT_USER.reset(token)


_migrate_user_databases()


app = FastAPI(title="Health Agent Platform", version="0.1.0")

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


class AnalyzeRequest(BaseModel):
    force_intent: str | None = Field(default=None, pattern="^(medical|psych|food|chitchat)$")
    api_base: str | None = Field(default=None, max_length=300)
    api_model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=300)
    api_models: list[str] | None = None
    api_format: str = Field(default="openai", pattern="^(openai|anthropic)$")
    specialist: str | None = Field(default=None, pattern="^(medical|psych|food)$")
    fresh_context: bool = False
    symptoms: str = Field(min_length=1, max_length=2000)
    answers: dict[str, str] | None = None
    provider: str | None = Field(default=None, pattern="^(mock|deepseek|custom)$")
    chat_mode: bool = False
    symptom_choice: str | None = Field(default=None, pattern="^(still|resolved)$")
    previous_symptoms: str | None = Field(default=None, max_length=2000)
    current_symptoms: str | None = Field(default=None, max_length=2000)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.post("/api/demo/reset")
def demo_reset_endpoint() -> dict:
    if not settings.demo_reset_enabled:
        raise HTTPException(status_code=403, detail="演示数据重置已在服务器上关闭")
    result = demo_reset.reset(seed=True)
    resp_cache.clear()
    return result


_RATE_LIMIT: dict[str, deque] = defaultdict(deque)
_ANALYZE_SLOTS = threading.BoundedSemaphore(max(1, settings.max_concurrent_analyses))


def _validate_custom_base(base: str) -> None:
    """Block obvious SSRF targets unless the operator explicitly allows local models."""
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=400, detail="API 地址必须是 http(s) URL")
    if settings.allow_private_custom:
        return
    host = parsed.hostname.lower()
    if host in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="不允许使用本机地址")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as error:
        raise HTTPException(status_code=400, detail=f"无法解析 API 域名：{host}") from error
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_reserved or address.is_multicast or address.is_unspecified):
            raise HTTPException(status_code=400, detail="不允许访问内网/本机地址")


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    path = request.url.path
    sid = None
    context_token = None
    if settings.access_code:
        sid = sessions.verify(request.cookies.get(sessions.COOKIE))
        public = (path.startswith("/static") or path in
                  ("/api/login", "/api/health", "/favicon.ico"))
        if sid is None:
            if path in ("/", "/login"):
                return HTMLResponse(LOGIN_HTML)
            if not public:
                return JSONResponse(status_code=401, content={"detail": "请先输入访问码"})
    if request.method == "POST":
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        limit = 1024 * 1024
        if length > limit:
            return JSONResponse(status_code=413, content={"detail": "请求体过大"})
    if request.method == "POST" and (
            path.startswith("/api/custom") or path.startswith("/api/conversations")
            or path in ("/api/analyze", "/api/login")):
        ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for", "")
        if ip in ("127.0.0.1", "::1") and forwarded:
            ip = forwarded.split(",")[0].strip() or ip
        now = time.monotonic()
        # Judges often share one venue NAT address; authenticated traffic is
        # counted per browser session so one judge cannot exhaust everyone.
        bucket = f"user:{sid}" if sid and path != "/api/login" else f"ip:{ip}"
        window = _RATE_LIMIT[bucket]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.rate_limit_per_minute:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
        window.append(now)
    if sid:
        sessions.ensure(sid)
        context_token = db.CURRENT_USER.set(sid)
    try:
        response = await call_next(request)
    finally:
        if context_token is not None:
            db.CURRENT_USER.reset(context_token)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


LOGIN_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>健康助手 · 访问码</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f6f7f9;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#0f172a}
.card{width:min(400px,88vw);background:#fff;border:1px solid #e2e8f0;border-radius:18px;
padding:28px;box-shadow:0 20px 60px rgba(15,23,42,.08)}
h1{font-size:20px;margin:0 0 6px}p{font-size:13px;color:#64748b;line-height:1.6;margin:0 0 16px}
input{width:100%;box-sizing:border-box;border:1px solid #e2e8f0;border-radius:10px;
padding:11px 12px;font-size:15px;font-family:inherit}
button{width:100%;margin-top:12px;border:0;border-radius:10px;padding:11px;background:#0f172a;
color:#fff;font-size:15px;cursor:pointer}button:disabled{opacity:.6}
.err{color:#b91c1c;font-size:13px;min-height:18px;margin-top:8px}
</style></head><body>
<div class="card">
<h1>健康助手</h1>
<p>请输入访问码。每个浏览器会使用独立的数据空间；访问码由管理员提供。</p>
<form id="f"><input id="code" type="password" autocomplete="current-password"
placeholder="访问码" autofocus /><button id="go">进入</button></form>
<div class="err" id="err"></div>
</div>
<script>
const form = document.getElementById('f');
form.onsubmit = async (event) => {
  event.preventDefault();
  const button = document.getElementById('go');
  const err = document.getElementById('err');
  const code = document.getElementById('code').value.trim();
  if (!code) return;
  button.disabled = true; err.textContent = '';
  try {
    const response = await fetch('/api/login', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({code})});
    if (response.ok) { location.href = '/'; return; }
    const data = await response.json().catch(() => ({}));
    err.textContent = data.detail || '访问码不正确';
  } catch (error) { err.textContent = '网络错误，请重试'; }
  finally { button.disabled = false; }
};
</script></body></html>"""


class LoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)


@app.post("/api/login")
def login(payload: LoginIn, request: Request) -> JSONResponse:
    if not settings.access_code:
        return JSONResponse(content={"ok": True})
    import secrets as secrets_module
    if not secrets_module.compare_digest(payload.code.strip(), settings.access_code):
        raise HTTPException(status_code=401, detail="访问码不正确")
    sid = sessions.new_sid()
    sessions.ensure(sid)
    response = JSONResponse(content={"ok": True})
    response.set_cookie(sessions.COOKIE, sessions.sign(sid), max_age=sessions.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")
    return response


@app.post("/api/logout")
def logout() -> JSONResponse:
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(sessions.COOKIE, path="/")
    return response


@app.get("/api/health")
def health_metrics() -> dict:
    return {"status": "ok", "cache": resp_cache.stats()}



class CustomModelsIn(BaseModel):
    base: str = Field(min_length=8, max_length=300)
    api_key: str = Field(min_length=4, max_length=300)
    api_format: str = Field(default="openai", pattern="^(openai|anthropic)$")


@app.post("/api/custom/models")
def custom_models(payload: CustomModelsIn) -> dict:
    base = payload.base.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="接口地址必须以 http:// 或 https:// 开头")
    _validate_custom_base(base)
    if payload.api_format == "anthropic":
        headers = {"x-api-key": payload.api_key,
                   "anthropic-version": "2023-06-01"}
    else:
        headers = {"Authorization": f"Bearer {payload.api_key}"}
    try:
        response = httpx.get(f"{base}/models", headers=headers, timeout=12)
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"连接失败：{type(error).__name__}") from error
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"接口返回 {response.status_code}，请检查地址或 Key",
        )
    try:
        data = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="接口返回的不是 JSON") from error
    raw = data.get("data") or data.get("models") or []
    models = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
        else:
            name = str(item)
        if name:
            models.append(str(name))
    return {"models": sorted(set(models)), "count": len(set(models))}


@app.get("/api/config")
def config() -> dict:
    """What the panel is allowed to offer (never exposes the key)."""
    client = LLMClient()
    return {"deepseek_available": bool(client.api_key), "default_provider": "mock",
            "custom_api": {"base": settings.custom_api_base,
                           "model": settings.custom_api_model}}


INJURY_CUES = ("摔", "摔倒", "摔到", "摔了一跤", "扭伤", "扭到", "崴脚", "崴了",
               "撞伤", "撞到", "磕到", "磕伤", "骨折", "脱位", "外伤", "伤口",
               "流血", "淤青", "瘀青", "拉伤", "闪腰")
BODY_PARTS = (
    "大腿", "小腿", "腿", "膝盖", "脚", "脚踝", "脚腕", "脚背", "脚跟", "脚趾",
    "手腕", "胳膊", "手臂", "手肘", "肘", "肩膀", "肩", "脖子", "颈椎",
    "腰", "后背", "背", "脊柱", "肋骨", "胸口", "胸", "腹", "腹部", "肚子", "胃",
    "头", "额头", "太阳穴", "牙", "眼睛", "耳朵", "鼻子", "喉咙", "嗓子",
    "手指", "髋", "屁股", "臀部", "会阴",
)


def _new_topic_break(current: str) -> bool:
    return any(word in current for word in INJURY_CUES)


BODY_NOISE = ("刚才", "回头", "馒头", "骨头", "跟头", "枕头", "石头", "木头",
              "念头", "关头", "抬头", "低头", "点头", "摇头", "舌头", "前头",
              "后头", "里头", "外头", "上头", "下头", "手头", "眉头", "带头",
              "牵头", "埋头", "出头", "报头", "街头", "到头", "转头")


def _body_parts(text: str) -> list[str]:
    cleaned = text or ""
    for noise in BODY_NOISE:
        cleaned = cleaned.replace(noise, "")
    return [part for part in BODY_PARTS if part in cleaned]


def _body_part_shift(current: str, history: str) -> bool:
    current_parts = _body_parts(current)
    if not current_parts:
        return False
    history_parts = _body_parts(history)
    return not any(part in history_parts for part in current_parts)


def _contextual_symptoms(symptoms: str, conversation_id: str | None,
                         answers: dict[str, str] | None = None) -> str:
    """Merge previous turns and follow-up answers so new details change the advice."""
    current = (symptoms or "").strip()
    if not current:
        return current
    parts: list[str] = []
    decision = router.rules(current)
    smalltalk = decision.get("intent") == "chitchat" and decision.get("confidence", 0) >= 0.85
    psych_cues = ("烦", "焦虑", "压力", "心情", "难过", "想哭", "崩溃", "内耗",
                  "委屈", "孤独", "孤单", "不开心", "低落", "没希望", "提不起劲")
    physical_cues = ("痛", "疼", "咳", "痰", "烧", "晕", "吐", "泻", "胀", "肿",
                     "血", "伤", "骨折", "皮疹", "小便", "大便")
    food_cues = ("吃", "喝", "热量", "减肥", "减脂", "胖", "营养", "早餐", "午餐",
                 "晚餐", "食物", "饮食", "食谱", "增肌", "健身", "练肌肉", "蛋白")
    # 明确在说情绪或饮食时，不要把上一段身体症状拼进来，否则会被旧症状带回医疗
    clear_topic_shift = ((any(word in current for word in psych_cues)
                          or any(word in current for word in food_cues))
                         and not any(word in current for word in physical_cues))
    if (conversation_id and not smalltalk and not clear_topic_shift
            and not _new_topic_break(current)):
        history = conversations.recent_user_texts(conversation_id, 6)
        if _body_part_shift(current, "".join(history)):
            history = []
        symptom_cues = ("痛", "疼", "咳", "痰", "烧", "热", "晕", "吐", "泻", "胀",
                        "痒", "麻", "肿", "血", "失眠", "睡不着", "累", "乏力",
                        "焦虑", "压力", "心情", "吃", "喝", "热量", "减肥", "胖")
        follow = ("那", "这个", "它", "还", "继续", "补充", "另外", "怎么", "几天",
                  "严重", "怎么办", "有用", "可以")
        cue_hit = any(word in current for word in symptom_cues)
        follow_hit = any(word in current for word in follow)
        if history and (cue_hit or follow_hit
                        or (len(current) <= 30 and decision.get("intent") != "clarify")):
            current_intent = decision.get("intent")
            if current_intent in ("medical", "psych", "food"):
                history = [item for item in history
                           if router.rules(item).get("intent") == current_intent]
            parts.extend(history[-3:])
    parts.append(current)
    for value in (answers or {}).values():
        value = str(value).strip()
        if value:
            parts.append(value)
    seen: list[str] = []
    for part in parts:
        part = part.strip()[:80]
        if part and part not in seen:
            seen.append(part)
    return "；".join(seen)


def _guarded_route(*args, **kwargs):
    if not _ANALYZE_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="当前问诊人数较多，请稍后再试")
    try:
        return _route_and_answer(*args, **kwargs)
    finally:
        _ANALYZE_SLOTS.release()


def _route_and_answer(symptoms: str, provider: str | None, answers: dict | None,
                      conversation_id: str | None = None,
                      force_intent: str | None = None,
                      observed: dict | None = None,
                      api_base: str | None = None,
                      api_model: str | None = None,
                      api_key: str | None = None,
                      api_models: list[str] | None = None,
                      api_format: str = "openai",
                      specialist: str | None = None,
                      fresh_context: bool = False) -> dict:
    language_result = language.enrich(symptoms)
    analysis_text = language_result["text"]
    effective = (analysis_text if fresh_context
                 else _contextual_symptoms(analysis_text, conversation_id, answers))
    answers_used = dict(answers or {})
    prior_history = ""
    if conversation_id and not fresh_context:
        prior_history = "".join(conversations.recent_user_texts(conversation_id, 6))
    topic_break = (fresh_context or _new_topic_break(analysis_text)
                   or _body_part_shift(analysis_text, prior_history))
    if conversation_id and not topic_break and not fresh_context:
        history_answers = conversations.recent_answers(conversation_id)
        if history_answers and router.rules(effective).get("intent") == "medical":
            merged = dict(history_answers)
            merged.update(answers_used)
            answers_used = merged
            extra = [value for value in history_answers.values() if value]
            if extra:
                effective = effective + ";" + ";".join(dict.fromkeys(extra))
    remembered = observed if observed is not None else memory.observe(symptoms)
    memory.sync_profile(profile_store)
    client = None
    if provider in ("deepseek", "custom"):
        if api_base:
            _validate_custom_base(api_base)
        try:
            client = LLMClient(provider=provider, api_key=api_key,
                               base_url=api_base, model=api_model,
                               models=api_models, api_format=api_format)
        except HTTPException:
            raise
        except Exception:
            client = None
    if force_intent:
        decision = {"intent": force_intent, "confidence": 1.0, "reason": "用户选择了入口"}
    else:
        decision = router.route(effective, client)
        if specialist:
            detected = decision.get("intent")
            strong_medical = any(word in effective for word in (
                "痛", "疼", "发烧", "发热", "咳", "吐", "泻", "出血", "肿", "晕",
                "血压", "血糖", "胸", "伤", "骨折", "小便", "大便", "皮疹"))
            if detected in ("clarify", "chitchat"):
                decision = {"intent": specialist, "confidence": 0.85,
                            "reason": "用户在专家栏目中提问"}
            elif specialist != "medical" and detected == "medical" and not strong_medical:
                decision = {"intent": specialist, "confidence": 0.8,
                            "reason": "没有明显躯体症状，沿用当前专家"}
    intent = decision["intent"]
    if intent == "clarify":
        route_step = {
            "step": "intent", "agent": "路由 Agent", "title": "判断你想问什么",
            "summary": "拿不准，先问一句：" + decision.get("reason", ""),
        }
        return {
            "kind": "clarify",
            "question": "你想问的是哪方面？",
            "options": decision.get("options", []),
            "original": symptoms,
            "intent": decision,
            "trace": [route_step],
        }
    notes = [] if topic_break else memory.recent_notes()
    if intent == "psych":
        result = psych.respond(effective) or chitchat.respond(effective)
    elif intent == "food":
        result = (food.answer(effective)
                  or food.guide(effective)
                  or {"kind": "food", "analysis": None, "items": []})
    elif intent == "chitchat":
        result = chitchat.respond(effective)
    else:
        prior_medical = False
        if conversation_id and not answers and not topic_break:
            prior_medical = any(
                router.rules(item).get("intent") == "medical"
                for item in conversations.recent_user_texts(conversation_id, 3)
            )
        result = analyze(effective, provider=provider, answers=answers_used,
                         api_base=api_base, api_model=api_model, api_key=api_key,
                         api_models=api_models, api_format=api_format,
                         medications=meds.list_active(), profile=profile_store.get(),
                         memory_notes=notes, is_followup=prior_medical)
    result = dict(result)
    if intent in ("medical", "psych"):
        if intent == "medical":
            names = [item.get("name") for item in (result.get("tcm") or [])[:3]]
            decision_map = {"cold": "偏风寒", "heat": "偏风热",
                            "ambiguous": "辨证不明确", "not_applicable": "按症状匹配"}
            label = decision_map.get(
                (result.get("differentiation") or {}).get("decision"), "已分析")
            summary = f"{label}；推荐：{'、'.join(names) or '暂无'}"
        else:
            summary = f"心理支持：{result.get('topic', {}).get('name', '')}"
        try:
            memory.add_note(conversation_id, symptoms, summary)
        except Exception:
            pass
    result["memory"] = {"new_facts": remembered["new"], "notes": notes}
    if intent == "medical" and result.get("lifestyle"):
        try:
            plan.ensure(symptoms, result["lifestyle"])
        except Exception:
            pass
    result["intent"] = decision
    route_step = {
        "step": "intent", "agent": "路由 Agent", "title": "判断你想问什么",
        "summary": {"medical": "身体不舒服，进入问诊流程",
                    "psych": "情绪/心理，进入心理支持",
                    "food": "食物营养，进入食物分析",
                    "chitchat": "闲聊，先接住话头"}[intent]
        + f"（{decision['reason']}）",
    }
    matched = language_result.get("matches") or []
    language_step = {
        "step": "language", "agent": "语言检索 Agent", "title": "先归一化口语",
        "summary": ("识别到：" + "、".join(matched[:5])) if matched
        else "没有需要归一化的词，按原话理解",
    }
    result["trace"] = [language_step, route_step] + result.get("trace", [])
    return result


def _chat_result(base: dict | None, reply: str, provider: str,
                 fallback_reason: str | None = None,
                 intent: dict | None = None) -> dict:
    reply = (reply or "").strip() or "我先确认一下：你是身体不舒服、情绪方面，还是饮食营养问题？"
    if (base and base.get("kind") in ("medical", "psych", "food")
            and "不替代面诊" not in reply and "信息参考" not in reply):
        reply += "\n\n信息参考，不替代面诊。"
    base = base or {}
    trace = list(base.get("trace") or [])
    trace.append({
        "step": "chat",
        "agent": "健康对话 Agent",
        "title": "把证据说成人话",
        "summary": "只处理身体、心理、膳食三类健康问题" if provider != "local"
                   else "确定性拒答/澄清，不调用模型",
    })
    result = {
        "kind": "chat", "mode": "chat", "chat_reply": reply,
        "provider": provider, "fallback_reason": fallback_reason,
        "intent": intent or base.get("intent") or {"intent": "chat"},
        "sources": base.get("sources") or [],
        "triage": base.get("triage"),
        "lifestyle": base.get("lifestyle"),
        "tcm": base.get("tcm"),
        "western": base.get("western"),
        "differentiation": base.get("differentiation"),
        "topic": base.get("topic"),
        "report_markdown": base.get("report_markdown"),
        "followups": base.get("followups"),
        "trace": trace,
    }
    if base.get("memory") is not None:
        result["memory"] = base.get("memory")
    if base.get("review") is not None:
        result["review"] = base.get("review")
    return result


def _guarded_chat(*args, **kwargs) -> dict:
    if not _ANALYZE_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="当前问诊人数较多，请稍后再试")
    try:
        return _chat_answer(*args, **kwargs)
    finally:
        _ANALYZE_SLOTS.release()


def _merge_bases(primary: dict, secondary: dict) -> dict:
    """Merge two local medical analyses for a confirmed two-symptom answer."""
    merged = dict(primary)
    for key in ("tcm", "western"):
        seen: set[str] = set()
        items: list[dict] = []
        for source in (primary, secondary):
            for item in source.get(key) or []:
                name = str(item.get("name") or "")
                if name and name not in seen:
                    seen.add(name)
                    items.append(item)
        merged[key] = items
    # Triage: any warning from either symptom wins.
    triage = dict(primary.get("triage") or {})
    other_triage = secondary.get("triage") or {}
    if other_triage.get("urgent"):
        triage["urgent"] = True
    triage["reasons"] = list(dict.fromkeys(
        (triage.get("reasons") or []) + (other_triage.get("reasons") or [])
    ))
    merged["triage"] = triage
    # Lifestyle: union tags/diet/exercise/avoid/sources.
    life = dict(primary.get("lifestyle") or {})
    other_life = secondary.get("lifestyle") or {}
    life["tags"] = list(dict.fromkeys((life.get("tags") or []) + (other_life.get("tags") or [])))
    for field in ("diet", "exercise", "avoid"):
        life[field] = list(dict.fromkeys((life.get(field) or []) + (other_life.get(field) or [])))
    seen_sources = set()
    sources = []
    for source in (primary.get("sources") or []) + (secondary.get("sources") or []):
        key = str(source.get("url") or source.get("title") or "")
        if key and key not in seen_sources:
            seen_sources.add(key)
            sources.append(source)
    merged["sources"] = sources
    merged["lifestyle"] = life
    merged["differentiation"] = primary.get("differentiation") or secondary.get("differentiation")
    return merged


def _previous_body_symptom(conversation_id: str, current: str) -> str:
    """Find the latest earlier medical symptom that referred to another body part."""
    current_parts = _body_parts(current)
    if not current_parts:
        return ""
    for text in reversed(conversations.recent_user_texts(conversation_id, 6)):
        item = (text or "").strip()
        if not item:
            continue
        if router.rules(item).get("intent") != "medical":
            continue
        parts = _body_parts(item)
        if parts and not (set(parts) & set(current_parts)):
            return item
    return ""


def _symptom_confirm_result(previous: str, current: str, base: dict) -> dict:
    reply = (
        f"你之前说「{previous}」，现在又说「{current}」。\n\n"
        f"之前的「{previous}」现在还在吗？还在的话我把两件事一起分析；"
        "已经好了的话，我就只按新症状处理。"
    )
    result = _chat_result(base, reply, "local",
                          intent={"intent": "medical", "confidence": 0.9,
                                  "reason": "检测到身体部位切换"})
    result["kind"] = "symptom_confirm"
    result["symptom_confirm"] = {
        "previous": previous,
        "current": current,
        "options": [
            {"label": "还在，两个一起看", "value": "still"},
            {"label": "已经好了，只看新症状", "value": "resolved"},
        ],
    }
    return result


def _chat_answer(symptoms: str, provider: str | None, answers: dict | None,
                 conversation_id: str | None = None,
                 force_intent: str | None = None,
                 api_base: str | None = None,
                 api_model: str | None = None,
                 api_key: str | None = None,
                 api_models: list[str] | None = None,
                 api_format: str = "openai",
                 specialist: str | None = None,
                 fresh_context: bool = False,
                 symptom_choice: str | None = None,
                 previous_symptoms: str | None = None,
                 current_symptoms: str | None = None) -> dict:
    confirm_handled = False
    if not symptom_choice and conversation_id:
        pending = conversations.last_symptom_confirm(conversation_id)
        if pending:
            answer = (symptoms or "").strip()
            if any(word in answer for word in ("还在", "还有", "仍然", "没变化", "一样", "还在的")):
                symptom_choice = "still"
            elif any(word in answer for word in ("好了", "没有了", "不在了", "没了", "消失", "不痛了")):
                symptom_choice = "resolved"
            if symptom_choice:
                previous_symptoms = pending["previous"]
                current_symptoms = pending["current"]
    if symptom_choice:
        previous = (previous_symptoms or "").strip()
        current = (current_symptoms or symptoms or "").strip()
        if symptom_choice == "still" and previous:
            symptoms = f"{previous}；{current}"
        else:
            symptoms = current or symptoms
        fresh_context = True
        confirm_handled = True

    history = [] if fresh_context else (
        conversations.recent_dialogue(conversation_id, 8) if conversation_id else []
    )
    last_assistant = ""
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            last_assistant = str(turn.get("content") or "")
            break
    context_text = "；".join(
        str(turn.get("content") or "") for turn in history if turn.get("role") == "user"
    )
    candidate = router.rules(context_text).get("intent")
    context_intent = candidate if candidate in ("medical", "psych", "food") else None
    follow_cues = ("这个", "那", "它", "还", "继续", "补充", "另外", "怎么",
                   "多久", "几天", "严重", "要紧", "需要", "可以", "会不会",
                   "有没有", "怎么办", "然后呢", "是吗")
    asked_question = bool(last_assistant and ("？" in last_assistant or "?" in last_assistant))
    short_follow_up = bool(
        context_intent and len((symptoms or "").strip()) <= 30
        and any(cue in (symptoms or "") for cue in follow_cues)
    )
    follow_up = asked_question or short_follow_up
    scope = chat_mode.scope(symptoms, force_intent, follow_up=follow_up,
                            context_intent=context_intent)
    if scope["action"] == "refuse":
        return _chat_result(None, chat_mode.refusal_text(), "local",
                            intent={"intent": "off_topic", "confidence": 0.95,
                                    "reason": "超出健康话题范围"})
    if scope["action"] == "clarify":
        return _chat_result(None, chat_mode.clarify_text(), "local",
                            intent={"intent": "clarify", "confidence": 0.4,
                                    "reason": "健康领域内但信息不足"})
    if scope["action"] == "smalltalk":
        base = chitchat.respond(symptoms)
        return _chat_result(base, chat_mode.smalltalk_text(base), "local",
                            intent={"intent": "chitchat", "confidence": 0.9,
                                    "reason": "问候/能力询问"})

    # Get the deterministic evidence first.  provider=mock means this is local
    # and does not spend another model call.
    base = _route_and_answer(
        symptoms, provider="mock", answers=answers,
        conversation_id=conversation_id, force_intent=force_intent,
        api_base=api_base, api_model=api_model, api_key=api_key,
        api_models=api_models, api_format=api_format, specialist=specialist,
        fresh_context=fresh_context,
    )
    if base.get("kind") == "clarify":
        return _chat_result(base, chat_mode.clarify_text(), "local",
                            intent=base.get("intent"))
    if base.get("kind") == "psych" and base.get("crisis"):
        return _chat_result(base, chat_mode.local_reply(base), "local",
                            intent=base.get("intent"))
    if (base.get("triage") or {}).get("urgent"):
        return _chat_result(base, chat_mode.local_reply(base), "local",
                            intent=base.get("intent"))

    if symptom_choice == "still" and previous_symptoms:
        current_base = _route_and_answer(
            current_symptoms or symptoms, provider="mock", answers=None, fresh_context=True,
        )
        previous_base = _route_and_answer(
            previous_symptoms, provider="mock", answers=None, fresh_context=True,
        )
        base = _merge_bases(current_base, previous_base)

    if (not confirm_handled and not fresh_context and conversation_id
            and base.get("kind") in (None, "medical")):
        previous = _previous_body_symptom(conversation_id, symptoms)
        if previous:
            return _symptom_confirm_result(previous, symptoms, base)

    if not provider or provider == "mock":
        return _chat_result(base, chat_mode.local_reply(base), "mock",
                            intent=base.get("intent"))

    client = None
    try:
        if api_base:
            _validate_custom_base(api_base)
        client = LLMClient(provider=provider, api_key=api_key,
                           base_url=api_base, model=api_model,
                           models=api_models, api_format=api_format)
    except HTTPException:
        raise
    except Exception:
        client = None

    if client is None or not client.live:
        return _chat_result(base, chat_mode.local_reply(base), "mock",
                            "model client unavailable", intent=base.get("intent"))

    messages = chat_mode.prompt_messages(
        symptoms, base, history, profile_store.get(),
        meds.list_active(), [],
    )
    try:
        reply = client.chat(messages)
    except Exception as error:
        return _chat_result(base, chat_mode.local_reply(base), "mock-fallback",
                            f"model unavailable: {str(error)[:200]}",
                            intent=base.get("intent"))
    if not (reply or "").strip():
        return _chat_result(base, chat_mode.local_reply(base), "mock-fallback",
                            "model returned empty content", intent=base.get("intent"))
    evidence_text = "；".join(
        [symptoms]
        + [str(turn.get("content") or "") for turn in history if turn.get("role") == "user"]
        + [str(value) for value in (answers or {}).values()]
        + [json.dumps(profile_store.get(), ensure_ascii=False)]
        + [json.dumps([item.get("name") for item in meds.list_active()], ensure_ascii=False)]
    )
    if chat_mode.unsupported_assertion(reply, evidence_text):
        retry_messages = messages + [
            {"role": "assistant", "content": reply[:3000]},
            {"role": "user", "content": (
                "你上一版写入了用户没有报告的症状。请重写：只依据当前对话和平台事实，"
                "不要写用户有腹泻/呕吐/发热等未提及症状；信息不足就追问。"
            )},
        ]
        try:
            retry = client.chat(retry_messages)
        except Exception:
            retry = ""
        if retry and not chat_mode.unsupported_assertion(retry, evidence_text):
            return _chat_result(base, retry, provider, intent=base.get("intent"))
        return _chat_result(base, chat_mode.local_reply(base), "mock-fallback",
                            "model introduced a symptom that the user did not report",
                            intent=base.get("intent"))
    return _chat_result(base, reply, provider, intent=base.get("intent"))


class MedicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    dose: str = ""
    method: str = ""
    note: str = ""
    interval_hours: float = Field(default=8, ge=0.5, le=24)
    doses_per_day: int = Field(default=2, ge=1, le=12)
    start_time: str = Field(default="08:00", pattern=r"^\d{1,2}:\d{2}$")
    total_doses: int | None = Field(default=None, ge=1, le=999)
    stock_total: float | None = Field(default=None, ge=0, le=9999)
    stock_unit: str = "盒"
    expiry_date: str = ""


class ProfileIn(BaseModel):
    age: int | None = Field(default=None, ge=0, le=120)
    sex: str = Field(default="", pattern="^(male|female|)$")
    pregnant: bool = False
    allergies: list[str] = []
    conditions: list[str] = []
    diet_pref: str = Field(default="", max_length=30)
    avoid_foods: str = Field(default="", max_length=200)
    meal_style: str = Field(default="", max_length=20)
    activity_level: str = Field(default="", max_length=20)


@app.get("/api/profile")
def get_profile() -> dict:
    return {"profile": profile_store.get()}


@app.put("/api/profile")
def put_profile(payload: ProfileIn) -> dict:
    return {"profile": profile_store.update(
        payload.age, payload.sex, payload.pregnant, payload.allergies, payload.conditions,
        payload.diet_pref, payload.avoid_foods, payload.meal_style, payload.activity_level)}


class CheckinIn(BaseModel):
    diet: bool = False
    exercise: bool = False
    meds: bool = False
    note: str = ""
    score: int | None = Field(default=None, ge=0, le=10)


@app.get("/api/plan")
def get_plan() -> dict:
    active = plan.active()
    if active is None:
        return {"plan": None}
    return {"plan": plan.detail(active["id"])}


@app.post("/api/plan/checkin")
def plan_checkin(payload: CheckinIn) -> dict:
    active = plan.active()
    if active is None:
        raise HTTPException(status_code=404, detail="no active plan")
    return {"plan": plan.checkin(active["id"], payload.diet, payload.exercise,
                                 payload.meds, payload.note, payload.score)}


@app.post("/api/plan/finish")
def plan_finish() -> dict:
    active = plan.active()
    if active is None:
        return {"finished": False}
    plan.finish(active["id"])
    return {"finished": True}


@app.get("/api/plan/reminders/due")
def plan_reminders() -> dict:
    return {"items": plan.due()}


@app.post("/api/notifications/test")
def notifications_test() -> dict:
    notify.enqueue("test", "⏰ 测试提醒", "大郎，该吃药了！这是一条测试提醒，看到就说明通知链路是通的。")
    return {"queued": True}


@app.post("/api/notifications/test-med")
def notifications_test_med() -> dict:
    items = meds.list_active()
    if not items:
        return {"queued": False, "reason": "no active medication"}
    item = items[0]
    body = f"大郎，该吃药了！{item['name']} {item.get('dose') or ''}，{item.get('method') or ''}".strip()
    notify.enqueue(f"med:{item['id']}", "⏰ 该吃药了", body)
    return {"queued": True}


@app.get("/api/memory")
def memory_list() -> dict:
    return {"facts": memory.facts(), "notes": memory.recent_notes(5)}


class MemoryPatch(BaseModel):
    value: str = Field(min_length=1, max_length=40)


@app.put("/api/memory/facts/{fact_id}")
def memory_update(fact_id: int, payload: MemoryPatch) -> dict:
    result = memory.update_fact(fact_id, payload.value)
    if result is None:
        raise HTTPException(status_code=400, detail="cannot update fact")
    # keep profile in sync: remove old value, add new one
    profile_store.remove_fact(result["fact_type"], result["old_value"])
    if result["fact_type"] == "allergy":
        current = profile_store.get()
        profile_store.update(current.get("age"), current.get("sex"),
                             bool(current.get("pregnant")),
                             list(dict.fromkeys((current.get("allergies") or []) + [result["value"]])),
                             current.get("conditions") or [])
    elif result["fact_type"] == "condition":
        current = profile_store.get()
        profile_store.update(current.get("age"), current.get("sex"),
                             bool(current.get("pregnant")),
                             current.get("allergies") or [],
                             list(dict.fromkeys((current.get("conditions") or []) + [result["value"]])))
    return {"updated": True, "fact": {"type": result["fact_type"], "value": result["value"]}}


@app.delete("/api/memory/facts/{fact_id}")
def memory_delete(fact_id: int) -> dict:
    fact = memory.delete_fact(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    profile_store.remove_fact(fact["fact_type"], fact["value"])
    return {"deleted": True, "fact": {"type": fact["fact_type"], "value": fact["value"]}}


@app.delete("/api/memory/notes")
def memory_clear_notes() -> dict:
    return {"cleared": memory.clear_notes()}


class PushIn(BaseModel):
    subscription: dict = {}


@app.get("/api/push/config")
def push_config() -> dict:
    data = push_store.keys()
    return {"publicKey": data["public_key"], "subscriptions": push_store.count()}


@app.post("/api/push/subscribe")
def push_subscribe(payload: PushIn) -> dict:
    return {"subscribed": push_store.subscribe(payload.subscription)}


class PushOut(BaseModel):
    endpoint: str = ""


@app.post("/api/push/unsubscribe")
def push_unsubscribe(payload: PushOut) -> dict:
    return {"unsubscribed": push_store.unsubscribe(payload.endpoint)}


@app.post("/api/push/test")
def push_test() -> dict:
    return push_store.send("健康助手", "这是一条跨设备测试推送；收到说明后台提醒已生效。", "test")


@app.get("/api/notifications/unread")
def notifications_unread() -> dict:
    try:
        notify.scan_session()
    except Exception:
        pass
    return {"items": notify.unread()}


class CustomTestIn(BaseModel):
    base: str = Field(min_length=8, max_length=300)
    api_key: str = Field(min_length=4, max_length=300)
    model: str = Field(min_length=1, max_length=120)
    api_format: str = Field(default="openai", pattern="^(openai|anthropic)$")


class AckIn(BaseModel):
    ids: list[int] = []


@app.post("/api/notifications/ack")
def notifications_ack(payload: AckIn) -> dict:
    wanted = set(payload.ids or [])
    rows = [row for row in notify.unread() if row["id"] in wanted]
    acked = notify.ack(payload.ids)
    crisis_acked = 0
    if any(row.get("kind") == "crisis" for row in rows):
        crisis_acked = crisis.ack_all()
    return {"acked": acked, "crisis_acked": crisis_acked}


class MedicationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    dose: str | None = None
    method: str | None = None
    note: str | None = None
    interval_hours: float | None = Field(default=None, ge=0.5, le=24)
    doses_per_day: int | None = Field(default=None, ge=1, le=12)
    start_time: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    total_doses: int | None = Field(default=None, ge=1, le=999)
    stock_total: float | None = Field(default=None, ge=0, le=9999)
    stock_unit: str | None = None
    stock_remaining: float | None = Field(default=None, ge=0, le=9999)
    expiry_date: str | None = None


@app.patch("/api/medications/{item_id}")
def update_medication(item_id: str, payload: MedicationPatch) -> dict:
    fields = {key: value for key, value in payload.model_dump().items() if value is not None}
    item = meds.update(item_id, **fields)
    if item is None:
        raise HTTPException(status_code=400, detail="nothing to update or invalid")
    return {"item": item}


@app.post("/api/medications/{item_id}/take")
def take_medication(item_id: str) -> dict:
    item = meds.take(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"item": item}


@app.post("/api/medications/{item_id}/pause")
def pause_medication(item_id: str, minutes: int = 30) -> dict:
    return {"paused": meds.pause(item_id, minutes)}


@app.post("/api/medications/{item_id}/skip")
def skip_medication(item_id: str) -> dict:
    return {"skipped": meds.skip(item_id)}


class CabinetIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    total: int = Field(default=7, ge=1, le=999)


@app.get("/api/cabinet")
def cabinet_list() -> dict:
    return {"items": cabinet.list_all()}


@app.post("/api/cabinet")
def cabinet_add(payload: CabinetIn) -> dict:
    return {"item": cabinet.add(payload.name, payload.total)}


@app.post("/api/cabinet/{item_id}/take")
def cabinet_take(item_id: str) -> dict:
    item = cabinet.take(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="not found")
    return {"item": item}


@app.delete("/api/cabinet/{item_id}")
def cabinet_delete(item_id: str) -> dict:
    if not cabinet.delete(item_id):
        raise HTTPException(status_code=404, detail="cabinet item not found")
    return {"deleted": True}


@app.get("/api/medications")
def list_medications() -> dict:
    return {"items": meds.list_all()}


@app.post("/api/medications")
def add_medication(payload: MedicationIn) -> dict:
    item = meds.add(payload.name, payload.dose, payload.method, payload.note,
                    payload.interval_hours, payload.doses_per_day, payload.start_time,
                    payload.total_doses, payload.stock_total, payload.stock_unit,
                    payload.expiry_date)
    if item is None:
        raise HTTPException(status_code=400, detail="interval_hours / doses_per_day / start_time 不合法")
    return {"item": item}


@app.delete("/api/medications/{item_id}")
def delete_medication(item_id: str) -> dict:
    if not meds.delete(item_id):
        raise HTTPException(status_code=404, detail="medication not found")
    return {"deleted": True}


@app.get("/api/crisis/followups/due")
def crisis_followups_due() -> dict:
    return {"items": crisis.due()}


@app.post("/api/crisis/followups/{followup_id}/ack")
def crisis_followup_ack(followup_id: str) -> dict:
    return {"acked": crisis.ack(followup_id)}


@app.get("/api/reminders/due")
def due_reminders() -> dict:
    return {"items": meds.due()}


@app.post("/api/medications/{item_id}/ack")
def ack_medication(item_id: str) -> dict:
    return {"acked": meds.ack(item_id)}


@app.post("/api/medications/{item_id}/test")
def test_reminder(item_id: str) -> dict:
    item = meds.fire_now(item_id)
    return {"item": item}


class MessageIn(BaseModel):
    symptoms: str = Field(min_length=1, max_length=2000)
    answers: dict[str, str] | None = None
    provider: str | None = Field(default=None, pattern="^(mock|deepseek|custom)$")
    user_text: str | None = Field(default=None, max_length=500)
    force_intent: str | None = Field(default=None, pattern="^(medical|psych|food|chitchat)$")
    api_base: str | None = Field(default=None, max_length=300)
    api_model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=300)
    api_models: list[str] | None = None
    api_format: str = Field(default="openai", pattern="^(openai|anthropic)$")
    specialist: str | None = Field(default=None, pattern="^(medical|psych|food)$")
    fresh_context: bool = False
    chat_mode: bool = False
    symptom_choice: str | None = Field(default=None, pattern="^(still|resolved)$")
    previous_symptoms: str | None = Field(default=None, max_length=2000)
    current_symptoms: str | None = Field(default=None, max_length=2000)


@app.get("/api/conversations")
def list_conversations(q: str = "") -> dict:
    return {"items": conversations.list_all(q)}


@app.post("/api/conversations")
def create_conversation(payload: dict | None = None) -> dict:
    title = (payload or {}).get("title") or "新会话"
    return {"conversation": conversations.create(str(title)[:40])}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> JSONResponse:
    data = conversations.get(conversation_id)
    if data is None:
        return JSONResponse(status_code=404, content={"detail": "conversation not found"})
    return JSONResponse(content=data)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=40)


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, payload: RenameIn) -> dict:
    return {"renamed": conversations.rename(conversation_id, payload.title)}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    return {"deleted": conversations.delete(conversation_id)}


@app.post("/api/conversations/{conversation_id}/messages")
def conversation_message(conversation_id: str, payload: MessageIn) -> dict:
    if conversations.get(conversation_id) is None:
        return JSONResponse(status_code=404, content={"detail": "conversation not found"})
    if payload.chat_mode:
        result = _guarded_chat(payload.symptoms, payload.provider, payload.answers,
                               conversation_id=conversation_id,
                               force_intent=payload.force_intent,
                               api_base=payload.api_base, api_model=payload.api_model,
                               api_key=payload.api_key, api_models=payload.api_models,
                               api_format=payload.api_format, specialist=payload.specialist,
                               fresh_context=payload.fresh_context,
                               symptom_choice=payload.symptom_choice,
                               previous_symptoms=payload.previous_symptoms,
                               current_symptoms=payload.current_symptoms)
    else:
        result = _guarded_route(payload.symptoms, payload.provider, payload.answers,
                               conversation_id=conversation_id,
                               force_intent=payload.force_intent,
                               api_base=payload.api_base, api_model=payload.api_model,
                               api_key=payload.api_key, api_models=payload.api_models,
                               api_format=payload.api_format, specialist=payload.specialist,
                               fresh_context=payload.fresh_context)
    if payload.symptom_choice == "resolved":
        result["resolution_note"] = (
            "已按新症状处理。如果之后还要看之前的症状，建议新开会话，避免旧上下文干扰。"
        )
    conversations.add_turn(conversation_id, payload.user_text or payload.symptoms, result)
    return {"result": result}


class FoodIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


@app.get("/api/food/search")
def food_search(q: str = "") -> dict:
    return {"items": [food.analyze(item) for item in food.search(q)]}


@app.post("/api/food/analyze")
def food_analyze(payload: FoodIn) -> JSONResponse:
    result = food.answer(payload.text)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "没有识别到食物名称"})
    return JSONResponse(content=result)


@app.get("/api/meta")
def meta() -> dict:
    """Agent team and workflow definition (read-only, no secrets)."""
    return describe()


@app.get("/api/experiment")
def experiment() -> JSONResponse:
    """Latest single-vs-multi comparison run, if any."""
    path = BASE.parent / "out" / "experiment.json"
    if not path.is_file():
        return JSONResponse(status_code=404, content={"detail": "no experiment yet"})
    import json
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@app.get("/api/ablation")
def ablation_data() -> dict:
    file = Path(__file__).resolve().parents[1] / "out" / "ablation.json"
    if not file.is_file():
        raise HTTPException(status_code=404, detail="ablation not generated yet")
    return json.loads(file.read_text(encoding="utf-8"))


@app.post("/api/analyze")
def analyze_endpoint(request: AnalyzeRequest) -> dict:
    started = time.time()
    if request.chat_mode:
        result = _guarded_chat(
            request.symptoms, request.provider, request.answers,
            force_intent=request.force_intent,
            api_base=request.api_base, api_model=request.api_model,
            api_key=request.api_key, api_models=request.api_models,
            api_format=request.api_format, specialist=request.specialist,
            fresh_context=request.fresh_context,
            symptom_choice=request.symptom_choice,
            previous_symptoms=request.previous_symptoms,
            current_symptoms=request.current_symptoms,
        )
        if request.symptom_choice == "resolved":
            result["resolution_note"] = (
                "已按新症状处理。如果之后还要看之前的症状，建议新开会话，避免旧上下文干扰。"
            )
        result["cached"] = False
        result["elapsed_ms"] = int((time.time() - started) * 1000)
        return result
    observed = memory.observe(request.symptoms)
    memory.sync_profile(profile_store)
    provider = request.provider or ""
    key = resp_cache.make_key(
        request.symptoms, request.answers, provider, request.force_intent,
        request.api_base, request.api_model, request.api_format, request.api_models,
        request.fresh_context, profile_store.get(), [item["name"] for item in meds.list_all()],
        observed["new"],
    )
    hit = resp_cache.get(key) if not observed["new"] else None
    if hit is not None:
        hit["cached"] = True
        hit["elapsed_ms"] = int((time.time() - started) * 1000)
        # 缓存命中也要保证康复计划等副作用发生
        if hit.get("lifestyle"):
            try:
                plan.ensure(request.symptoms, hit["lifestyle"])
            except Exception:
                pass
        return hit
    result = _guarded_route(request.symptoms, request.provider, request.answers,
                               force_intent=request.force_intent, observed=observed,
                               api_base=request.api_base, api_model=request.api_model,
                               api_key=request.api_key, api_models=request.api_models,
                               api_format=request.api_format, specialist=request.specialist,
                               fresh_context=request.fresh_context)
    result["cached"] = False
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    if (result.get("kind") == "medical" or result.get("tcm")) and not result.get("fallback_reason"):
        resp_cache.put(key, {k: v for k, v in result.items() if k not in ("cached", "elapsed_ms")})
    return result





@app.post("/api/custom/test")
def custom_test(payload: CustomTestIn) -> dict:
    """Send one tiny chat so activation checks the real endpoint, not just /models."""
    _validate_custom_base(payload.base)
    candidate = LLMClient(provider="custom", api_key=payload.api_key,
                          base_url=payload.base, model=payload.model,
                          models=[payload.model], api_format=payload.api_format)
    try:
        reply = candidate.chat([{"role": "user", "content": "只回复两个字：收到"}])
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"连接失败：{str(error)[:240]}") from error
    return {"ok": True, "reply": (reply or "")[:60]}
