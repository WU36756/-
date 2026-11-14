"""Personalise diet/exercise advice with the user's profile and medications."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def _add(target: list[str], line: str) -> None:
    if line and line not in target:
        target.append(line)


def apply(lifestyle: dict[str, Any] | None, profile: dict[str, Any] | None,
          medications: list[dict[str, Any]] | None, triage: Any = None) -> dict[str, Any]:
    plan = deepcopy(lifestyle or {})
    diet = list(plan.get("diet") or [])
    exercise = list(plan.get("exercise") or [])
    avoid = list(plan.get("avoid") or [])
    notes: list[str] = []

    profile = profile or {}
    allergies = [str(item) for item in (profile.get("allergies") or []) if item]
    conditions = [str(item) for item in (profile.get("conditions") or []) if item]
    pregnant = bool(profile.get("pregnant"))
    try:
        age = int(profile.get("age") or 0)
    except (TypeError, ValueError):
        age = 0
    meds = " ".join(str(item.get("name") or "") for item in (medications or []))
    diet_pref = str(profile.get("diet_pref") or "").strip()
    avoid_foods = [item.strip() for item in str(profile.get("avoid_foods") or "")
                   .replace("，", ",").split(",") if item.strip()]
    meal_style = str(profile.get("meal_style") or "").strip()
    activity_level = str(profile.get("activity_level") or "").strip()
    daily_actions: list[str] = []

    if pregnant:
        _add(diet, "孕期：补充叶酸和铁，肉类蛋类彻底煮熟")
        _add(avoid, "孕期避免酒精、生食、未消毒奶制品")
        _add(exercise, "孕期以散步等温和活动为主，避免仰卧和跳跃动作")
        notes.append("已按孕期调整")

    if any("糖尿病" in item for item in conditions):
        _add(diet, "糖尿病：主食选低 GI、控制水果份量，避免含糖饮料")
        _add(avoid, "糖尿病：血糖不稳时少吃蜂蜜、粥类等升糖快的食物")
        notes.append("已按糖尿病调整")

    if any("高血压" in item for item in conditions):
        _add(diet, "高血压：每日盐不超过 5 g，少腌制和加工食品")
        notes.append("已按高血压调整")

    if allergies:
        _add(avoid, "明确过敏原：" + "、".join(allergies) + "（含同类食物/药物）")
        notes.append("已避开过敏原")

    if age >= 65:
        _add(diet, "老年：保证优质蛋白，食物软烂易咀嚼")
        _add(exercise, "老年：选低冲击运动，注意防跌倒")
        notes.append("已按年龄调整")

    if "华法林" in meds:
        _add(diet, "服用华法林：绿叶蔬菜摄入保持稳定，不要突然大量增减")
        notes.append("已按华法林调整")
    if any(word in meds for word in ("布洛芬", "阿司匹林", "双氯芬酸")):
        _add(diet, "服用止痛药：饭后服用，避免空腹和饮酒")
        notes.append("已按止痛药调整")
    if "丹参" in meds:
        _add(avoid, "服用丹参：避免饮酒，注意与抗凝药同用风险")
        notes.append("已按丹参调整")

    if diet_pref == "素食":
        _add(diet, "素食：每餐用豆腐/豆制品/鸡蛋/奶补足蛋白；全素注意维生素 B12 和铁")
        _add(avoid, "素食：不要只吃精制主食，搭配豆类和坚果")
        notes.append("已按素食偏好调整")
        daily_actions.append("检查今天是否吃到豆制品或蛋奶")
    elif diet_pref == "高蛋白":
        _add(diet, "高蛋白：每餐一掌心蛋白，训练后 1 小时内补充蛋白+碳水")
        notes.append("已按高蛋白偏好调整")
    elif diet_pref == "控糖":
        _add(diet, "控糖：先吃菜和蛋白，主食每餐 1 拳，水果放两餐之间")
        notes.append("已按控糖偏好调整")
    elif diet_pref == "低盐":
        _add(diet, "低盐：用醋、柠檬、香辛料代替盐，少蘸酱和喝汤")
        notes.append("已按低盐偏好调整")
    elif diet_pref == "清淡":
        _add(diet, "清淡：优先蒸、煮、炖，少油炸和浓汤")
        notes.append("已按清淡偏好调整")

    if avoid_foods:
        _add(avoid, "个人忌口：" + "、".join(avoid_foods) + "（点餐/买包装食品前看配料表）")
        notes.append("已避开个人忌口")
        daily_actions.append("检查今天是否误吃了忌口食物")

    if meal_style == "外卖":
        _add(diet, "外卖：选蒸煮炖，酱汁分开放，主食减半或用粗粮")
        notes.append("已按外卖场景调整")
    elif meal_style == "食堂":
        _add(diet, "食堂：先夹蔬菜和蛋白，主食 1 拳，菜汤少喝")
        notes.append("已按食堂场景调整")
    elif meal_style == "自己做":
        _add(diet, "自己做：一次备好 2–3 份，冷藏分装，少油少盐")
        notes.append("已按自己做调整")

    if activity_level == "久坐":
        _add(exercise, "久坐：每小时起身 2–3 分钟，先从每天 10 分钟散步开始")
        notes.append("已按久坐状态降低运动门槛")
        daily_actions.append("每坐 1 小时起身活动 2 分钟")
    elif activity_level == "规律运动":
        _add(exercise, "已有运动习惯：保持每周 3 次，注意恢复和睡眠")
        notes.append("已按规律运动调整")

    if any("高血压" in item for item in conditions):
        daily_actions.append("早晚各测一次血压并记录")
    if any("糖尿病" in item for item in conditions):
        daily_actions.append("记录空腹或餐后 2 小时血糖")
    if any("痛风" in item for item in conditions):
        daily_actions.append("饮水达到 2000 ml，记录高嘌呤食物")
    if age >= 65:
        daily_actions.append("检查家中地面防滑，做 5 分钟平衡练习")
    if any("华法林" in str(item.get("name") or "") for item in (medications or [])):
        daily_actions.append("观察牙龈、皮肤有无异常出血")

    if getattr(triage, "high_fever", False):
        _add(diet, "高热：少量多次补水，必要时口服补液盐")
        notes.append("已按高热调整")

    plan["diet"] = diet
    plan["exercise"] = exercise
    plan["avoid"] = avoid
    plan["notes"] = notes
    plan["daily_actions"] = list(dict.fromkeys(daily_actions))
    return plan
