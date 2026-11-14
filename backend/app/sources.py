"""Authoritative source allowlist and a small symptom language map."""

from urllib.parse import urlparse

ALLOWLIST = (
    "api.fda.gov",
    "dailymed.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
    "eutils.ncbi.nlm.nih.gov",
    "www.nhs.uk",
    "nhs.uk",
    "www.who.int",
    "www.cdc.gov",
)

# Used by mock mode (and as a hint for the real agent) to turn Chinese symptoms
# into English search terms.
SYMPTOM_HINTS = {
    "脱发": "hair loss",
    "颈肩痛": "neck pain",
    "更年期": "menopause",
    "耳鸣": "tinnitus",
    "脚气": "athlete's foot",
    "冻疮": "chilblains",
    "声音嘶哑": "hoarse voice",
    "头晕": "dizziness",
    "牙龈出血": "gum disease",
    "眼睛红": "conjunctivitis",
    "月经不调": "irregular periods",
    "痱子": "prickly heat",
    "尿频": "urinary frequency",
    "肌肉酸痛": "muscle pain",
    "头痛": "headache",
    "头疼": "headache",
    "发热": "fever",
    "发烧": "fever",
    "咳嗽": "cough",
    "咽痛": "sore throat",
    "喉咙痛": "sore throat",
    "鼻塞": "nasal congestion",
    "流鼻涕": "runny nose",
    "腹泻": "diarrhea",
    "拉肚子": "diarrhea",
    "恶心": "nausea",
    "呕吐": "vomiting",
    "皮疹": "rash",
    "瘙痒": "itching",
    "失眠": "insomnia",
    "焦虑": "anxiety",
    "胃胀": "bloating",
    "腹胀": "bloating",
    "反酸": "heartburn",
    "痛经": "dysmenorrhea",
    "鼻炎": "allergic rhinitis",
    "湿疹": "eczema",
    "便秘": "constipation",
    "晕车": "motion sickness",
    "牙痛": "toothache",
    "痔疮": "piles",
    "腰痛": "back pain",
    "眼睛干": "dry eyes",
    "口臭": "bad breath",
    "中暑": "heat exhaustion",
    "口腔溃疡": "mouth ulcer",
    "痤疮": "acne",
    "荨麻疹": "hives",
    "关节痛": "joint pain",
    "肌肉痛": "muscle pain",
}

# Demo-only mapping for mock mode: a common over-the-counter option to look up.
DEMO_DRUG_HINTS = {
    "headache": "ibuprofen",
    "fever": "acetaminophen",
    "cough": "dextromethorphan",
    "sore throat": "acetaminophen",
    "nasal congestion": "pseudoephedrine",
    "diarrhea": "loperamide",
    "heartburn": "omeprazole",
    "constipation": "lactulose",
    "eczema": "hydrocortisone",
    "motion sickness": "dimenhydrinate",
    "toothache": "acetaminophen",
    "allergic rhinitis": "cetirizine",
    "dysmenorrhea": "ibuprofen",
    "bloating": "simethicone",
}


def is_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == item or host.endswith("." + item) for item in ALLOWLIST)


def english_terms(text: str) -> list[str]:
    terms: list[str] = []
    for zh, en in SYMPTOM_HINTS.items():
        if zh in text and en not in terms:
            terms.append(en)
    return terms

# Authoritative guidance pages for common complaints (NHS is reachable and
# stable).  Keyed by a Chinese symptom word the patient is likely to use.
GUIDE_PAGES = {
    "脱发": "https://www.nhs.uk/conditions/hair-loss/",
    "掉发": "https://www.nhs.uk/conditions/hair-loss/",
    "颈肩痛": "https://www.nhs.uk/conditions/neck-pain/",
    "颈椎": "https://www.nhs.uk/conditions/neck-pain/",
    "更年期": "https://www.nhs.uk/conditions/menopause/",
    "耳鸣": "https://www.nhs.uk/conditions/tinnitus/",
    "脚气": "https://www.nhs.uk/conditions/athletes-foot/",
    "冻疮": "https://www.nhs.uk/conditions/chilblains/",
    "声音嘶哑": "https://www.nhs.uk/conditions/laryngitis/",
    "头晕": "https://www.nhs.uk/conditions/dizziness/",
    "牙龈出血": "https://www.nhs.uk/conditions/gum-disease/",
    "眼睛红": "https://www.nhs.uk/conditions/conjunctivitis/",
    "月经不调": "https://www.nhs.uk/conditions/irregular-periods/",
    "痱子": "https://www.nhs.uk/conditions/prickly-heat/",
    "长痘": "https://www.nhs.uk/conditions/acne/",
    "痘": "https://www.nhs.uk/conditions/acne/",
    "痤疮": "https://www.nhs.uk/conditions/acne/",
    "痘痘": "https://www.nhs.uk/conditions/acne/",
    "荨麻疹": "https://www.nhs.uk/conditions/hives/",
    "瘙痒": "https://www.nhs.uk/conditions/itching/",
    "皮肤痒": "https://www.nhs.uk/conditions/itching/",
    "鼻炎": "https://www.nhs.uk/conditions/allergic-rhinitis/",
    "湿疹": "https://www.nhs.uk/conditions/atopic-eczema/",
    "口腔溃疡": "https://www.nhs.uk/conditions/mouth-ulcers/",
    "痔疮": "https://www.nhs.uk/conditions/piles-haemorrhoids/",
    "牙痛": "https://www.nhs.uk/conditions/toothache/",
    "晕车": "https://www.nhs.uk/conditions/motion-sickness/",
    "腰痛": "https://www.nhs.uk/conditions/back-pain/",
    "眼睛干": "https://www.nhs.uk/conditions/dry-eyes/",
    "口臭": "https://www.nhs.uk/conditions/bad-breath/",
    "中暑": "https://www.nhs.uk/conditions/heat-exhaustion-and-heatstroke/",
    "关节痛": "https://www.nhs.uk/conditions/arthritis/",
    "失眠": "https://www.nhs.uk/conditions/insomnia/",
    "睡不着": "https://www.nhs.uk/conditions/insomnia/",
    "咳嗽": "https://www.nhs.uk/conditions/cough/",
    "头痛": "https://www.nhs.uk/conditions/headache/",
    "头疼": "https://www.nhs.uk/conditions/headache/",
    "发热": "https://www.nhs.uk/conditions/fever-in-adults/",
    "发烧": "https://www.nhs.uk/conditions/fever-in-adults/",
    "咽痛": "https://www.nhs.uk/conditions/sore-throat/",
    "咽喉痛": "https://www.nhs.uk/conditions/sore-throat/",
    "鼻塞": "https://www.nhs.uk/conditions/common-cold/",
    "流鼻涕": "https://www.nhs.uk/conditions/common-cold/",
    "胃胀": "https://www.nhs.uk/conditions/indigestion/",
    "腹胀": "https://www.nhs.uk/conditions/indigestion/",
    "反酸": "https://www.nhs.uk/conditions/heartburn-and-acid-reflux/",
    "便秘": "https://www.nhs.uk/conditions/constipation/",
    "腹泻": "https://www.nhs.uk/conditions/diarrhoea-and-vomiting/",
    "痛经": "https://www.nhs.uk/conditions/period-pain/",
    "焦虑": "https://www.nhs.uk/conditions/anxiety/",
    "皮疹": "https://www.nhs.uk/conditions/rashes-babies-and-children/",
}


GUIDE_SUMMARIES = {
    "https://www.nhs.uk/conditions/hair-loss/":
        "脱发常见于遗传、压力、营养或激素变化；规律作息、均衡饮食有帮助，突然大量脱发或伴头皮病变应就医。",
    "https://www.nhs.uk/conditions/neck-pain/":
        "颈肩痛多与姿势、劳损有关；调整坐姿、适度活动、热敷有帮助，伴手臂麻木无力应就医。",
    "https://www.nhs.uk/conditions/menopause/":
        "更年期常见潮热、盗汗、失眠、情绪波动；规律运动、补钙和放松有帮助，症状明显可就诊妇科。",
    "https://www.nhs.uk/conditions/tinnitus/":
        "耳鸣常与噪声、耳部疾病或压力有关；避免噪声、规律休息有帮助，突发耳鸣或听力下降应就医。",
    "https://www.nhs.uk/conditions/athletes-foot/":
        "脚气由真菌感染引起；保持足部干燥、勤换鞋袜，外用抗真菌药需坚持 1–2 周。",
    "https://www.nhs.uk/conditions/chilblains/":
        "冻疮与寒冷潮湿有关；保暖、避免忽冷忽热有帮助，破溃感染应就医。",
    "https://www.nhs.uk/conditions/laryngitis/":
        "声音嘶哑常与用嗓过度或上呼吸道感染有关；少说话、多喝水，超过两周应就诊耳鼻喉科。",
    "https://www.nhs.uk/conditions/dizziness/":
        "头晕原因多样（血压、耳石、贫血等）；缓慢起身、避免脱水，反复发作或伴神经症状应就医。",
    "https://www.nhs.uk/conditions/gum-disease/":
        "牙龈出血常与牙菌斑、牙结石有关；正确刷牙、使用牙线、定期洗牙有帮助，持续出血应看牙医。",
    "https://www.nhs.uk/conditions/conjunctivitis/":
        "结膜炎表现为眼红、分泌物增多；注意手卫生、不共用毛巾，视力下降或眼痛应就医。",
    "https://www.nhs.uk/conditions/irregular-periods/":
        "月经不调与压力、体重、激素等有关；记录周期、规律作息，持续异常应就诊妇科。",
    "https://www.nhs.uk/conditions/prickly-heat/":
        "痱子与出汗、闷热有关；保持皮肤干爽、穿透气衣物，感染化脓应就医。",
    "https://www.nhs.uk/conditions/acne/":
        "痤疮与毛囊皮脂腺堵塞和炎症有关；温和清洁、避免挤压，中重度或留下瘢痕时应就诊皮肤科。",
    "https://www.nhs.uk/conditions/hives/":
        "荨麻疹表现为风团和瘙痒，常与过敏有关；避免诱因、冷敷可缓解。若伴呼吸困难、喉头水肿或头晕，应立即就医。",
    "https://www.nhs.uk/conditions/insomnia/":
        "失眠指经常难以入睡或睡不安稳；多数可通过固定作息、睡前放松、减少咖啡因和屏幕时间改善。持续三个月以上、或明显影响白天生活时，应就医。",
    "https://www.nhs.uk/conditions/cough/":
        "咳嗽多由感冒或呼吸道感染引起，通常数周内自行缓解；多喝水、休息、避免吸烟。出现咳血、呼吸困难或咳嗽超过三周应就医。",
    "https://www.nhs.uk/conditions/headache/":
        "多数头痛可自行缓解，可通过补水、休息、放松减轻。突发剧烈头痛、伴发热颈硬或神经症状应就医。",
    "https://www.nhs.uk/conditions/fever-in-adults/":
        "成人和儿童发热多与感染有关，多数可自行缓解；注意补液、休息。儿童高热、精神差或持续超过 3 天应及时就医。",
    "https://www.nhs.uk/conditions/sore-throat/":
        "咽痛多为病毒感染，通常自行缓解；多喝水、温盐水含漱。伴高热、吞咽困难或呼吸困难应就医。",
    "https://www.nhs.uk/conditions/common-cold/":
        "普通感冒多由病毒引起，通常一周左右自愈；休息、补水即可。症状加重或高热应就医。",
    "https://www.nhs.uk/conditions/indigestion/":
        "消化不良常与进食过快、油腻或压力有关；少量多餐、避免诱因。持续不适或伴消瘦、黑便应就医。",
    "https://www.nhs.uk/conditions/heartburn-and-acid-reflux/":
        "反酸烧心与胃食管反流有关；避免饱餐和睡前饮食，抬高床头可能有帮助。症状频繁或吞咽困难应就医。",
    "https://www.nhs.uk/conditions/constipation/":
        "便秘可通过增加膳食纤维、水分和规律运动改善；不要长期依赖泻药。伴腹痛、便血或体重下降应就医。",
    "https://www.nhs.uk/conditions/diarrhoea-and-vomiting/":
        "腹泻呕吐要注意补液防脱水；可少量多次饮水或口服补液盐。血便、高热或明显脱水应就医。",
    "https://www.nhs.uk/conditions/period-pain/":
        "痛经常见，可热敷、休息缓解；疼痛进行性加重、经量异常或非经期出血应就医。",
    "https://www.nhs.uk/conditions/anxiety/":
        "焦虑可通过规律作息、运动和放松训练缓解；持续影响工作生活时建议寻求专业帮助。",
    "https://www.nhs.uk/conditions/itching/":
        "皮肤瘙痒常见于干燥、过敏或湿疹；保湿、避免搔抓和热水烫洗有帮助。持续瘙痒、皮疹扩散或伴全身症状应就医。",
    "https://www.nhs.uk/conditions/piles-haemorrhoids/":
        "痔疮常见便血、肛门肿痛；增加纤维与水分、避免久坐有帮助，出血量大或贫血应就医。",
    "https://www.nhs.uk/conditions/allergic-rhinitis/":
        "过敏性鼻炎常由花粉、尘螨等引起，表现为鼻塞、流涕、打喷嚏；避免过敏原、生理盐水冲洗鼻腔有帮助，症状持续应就医。",
    "https://www.nhs.uk/conditions/atopic-eczema/":
        "湿疹表现为皮肤干燥、瘙痒、红斑；保湿、避免刺激物和热水烫洗有帮助，渗出或感染时应就医。",
    "https://www.nhs.uk/conditions/mouth-ulcers/":
        "口腔溃疡多在一两周内自愈；避免辛辣刺激、保持口腔清洁，超过三周不愈应就医。",
    "https://www.nhs.uk/conditions/toothache/":
        "牙痛常与龋齿或牙髓炎有关；可短期止痛，但应尽快看牙医，面部肿胀或发热需急诊。",
    "https://www.nhs.uk/conditions/motion-sickness/":
        "晕车与内耳平衡有关；坐前排、看远处、避免空腹或过饱有帮助，频繁发作应就医。",
    "https://www.nhs.uk/conditions/back-pain/":
        "腰痛多数可自行缓解；保持活动、避免久坐和负重，出现下肢麻木无力或大小便异常应就医。",
    "https://www.nhs.uk/conditions/dry-eyes/":
        "眼干常与用眼过度、环境干燥有关；规律休息、人工泪液有帮助，持续或伴视力下降应就医。",
    "https://www.nhs.uk/conditions/bad-breath/":
        "口臭多与口腔卫生、牙龈问题有关；刷牙、牙线、清洁舌苔有帮助，持续应看牙医。",
    "https://www.nhs.uk/conditions/heat-exhaustion-and-heatstroke/":
        "中暑先兆包括头晕、乏力、恶心；应立即到阴凉处、补水降温，意识改变或高热无汗需急救。",
    "https://www.nhs.uk/conditions/arthritis/":
        "关节痛与退行性变或炎症有关；适度活动、控制体重有帮助，关节红肿发热应就医。",
}


def guide_pages(text: str, limit: int = 2) -> list[str]:
    """Pick at most ``limit`` authoritative guide URLs for the symptom text."""
    urls: list[str] = []
    for keyword, url in GUIDE_PAGES.items():
        if keyword in (text or "") and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls

