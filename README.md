# 健康助手：多 Agent 驱动的可核验健康咨询平台

面向 2026 未来杯的创新健康助手：从一句自然语言，走到有证据、能执行的健康方案。

> 本项目只做健康信息整理与就医建议，**不做诊断、不开处方**。出现胸痛、呼吸困难、意识改变等红旗症状时，直接建议急诊。

## 在线 Demo

- 地址：<http://47.107.248.43>
- 访问码：`health-demo-2026`
- 每个浏览器自动获得独立数据空间；可点“我的药品 → 重置演示数据”恢复干净演示。
- 建议用 Edge / Chrome 打开。
- 可运行源码包：<http://47.107.248.43/static/health-agent-source.zip>（不含数据库、API Key、VAPID 私钥）。

> 桌面通知 / Web Push 需要 HTTPS 或 localhost。当前公开 Demo 是 HTTP，因此只能看到页面内提醒；配置 HTTPS 后即可使用 Windows 桌面通知。

## 功能

- **多 Agent 流水线**：语言归一 → 路由 → 红旗分诊 → 风寒/风热辨证 → 证据检索（PubMed / openFDA / NHS / WHO / CDC）→ 中药知识库匹配 → 报告撰写 → 安全审查 → 修复重写。
- **三合一入口**：身体不适、情绪困扰、饮食营养共用一套个人资料、用药记录和记忆。
- **个人资料**：年龄、性别、孕期、过敏、慢病、饮食偏好、忌口、就餐场景、活动量；回答自动带上。
- **具体回答**：中药 195 味、西药 28 种、食物 160 种、膳食方案 22 套；药名、用法、禁忌、价格、来源引用。
- **安全审查**：引用锚定、剂量核对、越界措辞、红旗分诊；不过自动重写，仍不过降级模板。
- **我的药品**：提醒（间隔 / 每天次数 / 首次时间 / 备注）+ 疗程龙珠 + 库存 + 复诊。
- **用药提醒**：页面内提醒 + 浏览器桌面通知；HTTPS 下可开启 Web Push，关页/跨设备提醒。
- **龙珠打卡**：设几颗龙珠就打卡几次，每打卡一次点亮一颗；集齐 7/7 出现“神龙出现 · 疗程结束”。
- **康复计划**：从最近一次建议生成 7 天每日任务；第 3 天鼓励，第 7 天复诊提醒；按慢病/忌口/在用药物调整。
- **自定义模型接口**：OpenAI / Anthropic 兼容；拉取模型 → 勾选 → 更新 → 测试激活；也支持手动兜底。
- **可复现实验**：单 Agent vs 多 Agent 对比、消融实验、14 步轨迹。

## 快速启动

要求：Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```bash
cd backend
uv sync
cp ../.env.example .env
# 按需修改 .env，最低只需设置 APP_ACCESS_CODE
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100
```

打开 <http://127.0.0.1:8100>，输入 `.env` 里的 `APP_ACCESS_CODE`。

### 模式

- 默认 `APP_LLM_PROVIDER=mock`：不调用外部模型，链路、个人资料、药品、计划都可演示。
- 真实模型：在 `.env` 设置

```env
APP_LLM_PROVIDER=deepseek
APP_DEEPSEEK_API_KEY=sk-...
APP_MODEL=deepseek-flash
APP_MAX_TOKENS=20000
APP_REASONING_EFFORT=low
APP_TIMEOUT_SECONDS=180
```

也可以在页面里选 **自定义接口**，用自己的 OpenAI / Anthropic 兼容供应商；模型名通过“拉取模型”勾选，不需要手填。

### 测试

```bash
cd backend
uv run pytest -q
```

当前测试：**84 passed**。

## 目录

```text
backend/
  app/
    main.py            FastAPI 入口、鉴权、限流、API
    pipeline.py        多 Agent 编排
    llm.py             OpenAI / Anthropic 兼容客户端
    language.py        语言归一（59 类症状 / 442 条口语说法 / 104 组同义词）
    router.py          三合一路由
    differentiation.py 风寒/风热辨证
    personalize.py 个人资料驱动的膳食/运动
    profile.py         个人资料（每浏览器独立 SQLite）
    meds.py            用药提醒、疗程龙珠、库存
    plan.py            7 天康复计划
    notify.py          提醒扫描与站内通知
    push.py            Web Push / VAPID
    safety.py          安全审查
    static/            SPA（index.html / app.js / styles.css / sw.js）
    data/              中药、西药、食物、心理、膳食 JSON
  tests/               pytest
docs/                  方案书、演示脚本、实验说明
deploy/                systemd / nginx 示例
Dockerfile
docker-compose.yml
```

## 数据与安全

- 每个浏览器一个独立 SQLite 数据库，放在 `backend/data/users/`；不会把其他人的对话带到当前空间。
- 个人资料、对话、药品、计划、提醒均为本地数据；不上传到本项目的服务器之外。
- 选择 DeepSeek 时症状文本会发送到 DeepSeek；选择 Mock 时不会调用外部模型。
- 不提交数据库、VAPID 私钥、`.env` 或 API Key；仓库只保留 `.env.example`。
- 公开部署请使用 HTTPS，并设置 `APP_COOKIE_SECURE=true`；当前 Demo 为 HTTP，仅用于比赛演示。
- 访问码是共享入口；正式上线建议改为个人账号体系。

## 已知边界

- 只支持 OpenAI / Anthropic 兼容的 `chat/completions` 接口；只支持 `/responses` 的供应商暂不支持。
- 服务器直连 OpenAI 官方可能超时；可使用代理、网关，或改用 DeepSeek / Kimi / 通义 / 智谱等。
- 自定义接口必须支持 `/models` 才能自动拉取模型；不支持时会出现“手动填一个”的兜底。
- Web Push 需要 HTTPS、浏览器通知权限和 Service Worker；HTTP 下只能页面内提醒。
- 同时最多 2 个问诊（`_ANALYZE_SLOTS`），超过会返回 503；每会话每分钟 60 次请求，超过返回 429。

## 比赛材料

- 路演 PPT：`健康助手_未来杯_完整版.pptx`（21 页，含真实运行截图、对比/消融实验、个人资料、药品提醒、龙珠打卡、康复计划、自定义接口）。
- 方案书：`docs/方案书.md`
- 演示脚本：`docs/demo-script.md`
- 实验说明：`docs/experiment.md`
