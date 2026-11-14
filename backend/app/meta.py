"""Team and workflow metadata exposed to the panel (read-only)."""

from __future__ import annotations

TEAM = [
    {
        "id": "triage",
        "name": "分诊 Agent",
        "role": "识别红旗症状，决定是否需要立即就医",
        "skills": ["急症识别", "症状归一化"],
        "tools": [],
        "knowledge": "确定性红旗规则（不依赖模型）",
        "prompt": "红旗症状直接短路到就医报告",
    },
    {
        "id": "differentiate",
        "name": "辨证 Agent",
        "role": "判断风寒/风热倾向；不确定时分支讨论并追问",
        "skills": ["问诊追问", "证型打分"],
        "tools": [],
        "knowledge": "寒热辨证要点（怕冷/口渴、痰涕颜色、咽痛、出汗）",
        "prompt": "证据不足时不得臆断，输出两支并提问",
    },
    {
        "id": "retrieval",
        "name": "检索 Agent ×3",
        "role": "并行取证：文献、说明书、机构指南",
        "skills": ["PubMed 检索", "openFDA 说明书", "网页正文抽取"],
        "tools": ["pubmed_search", "openfda_label_search", "fetch_url"],
        "knowledge": "权威来源白名单（PubMed/openFDA/DailyMed/NHS/WHO/CDC）",
        "prompt": "指南与系统综述优先；相关性过滤；限速与降级",
    },
    {
        "id": "tcm",
        "name": "中药知识库 Agent",
        "role": "从策展知识库匹配中成药并按价格/匹配度排序",
        "skills": ["症状匹配", "价格排序", "禁忌提示"],
        "tools": ["tcm_search"],
        "knowledge": "20 条 OTC 中成药（剂型/用法/禁忌/参考价/辨证方向）",
        "prompt": "只能从知识库选药，不得编造药名或剂量",
    },
    {
        "id": "writer",
        "name": "报告撰写 Agent",
        "role": "生成结构化中文报告，逐条标注引用",
        "skills": ["循证写作", "引用标注", "风险提示"],
        "tools": [],
        "knowledge": "报告模板与安全写作规则",
        "prompt": "不得诊断、不得开处方；每条结论必须带来源编号",
    },
    {
        "id": "reviewer",
        "name": "安全审查 Agent",
        "role": "引用锚定、剂量核对、红旗与越界措辞检查",
        "skills": ["引用核验", "剂量核对", "措辞审查"],
        "tools": [],
        "knowledge": "安全审查规则（含不通过即打回重写）",
        "prompt": "审查不通过 → 定向重写 ≤2 轮 → 仍不过则降级模板",
    },
]

WORKFLOW = {
    "id": "health-consult-v1",
    "name": "症状咨询工作流",
    "nodes": [
        {"id": "triage", "title": "红旗分诊", "agent": "triage", "depends_on": []},
        {"id": "differentiate", "title": "风寒/风热辨证", "agent": "differentiate", "depends_on": ["triage"]},
        {"id": "retrieval", "title": "并行取证（PubMed / openFDA / NHS）", "agent": "retrieval",
         "depends_on": ["differentiate"], "parallel": True},
        {"id": "tcm", "title": "中成药知识库匹配", "agent": "tcm", "depends_on": ["differentiate"]},
        {"id": "compose", "title": "报告撰写", "agent": "writer", "depends_on": ["retrieval", "tcm"]},
        {"id": "review", "title": "安全审查", "agent": "reviewer", "depends_on": ["compose"]},
        {"id": "repair", "title": "修复重写（自循环）", "agent": "writer", "depends_on": ["review"], "loop": True},
        {"id": "finalize", "title": "输出报告", "agent": "reviewer", "depends_on": ["review"]},
    ],
}


def describe() -> dict:
    return {"team": TEAM, "workflow": WORKFLOW}
