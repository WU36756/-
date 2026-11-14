# 用专家自己的模型接口（Kimi / WorkBuddy / 其他 OpenAI 兼容服务）

平台支持**任何 OpenAI 兼容的 chat-completions 接口**，不需要改代码。

## 使用方法

1. 打开页面，点输入框左下角的模型下拉框；
2. 选 **「自定义接口（Kimi 等）」**；
3. 填三项：
   - **接口地址（Base URL）**：到 `/v1` 为止，例如 `https://api.moonshot.cn/v1`；
   - **模型名**：服务商控制台里的模型 ID；
   - **API Key**：专家自己的 key；
4. 点「保存并使用」，然后正常提问。

Key 只存在**本机浏览器的 sessionStorage**，关闭标签页就清掉；平台不会把它写进数据库或日志。

## Kimi（Moonshot）

以 Moonshot 开放平台为例：

```
Base URL: https://api.moonshot.cn/v1
模型名:   moonshot-v1-8k（或控制台里可用的 kimi 系列模型 ID）
API Key:  专家自己的 sk-...
```

模型名以 Moonshot 控制台当前提供的为准。

## WorkBuddy

在 WorkBuddy 控制台找到它的 **OpenAI 兼容接口**：

```
Base URL: 控制台给出的 .../v1
模型名:   控制台给出的模型 ID
API Key:  专家自己的 key
```

## 其他常见服务

| 服务 | Base URL 示例 |
|---|---|
| DeepSeek | `https://api.deepseek.com/v1` |
| 通义千问（兼容模式） | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` |
| 本地 vLLM / Ollama | `http://127.0.0.1:8000/v1` |

模型名和 key 都填服务商文档里的值。

## 注意事项

- 接口必须兼容 `POST {base}/chat/completions`，返回 `choices[0].message.content`；
- 平台会发送**当前症状文本 + 编号来源**，不会上传历史对话、用药记录或图片；
- 第三方模型可能不支持 `reasoning_effort`、`response_format` 等参数，平台已自动跳过/降级；
- 第一次调用通常 30–60 秒；相同问题再次提问会走缓存；
- 如果模型输出没通过安全审查，平台会显示「已降级」并说明原因，不会假装是模型结果。

## 专家复现建议

1. 先用自己的 key 在「自定义接口」里问一个简单问题，确认能出报告；
2. 如果看到「已降级」，展开轨迹看审查原因（引用不匹配、缺免责声明等）；
3. 需要严格对比时，固定同一个模型名和温度。

## 快速确认模型名（推荐）

1. 填好「接口地址」和「API Key」；
2. 点 **「测试连接 / 拉取模型」**；
3. 成功会显示找到的模型数量，并出现下拉框，直接选一个即可；
4. 失败会提示「接口返回 401/404，请检查地址或 Key」。

原理：平台代你请求 `{base}/models`，不会把 key 写进日志或数据库。

## 新界面（v2026-11-12）

「⚙ 自定义接口」改为供应商配置式：

- **供应商名称**：随便起，例如 Kimi、WorkBuddy，激活后显示在模型下拉框；
- **API 地址**：Base URL（到 `/v1` 为止），服务器已预填演示网关；
- **API 密钥**：可点「添加 API 密钥」存多个，请求使用第一个；
- **API 格式**：OpenAI / Anthropic 两种，平台分别调用 `/chat/completions` 和 `/messages`；
- **Responses API**：暂未支持，开关置灰（避免 404）；
- **模型优先级**：可添加多个模型，按顺序尝试，前一个失败自动换下一个；
- **从服务商拉取模型列表**：调用 `{base}/models` 填入可选模型；
- **测试连接并激活**：成功后自动保存并切换到该供应商；
- **完成**：不测试，直接保存。

密钥仍只存在浏览器 sessionStorage，不上传、不入库。

