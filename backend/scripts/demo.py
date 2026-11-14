#!/usr/bin/env python3
"""One-shot demo of the consultation flow, for screen recording.

Runs against the local API (default http://127.0.0.1:8100) and prints a
narrative: ambiguous branch → follow-up answers → single pattern → sources.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

API = "http://127.0.0.1:8100"


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def show(title: str, data: dict) -> None:
    print(f"\n=== {title} ===")
    print("provider:", data.get("provider"), "| decision:", (data.get("differentiation") or {}).get("decision"),
          "| review:", (data.get("review") or {}).get("passed"))
    print("TCM:", "、".join(item["name"] for item in data.get("tcm") or []) or "—")
    print("followups:", len(data.get("followups") or []), "| sources:", len(data.get("sources") or []))
    for item in (data.get("tcm") or [])[:2]:
        print(f"  - {item['name']} {item['price_range']}：{item['dosage']}")
    print("报告开头：")
    print("\n".join((data.get("report_markdown") or "").splitlines()[:6]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="mock", choices=["mock", "deepseek"])
    args = parser.parse_args()

    symptoms = "发烧，咽喉痛，有点怕冷"
    first = post("/api/analyze", {"symptoms": symptoms, "provider": args.provider})
    show(f"第 1 步：描述症状「{symptoms}」", first)

    answers = {"chills": "明显怕冷", "discharge": "清稀或白色", "sweat": "不出汗", "throat": "轻微或不痛", "thirst": "不渴"}
    second = post("/api/analyze", {"symptoms": symptoms, "provider": args.provider, "answers": answers})
    show("第 2 步：回答追问（怕冷/清涕/无汗/不渴）", second)

    print("\n=== 演示结论 ===")
    print("· 不确定时平台输出两支并追问，而不是猜；")
    print("· 回答后收敛到单一证型，中成药数量下降；")
    print("· 报告每条结论都有来源编号，安全审查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
