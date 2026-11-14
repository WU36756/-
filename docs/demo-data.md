# 演示数据与现场操作

## 当前演示状态

- 画像：30 岁女性，无过敏，无慢病；
- 我的药：感冒颗粒（6 次疗程、库存 12、30 天到期）、丹参片（10 次、库存 20、90 天到期）；
- 对话：2 段（发烧头痛、失眠多梦）；
- 康复计划：重置后为空，演示时问一次诊即可自动生成；
- 模型：默认 Mock；选择 DeepSeek 需在页面切换。

## 一键重置

页面 → 个人资料 → 底部「重置演示数据」→ 确认。

会清空：对话、用药、计划、记忆、通知、危机回访、响应缓存。
会重建：干净画像 + 2 条药。

## 手动重置（命令行）

```bash
curl -sS -X POST http://127.0.0.1:8100/api/demo/reset
```

## 演示前检查

```bash
curl -sS http://127.0.0.1:8100/api/health
# {"status":"ok","cache":{"entries":N,"ttl_seconds":600}}
```

## 断网演示

```bash
# 在 systemd 服务里设置 DEMO_OFFLINE=1 后重启
sudo systemctl edit health-panel.service
# [Service]
# Environment=DEMO_OFFLINE=1
sudo systemctl restart health-panel.service
```

断网时：检索走证据缓存，模型走 Mock；知识库、心理、食物、用药、计划全部可用。

## 演示视频录制

见 `docs/video-script.md`；现场路线见 `docs/demo-script.md`。

## 常见问题

| 现象 | 处理 |
|---|---|
| 页面空白 | 刷新；仍异常 `sudo systemctl restart health-panel.service` |
| 图片识别慢/失败 | 首次要加载 CLIP；换清晰单食物图 |
| 提醒不弹 | 页面需打开；Windows 通知器需登录常驻 |
| 数据乱了 | 重置演示数据 |
