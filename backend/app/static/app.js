
const $ = s => document.querySelector(s);
const thread = $('#thread');
const state = { symptoms: '', answers: {}, busy: false, autoScroll: true, lastTrace: [], conversationId: null, answerLabels: {}, freshContext: false };
let provider = 'mock';

function esc(t) {
  return String(t ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function greet() {
  const h = new Date().getHours();
  const word = h < 6 ? '夜深了' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好';
  $('#greet').textContent = `${word}，今天身体怎么样？`;
}
greet();

function addUser(text, raw) {
  document.body.classList.add('chat');
  const el = document.createElement('div');
  el.className = 'msg user';
  el.innerHTML = `<div class="body">${raw ? text : esc(text)}</div>`;
  thread.appendChild(el);
  if (state.autoScroll !== false) thread.scrollTop = thread.scrollHeight;
}

function addAssistant(html) {
  const el = document.createElement('div');
  el.className = 'msg assistant';
  el.innerHTML = `<div class="avatar">助</div><div class="body">${html}</div>`;
  thread.appendChild(el);
  if (state.autoScroll !== false) thread.scrollTop = thread.scrollHeight;
  return el;
}

function addTyping() {
  const el = document.createElement('div');
  el.className = 'msg assistant';
  el.innerHTML = `<div class="avatar">助</div><div class="body"><span class="typing">正在检索权威来源</span></div>`;
  thread.appendChild(el);
  if (state.autoScroll !== false) thread.scrollTop = thread.scrollHeight;
  return el;
}

function tcmCard(item) {
  return `<div class="tcm">
    <div class="top"><span class="name">${esc(item.name)}</span>
      <span class="tag">${esc(item.otc)}</span><span class="tag">${esc(item.price_range)}</span>
      <span class="tag">${esc(item.pattern)}</span></div>
    <p><b>用法</b>：${esc(item.dosage)}</p>
    <p><b>禁忌</b>：${esc(item.contraindications)}</p>
    <p><b>注意</b>：${esc(item.cautions)}</p>
  </div>`;
}

function questionBlock(q, index) {
  const opts = q.options.map(o => `<button class="opt" data-qid="${esc(q.id)}" data-val="${esc(o)}">${esc(o)}</button>`).join('');
  return `<div class="q"><div class="ask">${index + 1}. ${esc(q.question)}</div><div class="opts">${opts}</div></div>`;
}

const STEP_LABEL = { triage: '红旗分诊', differentiate: '辨证', tcm_kb: '中成药匹配',
  parallel: '并行取证', agent: '模型推理', compose: '报告撰写', review: '安全审查',
  repair: '修复重写', fallback: '降级模板' };

function runStrip(data) {
  const steps = [];
  for (const step of (data.trace || [])) {
    if (step.step === 'tool') { if (!steps.find(s => s.k === 'tools')) steps.push({ k: 'tools', label: '工具调用' }); continue; }
    const label = STEP_LABEL[step.step];
    if (label && !steps.find(s => s.k === step.step)) {
      steps.push({ k: step.step, label, ok: step.step !== 'fallback' });
    }
  }
  if (!steps.length) return '';
  return `<div class="runstrip">${steps.map(s =>
    `<span class="step ${s.ok === false ? '' : 'ok'}">${esc(s.label)}</span>`).join('<span style="color:#cbd5e1">→</span>')}</div>`;
}

function summary(data) {
  const modelLabel = data.provider === 'mock-fallback' ? '内置演示（备用）'
    : (data.provider === 'mock' ? '内置演示' : data.provider);
  const used = `<div style="font-size:12px;color:#94a3b8;margin-bottom:6px">模型：${esc(modelLabel)}</div>`;
  const t = data.triage || {}, d = data.differentiation || {};
  const bits = [];
  const profile = data.profile || {};
  const profileBits = [];
  if (profile.age) profileBits.push(profile.age + ' 岁');
  if (profile.sex === 'female') profileBits.push('女性' + (profile.pregnant ? '，孕期' : ''));
  if (profile.sex === 'male') profileBits.push('男性');
  if ((profile.allergies || []).length) profileBits.push('过敏：' + profile.allergies.join('、'));
  if ((profile.conditions || []).length) profileBits.push('慢病：' + profile.conditions.join('、'));
  const safetyWarns = (data.safety_warnings || [])
    .map(text => `<div>⚠️ ${esc(text)}</div>`).join('');
  if (profileBits.length || safetyWarns) {
    const coverage = data.safety_coverage
      ? `<div style="font-size:12px;color:#94a3b8;margin-top:4px">${esc(data.safety_coverage)}</div>` : '';
    bits.push(`<div class="notice warn">👤 <b>个人情况</b>：${esc(profileBits.join(' · '))}${safetyWarns}${coverage}</div>`);
  }
  const mem = data.memory || {};
  if ((mem.new_facts || []).length) {
    const labels = mem.new_facts.map(item =>
      item.type === 'allergy' ? '过敏：' + item.value
        : item.type === 'condition' ? '慢病：' + item.value
        : '孕期').join('、');
    bits.push(`<div class="notice ok">🧠 记住了：${esc(labels)}，以后会自动考虑。</div>`);
  }
  if ((mem.notes || []).length) {
    const last = mem.notes[0];
    bits.push(`<div class="notice" style="background:#f8fafc;color:#475569">🧠 上次记录：${esc(last.symptoms)} → ${esc(last.summary)}</div>`);
  }
  const meds = data.medications || [];
  if (meds.length) {
    const names = meds.map(item => `${item.name}${item.dose ? ' ' + item.dose : ''}`).join('、');
    const warns = (data.med_warnings || []).map(text => `⚠️ ${esc(text)}`).join('；');
    bits.push(`<div class="notice warn">💊 <b>正在用药</b>：${esc(names)}（来自用药记录）${warns ? '；' + warns : ''}</div>`);
  }
  if (t.urgent) bits.push('<div class="notice bad">检测到需要立即就医的信号：' + esc((t.reasons || []).join('、')) + '。请立刻联系急救或前往急诊。</div>');
  else if (t.high_fever) bits.push('<div class="notice warn">你提到高热。建议先就医评估，不要自行叠加中成药与退热药。</div>');
  if (d.decision === 'cold') bits.push('<div class="notice ok">根据你的描述，更符合<b>风寒</b>表现（仅供参考，不作为诊断）。</div>');
  if (d.decision === 'heat') bits.push('<div class="notice ok">根据你的描述，更符合<b>风热</b>表现（仅供参考，不作为诊断）。</div>');
  if (d.decision === 'ambiguous') bits.push('<div class="notice ok">目前还分不清风寒还是风热，我按两种情况分别列出；也可以先回答下面的问题。</div>');
  if (data.fallback_reason) {
  const tip = provider === 'custom'
    ? '自定义接口这次没连上，已用内置演示答案；请点左上角「⚙ 自定义接口」→“测试连接并激活”，或先用 Mock。'
    : '模型暂时不可用，已用内置演示答案；可稍后重试，或切换到 Mock 继续体验。';
  bits.push('<div class="notice warn">' + tip + '</div>');
}
  return used + bits.join('');
}

function tcmSection(data) {
  const tcm = data.tcm || [];
  if (!tcm.length) return '';
  if ((data.differentiation || {}).decision === 'ambiguous') {
    const cold = tcm.filter(x => x.pattern_tag === '风寒');
    const heat = tcm.filter(x => x.pattern_tag === '风热');
    const other = tcm.filter(x => x.pattern_tag !== '风寒' && x.pattern_tag !== '风热');
    return `${cold.length ? '<div class="group-title">若偏风寒（怕冷、清涕、白痰、不出汗）</div>' + cold.map(tcmCard).join('') : ''}
            ${heat.length ? '<div class="group-title">若偏风热（咽痛明显、黄痰、口渴、易出汗）</div>' + heat.map(tcmCard).join('') : ''}
            ${other.length ? '<div class="group-title">其他对症</div>' + other.map(tcmCard).join('') : ''}`;
  }
  return `<div class="group-title">首选中药（${tcm.length} 个：中成药 + 中药材）</div>` + tcm.map(tcmCard).join('');
}

function lead(data) {
  const t = data.triage || {};
  if (t.urgent) return '';
  const guides = (data.evidence || []).filter(e => /nhs\.uk|who\.int|cdc\.gov/.test(e.url || ''));
  const tcm = data.tcm || [];
  const parts = [];
  if (guides.length) {
    const point = (guides[0].summary_zh || '').trim();
    if (point) {
      const host = (guides[0].source || '').replace(/^www\./, '');
      const label = host.includes('nhs') ? 'NHS 指南' : (host || '权威指南');
      parts.push(`根据 ${label}：${point.replace(/[。；]\s*$/, '')}`);
    }
  }
  if (tcm.length) parts.push(`平台知识库匹配到 ${tcm.map(x => x.name).join('、')}，用法与禁忌见下`);
  if (!parts.length) return '';
  return `<p style="margin:0 0 10px;color:#334155;font-size:15.5px;line-height:1.75">${esc(parts.join('；'))}。</p>`;
}

function guideTitle(guide) {
  const title = guide.title || '';
  if (title && !title.startsWith('http')) return title;
  const url = guide.url || '';
  const match = url.match(/conditions\/([^/]+)/);
  const slug = match ? match[1].replace(/-/g, ' ') : url;
  const host = (guide.source || '').replace(/^www\./, '');
  return `${host} · ${slug}`;
}

function shortTitle(source) {
  const title = source.title || '';
  if (title && !title.startsWith('http')) return title;
  const url = source.url || '';
  const match = url.match(/conditions\/([^/]+)/);
  const slug = match ? match[1].replace(/-/g, ' ') : (source.source || url);
  return `${(source.source || '').replace(/^www\./, '')} · ${slug}`;
}

function traceTimeline(data) {
  const steps = data.trace || [];
  if (!steps.length) return '';
  const items = steps.map(step => {
    const failed = (step.step === 'review' && step.passed === false) || step.step === 'fallback';
    const ms = step.ms ? `<span class="ms">${esc(step.ms)} ms</span>` : '';
    return `<li class="${failed ? 'fail' : ''}"><span class="dot"></span>
      <div class="head"><span class="title">${esc(step.title || step.step)}</span>
        <span class="agent">${esc(step.agent || '')}</span>${ms}</div>
      <div class="detail">${esc(step.summary || '')}</div></li>`;
  }).join('');
  return `<details class="tracebox"><summary>轨迹（${steps.length} 步 · 多 Agent 协作）</summary>`
    + `<ol class="timeline">${items}</ol></details>`;
}


function lifestyleSection(data) {
  const plan = data.lifestyle || {};
  if (!plan.diet || !plan.diet.length) return '';
  const list = items => items.map(text => `<li>${esc(text)}</li>`).join('');
  const avoid = (plan.avoid || []).length
    ? `<div class="life-avoid">注意：${esc(plan.avoid.join('；'))}</div>` : '';
  return '<div class="group-title">膳食与恢复计划（按当前身体状况）</div>'
    + `<div class="life-card"><h4>🥗 膳食建议</h4><ul>${list(plan.diet)}</ul>${avoid}</div>`
    + `<div class="life-card"><h4>🏃 恢复训练计划</h4><ul>${list(plan.exercise || [])}</ul></div>`;
}
function sourceChip(data) {
  const sources = data.sources || [];
  if (!sources.length) return '';
  const items = sources.map(source =>
    `<li>${esc(shortTitle(source))}${source.url ? ` — <a href="${esc(source.url)}" target="_blank" rel="noopener">查看原文</a>` : ''}</li>`
  ).join('');
  return `<details class="srcchip"><summary>🌐 ${sources.length} 个来源</summary><div class="srclist"><ol>${items}</ol></div></details>`;
}

function guideSection(data) {
  const guides = (data.evidence || []).filter(e => {
    const url = (e.url || '');
    return url.includes('nhs.uk') || url.includes('who.int') || url.includes('cdc.gov');
  });
  if (!guides.length) return '';
  return '<div class="group-title">权威指南（平台实时检索）</div>' + guides.map(g => `
    <div class="tcm">
      <div class="top"><span class="name">${esc(guideTitle(g))}</span>
        <span class="tag">${esc(g.source)}</span></div>
      <p>${esc((g.snippet || '').slice(0, 360))}</p>
      ${g.url ? `<p><a href="${esc(g.url)}" target="_blank" rel="noopener" style="font-size:12px;color:#0f766e">查看原文</a></p>` : ''}
    </div>`).join('');
}

function westernSection(data) {
  const western = data.western || [];
  if (!western.length) return '';
  return '<div class="group-title">备选西药（中药不适用或需要快速退热/止痛时）</div>' +
    western.map(item => `
      <div class="tcm">
        <div class="top"><span class="name">${esc(item.name)}</span>
          <span class="tag">OTC 西药</span><span class="tag">${esc(item.price_range)}</span></div>
        <p><b>适用</b>：${esc((item.indications || []).join('、'))}</p>
        <p><b>用法（按说明书）</b>：${esc(item.dosage)}</p>
        <p><b>禁忌</b>：${esc(item.contraindications)}</p>
        <p><b>注意</b>：${esc(item.cautions)}</p>
      </div>`).join('') +
    '<p style="font-size:12.5px;color:#64748b">西药请按说明书剂量与禁忌使用；高热、持续发热或特殊人群先就医。</p>';
}

function detailsBlock(data) {
  const sources = data.sources || [];
  const review = data.review || {};
  let html = '';
  if (data.report_markdown) {
    html += `<details><summary>完整报告</summary><div class="inner" style="white-space:pre-wrap">${esc(data.report_markdown)}</div></details>`;
  }
  // sources are shown by the "🌐 N 个来源" chip above
  // trajectory is shown by traceTimeline() above
  if (!review.passed && (review.findings || []).length) {
    html += `<details open><summary>安全审查未通过</summary><div class="inner"><ul>${review.findings.map(f => `<li>${esc(f)}</li>`).join('')}</ul></div></details>`;
  }
  return html;
}

async function analyze(symptoms, answers) {
  const response = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symptoms, answers, provider }),
  });
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.json();
}

async function send(text, isAnswer, silentUser) {
  if (state.busy || !text) return;
  let custom = null;
  if (provider === 'custom') {
    custom = customConfig();
    if (!custom) {
      openCustomModal();
      const status = document.getElementById('cusStatus');
      if (status) {
        status.style.color = '#b91c1c';
        status.textContent = '还没有配置：填好 API Key 后点“测试连接并激活”；没有 key 就关掉窗口用 Mock。';
      }
      return;
    }
  }
  state.busy = true;
  setDisabled(true);
  if (!isAnswer) { state.symptoms = text; state.answers = {}; state.answerLabels = {}; }
  if (!silentUser) addUser(text);
  const isFirstTurn = document.querySelectorAll('#thread .msg.assistant').length === 0;
  const typing = addTyping();
  const typingStarted = Date.now();
  const typingTimer = setInterval(() => {
    if (!document.body.contains(typing)) { clearInterval(typingTimer); return; }
    const label = typing.querySelector('.typing');
    if (!label) return;
    const seconds = Math.round((Date.now() - typingStarted) / 1000);
    if (seconds < 20) {
      label.textContent = '正在检索权威来源';
    } else if (isFirstTurn) {
      label.textContent = `正在生成建议… ${seconds} 秒（首次调用模型约 1–2 分钟，请稍候）`;
    } else {
      label.textContent = `正在生成建议… ${seconds} 秒（多 Agent 串行处理中，请稍候）`;
    }
  }, 2000);
  try {
    if (!state.conversationId) {
      const created = await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: text.slice(0, 24) }),
      }).then(response => response.json());
      state.conversationId = created.conversation.id;
    }
    const response = await fetch(`/api/conversations/${state.conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symptoms: state.symptoms, answers: state.answers, provider, user_text: text,
        force_intent: state.forceIntent || null,
        fresh_context: !!state.freshContext,
        api_base: custom ? custom.base : null,
        api_model: custom ? custom.models[0] : null,
        api_models: custom ? custom.models : null,
        api_format: custom ? custom.format : 'openai',
        api_key: custom ? custom.keys[0] : null,
      }),
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = (await response.json()).result;
    typing.remove();
    if (data.kind === 'chitchat') {
      addAssistant(chitchatAnswerHtml(data));
      state.lastTrace = data.trace || [];
      updateTraceFab();
      loadConversations();
      return;
    }
    if (data.kind === 'clarify') {
      const el = addAssistant(clarifyAnswerHtml(data));
      el.querySelectorAll('button[data-intent]').forEach(button => {
        button.onclick = () => {
          if (state.busy) return;
          state.forceIntent = button.dataset.intent;
          const original = data.original || state.symptoms || button.textContent.trim();
          send(original, true, true);
        };
      });
      state.lastTrace = data.trace || [];
      updateTraceFab();
      return;
    }
    if (data.kind === 'psych') {
      addAssistant(psychAnswerHtml(data));
      state.lastTrace = data.trace || [];
      updateTraceFab();
      loadConversations();
      return;
    }
    if (data.kind === 'food') {
      addAssistant(foodAnswerHtml(data));
      state.lastTrace = data.trace || [];
      updateTraceFab();
      loadConversations();
      return;
    }
    if (data.kind === 'food_guide') {
      addAssistant(foodGuideHtml(data));
      state.lastTrace = data.trace || [];
      updateTraceFab();
      loadConversations();
      return;
    }
    const follow = (data.followups || []).map((q, i) => questionBlock(q, i)).join('')
      + (data.followups && data.followups.length
        ? '<div class="follow-actions"><button type="button" class="opt-submit" disabled>请回答全部问题</button>'
          + '<button type="button" class="opt-skip">跳过剩余问题，直接生成</button>'
          + '<span class="follow-hint">答完才会生成建议，可随时改选</span></div>'
        : '');
    const el = addAssistant(runStrip(data) + lead(data) + summary(data) + follow
      + tcmSection(data) + westernSection(data) + lifestyleSection(data) + sourceChip(data)
      + `<div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>` + detailsBlock(data));
    state.lastTrace = data.trace || [];
    updateTraceFab();
    loadConversations();
    if (new URLSearchParams(location.search).has('trace')) { openTraceDrawer(); }
    const questions = data.followups || [];
    const submit = el.querySelector('.opt-submit');
    const refreshSubmit = () => {
      if (!submit) return;
      const answered = questions.filter(q => state.answers[q.id]).length;
      submit.disabled = answered < questions.length;
      submit.textContent = answered < questions.length
        ? `还差 ${questions.length - answered} 个问题`
        : '生成建议';
    };
    el.querySelectorAll('.opt').forEach(btn => {
      btn.onclick = () => {
        if (state.busy) return;
        state.answers[btn.dataset.qid] = btn.dataset.val;
        state.answerLabels[btn.dataset.qid] = btn.textContent.trim();
        el.querySelectorAll(`.opt[data-qid="${btn.dataset.qid}"]`).forEach(other => {
          other.classList.toggle('selected', other === btn);
        });
        refreshSubmit();
      };
    });
    if (submit) {
      submit.onclick = () => {
        if (state.busy) return;
        const summary = Object.values(state.answerLabels || {}).join('；');
        send('补充：' + summary, true);
      };
    }
    const skip = el.querySelector('.opt-skip');
    if (skip) {
      skip.onclick = () => {
        if (state.busy) return;
        const summary = Object.values(state.answerLabels || {}).join('；');
        send(summary ? '补充（部分）：' + summary : '不补充了，直接生成建议', true);
      };
    }
  } catch (error) {
    typing.remove();
    addAssistant(`<div class="notice bad">请求失败：${esc(error.message)}</div>`);
  } finally {
    state.busy = false;
    setDisabled(false);
    state.forceIntent = null;
    state.freshContext = false;
    document.querySelectorAll('.fresh-context').forEach(box => { box.checked = false; });
  }
}


function setDisabled(value) {
  $('#sendHero').disabled = value;
  $('#sendDock').disabled = value;
}

function bind(input, button) {
  const submit = () => {
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    input.value = '';
    send(value, false);
  };
  button.onclick = submit;
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
  });
}

bind($('#inputHero'), $('#sendHero'));
bind($('#inputDock'), $('#sendDock'));

document.querySelectorAll('.modelSel').forEach(sel => {
  sel.addEventListener('change', () => {
    provider = sel.value;
    document.querySelectorAll('.modelSel').forEach(other => { other.value = provider; });
  });
});
fetch('/api/config').then(response => response.json()).then(cfg => {
  if (!cfg.deepseek_available) {
    document.querySelectorAll('.modelSel option[value="deepseek"]').forEach(option => {
      option.disabled = true;
      option.textContent = 'DeepSeek · 未配置 Key';
    });
  }
}).catch(() => {});

const urlParams = new URLSearchParams(location.search);
const preset = urlParams.get('q');
state.autoScroll = !urlParams.has('top');
if (preset) { send(preset, false); }
function bindChips() {
  document.querySelectorAll('#heroChips .chip').forEach(chip => {
    chip.onclick = () => send(chip.dataset.ex, false);
  });
}
bindChips();

async function loadMeta() {
  try {
    const meta = await (await fetch('/api/meta')).json();
    document.getElementById('flowBox').innerHTML = meta.workflow.nodes.map((node, index) =>
      (index ? '<span class="arrow">→</span>' : '') +
      `<span class="node ${node.loop ? 'loop' : ''}">${esc(node.title)}</span>`).join('');
    document.getElementById('teamBox').innerHTML = meta.team.map(agent => `
      <div class="agent">
        <div class="n">${esc(agent.name)}</div>
        <div class="r">${esc(agent.role)}</div>
        <div class="kv"><b>技能</b>：${esc((agent.skills || []).join('、'))}</div>
        <div class="kv"><b>工具</b>：${esc((agent.tools || []).join('、') || '—')}</div>
        <div class="kv"><b>知识</b>：${esc(agent.knowledge)}</div>
      </div>`).join('');
  } catch (error) { /* metadata is optional */ }
}
function openTeam() {
  loadMeta();
  document.getElementById('teamModal').classList.add('open');
}
document.getElementById('closeTeam').onclick = () => document.getElementById('teamModal').classList.remove('open');
if (new URLSearchParams(location.search).has('cabinet')) {
  setTimeout(() => openCabinet(), 600);
}
if (new URLSearchParams(location.search).has('plan')) {
  setTimeout(() => openPlan(), 600);
}
if (new URLSearchParams(location.search).has('profile')) {
  setTimeout(() => openProfile(), 600);
}
if (new URLSearchParams(location.search).has('abl')) {
  setTimeout(() => openAblation(), 600);
}
if (new URLSearchParams(location.search).has('team')) {
  openTeam();
}

async function loadExperiment() {
  const box = document.getElementById('expTable');
  const sub = document.getElementById('expSub');
  try {
    const response = await fetch('/api/experiment');
    if (!response.ok) {
      box.innerHTML = '<p class="muted">还没有实验数据。运行：uv run python scripts/experiment.py --provider deepseek</p>';
      sub.textContent = '';
      return;
    }
    const data = await response.json();
    const s = data.summary, b = s.baseline, m = s.multi;
    sub.textContent = `模型 ${data.provider} · ${s.cases} 个用例 · 单 Agent 为一次模型调用（无工具/无审查）`;
    const rows = [
      ['平均耗时', b.avg_latency_s + ' s', m.avg_latency_s + ' s'],
      ['平均 token', b.avg_tokens, m.avg_tokens],
      ['引用可核验率', Math.round(b.avg_verifiability * 100) + '%', Math.round(m.avg_verifiability * 100) + '%'],
      ['平均安全审查问题', b.avg_review_findings, m.avg_review_findings],
      ['含免责声明', b.disclaimers + '/' + s.cases, m.disclaimers + '/' + s.cases],
      ['红旗场景正确率', b.red_flag_ok + '/' + s.cases, m.red_flag_ok + '/' + s.cases],
    ];
    box.innerHTML = '<table class="xtable"><tr><th>指标</th><th>单 Agent</th><th>多 Agent</th></tr>' +
      rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join('') + '</table>' +
      '';
  } catch (error) {
    box.innerHTML = '<p class="muted">加载失败：' + esc(error.message) + '</p>';
  }
}
function openExperiment() {
  loadExperiment();
  document.getElementById('expModal').classList.add('open');
}
document.getElementById('closeExp').onclick = () => document.getElementById('expModal').classList.remove('open');
if (new URLSearchParams(location.search).has('exp')) {
  openExperiment();
}

function updateTraceFab() {
  const fab = document.getElementById('traceFab');
  const count = (state.lastTrace || []).length;
  fab.textContent = count ? `⏱ 轨迹 ${count}` : '⏱ 轨迹';
  fab.classList.toggle('visible', count > 0);
}

function traceItems(trace) {
  return trace.map(step => {
    const failed = (step.step === 'review' && step.passed === false) || step.step === 'fallback';
    const ms = step.ms ? `<span class="ms">${esc(step.ms)} ms</span>` : '';
    return `<li class="${failed ? 'fail' : ''}"><span class="dot"></span>
      <div class="head"><span class="title">${esc(step.title || step.step)}</span>
        <span class="agent">${esc(step.agent || '')}</span>${ms}</div>
      <div class="detail">${esc(step.summary || '')}</div></li>`;
  }).join('');
}

function openTraceDrawer() {
  const trace = state.lastTrace || [];
  document.getElementById('traceBody').innerHTML = trace.length
    ? `<ol class="timeline">${traceItems(trace)}</ol>`
    : '<p class="muted">还没有轨迹，先发起一次咨询。</p>';
  document.getElementById('traceBackdrop').classList.add('open');
  document.getElementById('traceDrawer').classList.add('open');
}

function closeTraceDrawer() {
  document.getElementById('traceBackdrop').classList.remove('open');
  document.getElementById('traceDrawer').classList.remove('open');
}

document.getElementById('traceFab').onclick = openTraceDrawer;
document.getElementById('closeTrace').onclick = closeTraceDrawer;
document.getElementById('traceBackdrop').onclick = closeTraceDrawer;

// ---------------- 用药提醒 ----------------
const medState = { items: [] };

async function loadMeds() {
  try {
    const response = await fetch('/api/medications');
    const data = await response.json();
    medState.items = data.items || [];
  } catch (error) { medState.items = []; }
  renderMeds();
}


function medSchedule(item) {
  if (!item.start_time) return ['—'];
  const [hour, minute] = item.start_time.split(':').map(Number);
  const times = [];
  for (let index = 0; index < (item.doses_per_day || 0); index += 1) {
    const total = hour * 60 + minute + index * (item.interval_hours || 0) * 60;
    const day = total >= 1440 ? '（次日）' : '';
    const clock = `${String(Math.floor((total % 1440) / 60)).padStart(2, '0')}:${String(Math.round(total % 60)).padStart(2, '0')}`;
    times.push(clock + day);
  }
  return times.length ? times : ['—'];
}

function renderMeds() {
  const box = document.getElementById('medList');
  const badge = document.getElementById('medBadge');
  badge.hidden = !medState.items.length;
  badge.textContent = medState.items.length;
  if (!medState.items.length) {
    box.innerHTML = '<div class="med-empty">还没有药。添加一个，提醒、疗程和库存就都有了。</div>';
    return;
  }
  box.innerHTML = medState.items.map(item => {
    const schedule = medSchedule(item).join(' / ') || '未设置';
    const total = item.total_doses || 0;
    const progress = total
      ? `<div class="cab-balls" style="margin:8px 0">${dragonBalls(item.taken || 0, total, item.completed)}</div>
         <div class="m">疗程：已打卡 ${item.taken} / ${total} 次${item.completed ? ' 🏆' : ''}</div>`
      : '<div class="m">疗程：未设置总次数</div>';
    const stock = (item.stock_remaining === null || item.stock_remaining === undefined)
      ? '库存：未记录'
      : `库存：还剩 ${item.stock_remaining} 次`;
    const stockWarn = (item.stock_remaining !== null && item.stock_remaining !== undefined
      && item.stock_remaining <= 3)
      ? '<span style="color:#b91c1c">（快没了）</span>' : '';
    return `<div class="med-item" data-id="${esc(item.id)}">
      <div class="n">${esc(item.name)} ${item.completed ? '🏆' : ''}</div>
      <div class="m">${esc(item.dose || '剂量未填')} · ${esc(item.method || '用法未填')}</div>
      <div class="m">提醒：每 ${item.interval_hours} 小时 · 每天 ${item.doses_per_day} 次 · 首次 ${esc(item.start_time || '')}（今日 ${esc(schedule)}）</div>
      ${progress}
      <div class="m">${stock} ${stockWarn}</div>
      <div class="a">
        <button data-act="take">打卡一次</button>
        <button data-act="edit">编辑</button>
        <button data-act="test">立即提醒（演示）</button>
        <button data-act="del">删除</button>
      </div>
    </div>`;
  }).join('');
  box.querySelectorAll('.med-item').forEach(card => {
    const id = card.dataset.id;
    card.querySelector('[data-act="take"]').onclick = () => takeMed(id, card);
    card.querySelector('[data-act="edit"]').onclick = () => editMed(id);
    card.querySelector('[data-act="test"]').onclick = () => testMed(id);
    card.querySelector('[data-act="del"]').onclick = () => deleteMed(id);
  });
}

async function takeMed(id, card) {
  const response = await fetch(`/api/medications/${id}/take`, { method: 'POST' });
  const result = await response.json();
  await loadMeds();
  if (result.item && result.item.just_completed) {
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `<div class="t">🐉 神龙出现</div>
      <div class="d">${esc(result.item.name)} 的 ${result.item.total_doses} 次全部完成，疗程结束！</div>
      <button type="button">太好了</button>`;
    toast.querySelector('button').onclick = () => toast.remove();
    document.getElementById('toasts').appendChild(toast);
    setTimeout(() => toast.remove(), 30000);
  }
}


let editingMedId = null;

function editMed(id) {
  const item = medState.items.find(entry => entry.id === id);
  if (!item) return;
  editingMedId = id;
  document.getElementById('medName').value = item.name || '';
  document.getElementById('medDose').value = item.dose || '';
  document.getElementById('medMethod').value = item.method || '';
  document.getElementById('medInterval').value = item.interval_hours || 8;
  document.getElementById('medDoses').value = item.doses_per_day || 2;
  document.getElementById('medStart').value = item.start_time || '08:00';
  document.getElementById('medNote').value = item.note || '';
  document.getElementById('medTotal').value = item.total_doses || '';
  document.getElementById('medStock').value = item.stock_total ?? '';
  document.getElementById('addMed').textContent = '保存修改';
  document.getElementById('medName').focus();
}

function resetMedForm() {
  editingMedId = null;
  document.getElementById('addMed').textContent = '添加';
  ['medName', 'medDose', 'medMethod', 'medNote', 'medTotal', 'medStock']
    .forEach(id => { document.getElementById(id).value = ''; });
}

async function addMed() {
  const permissionPromise = typeof requestDesktopPermission === 'function'
    ? requestDesktopPermission() : Promise.resolve(false);
  const name = document.getElementById('medName').value.trim();
  if (!name) { document.getElementById('medName').focus(); return; }
  const interval = parseFloat(document.getElementById('medInterval').value) || 8;
  const doses = parseInt(document.getElementById('medDoses').value, 10) || 2;
  const start = document.getElementById('medStart').value || '08:00';
  const payload = {
    name, dose: document.getElementById('medDose').value.trim(),
    method: document.getElementById('medMethod').value.trim(),
    interval_hours: interval, doses_per_day: doses, start_time: start,
    note: document.getElementById('medNote').value.trim(),
    total_doses: parseInt(document.getElementById('medTotal').value, 10) || null,
    stock_total: document.getElementById('medStock').value === ''
      ? null : parseFloat(document.getElementById('medStock').value),
  };
  const response = editingMedId
    ? await fetch(`/api/medications/${editingMedId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
    : await fetch('/api/medications', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
  if (!response.ok) { alert('保存失败：请检查间隔（0.5–24 小时）、次数（1–12）和首次时间'); return; }
  resetMedForm();
  await loadMeds();
  const granted = await permissionPromise;
  const hint = document.getElementById('medNotifyHint');
  if (hint) {
    hint.textContent = !window.isSecureContext
      ? '当前用 HTTP 访问，浏览器会拦截桌面通知；页面打开时仍会站内提醒。换成 HTTPS 后可开启。'
      : granted
        ? '桌面通知已开启：到点会弹窗提醒；关页后的提醒由后台推送负责。'
        : '未获得桌面通知权限：页面内仍会提醒；可在浏览器设置里允许通知。';
    hint.style.color = granted && window.isSecureContext ? '#0f766e' : '#b45309';
  }
  if (granted) {
    try { new Notification('用药提醒已开启', { body: '到点会提醒你吃药' }); } catch (error) { /* ignore */ }
    if (typeof subscribePushSilently === 'function') {
      subscribePushSilently().catch(() => {});
    }
  }
}

async function deleteMed(id) {
  await fetch(`/api/medications/${id}`, { method: 'DELETE' });
  await loadMeds();
}

async function testMed(id) {
  const response = await fetch(`/api/medications/${id}/test`, { method: 'POST' });
  const data = await response.json();
  if (data.item) showReminder([data.item]);
}

function reminderText(item) {
  const dose = item.dose ? ` ${item.dose}` : '';
  const method = item.method ? `，${item.method}` : '';
  const note = item.note ? `（${item.note}）` : '';
  if (item.stage === 2) {
    return `大郎，该吃药了！别忘了哦～ ${item.name}${dose}${method}${note}`;
  }
  return `大郎，该吃药了！${item.name}${dose}${method}${note}`;
}

function showToast(item) {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast';
  const title = item.stage === 2 ? '⏰ 第二次提醒' : '⏰ 该吃药了';
  el.innerHTML = `<div class="t">${title}</div><div class="d">${esc(reminderText(item))}</div>
    <button type="button">知道了</button>`;
  el.querySelector('button').onclick = () => {
    el.remove();
    fetch(`/api/medications/${item.id}/ack`, { method: 'POST' }).catch(() => {});
  };
  box.appendChild(el);
  setTimeout(() => el.remove(), 60000);
}

async function requestDesktopPermission() {
  if (!window.isSecureContext) return false;
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  try {
    return (await Notification.requestPermission()) === 'granted';
  } catch (error) {
    return false;
  }
}

async function subscribePushSilently() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
  if (!('Notification' in window) || Notification.permission !== 'granted') return false;
  try {
    const registration = await navigator.serviceWorker.register('/static/sw.js');
    const config = await (await fetch('/api/push/config')).json();
    const existing = await registration.pushManager.getSubscription();
    const subscription = existing || await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.publicKey),
    });
    const response = await fetch('/api/push/subscribe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription }),
    });
    return Boolean((await response.json()).subscribed);
  } catch (error) {
    return false;
  }
}

function showNotification(item) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  new Notification('该吃药了', { body: reminderText(item) });
}

function injectReminderMessage(item) {
  document.body.classList.add('chat');
  const el = addAssistant(`<div class="notice warn">💊 <b>用药提醒</b><br>${esc(reminderText(item))}</div>`);
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function showReminder(items) {
  items.forEach(item => {
    showToast(item);
    showNotification(item);
    injectReminderMessage(item);
  });
}

async function pollReminders() {
  try {
    const response = await fetch('/api/reminders/due');
    const data = await response.json();
    if (data.items && data.items.length) showReminder(data.items);
  } catch (error) { /* offline is fine */ }
}

document.getElementById('addMed').onclick = async () => {
  try { await addMed(); }
  catch (error) { alert('添加失败：' + (error && error.message ? error.message : '未知错误')); }
};
document.getElementById('closeMeds').onclick = () => {
  resetMedForm();
  document.getElementById('medOverlay').classList.remove('open');
  document.querySelectorAll('.side-item').forEach(i => i.classList.toggle('active', i.dataset.nav === 'chat'));
};
document.querySelectorAll('.side-item').forEach(button => {
  button.onclick = () => {
    document.querySelectorAll('.side-item').forEach(item => item.classList.remove('active'));
    button.classList.add('active');
    const nav = button.dataset.nav;
    if (nav === 'meds') {
      loadMeds();
      document.getElementById('medOverlay').classList.add('open');
    } else if (nav === 'team') {
      openTeam();
    } else if (nav === 'exp') {
      openExperiment();
    } else if (nav === 'abl') {
      openAblation();
    } else if (nav === 'profile') {
      openProfile();
    } else if (nav === 'plan') {
      openPlan();
    } else if (nav === 'cabinet') {
      openCabinet();
    } else {
      document.getElementById('medOverlay').classList.remove('open');
    }
  };
});
document.getElementById('medOverlay').onclick = event => {
  if (event.target.id === 'medOverlay') {
    document.getElementById('medOverlay').classList.remove('open');
  }
};
async function pollCrisisFollowups() {
  try {
    const response = await fetch('/api/crisis/followups/due');
    const data = await response.json();
    (data.items || []).forEach(item => {
      const toast = document.createElement('div');
      toast.className = 'toast';
      toast.innerHTML = `<div class="t">💛 我在惦记你</div>
        <div class="d">昨天你提到状态不太好，今天好一点了吗？不用急着回答，先照顾自己。</div>
        <button type="button">好多了</button>`;
      toast.querySelector('button').onclick = () => {
        toast.remove();
        fetch(`/api/crisis/followups/${item.id}/ack`, { method: 'POST' }).catch(() => {});
      };
      document.getElementById('toasts').appendChild(toast);
      setTimeout(() => toast.remove(), 120000);
    });
  } catch (error) { /* offline */ }
}

loadMeds();

const demoParams = new URLSearchParams(location.search);
if (demoParams.has('meds')) {
  setTimeout(() => document.querySelector('[data-nav="meds"]').click(), 400);
}
if (demoParams.has('remind')) {
  setTimeout(() => { if (medState.items[0]) testMed(medState.items[0].id); }, 1500);
}

// ---------------- 对话历史 ----------------
async function loadConversations(query) {
  const search = document.getElementById('convSearch');
  const keyword = query !== undefined ? query : (search ? search.value.trim() : '');
  try {
    const response = await fetch('/api/conversations' + (keyword ? `?q=${encodeURIComponent(keyword)}` : ''));
    const data = await response.json();
    const list = document.getElementById('convList');
    if (!data.items || !data.items.length) {
      list.innerHTML = `<div class="med-empty" style="padding:4px 10px">${keyword ? '没有匹配的会话' : '还没有历史对话'}</div>`;
      return;
    }
    list.innerHTML = data.items.map(item => `
      <div class="conv-row">
        <button class="conv-item ${item.id === state.conversationId ? 'active' : ''}" data-cid="${esc(item.id)}" data-title="${esc(item.title || '')}">
          ${esc(item.title || '新会话')}
          <span class="conv-time">${esc((item.updated_at || '').replace('T', ' ').slice(5, 16))}</span>
        </button>
        <span class="conv-actions">
          <button data-act="rename" title="重命名">✎</button>
          <button data-act="delete" title="删除">×</button>
        </span>
      </div>`).join('');
    list.querySelectorAll('.conv-item').forEach(button => {
      button.onclick = () => openConversation(button.dataset.cid);
    });
    list.querySelectorAll('.conv-row').forEach(row => {
      const cid = row.querySelector('.conv-item').dataset.cid;
      const title = row.querySelector('.conv-item').dataset.title;
      row.querySelector('[data-act="rename"]').onclick = async event => {
        event.stopPropagation();
        const next = prompt('会话名称', title || '');
        if (!next || next.trim() === title) return;
        await fetch(`/api/conversations/${cid}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: next.trim() }),
        });
        loadConversations();
      };
      row.querySelector('[data-act="delete"]').onclick = async event => {
        event.stopPropagation();
        if (!confirm('删除这个会话？')) return;
        await fetch(`/api/conversations/${cid}`, { method: 'DELETE' });
        if (state.conversationId === cid) newChat();
        else loadConversations();
      };
    });
  } catch (error) { /* offline */ }
}

function newChat() {
  state.conversationId = null;
  state.symptoms = '';
  state.answers = {};
  state.lastTrace = [];
  document.getElementById('thread').innerHTML = '';
  document.body.classList.remove('chat');
  updateTraceFab();
  loadConversations();
}

function historyResultHtml(data) {
  return runStrip(data) + lead(data) + summary(data)
    + tcmSection(data) + westernSection(data) + lifestyleSection(data) + sourceChip(data)
    + '<div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>' + detailsBlock(data);
}

async function openConversation(conversationId) {
  try {
    const response = await fetch(`/api/conversations/${conversationId}`);
    if (!response.ok) return;
    const data = await response.json();
    state.conversationId = conversationId;
    state.symptoms = '';
    state.answers = {};
    const thread = document.getElementById('thread');
    thread.innerHTML = '';
    document.body.classList.add('chat');
    (data.turns || []).forEach(turn => {
      addUser(turn.user_text || '');
      const kind = turn.result && turn.result.kind;
      addAssistant(kind === 'food' ? foodAnswerHtml(turn.result)
        : kind === 'food_guide' ? foodGuideHtml(turn.result)
        : kind === 'psych' ? psychAnswerHtml(turn.result)
        : kind === 'chitchat' ? chitchatAnswerHtml(turn.result)
        : kind === 'clarify' ? clarifyAnswerHtml(turn.result)
        : historyResultHtml(turn.result));
    });
    const last = (data.turns || [])[data.turns.length - 1];
    state.lastTrace = last ? (last.result.trace || []) : [];
    updateTraceFab();
    loadConversations();
  } catch (error) { /* ignore */ }
}

document.getElementById('convSearch').addEventListener('input', () => {
  clearTimeout(window.__convTimer);
  window.__convTimer = setTimeout(() => loadConversations(), 250);
});

document.querySelectorAll('.fresh-context').forEach(box => {
  box.onchange = () => {
    state.freshContext = box.checked;
    document.querySelectorAll('.fresh-context').forEach(other => { other.checked = box.checked; });
  };
});
document.getElementById('newChatBtn').onclick = newChat;
loadConversations();

const convParam = new URLSearchParams(location.search).get('conv');
if (convParam) { setTimeout(() => openConversation(convParam), 500); }

function ratingBadge(analysis) {
  const tone = analysis.rating_tone || 'warn';
  return `<span class="food-badge ${tone}">${esc(analysis.rating_label)}</span>`;
}

function foodCard(analysis) {
  if (!analysis) return '';
  const n = analysis.nutrition || {};
  const cells = [
    ['能量', n.energy_kcal, 'kcal'], ['蛋白质', n.protein_g, 'g'],
    ['脂肪', n.fat_g, 'g'], ['碳水', n.carb_g, 'g'],
    ['膳食纤维', n.fiber_g, 'g'], ['糖', n.sugar_g, 'g'],
    ['钠', n.sodium_mg, 'mg'],
  ].filter(([, value]) => value !== undefined && value !== null)
    .map(([label, value, unit]) => `<div><b>${esc(value)} ${unit}</b><span>${esc(label)}</span></div>`).join('');
  const benefits = (analysis.benefits || []).map(text => `<li>✓ ${esc(text)}</li>`).join('');
  const harms = (analysis.harms || []).map(text => `<li>⚠️ ${esc(text)}</li>`).join('');
  const sources = (analysis.sources || []).map(src =>
    `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.title)}</a>`).join(' · ');
  return `<div class="food-card">
    <div class="food-head"><span class="n">${esc(analysis.name)}</span>${ratingBadge(analysis)}
      <span class="muted" style="font-size:12px">${esc(analysis.unit || '每 100 g')}</span></div>
    <div class="nutrition">${cells}</div>
    <div class="food-lists">
      <div><b style="font-size:13px">好处</b><ul>${benefits || '<li>—</li>'}</ul></div>
      <div><b style="font-size:13px">多吃/常吃的坏处</b><ul>${harms || '<li>适量食用，无特殊风险</li>'}</ul></div>
    </div>
    ${analysis.tips ? `<div class="food-tip">💡 ${esc(analysis.tips)}</div>` : ''}
    ${sources ? `<div class="food-src">来源：${sources}</div>` : ''}
  </div>`;
}

function foodGuideHtml(data) {
  const sections = (data.sections || []).map(section =>
    `<div class="food-section"><div class="food-sub">${esc(section.heading)}</div>
      <ul>${(section.items || []).map(item => `<li>${esc(item)}</li>`).join('')}</ul></div>`
  ).join('');
  const sources = (data.sources || []).map(item =>
    `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.title)}</a>`
  ).join(' · ');
  return `<div class="food-card"><div class="food-head"><span class="n">🥗 ${esc(data.title)}</span></div>
    ${sections}${data.tips ? `<div class="notice" style="background:#f8fafc">${esc(data.tips)}</div>` : ''}
    ${sources ? `<div class="ai-note">参考：${sources}</div>` : ''}
    <div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div></div>`;
}

function foodAnswerHtml(data) {
  if (data.analysis) return foodCard(data.analysis) + '<div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>';
  if (data.items && data.items.length) return data.items.map(foodCard).join('') + '<div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>';
  return '<div class="notice warn">没有识别到具体食物，请换个说法。</div>';
}

if (new URLSearchParams(location.search).has('cabinet')) {
  setTimeout(() => openCabinet(), 600);
}
if (new URLSearchParams(location.search).has('plan')) {
  setTimeout(() => openPlan(), 600);
}
if (new URLSearchParams(location.search).has('profile')) {
  setTimeout(() => openProfile(), 600);
}
if (new URLSearchParams(location.search).has('abl')) {
  setTimeout(() => openAblation(), 600);
}
if (new URLSearchParams(location.search).has('team')) {
  setTimeout(() => openTeam(), 500);
}

function psychAnswerHtml(data) {
  const crisis = !!data.crisis;
  const empathy = (data.empathy || []).map(line => `<p>${esc(line)}</p>`).join('');
  const suggestions = (data.suggestions || []).map(line => `<li>${esc(line)}</li>`).join('');
  const professional = (data.professional || []).map(line => `<li>${esc(line)}</li>`).join('');
  const sources = (data.sources || []).map(src =>
    `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.title)}</a>`).join(' · ');
  const level = data.risk_level || 'none';
  const levelLabel = { high: '高风险', medium: '需要关注', low: '情绪低落' }[level] || '';
  const badge = crisis && levelLabel ? `<span class="risk-badge risk-${level}">${levelLabel}</span>` : '';
  const hotline = crisis
    ? `<div class="hotline">心理援助热线 12356 · 急救 120 / 110</div>${hotlinesHtml(data)}` : '';
  return `<div class="psych-card ${crisis ? 'psych-crisis' : ''}">
    <h4>${crisis ? '⚠️ 先确保你的安全' : '🫂 先抱抱你'}${badge}</h4>
    <div class="psych-empathy">${empathy}</div>
    ${hotline}
    <div class="psych-block"><b>可以试试这些</b><ul>${suggestions}</ul></div>
    ${professional ? `<div class="psych-help"><b>什么时候需要专业帮助</b><ul>${professional}</ul></div>` : ''}
    ${sources ? `<div class="psych-src">参考：${sources}</div>` : ''}
  </div><div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>`;
}

function chitchatAnswerHtml(data) {
  return `<div class="chat-card">${esc(data.reply || '我在听。')}</div>
    <div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>`;
}

function hotlinesHtml(data) {
  const list = data.hotlines || [];
  if (!list.length) return '';
  return `<div class="hotlines"><b>心理援助热线</b>${list.map(item =>
    `· ${esc(item.region)}：<b>${esc(item.number)}</b>${item.note ? `（${esc(item.note)}）` : ''}`).join('<br>')}
    </div>`;
}

async function openAblation() {
  const modal = document.getElementById('ablModal');
  modal.classList.add('open');
  const body = document.getElementById('ablBody');
  const sub = document.getElementById('ablSub');
  try {
    const data = await (await fetch('/api/ablation')).json();
    const labels = { full: '完整流程', no_review: '去掉安全审查',
                     no_kb: '去掉知识库', no_parallel: '去掉并行检索' };
    const rows = Object.entries(data.summary).map(([key, item]) =>
      `<tr><td>${labels[key] || key}</td><td>${item.avg_latency} s</td>
       <td>${item.avg_options}</td><td>${item.avg_sources}</td>
       <td>${item.cases_with_findings}</td></tr>`).join('');
    body.innerHTML = `<table class="xtable"><thead><tr>
      <th>变体</th><th>平均耗时</th><th>平均可选药物</th><th>平均来源</th><th>有审查问题用例</th>
      </tr></thead><tbody>${rows}</tbody></table>
      <p class="sub" style="margin-top:12px">${esc(data.injection
        ? `安全审查：干净报告 ${data.injection.clean_findings} 个问题；注入 2 条错误后抓到 ${data.injection.injected_findings} 个。`
        : '')}<br>${esc(data.router
        ? `路由 Agent：${data.router.router_correct}/${data.router.cases}（${Math.round(data.router.router_accuracy * 100)}%），全当问诊基线 ${Math.round(data.router.always_medical_accuracy * 100)}%。`
        : '')}</p>
      <p class="sub">去掉知识库后药物候选为 0；去掉并行后耗时约翻倍；去掉审查在模型路径才会暴露问题（见 docs/experiment.md）。</p>`;
    sub.textContent = '6 个用例，provider=mock；审查价值用"注入错误"验证。';
  } catch (error) {
    body.innerHTML = '<p class="sub">还没有生成消融数据，请先运行 scripts/ablation.py。</p>';
    sub.textContent = '';
  }
}

document.getElementById('closeAbl').onclick = () => document.getElementById('ablModal').classList.remove('open');
document.getElementById('ablModal').onclick = event => {
  if (event.target.id === 'ablModal') document.getElementById('ablModal').classList.remove('open');
};

async function openProfile(refreshOnly) {
  const modal = document.getElementById('profileModal');
  modal.classList.add('open');
  const profile = (await (await fetch('/api/profile')).json()).profile || {};
  document.getElementById('pfAge').value = profile.age || '';
  document.getElementById('pfSex').value = profile.sex || '';
  document.getElementById('pfPregnant').checked = !!profile.pregnant;
  document.getElementById('pfAllergies').value = (profile.allergies || []).join(',');
  document.getElementById('pfDietPref').value = profile.diet_pref || '';
  document.getElementById('pfMealStyle').value = profile.meal_style || '';
  document.getElementById('pfActivity').value = profile.activity_level || '';
  document.getElementById('pfAvoidFoods').value = profile.avoid_foods || '';
  document.querySelectorAll('#pfConditions input').forEach(box => {
    box.checked = (profile.conditions || []).includes(box.value);
  });
  document.getElementById('pfStatus').textContent = profile.updated_at
    ? `上次保存：${profile.updated_at.replace('T', ' ')}` : '还没保存';
  await loadMemoryList();
}

async function saveProfile() {
  const allergies = document.getElementById('pfAllergies').value
    .split(/[,，\s]+/).map(item => item.trim()).filter(Boolean);
  const conditions = [...document.querySelectorAll('#pfConditions input:checked')].map(box => box.value);
  const age = parseInt(document.getElementById('pfAge').value, 10);
  const response = await fetch('/api/profile', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      age: Number.isFinite(age) ? age : null,
      sex: document.getElementById('pfSex').value,
      pregnant: document.getElementById('pfPregnant').checked,
      allergies, conditions,
      diet_pref: document.getElementById('pfDietPref').value,
      avoid_foods: document.getElementById('pfAvoidFoods').value,
      meal_style: document.getElementById('pfMealStyle').value,
      activity_level: document.getElementById('pfActivity').value,
    }),
  });
  if (!response.ok) { document.getElementById('pfStatus').textContent = '保存失败'; return; }
  document.getElementById('pfStatus').textContent = '已保存，下次分析自动生效';
}

document.getElementById('clearNotes').onclick = async () => {
  if (!confirm('清空所有“上次记录”？已记住的过敏/慢病不受影响。')) return;
  await fetch('/api/memory/notes', { method: 'DELETE' });
  document.getElementById('pfStatus').textContent = '已清空上次记录';
};
document.getElementById('saveProfile').onclick = saveProfile;
document.getElementById('closeProfile').onclick = () => document.getElementById('profileModal').classList.remove('open');
document.getElementById('profileModal').onclick = event => {
  if (event.target.id === 'profileModal') document.getElementById('profileModal').classList.remove('open');
};

async function openPlan() {
  document.getElementById('planOverlay').classList.add('open');
  await loadPlan();
}

async function loadPlan() {
  const body = document.getElementById('planBody');
  const data = await (await fetch('/api/plan')).json();
  const plan = data.plan;
  if (!plan) {
    body.innerHTML = '<div class="notice" style="background:#f8fafc;color:#64748b">'
      + '还没有计划。先描述一次不舒服（比如失眠、胃胀），我会根据建议自动生成一周计划。</div>';
    return;
  }
  const p = plan.plan;
  const done = (plan.checkins || []).filter(item => item.diet && item.exercise)
    .map(item => item.check_date);
  const todayStr = new Date().toISOString().slice(0, 10);
  const week = plan.week || null;
  const todayPlan = week && week.days
    ? week.days.find(item => item.day === plan.days) : null;
  const weekHtml = week && week.days ? `
    <div class="plan-card"><div class="t">本周安排 · ${esc(week.theme || '恢复')}</div>
      ${week.days.map(item => `<div class="week-row ${item.day === plan.days ? 'active' : ''}">
        <div class="week-day">第 ${item.day} 天 · ${esc(item.focus)}</div>
        <ul>${(item.tasks || []).map(task => `<li>${esc(task)}</li>`).join('')}</ul>
      </div>`).join('')}
      <div class="s" style="color:#b45309;margin-top:6px">${esc(week.review || '')}</div>
      <div class="s">红旗：${esc((week.red_flags || []).join('；'))}</div>
    </div>` : '';
  const todayTasks = todayPlan && todayPlan.tasks
    ? `<ul class="today-tasks">${todayPlan.tasks.map(task => `<li>${esc(task)}</li>`).join('')}</ul>`
    : '';
  const today = plan.today || {};
  const grid = Array.from({ length: plan.total_days }, (_, index) => {
    const day = index + 1;
    const isDone = (plan.checkins || []).some(item =>
      item.diet && item.exercise && item.check_date === todayStr && day === plan.days);
    const filled = (plan.checkins || []).length > index;
    return `<div class="${filled ? 'done' : ''}">${day}</div>`;
  }).join('');
  body.innerHTML = `
    <div class="plan-day"><span>第 ${plan.days} / ${plan.total_days} 天</span>
      <span>坚持率 ${plan.adherence}%</span></div>
    <div class="plan-progress"><span style="width:${Math.round(plan.days / plan.total_days * 100)}%"></span></div>
    <div class="plan-card"><div class="t">本次目标</div>
      <div class="s">${esc(p.symptoms || '')}<br>${esc(p.summary || '')}</div></div>
    ${weekHtml}
    <div class="plan-card"><div class="t">今天的打卡</div>
      ${todayTasks}
      <div class="plan-check">
        <label><input type="checkbox" id="ckDiet" ${today.diet ? 'checked' : ''}/> 按建议吃</label>
        <label><input type="checkbox" id="ckExercise" ${today.exercise ? 'checked' : ''}/> 完成活动</label>
        <label><input type="checkbox" id="ckMeds" ${today.meds ? 'checked' : ''}/> 按时吃药</label>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin:6px 0 10px">
        <span style="font-size:13px;color:#64748b">今天症状评分</span>
        <input id="ckScore" type="range" min="0" max="10" value="${today.score >= 0 ? today.score : 5}" style="flex:1" />
        <b id="scoreVal" style="font-size:14px;color:#0f766e">${today.score >= 0 ? today.score : 5}</b>
      </div>
      <button class="primary" id="saveCheckin" type="button">保存打卡</button>
      <span id="planStatus" style="font-size:13px;color:#0f766e;margin-left:8px"></span>
    </div>
    <div class="plan-card"><div class="t">这一周</div><div class="plan-grid">${grid}</div>
      <div class="s">趋势：${esc((plan.trend || {}).label || '还不够判断')}${plan.trend && plan.trend.delta ? `（较第一天 ${plan.trend.delta > 0 ? '+' : ''}${plan.trend.delta} 分）` : ''}</div>
      <div id="trendChart"></div>
      ${plan.review_note ? `<div class="s" style="color:#b45309;margin-top:6px">${esc(plan.review_note)}</div>` : ''}
      <div class="s">第 7 天会根据评分自动调整：好转就延长一周，没好转就提醒复诊。</div></div>
    <button class="ghost" id="finishPlan" type="button" style="border:1px solid var(--line);border-radius:9px;padding:7px 12px;background:#fff;cursor:pointer">提前结束计划</button>`;
  const scoreInput = document.getElementById('ckScore');
  const scoreVal = document.getElementById('scoreVal');
  scoreInput.oninput = () => { scoreVal.textContent = scoreInput.value; };
  renderTrend(plan);
  document.getElementById('saveCheckin').onclick = async () => {
    const response = await fetch('/api/plan/checkin', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        diet: document.getElementById('ckDiet').checked,
        exercise: document.getElementById('ckExercise').checked,
        meds: document.getElementById('ckMeds').checked,
        score: parseInt(scoreInput.value, 10),
      }),
    });
    if (response.ok) {
      document.getElementById('planStatus').textContent = '已记录';
      await loadPlan();
    } else { document.getElementById('planStatus').textContent = '保存失败'; }
  };
  document.getElementById('finishPlan').onclick = async () => {
    await fetch('/api/plan/finish', { method: 'POST' });
    await loadPlan();
  };
}


function renderTrend(plan) {
  const box = document.getElementById('trendChart');
  if (!box) return;
  const scored = (plan.checkins || []).filter(item => item.score >= 0);
  if (scored.length < 2) {
    box.innerHTML = '<div class="s" style="color:#94a3b8">记录 2 天以上评分后显示趋势曲线</div>';
    return;
  }
  const width = 360, height = 84, pad = 8;
  const maxIndex = Math.max(1, scored.length - 1);
  const points = scored.map((item, index) => {
    const x = pad + (width - pad * 2) * (index / maxIndex);
    const y = pad + (height - pad * 2) * (1 - item.score / 10);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const dots = scored.map((item, index) => {
    const x = pad + (width - pad * 2) * (index / maxIndex);
    const y = pad + (height - pad * 2) * (1 - item.score / 10);
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="#0f766e"/>`;
  }).join('');
  box.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="width:100%;height:auto;margin-top:6px">
    <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#e2e8f0"/>
    <polyline points="${points}" fill="none" stroke="#0f766e" stroke-width="2.5" stroke-linejoin="round"/>
    ${dots}</svg>`;
}

async function pollPlanReminders() {
  try {
    const data = await (await fetch('/api/plan/reminders/due')).json();
    (data.items || []).forEach(item => {
      const texts = {
        d3: '已经坚持 3 天啦，今天感觉怎么样？记得打卡。',
        d7_good: '一周有改善，已自动延长一周；继续保持。',
        d7_review: '一周没有明显改善，建议复诊或咨询医生。',
        d14: '两周了：恢复得怎么样？如果还没好，建议复诊收尾。',
      };
      const text = texts[item.kind] || '康复计划提醒';
      const toast = document.createElement('div');
      toast.className = 'toast';
      toast.innerHTML = `<div class="t">🌱 康复计划</div><div class="d">${esc(text)}</div>
        <button type="button">${item.kind === 'd3' ? '去打卡' : '知道了'}</button>`;
      toast.querySelector('button').onclick = () => {
        toast.remove();
        if (item.kind === 'd3') openPlan();
      };
      document.getElementById('toasts').appendChild(toast);
      setTimeout(() => toast.remove(), 120000);
    });
  } catch (error) { /* offline */ }
}

document.getElementById('closePlan').onclick = () => document.getElementById('planOverlay').classList.remove('open');
document.getElementById('planOverlay').onclick = event => {
  if (event.target.id === 'planOverlay') document.getElementById('planOverlay').classList.remove('open');
};

const shownNotifications = new Set();

async function pollNotifications() {
  try {
    const data = await (await fetch('/api/notifications/unread')).json();
    const fresh = (data.items || []).filter(item => !shownNotifications.has(item.id));
    if (!fresh.length) return;
    fresh.forEach(item => {
      shownNotifications.add(item.id);
      showNotificationToast(item);
    });
    // 页面已经展示过，标记为已读，避免重复弹和后台通知器重复推
    const ids = fresh.map(item => item.id);
    await fetch('/api/notifications/ack', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }).catch(() => {});
  } catch (error) { /* offline */ }
}

function showNotificationToast(item) {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast';
  const kind = item.kind || '';
  let actions = '<button type="button" data-act="ack">知道了</button>';
  if (kind.startsWith('med:')) {
    actions = '<button type="button" data-act="take">已吃（打卡）</button>'
      + '<button type="button" data-act="ack" style="margin-left:8px;background:#e2e8f0;color:#0f172a">知道了</button>'
      + '<button type="button" data-act="snooze" style="margin-left:8px;background:#e2e8f0;color:#0f172a">10 分钟后</button>'
      + '<button type="button" data-act="skip" style="margin-left:8px;background:#fee2e2;color:#b91c1c">跳过这次</button>';
  } else if (kind === 'plan:d3') {
    actions = '<button type="button" data-act="plan">去打卡</button>'
      + '<button type="button" data-act="ack" style="margin-left:8px;background:#e2e8f0;color:#0f172a">知道了</button>';
  }
  el.innerHTML = `<div class="t">${esc(item.title)}</div><div class="d">${esc(item.body)}</div>${actions}`;
  const medId = kind.startsWith('med:') ? kind.slice(4) : null;
  const ack = () => fetch('/api/notifications/ack', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [item.id] }),
  }).catch(() => {});
  el.querySelectorAll('button').forEach(button => {
    button.onclick = () => {
      const act = button.dataset.act;
      if (act === 'take' && medId) {
        fetch(`/api/medications/${medId}/take`, { method: 'POST' }).catch(() => {});
      } else if (act === 'snooze' && medId) {
        fetch(`/api/medications/${medId}/pause?minutes=10`, { method: 'POST' }).catch(() => {});
      } else if (act === 'skip' && medId) {
        fetch(`/api/medications/${medId}/skip`, { method: 'POST' }).catch(() => {});
      } else if (act === 'plan') {
        openPlan();
      }
      ack();
      el.remove();
    };
  });
  box.appendChild(el);
  setTimeout(() => el.remove(), 120000);
}

setInterval(pollNotifications, 15000);
pollNotifications();

function dragonBalls(taken, total, completed) {
  const count = Math.max(1, Math.min(total, 30));
  const lit = completed ? count : Math.min(count, Math.round(taken / Math.max(1, total) * count));
  const colors = ['#ef4444', '#f97316', '#facc15', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899'];
  return Array.from({ length: count }, (_, index) => {
    const on = index < lit;
    const color = colors[index % colors.length];
    return `<span class="${on ? 'lit' : ''}" style="--c:${color};animation-delay:-${(index * 0.13).toFixed(2)}s">${on ? '★' : ''}</span>`;
  }).join('');
}

async function openCabinet() {
  document.getElementById('cabOverlay').classList.add('open');
  await loadCabinet();
}

async function loadCabinet() {
  const list = document.getElementById('cabList');
  const data = await (await fetch('/api/cabinet')).json();
  if (!data.items || !data.items.length) {
    list.innerHTML = '<div class="notice" style="background:#f8fafc;color:#64748b">药品柜是空的，先添加一个疗程。</div>';
    return;
  }
  list.innerHTML = data.items.map(item => `
    <div class="cab-item ${item.completed ? 'done' : ''}">
      <div class="n">${esc(item.name)} ${item.completed ? '🏆' : ''}</div>
      <div class="m">已打卡 ${item.taken} / ${item.total} 次</div>
      <div class="cab-balls">${dragonBalls(item.taken, item.total, item.completed)}</div>
      ${item.completed ? '<div class="cab-dragon">🐉 集齐龙珠，神龙出现！疗程完成～</div>' : ''}
      <div class="cab-actions">
        <button data-act="take" data-id="${esc(item.id)}">打卡一次</button>
        <button data-act="del" data-id="${esc(item.id)}">删除</button>
      </div>
    </div>`).join('');
  list.querySelectorAll('button[data-act="take"]').forEach(button => {
    button.onclick = async () => {
      const response = await fetch(`/api/cabinet/${button.dataset.id}/take`, { method: 'POST' });
      const result = await response.json();
      await loadCabinet();
      if (result.item && result.item.just_completed) {
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.innerHTML = `<div class="t">🐉 神龙出现</div>
          <div class="d">${esc(result.item.name)} 的 ${result.item.total} 次全部打卡完成，疗程结束！</div>
          <button type="button">太好了</button>`;
        toast.querySelector('button').onclick = () => toast.remove();
        document.getElementById('toasts').appendChild(toast);
        setTimeout(() => toast.remove(), 30000);
      }
    };
  });
  list.querySelectorAll('button[data-act="del"]').forEach(button => {
    button.onclick = async () => {
      await fetch(`/api/cabinet/${button.dataset.id}`, { method: 'DELETE' });
      await loadCabinet();
    };
  });
}

async function addCabinet() {
  const name = document.getElementById('cabName').value.trim();
  if (!name) return;
  const total = parseInt(document.getElementById('cabTotal').value, 10) || 7;
  await fetch('/api/cabinet', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, total }),
  });
  document.getElementById('cabName').value = '';
  await loadCabinet();
}

document.getElementById('cabAdd').onclick = addCabinet;
document.getElementById('closeCab').onclick = () => document.getElementById('cabOverlay').classList.remove('open');
document.getElementById('cabOverlay').onclick = event => {
  if (event.target.id === 'cabOverlay') document.getElementById('cabOverlay').classList.remove('open');
};

function clarifyAnswerHtml(data) {
  const options = (data.options || []).map(option =>
    `<button type="button" data-intent="${esc(option.intent)}">${esc(option.label)}</button>`).join('');
  return `<div class="clarify-card"><div class="q">🤔 ${esc(data.question || '你想问的是哪方面？')}</div>
    <div class="opts">${options}</div></div>
    <div class="ai-note">本回答由 AI 生成，内容仅供参考，请仔细甄别</div>`;
}

async function loadMemoryList() {
  const box = document.getElementById('memList');
  try {
    const data = await (await fetch('/api/memory')).json();
    const facts = data.facts || [];
    if (!facts.length) {
      box.innerHTML = '<span style="font-size:12.5px;color:#94a3b8">还没有记住任何信息</span>';
      return;
    }
    const labels = { allergy: '过敏', condition: '慢病', pregnancy: '孕期' };
    box.innerHTML = facts.map(fact =>
      `<span class="mem-chip">${labels[fact.fact_type] || fact.fact_type}：${esc(fact.value)}
        <button type="button" data-edit="${fact.id}" data-value="${esc(fact.value)}" title="修改">✎</button>
        <button type="button" data-id="${fact.id}" title="删除">×</button></span>`).join('');
    box.querySelectorAll('button[data-edit]').forEach(button => {
      button.onclick = async () => {
        const next = prompt('修改这条记忆', button.dataset.value || '');
        if (!next || next.trim() === button.dataset.value) return;
        await fetch(`/api/memory/facts/${button.dataset.edit}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value: next.trim() }),
        });
        await loadMemoryList();
        await openProfile(true);
      };
    });
    box.querySelectorAll('button[data-id]').forEach(button => {
      button.onclick = async () => {
        await fetch(`/api/memory/facts/${button.dataset.id}`, { method: 'DELETE' });
        await loadMemoryList();
        await openProfile(true);
      };
    });
  } catch (error) { box.innerHTML = ''; }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map(char => char.charCodeAt(0)));
}

async function enablePush() {
  const status = document.getElementById('pushStatus');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    status.textContent = '当前浏览器不支持 Web Push';
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    status.textContent = '未获得通知权限';
    return;
  }
  const registration = await navigator.serviceWorker.register('/static/sw.js');
  const config = await (await fetch('/api/push/config')).json();
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(config.publicKey),
  });
  const response = await fetch('/api/push/subscribe', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ subscription }),
  });
  const result = await response.json();
  status.textContent = result.subscribed ? '已开启：关页/其他设备也能收到' : '订阅失败';
}

async function testPush() {
  const status = document.getElementById('pushStatus');
  const result = await (await fetch('/api/push/test', { method: 'POST' })).json();
  status.textContent = `已发送：成功 ${result.sent}，失败 ${result.failed}，订阅 ${result.subscriptions}`;
}

document.getElementById('enablePush').onclick = enablePush;
document.getElementById('testPush').onclick = testPush;

/* --- 自定义模型接口（OpenAI / Anthropic） --- */
const CUSTOM_STORE = 'health-custom-api';
let serverCustomDefaults = { base: '', model: '' };
let cusKeysArr = [];
let cusModelsArr = [];
let cusFormatValue = 'openai';

fetch('/api/config').then(response => response.json())
  .then(data => { serverCustomDefaults = data.custom_api || serverCustomDefaults; })
  .catch(() => {});

function customConfig() {
  try {
    const raw = sessionStorage.getItem(CUSTOM_STORE);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data && data.base && data.models && data.models.length) {
      return { name: data.name || '自定义接口', base: data.base,
               format: data.format || 'openai',
               keys: Array.isArray(data.keys) ? data.keys : [],
               models: data.models };
    }
  } catch (error) { /* ignore */ }
  return null;
}

function saveCustomConfig(config) {
  sessionStorage.setItem(CUSTOM_STORE, JSON.stringify(config));
}

function renderCusKeys() {
  const box = document.getElementById('cusKeys');
  box.innerHTML = cusKeysArr.map((key, index) =>
    `<span class="cus-chip">密钥 ${index + 1} ····${esc(key.slice(-4))}
      <button type="button" data-idx="${index}">×</button></span>`).join('');
  box.querySelectorAll('button[data-idx]').forEach(button => {
    button.onclick = () => { cusKeysArr.splice(Number(button.dataset.idx), 1); renderCusKeys(); };
  });
}

function renderCusModels() {
  const box = document.getElementById('cusModels');
  box.innerHTML = cusModelsArr.map((model, index) =>
    `<span class="cus-chip">${index + 1}. ${esc(model)}
      <button type="button" data-idx="${index}">×</button></span>`).join('');
  box.querySelectorAll('button[data-idx]').forEach(button => {
    button.onclick = () => { cusModelsArr.splice(Number(button.dataset.idx), 1); renderCusModels(); };
  });
}

function openCustomModal() {
  const config = customConfig() || {};
  document.getElementById('cusName').value = config.name || '';
  document.getElementById('cusBase').value = config.base || serverCustomDefaults.base || '';
  document.getElementById('cusKey').value = '';
  cusKeysArr = Array.isArray(config.keys) ? [...config.keys] : [];
  cusModelsArr = Array.isArray(config.models) ? [...config.models]
    : (serverCustomDefaults.model ? [serverCustomDefaults.model] : []);
  cusFormatValue = config.format || 'openai';
  document.querySelectorAll('#cusFormat button').forEach(button => {
    button.classList.toggle('active', button.dataset.fmt === cusFormatValue);
  });
  document.getElementById('cusStatus').textContent = '';
  document.getElementById('cusFetch').innerHTML = '';
  renderCusKeys();
  renderCusModels();
  document.getElementById('customModal').classList.add('open');
}

function closeCustomModal() {
  document.getElementById('customModal').classList.remove('open');
}

document.getElementById('closeCustom').onclick = closeCustomModal;
document.getElementById('customModal').onclick = event => {
  if (event.target.id === 'customModal') closeCustomModal();
};

document.getElementById('addCusKey').onclick = () => {
  const input = document.getElementById('cusKey');
  const key = input.value.trim();
  if (!key) return;
  if (!cusKeysArr.includes(key)) cusKeysArr.push(key);
  input.value = '';
  renderCusKeys();
};


document.querySelectorAll('#cusFormat button').forEach(button => {
  button.onclick = () => {
    cusFormatValue = button.dataset.fmt;
    document.querySelectorAll('#cusFormat button').forEach(item => {
      item.classList.toggle('active', item === button);
    });
  };
});

let modelImportCandidates = [];
let modelImportSelected = new Set();

function renderModelImport() {
  const list = document.getElementById('modelImportList');
  const search = document.getElementById('modelSearch');
  const keyword = (search.value || '').trim().toLowerCase();
  const visible = modelImportCandidates.filter(name =>
    !keyword || name.toLowerCase().includes(keyword));
  list.innerHTML = visible.map(name =>
    `<label class="model-row"><input type="checkbox" data-model="${esc(name)}"
      ${modelImportSelected.has(name) ? 'checked' : ''} /><span>${esc(name)}</span></label>`
  ).join('') || '<div class="model-empty">没有匹配的模型</div>';
  list.querySelectorAll('input[data-model]').forEach(box => {
    box.onchange = () => {
      if (box.checked) modelImportSelected.add(box.dataset.model);
      else modelImportSelected.delete(box.dataset.model);
      updateModelImportCount();
    };
  });
  updateModelImportCount();
}

function updateModelImportCount() {
  const button = document.getElementById('modelImportUpdate');
  const all = document.getElementById('modelSelectAll');
  button.textContent = `更新列表（${modelImportSelected.size}/${modelImportCandidates.length}）`;
  button.disabled = modelImportSelected.size === 0;
  all.textContent = modelImportSelected.size === modelImportCandidates.length
    ? '取消全选' : '全选';
}

function openModelImport(models) {
  modelImportCandidates = models.slice(0, 20);
  modelImportSelected = new Set(models.length === 1 ? [models[0]] : []);
  document.getElementById('modelSearch').value = '';
  document.getElementById('modelImportHint').textContent =
    `从服务商拉到 ${models.length} 个模型，勾选后加入优先级。`;
  renderModelImport();
  document.getElementById('modelImportModal').classList.add('open');
}

async function fetchCusModels() {
  const status = document.getElementById('cusStatus');
  const base = document.getElementById('cusBase').value.trim();
  const key = cusKeysArr[0] || document.getElementById('cusKey').value.trim();
  if (!base || !key) {
    status.style.color = '#b91c1c';
    status.textContent = '先填 API 地址和密钥';
    return null;
  }
  status.style.color = '#64748b';
  status.textContent = '正在连接并拉取模型…';
  try {
    const response = await fetch('/api/custom/models', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base, api_key: key, api_format: cusFormatValue }),
    });
    const data = await response.json();
    if (!response.ok) {
      status.style.color = '#b91c1c';
      status.textContent = data.detail || ('HTTP ' + response.status);
      document.getElementById('manualModelFallback').open = true;
      return null;
    }
    const models = data.models || [];
    if (!models.length) {
      status.style.color = '#b91c1c';
      status.textContent = '服务商没有返回模型，请展开下方手动填写';
      document.getElementById('manualModelFallback').open = true;
      return [];
    }
    status.style.color = '#0f766e';
    status.textContent = `连接成功，找到 ${models.length} 个模型，请选择`;
    openModelImport(models);
    return models;
  } catch (error) {
    status.style.color = '#b91c1c';
    status.textContent = '连接失败：' + error.message;
    return null;
  }
}


function activateCustom() {
  const typedKey = document.getElementById('cusKey').value.trim();
  if (typedKey && !cusKeysArr.includes(typedKey)) cusKeysArr.push(typedKey);
  const name = document.getElementById('cusName').value.trim() || '自定义接口';
  const base = document.getElementById('cusBase').value.trim();
  if (!base) { alert('请填写 API 地址'); return false; }
  if (!cusModelsArr.length) { alert('先拉取模型并勾选一个'); return false; }
  if (!cusKeysArr.length) { alert('至少添加一个 API 密钥'); return false; }
  saveCustomConfig({ name, base, format: cusFormatValue,
                     keys: cusKeysArr, models: cusModelsArr });
  provider = 'custom';
  document.querySelectorAll('.modelSel').forEach(select => { select.value = 'custom'; });
  document.querySelectorAll('.modelSel option[value="custom"]').forEach(option => {
    option.textContent = name;
  });
  closeCustomModal();
  return true;
}

document.getElementById('fetchModels').onclick = () => { fetchCusModels(); };

document.getElementById('testActivate').onclick = async () => {
  const status = document.getElementById('cusStatus');
  const base = document.getElementById('cusBase').value.trim();
  const key = cusKeysArr[0] || document.getElementById('cusKey').value.trim();
  const model = cusModelsArr[0];
  status.style.color = '#b91c1c';
  if (!base) { status.textContent = '先填 API 地址'; return; }
  if (!key) { status.textContent = '先填 API 密钥'; return; }
  if (!model) { status.textContent = '先拉取模型并勾选一个'; return; }
  status.style.color = '#64748b';
  status.textContent = '正在测试对话接口（不依赖模型列表接口）…';
  try {
    const response = await fetch('/api/custom/test', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base, api_key: key, model, api_format: cusFormatValue }),
    });
    const data = await response.json();
    if (!response.ok) {
      status.style.color = '#b91c1c';
      status.textContent = data.detail || ('HTTP ' + response.status);
      return;
    }
    status.style.color = '#0f766e';
    status.textContent = '连接成功，已激活';
    activateCustom();
  } catch (error) {
    status.style.color = '#b91c1c';
    status.textContent = '连接失败：' + error.message;
  }
};


document.getElementById('clearCustom').onclick = () => {
  sessionStorage.removeItem(CUSTOM_STORE);
  cusKeysArr = [];
  cusModelsArr = [];
  document.getElementById('cusKey').value = '';
  renderCusKeys();
  renderCusModels();
  provider = 'mock';
  document.querySelectorAll('.modelSel').forEach(select => { select.value = 'mock'; });
  closeCustomModal();
};


document.getElementById('closeModelImport').onclick = () => {
  document.getElementById('modelImportModal').classList.remove('open');
};
document.getElementById('modelImportModal').onclick = event => {
  if (event.target.id === 'modelImportModal') {
    document.getElementById('modelImportModal').classList.remove('open');
  }
};
document.getElementById('modelSearch').addEventListener('input', renderModelImport);
document.getElementById('modelSelectAll').onclick = () => {
  if (modelImportSelected.size === modelImportCandidates.length) {
    modelImportSelected.clear();
  } else {
    modelImportSelected = new Set(modelImportCandidates);
  }
  renderModelImport();
};
document.getElementById('modelImportUpdate').onclick = () => {
  const selected = [...modelImportSelected];
  if (!selected.length) return;
  const rest = cusModelsArr.filter(model => !selected.includes(model));
  cusModelsArr = [...selected, ...rest].slice(0, 20);
  renderCusModels();
  document.getElementById('modelImportModal').classList.remove('open');
  const status = document.getElementById('cusStatus');
  status.style.color = '#0f766e';
  status.textContent = `已加入 ${selected.length} 个模型，继续点“测试连接并激活”`;
};

document.getElementById('addManualModel').onclick = () => {
  const input = document.getElementById('cusManualModel');
  const model = input.value.trim();
  if (!model) return;
  if (!cusModelsArr.includes(model) && cusModelsArr.length < 20) {
    cusModelsArr.push(model);
  }
  input.value = '';
  renderCusModels();
  const status = document.getElementById('cusStatus');
  status.style.color = '#0f766e';
  status.textContent = '已加入模型，点“测试连接并激活”';
};

document.getElementById('customEntry').onclick = openCustomModal;

if (new URLSearchParams(location.search).has('custom')) {
  setTimeout(() => openCustomModal(), 500);
}




/* 顶部三个实验入口 */
document.querySelectorAll('.topnav-item').forEach(button => {
  button.onclick = () => {
    if (button.dataset.top === 'team') openTeam();
    else if (button.dataset.top === 'exp') openExperiment();
    else if (button.dataset.top === 'abl') openAblation();
  };
});

/* --- 统一助手：不再分栏目，按问题自动回答 --- */
(function initUnifiedHero() {
  const greet = document.getElementById('greet');
  const sub = document.getElementById('heroSub');
  const chips = document.getElementById('heroChips');
  if (greet) greet.textContent = '健康助手';
  if (sub) sub.innerHTML = '身体不舒服、情绪困扰、饮食营养，直接说就行。<br>'
    + '我会先判断你问的是哪方面，再给对应的建议，不会答非所问。';
  if (chips) {
    const examples = [
      ['发烧咽痛', '发烧，咽喉痛，有点怕冷'],
      ['焦虑失眠', '最近压力大，焦虑，晚上睡不着'],
      ['减脂早餐', '减脂早餐怎么吃'],
      ['崴脚肿了', '崴脚了，脚踝肿了'],
    ];
    chips.innerHTML = examples.map(item =>
      `<span class="chip" data-ex="${esc(item[1])}">${esc(item[0])}</span>`).join('');
    bindChips();
  }
})();
