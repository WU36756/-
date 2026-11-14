# 部署到公网服务器（比赛演示版）

> 目标：评委和舍友用浏览器访问一个 HTTPS 地址，输入访问码后使用。
> 应用本身不内置登录，**公网必须由 Caddy 加 Basic Auth**，并把 8100 只绑在本机。

## 0. 你需要准备

- 一台 Ubuntu 22.04/24.04 服务器（2 核 2G 起，带公网 IP）；
- 一个域名（可选，但 HTTPS + 访问码强烈建议；没有域名可用 `https://IP` 自签，不推荐）；
- 安全组/防火墙放行 **80、443**，**不要**放行 8100；
- 一个给评委的访问码（用户名 `demo` + 密码，自己定）；
- 是否保留 `sshzyu.com` 网关默认值（只是地址，不含 key）。

## 1. 建用户和目录

```bash
sudo adduser --system --group --home /opt/health-agent health
sudo mkdir -p /opt/health-agent
sudo chown -R health:health /opt/health-agent
```

把项目代码（至少 `backend/`、`data/` 不在 git 里就单独拷）放到 `/opt/health-agent/backend`。

## 2. 安装依赖

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv sqlite3
# 以 health 用户执行
sudo -u health bash
cd /opt/health-agent/backend
python3.12 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e .
exit
```

图片识别功能已移除，不需要 torch/CLIP；部署只需要 FastAPI 和页面依赖。

## 3. 配置环境变量

```bash
sudo install -m 600 -o root -g root deploy/env.example /etc/health-panel.env
sudo editor /etc/health-panel.env
```

必改：

- `APP_DEEPSEEK_API_KEY=` 填服务器要用的 key（或留空，让用户自带）；
- `APP_CUSTOM_API_BASE/MODEL` 按需；
- `APP_DEMO_RESET_ENABLED=false`（公网必须）；
- `APP_RATE_LIMIT_PER_MINUTE=30`（按需）。

## 4. systemd 服务

```bash
sudo cp deploy/health-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now health-panel
sudo systemctl status health-panel
curl -s http://127.0.0.1:8100/api/health
```

服务只监听 `127.0.0.1:8100`，公网访问不到。

## 5. Caddy：HTTPS 反向代理

应用自己带访问码登录页，**不需要再配 Caddy Basic Auth**（否则会弹两次登录）。

```bash
sudo apt install -y caddy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo editor /etc/caddy/Caddyfile   # 把域名换成你的
sudo systemctl reload caddy
```

验证：浏览器打开 `https://你的域名`，应该看到「健康助手 · 输入访问码」页面；输入 `/etc/health-panel.env` 里的 `APP_ACCESS_CODE` 进入。

每个新空间只复制主库的表结构，随后清空并重置为演示数据（不含主库里的测试对话/资料）；每个浏览器首次输入访问码后会分配一个独立数据空间（独立 SQLite 文件，位于 `data/users/`），会话之间互不可见；清 Cookie 或换浏览器等于换新空间。

> 本地用 http 调试访问码时，把 `APP_COOKIE_SECURE` 设为 `false`；公网 HTTPS 必须为 `true`。

## 6. 备份

```bash
sudo mkdir -p /var/backups/health-agent
sudo install -m 700 deploy/backup.sh /usr/local/bin/health-backup
# 每天 3:17 备份，保留 14 天
echo "17 3 * * * root /usr/local/bin/health-backup" | sudo tee /etc/cron.d/health-backup
```

恢复：停服务 → 解压备份覆盖 `data/health.db` → 起服务。

## 7. 上线前检查

- [ ] `http://服务器IP:8100` 打不开（只绑 127.0.0.1）；
- [ ] 直接访问域名出现访问码登录页，输入错误码返回 401；
- [ ] 登录后 `/api/profile` 返回自己的数据；换一个浏览器登录，看不到上一个浏览器的会话；
- [ ] `/api/demo/reset` 只影响当前浏览器空间；
- [ ] 页面「自定义接口」填自己的 key，点“测试连接并激活”能通过；
- [ ] 手机 4G 访问一次，确认不是只通内网；
- [ ] 关闭本机 localhost.run / ssh 隧道，避免绕过访问码；
- [ ] `data/health.db` 权限为 health 用户，`/etc/health-panel.env` 为 root 600；
- [ ] 用演示数据跑一遍完整问诊，清空测试会话和个人资料。

## 8. 常见问题

- **弹不出登录框**：Caddy 未 reload 或哈希填错；`caddy validate --config /etc/caddy/Caddyfile`。
- **502**：服务没起或端口不对；`journalctl -u health-panel -n 100`。
- **问诊 1–2 分钟**：多 Agent 串行调用，正常；同问题会走缓存。
- **评委用自己的 key 仍降级**：先在页面点“测试连接并激活”，失败会显示 401/404/超时原因。
- 图片识别功能已下线；食物问题请直接输入中文名，例如“西兰花健康吗”。

## 9. 安全边界（必须知道）

- 应用没有账号体系，**访问码是唯一门槛**；不要把无访问码的地址发到群里；
- 服务器上的 DeepSeek key 只放在 `/etc/health-panel.env`，不要写进 git；
- 自定义接口默认禁止访问内网/本机地址（防 SSRF），本地模型需要显式 `APP_ALLOW_PRIVATE_CUSTOM=true`；
- 日志/数据库含用户症状，属于敏感信息，备份和日志要限权、定期清理；
- 演示结束建议重置数据库或换 key。
