"""Offline tests: triage, allowlist, citations, report review."""

from app.report import DISCLAIMER, citation_numbers, review_report
from app.sources import english_terms, is_allowed
from app.triage import triage


def test_red_flag_short_circuits() -> None:
    result = triage("胸痛，喘不上气")
    assert result.urgent
    assert result.reasons


def test_sensitive_group_detected() -> None:
    assert triage("孕妇头痛").sensitive


def test_allowlist() -> None:
    assert is_allowed("https://www.nhs.uk/conditions/headache/")
    assert is_allowed("https://api.fda.gov/drug/label.json")
    assert not is_allowed("https://example.com/health")
    assert not is_allowed("https://www.nhs.uk.evil.com/x")


def test_english_terms() -> None:
    assert "headache" in english_terms("头痛发烧")


def test_citation_numbers() -> None:
    assert citation_numbers("见 [1] 与 [2]") == {1, 2}


def test_review_flags_missing_disclaimer() -> None:
    review = review_report("头疼可以吃布洛芬。", [], triage("头痛"))
    assert not review.passed
    assert any("免责声明" in item for item in review.findings)


def test_review_flags_unsourced_dose() -> None:
    markdown = f"布洛芬 200mg。\n{DISCLAIMER}\n[1] 来源"
    review = review_report(markdown, [{"title": "x", "url": "u", "source": "s", "retrieved_at": "t"}], triage("头痛"))
    assert any("剂量" in item for item in review.findings)


# --- PubMed query strategy (problem 1) ---

from app import pubmed_query


def test_strict_query_is_field_tagged_and_review_filtered() -> None:
    query = pubmed_query.build_query("headache fever")
    assert "[tiab]" in query
    assert "guideline[pt]" in query


def test_relaxed_query_has_no_type_filter() -> None:
    query = pubmed_query.build_query("headache", strict=False)
    assert "[tiab]" in query
    assert "guideline[pt]" not in query


def test_relevance_filter_drops_unrelated_titles() -> None:
    assert pubmed_query.is_relevant("Management of tension-type headache", ["headache"])
    assert not pubmed_query.is_relevant("Malaria vaccine trial in children", ["headache"])


def test_ranking_prefers_guideline_over_case_report() -> None:
    items = [
        {"title": "Headache case report", "pubtype": ["Case Reports"], "pubdate": "2024"},
        {"title": "Headache guideline", "pubtype": ["Practice Guideline"], "pubdate": "2019"},
    ]
    selected = pubmed_query.select(items, ["headache"], 2)
    assert selected[0]["title"] == "Headache guideline"


def test_select_falls_back_when_nothing_is_relevant() -> None:
    items = [{"title": "Unrelated study", "pubtype": [], "pubdate": "2024"}]
    assert pubmed_query.select(items, ["headache"], 2)


# --- TCM-first knowledge base ---

from app import tcm as tcm_mod
from app.report import review_report as review_report_tcm
from app.triage import triage as triage_tcm


def test_kb_is_otc_only_and_priced() -> None:
    kb = tcm_mod.load_kb()
    assert len(kb) >= 20
    assert all(("OTC" in item["otc"]) or item.get("kind") == "herb" for item in kb)
    assert all(item["price_range"] and item["dosage"] for item in kb)


def test_tcm_search_matches_symptoms():
    items = tcm_mod.search_tcm("\u53d1\u70e7\uff0c\u54bd\u5589\u75db", limit=8)
    names = [item["name"] for item in items]
    assert names
    assert any(name in names for name in (
        "\u5c0f\u67f4\u80e1\u9897\u7c92", "\u94f6\u7fd8\u89e3\u6bd2\u7247",
        "\u677f\u84dd\u6839\u9897\u7c92", "\u82a6\u6839", "\u8fde\u7fd8",
        "\u9c7c\u8165\u8349", "\u8584\u8377"))


def test_recommend_has_mixed_forms():
    from app.tcm import recommend

    items = recommend("\u53d1\u70e7\uff0c\u54bd\u5589\u75db", "not_applicable")
    assert len(items) >= 3
    assert any(item.get("kind") == "patent" for item in items)
    assert any(item.get("kind") == "herb" for item in items)


def test_high_fever_flagged() -> None:
    assert triage_tcm("高烧39度").high_fever
    assert not triage_tcm("低热").high_fever


def test_review_requires_tcm_citation() -> None:
    markdown = "建议多喝水。\n\n**免责声明**：仅供参考。\n\n[1] 某来源"
    review = review_report_tcm(markdown, [], triage_tcm("头痛"), [{"name": "感冒清热颗粒"}])
    assert not review.passed
    assert any("中成药" in finding for finding in review.findings)


def test_negated_diagnosis_is_allowed() -> None:
    from app.report import DISCLAIMER, review_report
    from app.triage import triage as triage_fn
    markdown = f"不能据此确诊为任何疾病。\n{DISCLAIMER}\n[1] 来源"
    review = review_report(markdown, [{"title": "x", "url": "u", "source": "s", "retrieved_at": "t"}], triage_fn("头痛"))
    assert not any("确诊" in finding for finding in review.findings)


def test_affirmative_diagnosis_is_blocked() -> None:
    from app.report import DISCLAIMER, review_report
    from app.triage import triage as triage_fn
    markdown = f"你确诊为感冒。\n{DISCLAIMER}\n[1] 来源"
    review = review_report(markdown, [{"title": "x", "url": "u", "source": "s", "retrieved_at": "t"}], triage_fn("头痛"))
    assert any("确诊" in finding for finding in review.findings)


# --- wind-cold vs wind-heat differentiation ---

from app.differentiation import differentiate
from app.report import template_report
from app.tcm import search_tcm
from app.triage import triage as triage_diff


def test_ambiguous_when_no_markers() -> None:
    assert differentiate("发烧，咽痛")["decision"] == "ambiguous"


def test_cold_markers_decide() -> None:
    assert differentiate("发烧，怕冷，清鼻涕，不出汗")["decision"] == "cold"


def test_heat_markers_decide() -> None:
    assert differentiate("发烧，咽痛，黄痰，口渴，容易出汗")["decision"] == "heat"


def test_answers_can_decide() -> None:
    decision = differentiate("发烧", {"chills": "明显怕冷", "discharge": "清稀或白色", "sweat": "不出汗"})
    assert decision["decision"] == "cold"


def test_branch_report_contains_both_branches() -> None:
    symptoms = "发烧，咽痛"
    diff = differentiate(symptoms)
    tcm = [item for item in search_tcm(symptoms, limit=6) if item.get("pattern_tag") in diff["tags"]]
    markdown = template_report(symptoms, triage_diff(symptoms), [], tcm, [], diff, diff["followups"])
    assert diff["decision"] == "ambiguous"
    assert "若偏风寒" in markdown and "若偏风热" in markdown
    assert diff["followups"]


def test_decided_report_has_single_branch() -> None:
    symptoms = "发烧，怕冷，清鼻涕，不出汗"
    diff = differentiate(symptoms)
    tcm = [item for item in search_tcm(symptoms, limit=6) if item.get("pattern_tag") in diff["tags"]]
    markdown = template_report(symptoms, triage_diff(symptoms), [], tcm, [], diff, diff["followups"])
    assert diff["decision"] == "cold"
    assert "若偏风热" not in markdown


def test_kb_expansion_covers_more_symptoms() -> None:
    for symptoms, expected in (
        ("胃胀，反酸", "香砂养胃丸"),
        ("压力大，情绪郁闷", "逍遥丸"),
        ("腰酸，耳鸣，盗汗", "六味地黄丸"),
        ("痛经，有血块", "益母草颗粒"),
    ):
        names = [item["name"] for item in tcm_mod.search_tcm(symptoms)]
        assert expected in names, f"{expected} not matched for {symptoms}"


# --- citation anchoring (problem 2) ---

from app.citations import citation_numbers as cite_numbers
from app.citations import verify_citations


def test_citation_range_expands() -> None:
    assert cite_numbers("见 [1-3] 与 [5]") == {1, 2, 3, 5}


def test_matching_citation_passes() -> None:
    sources = [{"title": "板蓝根颗粒说明书", "snippet": "咽喉肿痛，感冒初起，口咽干燥"}]
    assert verify_citations("板蓝根颗粒适用于咽喉肿痛、口咽干燥，也可用于感冒初起时服用[1]。", sources) == []


def test_unrelated_citation_is_flagged() -> None:
    sources = [{"title": "板蓝根颗粒说明书", "snippet": "咽喉肿痛，感冒初起"}]
    findings = verify_citations("板蓝根颗粒适用于高血压、糖尿病和心脏病患者长期服用治疗[1]。", sources)
    assert findings and "引用 [1]" in findings[0]


def test_dosage_number_must_match_source() -> None:
    sources = [{"title": "板蓝根颗粒说明书", "snippet": "开水冲服，一次 1 袋，一日 3–4 次"}]
    ok = verify_citations("板蓝根颗粒应使用开水冲服，一次 1 袋，一日 3 次，按说明书使用[1]。", sources)
    bad = verify_citations("板蓝根颗粒应使用开水冲服，一次 5 袋，一日 9 次，按说明书使用[1]。", sources)
    assert ok == []
    assert bad and "引用 [1]" in bad[0]


def test_cross_language_citation_is_not_flagged() -> None:
    sources = [{"title": "2025 guideline update to acute treatment of migraine", "snippet": "American Headache Society"}]
    assert verify_citations("偏头痛急性期治疗指南推荐该方案[1]。", sources) == []


# --- anchoring: high-risk claims only ---

from app.citations import verify_citations as verify2


def test_disclaimer_and_questions_are_not_anchored() -> None:
    sources = [{"title": "板蓝根颗粒说明书", "snippet": "咽喉肿痛，感冒初起"}]
    text = "> **免责声明**：本报告仅供信息参考，不能替代医生面诊[1]。\n是否怕冷？[1]"
    assert verify2(text, sources) == []


def test_drug_claim_with_wrong_fact_is_flagged() -> None:
    sources = [{"title": "板蓝根颗粒说明书", "snippet": "咽喉肿痛，感冒初起，口咽干燥"}]
    findings = verify2("板蓝根颗粒可治愈高血压与糖尿病且没有任何副作用[1]。", sources)
    assert findings and "引用 [1]" in findings[0]


def test_meta_sentence_is_skipped() -> None:
    sources = [{"title": "板蓝根颗粒说明书", "snippet": "咽喉肿痛"}]
    assert verify2("- 来源均为单药说明书，没有提供联合用药方案[1]。", sources) == []


# --- relevance gating: insomnia must not get wind-cold drugs ---

from app.differentiation import is_respiratory
from app.report import template_report as template_report_gate
from app.triage import triage as triage_gate


def test_respiratory_detection() -> None:
    assert is_respiratory("发烧，咽喉痛")
    assert is_respiratory("咳嗽三天，有黄痰")
    assert not is_respiratory("我现在有点失眠")
    assert not is_respiratory("胃胀，反酸")


def test_non_respiratory_report_has_no_wind_cold_branch() -> None:
    symptoms = "我现在有点失眠"
    tcm = [{"id": "anshen", "name": "安神补脑液", "otc": "甲类 OTC", "form": "口服液",
            "pattern": "气血两虚/失眠", "pattern_tag": "虚证", "indications": ["失眠", "健忘"], "price_range": "约 20–40 元/盒",
            "dosage": "口服，一次 10 ml，一日 2 次（见来源 [1]）",
            "contraindications": "对本品过敏者禁用", "cautions": "长期失眠应就医",
            "matched": ["失眠"]}]
    evidence = [{"source": "www.nhs.uk", "title": "Insomnia", "url": "https://www.nhs.uk/conditions/insomnia/",
                 "snippet": "Insomnia means you regularly have problems sleeping. See a GP if it keeps happening.",
                 "retrieved_at": "2026-11-10"}]
    diff = {"decision": "not_applicable", "scores": {"cold": 0, "heat": 0}, "tags": [], "reason": None}
    markdown = template_report_gate(symptoms, triage_gate(symptoms), evidence, tcm, [], diff, [])
    assert "若偏风寒" not in markdown and "若偏风热" not in markdown
    assert "安神补脑液" in markdown
    assert "权威指南要点" in markdown


# --- 4-5 options, patent medicines + herbs ---

from app.tcm import recommend


def test_not_applicable_gives_four_to_five_with_herbs() -> None:
    items = recommend("我现在有点失眠", "not_applicable")
    assert 4 <= len(items) <= 5
    assert any(item.get("kind") == "herb" for item in items)
    assert any(item.get("kind", "patent") == "patent" for item in items)


def test_ambiguous_gives_four_to_five_total():
    items = recommend("发烧，咽喉痛，有点怕冷", "ambiguous")
    cold = [i for i in items if i.get("pattern_tag") == "风寒"]
    heat = [i for i in items if i.get("pattern_tag") == "风热"]
    assert 4 <= len(items) <= 5
    assert cold and heat
    assert any(i.get("kind") == "herb" for i in items)


def test_decided_pattern_gives_four_to_five() -> None:
    items = recommend("咳嗽三天，有黄痰", "heat", tag="风热")
    assert 4 <= len(items) <= 5


def test_yellow_phlegm_points_to_heat() -> None:
    from app.differentiation import differentiate as diff_fn
    decision = diff_fn("咳嗽三天，有黄痰")
    assert decision["decision"] == "heat"


def test_food_junk_rating_and_sources():
    from app import food

    items = food.search("可乐")
    assert items, "可乐 should be in the food KB"
    card = food.analyze(items[0])
    assert card["rating"] == "limit"
    assert card["harms"]
    assert any(src["url"].startswith("http") for src in card["sources"])


def test_food_healthy_rating():
    from app import food

    card = food.analyze(food.search("西兰花")[0])
    assert card["rating"] == "recommend"
    assert card["nutrition"]["energy_kcal"] > 0


def test_food_question_routing():
    from app import food

    assert food.should_route("西兰花健康吗")
    assert food.should_route("鸡胸肉热量高吗")
    assert not food.should_route("胃胀能吃西兰花吗")
    assert not food.should_route("我现在有点失眠")


def test_food_answer_shape():
    from app import food

    answer = food.answer("可乐是垃圾食品吗")
    assert answer["kind"] == "food"
    assert answer["analysis"]["rating_label"] in ("少吃 / 避免", "适量", "推荐")


def test_psych_conflict_is_warm():
    from app import psych

    answer = psych.respond("今天和室友吵了一架，心情不好")
    assert answer["kind"] == "psych"
    assert answer["topic"]["id"] == "conflict"
    assert any("宝宝" in line or "抱抱" in line for line in answer["empathy"])
    assert answer["suggestions"]


def test_psych_crisis_has_hotline():
    from app import psych

    answer = psych.respond("我不想活了")
    assert answer["crisis"] is True
    assert any("12356" in line for line in answer["suggestions"])


def test_psych_does_not_route_medical():
    from app import psych

    assert not psych.should_route("发烧，头痛")
    assert psych.should_route("最近压力很大，撑不住")


def test_psych_bullying_priority():
    from app import psych

    answer = psych.respond("被室友排挤，很难受")
    assert answer["topic"]["id"] == "bullying"


def test_router_four_intents():
    from app import router

    assert router.rules("你好")["intent"] == "chitchat"
    assert router.rules("今天和室友吵了一架")["intent"] == "psych"
    assert router.rules("西兰花健康吗")["intent"] == "food"
    assert router.rules("发烧，头痛")["intent"] == "medical"


def test_crisis_risk_levels():
    from app import psych

    assert psych.crisis_level("我已经买好了药，今晚就结束") == "high"
    assert psych.crisis_level("我不想活了") == "medium"
    assert psych.crisis_level("最近真的撑不下去了") == "low"


def test_crisis_response_has_hotlines():
    from app import psych

    answer = psych.respond("我不想活了")
    numbers = [item["number"] for item in answer["hotlines"]]
    assert "12356" in numbers
    assert answer["risk_level"] == "medium"


def test_chitchat_reply():
    from app import chitchat

    answer = chitchat.respond("你能做什么")
    assert answer["kind"] == "chitchat"
    assert "食物" in answer["reply"]


def test_safety_pregnancy_excludes_herbs():
    from app import safety

    tcm = [{"name": "益母草颗粒", "contraindications": "孕妇禁用"},
           {"name": "百合", "contraindications": "风寒咳嗽者不宜"}]
    result = safety.apply({"pregnant": True, "sex": "female"}, tcm, [])
    assert [item["name"] for item in result["tcm"]] == ["百合"]
    assert any("益母草颗粒" in line for line in result["warnings"])


def test_safety_allergy_excludes_drug():
    from app import safety

    western = [{"name": "布洛芬"}, {"name": "对乙酰氨基酚"}]
    result = safety.apply({"allergies": ["布洛芬"]}, [], western)
    assert [item["name"] for item in result["western"]] == ["对乙酰氨基酚"]
    assert any("过敏" in line for line in result["warnings"])


def test_safety_condition_and_interaction():
    from app import safety

    result = safety.apply({"conditions": ["胃溃疡"]}, [], [{"name": "布洛芬"}], [])
    assert any("胃溃疡" in line for line in result["warnings"])

    result = safety.apply({}, [], [{"name": "布洛芬"}], [{"name": "丹参片"}])
    assert any("出血" in line for line in result["warnings"])


def test_memory_extracts_allergy(tmp_path, monkeypatch):
    from app import memory

    import uuid

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    memory.init()
    name = "测试药" + uuid.uuid4().hex[:6]
    result = memory.observe(f"我对{name}过敏，最近有点失眠")
    assert any(item["type"] == "allergy" and item["value"] == name
               for item in result["new"])


def test_memory_notes_roundtrip(tmp_path, monkeypatch):
    from app import memory

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    memory.init()
    memory.add_note("test-conv", "失眠", "not_applicable；推荐：归脾丸")
    notes = memory.recent_notes(limit=1)
    assert notes and notes[0]["symptoms"] == "失眠"


def test_plan_checkin_and_adherence(tmp_path, monkeypatch):
    from app import plan

    monkeypatch.setattr(plan, "DB_PATH", tmp_path / "plan.db")
    plan.init()
    item = plan.ensure("测试失眠", {"diet": ["清淡饮食"], "exercise": ["散步"]})
    if item is None:
        item = plan.active()
    detail = plan.checkin(item["id"], True, True, True)
    assert detail["adherence"] >= 14
    assert detail["today"]["diet"] == 1


def test_plan_day3_and_day7_reminders(tmp_path, monkeypatch):
    import datetime
    import sqlite3

    from app import plan

    monkeypatch.setattr(plan, "DB_PATH", tmp_path / "plan.db")
    plan.init()
    start = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()
    conn = sqlite3.connect(plan.DB_PATH)
    conn.execute(
        "INSERT INTO plans (id, symptoms, summary, start_date, status, notified_d3,"
        " notified_d7, created_at) VALUES ('test-plan', '测试', '', ?, 'active', 0, 0,"
        " '2999-01-01T00:00:00')", (start,))
    conn.commit()
    kinds = {item["kind"] for item in plan.due()}
    conn.execute("UPDATE plans SET notified_d3 = 1, notified_d7 = 1 WHERE id = 'test-plan'")
    conn.execute("DELETE FROM plans WHERE id = 'test-plan'")
    conn.commit()
    conn.close()
    assert "d3" in kinds and ({"d7_review", "d7_good"} & kinds)


def test_cabinet_take_and_complete(tmp_path, monkeypatch):
    from app import cabinet

    monkeypatch.setattr(cabinet, "DB_PATH", tmp_path / "cabinet.db")
    cabinet.init()
    item = cabinet.add("测试药", 3)
    assert item["balls"] == 0
    first = cabinet.take(item["id"])
    assert first["taken"] == 1
    second = cabinet.take(item["id"])
    third = cabinet.take(item["id"])
    assert third["taken"] == 3 and third["completed"] == 1
    assert third["balls"] == 3
    assert third["just_completed"] is True
    cabinet.delete(item["id"])


def test_router_mixed_intent_does_not_ask():
    from app.router import rules

    for phrase in ("发烧，焦虑", "失眠，焦虑，压力大"):
        decision = rules(phrase)
        assert decision["intent"] != "clarify", phrase
        assert decision["intent"] in ("medical", "psych")


def test_router_drug_context_stays_medical():
    from app import router

    assert router.rules("吃药后失眠")["intent"] == "medical"


def test_memory_negation_skips_fact(tmp_path, monkeypatch):
    import uuid

    from app import memory

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    memory.init()
    name = "否定药" + uuid.uuid4().hex[:6]
    result = memory.observe(f"我没有{name}过敏")
    assert not any(item["value"] == name for item in result["new"])


def test_memory_delete_fact(tmp_path, monkeypatch):
    import uuid

    from app import memory

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    memory.init()
    name = "待删药" + uuid.uuid4().hex[:6]
    memory.observe(f"我对{name}过敏")
    fact = next(item for item in memory.facts() if item["value"] == name)
    assert memory.delete_fact(fact["id"])["value"] == name
    assert not any(item["value"] == name for item in memory.facts())


def test_drugdata_mapping():
    from app import drugdata

    assert drugdata.map_drug("布洛芬缓释胶囊") == "ibuprofen"
    assert drugdata.map_drug("华法林片") == "warfarin"
    assert drugdata.map_drug("丹参片") is None


def test_memory_clear_notes(tmp_path, monkeypatch):
    from app import memory

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    memory.init()
    memory.add_note("test-clear", "咳嗽", "已分析")
    assert memory.clear_notes() >= 0


def test_meds_take_stock_and_course(tmp_path, monkeypatch):
    from app import meds

    monkeypatch.setattr(meds, "DB_PATH", tmp_path / "meds.db")
    meds.init()
    item = meds.add("测试阿奇", "1片", "口服", "", 24, 1, "08:00",
                    total_doses=2, stock_total=1, stock_unit="片", expiry_date="2026-12-31")
    assert item["stock_remaining"] == 1
    first = meds.take(item["id"])
    assert first["taken"] == 1 and first["stock_remaining"] == 0
    second = meds.take(item["id"])
    assert second["taken"] == 2 and second["completed"] is True
    assert second["just_completed"] is True




def test_router_abdominal_pain():
    from app import router

    assert router.rules("我还有肚子痛")["intent"] == "medical"
    assert router.rules("肚子疼，有点拉肚子")["intent"] == "medical"


def test_abdominal_red_flags():
    from app.triage import triage

    assert triage("\u53f3\u4e0b\u8179\u6301\u7eed\u5267\u75db").urgent
    assert triage("\u809a\u5b50\u75db\uff0c\u53d1\u70e7\uff0c\u8fd8\u5410\u4e86").urgent
    assert not triage("\u809a\u5b50\u7ede\u75db\uff0c\u4e00\u9635\u4e00\u9635\u7684").urgent


def test_spoken_symptom_synonyms():
    from app.tcm import search_tcm

    names = [item["name"] for item in search_tcm("\u809a\u5b50\u7ede\u75db", limit=4)]
    assert names, "spoken symptom should match KB"


def test_ontology_red_flags():
    from app.triage import triage

    assert triage("\u7a81\u7136\u5267\u70c8\u5934\u75db\uff0c\u8116\u5b50\u786c").urgent
    assert triage("\u8170\u80cc\u75db\uff0c\u5927\u5c0f\u4fbf\u5931\u7981").urgent
    assert triage("\u8d77\u7ea2\u75b9\uff0c\u547c\u5438\u56f0\u96be").urgent


def test_ontology_routing_matrix():
    from app import router

    for text in ("\u504f\u5934\u75db", "\u5c3f\u9891\u5c3f\u6025", "\u8170\u75bc",
                 "\u8d77\u7ea2\u75b9\u5f88\u75d2", "\u7259\u75bc", "\u773c\u775b\u5e72",
                 "\u5173\u8282\u75db", "\u55d3\u5b50\u75bc"):
        assert router.rules(text)["intent"] == "medical", text


def test_colloquial_paraphrases():
    from app import tcm
    from app.router import rules

    for phrase in ("\u8111\u888b\u50cf\u8981\u70b8\u5f00\u4e00\u6837",
                   "\u55d3\u5b50\u50cf\u541e\u5200\u7247",
                   "\u8170\u50cf\u65ad\u4e86\u4e00\u6837",
                   "\u9f3b\u5b50\u5835\u5f97\u614c",
                   "\u62c9\u4e0d\u51fa\u6765"):
        assert rules(phrase)["intent"] == "medical", phrase
    assert rules("\u8fd9\u73a9\u610f\u513f\u5403\u4e86\u4f1a\u957f\u8089\u5417")["intent"] == "food"
    assert rules("\u6700\u8fd1\u63d0\u4e0d\u8d77\u52b2\uff0c\u5565\u90fd\u4e0d\u60f3\u505a")["intent"] == "psych"

    names = [item["name"] for item in tcm.search_tcm("\u62c9\u4e0d\u51fa\u6765", 5,
                                                     domains=["abdominal"])]
    assert names
    headache = [item["name"] for item in tcm.search_tcm("\u8111\u888b\u50cf\u8981\u70b8\u5f00",
                                                       5, domains=["headache"])]
    assert headache


def test_food_guide_for_meal_questions():
    from app import food

    guide = food.guide("\u51cf\u8102\u65e9\u9910\u548b\u5403")
    assert guide and guide["kind"] == "food_guide"
    assert guide["sections"]
    assert food.guide("\u9721\u9ea6\u5065\u5eb7\u5417") is None


def test_paraphrase_matrix():
    from app import router
    from app.triage import triage

    medical = ["老想上厕所", "身上一阵冷一阵热", "血糖高血压高怎么办",
               "脑袋嗡嗡的", "喉咙像冒火", "脚趾关节红肿"]
    psych = ["一点就炸", "脑子停不下来", "心里堵得慌", "最近撑不住"]
    food = ["血糖高能吃米饭吗", "晚上吃这个会不会长肉", "减脂早餐咋吃"]
    for phrase in medical:
        assert router.rules(phrase)["intent"] == "medical", phrase
    for phrase in psych:
        assert router.rules(phrase)["intent"] == "psych", phrase
    for phrase in food:
        assert router.rules(phrase)["intent"] == "food", phrase
    assert triage("\u75f0\u91cc\u5e26\u8840").urgent


def test_lifestyle_has_specific_plans():
    from app import lifestyle

    data = lifestyle.select("\u5931\u7720\uff0c\u591a\u68a6")
    assert "sleep" in data["tags"]
    assert data["diet"]
    assert all("12 \u79cd" not in line for line in data["diet"])
    assert data["exercise"]

    from app.plan import build_week

    week = build_week(["sleep"], data["diet"], data["exercise"], [])
    assert week["theme"] == "\u7761\u7720\u6062\u590d"
    assert len(week["days"]) == 7
    assert week["days"][0]["tasks"]


def test_diet_and_plan_audit():
    from app import food, lifestyle, router
    from app.plan import build_week

    assert router.rules("\u7cd6\u5c3f\u75c5")["intent"] == "medical"
    assert food.guide("\u7cd6\u5c3f\u75c5")["title"] == "\u63a7\u7cd6\u996e\u98df\u600e\u4e48\u5b89\u6392"

    dizzy = lifestyle.select("\u5934\u6655\u4e4f\u529b")
    assert dizzy["tags"] != ["anemia"]

    irregular = lifestyle.select("\u6708\u7ecf\u63a8\u8fdf")
    assert "menstrual_irregular" in irregular["tags"]
    assert "menstrual" not in irregular["tags"]

    week = build_week(irregular["tags"], irregular["diet"], irregular["exercise"],
                      irregular["avoid"])
    assert week["theme"] == "\u6708\u7ecf\u5468\u671f\u8c03\u7406"
    assert any("\u6708\u7ecf\u65e5\u671f" in task for task in week["days"][0]["tasks"])


def test_language_agent_normalizes_variants():
    from app.language import enrich
    from app.main import _body_part_shift, _new_topic_break

    assert "便秘" in enrich("\u6211\u62c9\u4e0d\u51fa\u5c4e")["normalized"]
    assert " diarrhea " not in enrich("\u8e72\u7a00")["normalized"]
    assert "\u817f\u9178\u75db" in enrich("\u5927\u817f\u9178\u75bc")["text"]
    assert enrich("\u5fc3\u91cc\u6709\u70b9\u7d2f")["matches"] == []
    assert _new_topic_break("\u819d\u76d6\u6454\u5230\u4e86")
    assert _body_part_shift("\u5927\u817f\u9178\u75db", "\u809a\u5b50\u75db")


def test_body_noise_and_dizziness():
    from app.language import enrich
    from app.main import _body_part_shift
    from app.symptoms import followups_for

    assert "头晕" in enrich("\u6211\u73b0\u5728\u5934\u6709\u70b9\u6655")["normalized"]
    assert _body_part_shift("\u5934\u6709\u70b9\u6655",
                            "\u6211\u521a\u624d\u6454\u4e86\u4e00\u8de4\uff0c\u819d\u76d6\u6709\u70b9\u75db")
    questions = followups_for("\u6211\u73b0\u5728\u5934\u6709\u70b9\u6655")
    assert questions[0]["id"] == "dizzy_type"


def test_profile_personalizes_plan():
    from app import lifestyle
    from app.personalize import apply
    from app.plan import build_week

    base = lifestyle.select("\u5931\u7720")
    profile = {"age": 18, "sex": "male", "diet_pref": "\u7d20\u98df",
               "avoid_foods": "\u9999\u83dc", "meal_style": "\u5916\u5356",
               "activity_level": "\u4e45\u5750", "conditions": ["\u9ad8\u8840\u538b"]}
    plan = apply(base, profile, [], None)
    assert plan["notes"]
    assert plan["daily_actions"]
    week = build_week(plan["tags"], plan["diet"], plan["exercise"],
                      plan["avoid"], plan["daily_actions"])
    assert any("\u8c46\u5236\u54c1" in task or "\u5fcc\u53e3" in task
               for task in week["days"][0]["tasks"])


def test_paraphrase_retrieval():
    from app.language import enrich

    cases = {
        "\u8111\u888b\u50cf\u88ab\u95e8\u5939\u4e86": "\u5934\u75db",
        "\u80c3\u91cc\u53cd\u9178\u6c34": "\u53cd\u9178",
        "\u8001\u60f3\u8dd1\u5395\u6240": "\u5c3f\u9891",
        "\u817f\u50cf\u704c\u4e86\u94c5": "\u4e4f\u529b",
        "\u665a\u4e0a\u7ffb\u6765\u8986\u53bb\u7761\u4e0d\u7740": "\u5931\u7720",
    }
    for phrase, canonical in cases.items():
        assert canonical in enrich(phrase)["matches"], phrase
    assert enrich("\u4eca\u5929\u5929\u6c14\u4e0d\u9519")["matches"] == []


def test_expanded_paraphrase_kb():
    from app.language import enrich
    assert "\u5934\u75db" in enrich("\u8111\u888b\u50cf\u88ab\u95e8\u5939\u4e86")["matches"]
    assert "\u4e4f\u529b" in enrich("\u817f\u50cf\u704c\u4e86\u94c5")["matches"]
    assert "\u75db\u7ecf" in enrich("\u5927\u59e8\u5988\u75bc\u5f97\u6253\u6eda")["matches"]
    assert enrich("\u6211\u4eca\u5929\u5f88\u5f00\u5fc3")["matches"] == []
    assert enrich("\u4e0d\u8212\u670d")["matches"] == []
