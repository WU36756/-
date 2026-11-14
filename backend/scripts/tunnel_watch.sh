#!/bin/bash
# 公网隧道看护：每 30 秒检查一次，挂了自动重连并更新 /tmp/tunnel.log
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

URL=""

get_url() {
  sed -r 's/\x1b\[[0-9;]*[mK]//g' /tmp/tunnel.log 2>/dev/null \
    | grep -aoE 'https://[a-zA-Z0-9]+\.lhr\.life' | tail -1
}

start_tunnel() {
  pkill -f "ssh.*localhost.run" 2>/dev/null
  sleep 2
  nohup ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 \
    -o ExitOnForwardFailure=yes -R 80:localhost:8100 nokey@localhost.run \
    > /tmp/tunnel.log 2>&1 &
  sleep 12
}

while true; do
  URL=$(get_url)
  if [ -z "$URL" ] || ! curl -fsS -m 10 "$URL/api/health" >/dev/null 2>&1; then
    start_tunnel
    URL=$(get_url)
  fi
  if [ -n "$URL" ]; then
    echo "$URL" > "/mnt/c/Users/32693/Desktop/健康助手-当前地址.txt" 2>/dev/null || true
  fi
  sleep 30
done
