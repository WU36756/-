# 部署与运行

## 方式一：本机直接运行（推荐演示）

```bash
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100
# 或使用 systemd 服务
sudo systemctl restart health-panel.service
```

打开：<http://127.0.0.1:8100>

要求：Python 3.12+、`uv`；首次运行会自动建 SQLite 表并带演示数据。

## 方式二：Docker（推荐提交/复现）

```bash
docker compose up --build -d
```

打开：<http://127.0.0.1:8100>

- 镜像只装核心依赖（FastAPI/uvicorn/httpx/pydantic/pywebpush），约 200MB；
- 食物图片识别需要 torch/CLIP，默认不在镜像内；需要时：

```bash
docker compose exec health-agent pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
docker compose exec health-agent pip install clip-anytorch
```

- 数据卷：`./backend/data` 挂载到容器内，删库即重置；
- 断网演示：`DEMO_OFFLINE=1 docker compose up -d`。

## 方式三：公网临时链接（评委远程看）

本机没有公网 IP，用 localhost.run 的 SSH 反向隧道：

```bash
ssh -o StrictHostKeyChecking=no -R 80:localhost:8100 nokey@localhost.run
```

终端会输出形如 `https://xxxx.lhr.life` 的地址，其他人可直接打开。

注意：

- 域名会周期性更换，**机器关机/断网就失效**；
- 只适合演示期间临时开放，不要放敏感数据；
- 需要长期稳定地址时，用云服务器 + Docker：

```bash
# 云服务器上
git clone <repo> && cd health-agent-platform
docker compose up -d
# 配 Nginx/HTTPS 反代 8100
```

## 当前演示地址

- 本机：<http://127.0.0.1:8100>
- 临时公网：`https://9d3e55599b2ce3.lhr.life`（随隧道变化，以终端输出为准）

## 验证

```bash
curl -s http://127.0.0.1:8100/api/health
# {"status":"ok","cache":{"entries":0,"ttl_seconds":600}}
```

## 提交物里放什么

- 源码 zip（不含 `.venv`、`out/`、缓存）；
- `Dockerfile` + `docker-compose.yml`（一条命令复现）；
- `docs/方案书.md` / `健康助手-方案书.docx`；
- `docs/demo-script.md`、`docs/video-script.md`、`docs/boundary.md`。
