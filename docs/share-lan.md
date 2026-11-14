# 让舍友的电脑访问

平台默认只监听本机。给舍友用有两种方式：**同一局域网**（快、稳定）或**公网临时链接**（跨网络、无需配置）。

## 方式 A：同一局域网（推荐，需要管理员权限一次）

### 1. 服务已经在 WSL 里监听 `0.0.0.0:8100`

已配置好，无需再改。Windows 本机可用 `http://127.0.0.1:8100` 访问。

### 2. 在 Windows 上开端口转发（管理员 PowerShell）

右键开始菜单 → **终端(管理员)**，运行：

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\32693\Downloads\wsl\share-lan.ps1"
```

脚本会：

- 读取当前 WSL 的 IP；
- 把 Windows 的 8100 端口转发到 WSL 的 8100；
- 放行防火墙入站 TCP 8100；
- 打印舍友应访问的地址。

### 3. 舍友访问

```
http://<你的 Windows 局域网 IP>:8100
```

例如 `http://10.13.104.58:8100`（IP 以脚本输出为准）。

要求：两台电脑连同一个 Wi-Fi/路由器，且 Windows 网络配置为"专用网络"。

### 4. 重启后 WSL IP 会变

WSL 每次重启 IP 可能变化，重新运行一次 `share-lan.ps1` 即可。

### 5. 撤销

```powershell
netsh interface portproxy delete v4tov4 listenport=8100 listenaddress=0.0.0.0
Remove-NetFirewallRule -DisplayName "Health Agent 8100"
```

## 方式 B：公网链接（跨网络，立即可用）

本机已开 localhost.run 隧道：

```
https://<当前隧道域名>.lhr.life
```

舍友在任何网络都能打开，只要这台电脑开着、隧道没断。

隧道断了重开：

```bash
ssh -o StrictHostKeyChecking=no -R 80:localhost:8100 nokey@localhost.run
```

## 注意

- 平台是单用户演示版，**没有登录**：同一局域网内知道地址的人都能看到演示数据；
- 只建议在宿舍/家庭网络使用，不要直接暴露到公网；
- 公网隧道域名会变，长期使用请部署到云服务器（见 `docs/deploy.md`）。
