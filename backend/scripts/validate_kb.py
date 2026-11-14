#!/usr/bin/env python3
"""Validate the curated knowledge bases before they ship.

Checks structure (required fields, unique ids), dosing format, price format,
OTC labelling, and a safety blacklist of risky materials. Exits non-zero when
anything must be fixed, so a growing KB cannot silently degrade.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TCM = ROOT / "app" / "data" / "tcm.json"
WESTERN = ROOT / "app" / "data" / "western.json"

REQUIRED_TCM = {"id", "kind", "name", "form", "otc", "pattern", "pattern_tag",
                "indications", "symptom_keys", "dosage", "contraindications",
                "cautions", "price_range"}
REQUIRED_WESTERN = {"id", "name", "name_en", "matched_terms", "indications",
                    "dosage", "contraindications", "cautions", "price_range"}
RISKY = ("附子", "川乌", "草乌", "马钱子", "雄黄", "朱砂", "罂粟壳", "细辛", "雷公藤", "斑蝥")

errors: list[str] = []
warnings: list[str] = []


def check_tcm() -> int:
    items = json.loads(TCM.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for item in items:
        iid = item.get("id", "?")
        missing = REQUIRED_TCM - item.keys()
        if missing:
            errors.append(f"[tcm:{iid}] 缺字段 {sorted(missing)}")
        if iid in seen:
            errors.append(f"[tcm:{iid}] id 重复")
        seen.add(iid)
        kind = item.get("kind")
        if kind not in ("patent", "herb"):
            errors.append(f"[tcm:{iid}] kind 必须是 patent/herb，实际 {kind}")
        if kind == "patent" and "OTC" not in str(item.get("otc", "")):
            errors.append(f"[tcm:{iid}] 中成药缺少 OTC 标识")
        if kind == "herb" and item.get("otc") != "中药材":
            warnings.append(f"[tcm:{iid}] 中药材 otc 应为 '中药材'")
        if not str(item.get("dosage", "")).strip():
            errors.append(f"[tcm:{iid}] 缺用法")
        if "元" not in str(item.get("price_range", "")):
            warnings.append(f"[tcm:{iid}] 价格格式异常: {item.get('price_range')}")
        for risky in RISKY:
            if risky in item.get("name", ""):
                warnings.append(f"[tcm:{iid}] 含风险药材 {risky}，需人工复核剂量与禁忌")
    return len(items)


def check_western() -> int:
    items = json.loads(WESTERN.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for item in items:
        iid = item.get("id", "?")
        missing = REQUIRED_WESTERN - item.keys()
        if missing:
            errors.append(f"[western:{iid}] 缺字段 {sorted(missing)}")
        if iid in seen:
            errors.append(f"[western:{iid}] id 重复")
        seen.add(iid)
        if not item.get("matched_terms"):
            errors.append(f"[western:{iid}] matched_terms 为空（不会被检索到）")
    return len(items)


def main() -> int:
    tcm_count = check_tcm()
    western_count = check_western()
    print(f"中药条目 {tcm_count}，西药条目 {western_count}")
    for warning in warnings:
        print("WARN", warning)
    for error in errors:
        print("ERROR", error)
    if errors:
        print(f"\n{len(errors)} 个错误，需修复")
        return 1
    print("校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
