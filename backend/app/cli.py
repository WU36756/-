"""CLI: analyze symptoms and write out/report.{md,json}."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .pipeline import analyze


def main() -> int:
    parser = argparse.ArgumentParser(description="Health agent platform (M1)")
    parser.add_argument("--symptoms", required=True)
    parser.add_argument("--provider", default=None, choices=["mock", "deepseek"])
    parser.add_argument("--answers", default=None, help='JSON answers, e.g. \'{"chills":"明显怕冷"}\'')
    parser.add_argument("--out", default="out")
    args = parser.parse_args()

    answers = json.loads(args.answers) if args.answers else None
    api_key = os.environ.get("APP_DEEPSEEK_API_KEY") or None
    result = analyze(args.symptoms, provider=args.provider, api_key=api_key, answers=answers)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "report.md").write_text(result["report_markdown"], encoding="utf-8")
    print(result["report_markdown"])
    print()
    print(f"[provider={result['provider']} urgent={result['triage']['urgent']} "
          f"decision={(result.get('differentiation') or {}).get('decision')} "
          f"tcm={len(result.get('tcm') or [])} followups={len(result.get('followups') or [])} "
          f"evidence={len(result.get('evidence') or [])} review_passed={result['review']['passed']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
