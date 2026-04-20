/* Mini Devin — Frontend Controller */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  sessionId:   null,
  eventSource: null,
  isRunning:   false,
  files:       {},   // filename → { filename, language, description, content, lines }
  tests:       [],
  review:      null,
  agentStates: {
    task_planner:'pending', code_generator:'pending',
    tester:'pending', debugger:'pending', reviewer:'pending',
  },
};

const AGENT_META = {
  task_planner:   { icon:'🧠', label:'Task Planner',   color:'#b57bee' },
  code_generator: { icon:'⚙️', label:'Code Generator', color:'#00d4ff' },
  tester:         { icon:'🧪', label:'Tester',         color:'#00ff88' },
  debugger:       { icon:'🐛', label:'Debugger',       color:'#ff8c42' },
  reviewer:       { icon:'🔍', label:'Reviewer',       color:'#ffd43b' },
  pipeline:       { icon:'🚀', label:'Pipeline',       color:'#8b949e' },
};

const $  = id => document.getElementById(id);
const taskInput = $('taskInput');
const runBtn    = $('runBtn');
const streamLog = $('streamLog');

// ── Example tasks ──────────────────────────────────────────────────────────────
document.querySelectorAll('.example-chip').forEach(chip =>
  chip.addEventListener('click', () => { taskInput.value = chip.dataset.task; taskInput.focus(); })
);

// ── Run ────────────────────────────────────────────────────────────────────────
runBtn.addEventListener('click', startPipeline);
taskInput.addEventListener('keydown', e => { if (e.ctrlKey && e.key === 'Enter') startPipeline(); });

async function startPipeline() {
  const task = taskInput.value.trim();
  if (!task || state.isRunning) return;
  resetUI();
  state.isRunning = true;
  runBtn.disabled = true;
  runBtn.innerHTML = '<span class="spin">⟳</span> Running...';
  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task }),
    });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
    const data = await res.json();
    state.sessionId = data.session_id;
    appendLog('pipeline', 'pipeline_start', `Session: ${data.session_id}`);
    connectStream(data.stream_url);
  } catch (err) {
    appendLog('pipeline', 'error', `❌ ${err.message}`);
    resetRunBtn();
  }
}

// ── SSE Stream ─────────────────────────────────────────────────────────────────
function connectStream(url) {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = new EventSource(url);
  state.eventSource.onmessage = e => { try { handleEvent(JSON.parse(e.data)); } catch(_){} };
  state.eventSource.onerror = () => {
    appendLog('pipeline', 'error', '⚠️ Stream lost');
    state.eventSource.close();
    resetRunBtn();
  };
}

// ── Event Handler ──────────────────────────────────────────────────────────────
function handleEvent(msg) {
  const { agent, event, data } = msg;
  switch (event) {
    case 'heartbeat':        return;
    case 'pipeline_start':   appendLog(agent, event, data.message); break;
    case 'agent_start':      setAgentState(agent,'running'); appendLog(agent, event, data.message); break;
    case 'thinking':         appendLog(agent, event, data.message); break;
    case 'stream_chunk':     appendChunk(data.agent, data.chunk); break;
    case 'agent_retry':      appendLog(agent, event, data.message); break;
    case 'agent_error':      appendLog(agent, event, `❌ ${data.error}`); break;
    case 'agent_complete':   setAgentState(agent,'success'); clearChunkBuf(agent); appendLog(agent, event, data.message); break;
    case 'cache_hit':        appendLog(agent, event, data.message); break;

    case 'files_generated':
      // ✅ Content arrives HERE — store it all keyed by filename
      appendLog(agent, event, data.message);
      (data.files || []).forEach(f => {
        state.files[f.filename] = {
          filename:    f.filename,
          language:    f.language   || 'text',
          description: f.description || '',
          content:     f.content    || '',
          lines:       f.lines      || (f.content ? f.content.split('\n').length : 0),
        };
      });
      renderFileList();
      break;

    case 'tests_complete':   appendLog(agent, event, data.message); renderTests(data); break;
    case 'no_bugs':          appendLog(agent, event, data.message); break;
    case 'debug_complete':   appendLog(agent, event, data.message); break;
    case 'review_complete':  appendLog(agent, event, data.message); renderReview(data); break;
    case 'pipeline_complete': onPipelineComplete(data); break;
    case 'pipeline_error':   appendLog('pipeline', event, data.message); break;
    default: if (data?.message) appendLog(agent, event, data.message);
  }
}

// ── Logging ────────────────────────────────────────────────────────────────────
let chunkBuf = {};

function appendLog(agent, event, message) {
  const now  = new Date();
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  const meta = AGENT_META[agent] || AGENT_META.pipeline;
  const el   = document.createElement('div');
  el.className = 'log-entry';
  el.innerHTML = `
    <span class="log-time">${time}</span>
    <span class="log-agent-tag tag-${agent}">${meta.icon} ${meta.label}</span>
    <span class="log-msg">${escHtml(message)}</span>`;
  streamLog.appendChild(el);
  streamLog.scrollTop = streamLog.scrollHeight;
}

function appendChunk(agent, chunk) {
  if (!chunkBuf[agent]) {
    const el   = document.createElement('div');
    el.className = 'log-entry';
    const meta = AGENT_META[agent] || AGENT_META.pipeline;
    el.innerHTML = `
      <span class="log-time">···</span>
      <span class="log-agent-tag tag-${agent}">${meta.icon} ${meta.label}</span>
      <span class="log-chunk" id="chunk-${agent}"></span>`;
    streamLog.appendChild(el);
    chunkBuf[agent] = document.getElementById(`chunk-${agent}`);
  }
  const el = chunkBuf[agent];
  el.textContent = (el.textContent + chunk).slice(-160) + '▋';
  streamLog.scrollTop = streamLog.scrollHeight;
}

function clearChunkBuf(agent) {
  if (chunkBuf[agent]) { chunkBuf[agent].textContent = chunkBuf[agent].textContent.replace('▋',''); delete chunkBuf[agent]; }
}

// ── Agent cards ────────────────────────────────────────────────────────────────
function setAgentState(agent, status) {
  state.agentStates[agent] = status;
  const card  = document.querySelector(`.agent-card[data-agent="${agent}"]`);
  if (!card) return;
  card.className = `agent-card ${status}`;
  const badge = card.querySelector('.agent-status-badge');
  if (badge) { badge.className = `agent-status-badge badge-${status}`; badge.textContent = cap(status); }
  const fill = card.querySelector('.agent-progress-fill');
  if (fill && status === 'success') fill.style.width = '100%';
}

// ── Files tab ──────────────────────────────────────────────────────────────────
function renderFileList() {
  const files = Object.values(state.files);
  if (!files.length) return;
  switchTab('files');

  const container = $('filesContainer');
  container.innerHTML = '';

  // ── Download-all bar ──
  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:12px;';
  bar.innerHTML = `
    <span style="font-size:12px;color:var(--text-secondary);">${files.length} file(s) generated</span>
    <button class="dl-btn dl-btn-all" onclick="downloadAllZip()">⬇ Download All (.zip)</button>`;
  container.appendChild(bar);

  // ── One card per file ──
  files.forEach((f, i) => {
    const card = document.createElement('div');
    card.className = 'file-item';
    card.id = `fi-${i}`;

    card.innerHTML = `
      <div class="file-item-header" onclick="toggleFile(${i})">
        <span class="file-name">📄 ${escHtml(f.filename)}</span>
        <div class="file-meta">
          <span class="file-lang">${escHtml(f.language)}</span>
          <span class="file-lines">${f.lines} lines</span>
          <button class="dl-btn" onclick="event.stopPropagation();dlFile('${escAttr(f.filename)}')">⬇</button>
        </div>
      </div>
      ${f.description ? `<div class="file-desc">${escHtml(f.description)}</div>` : ''}
      <div class="file-code-wrapper" id="fcw-${i}" style="display:none;">
        <div class="code-toolbar">
          <span class="code-lang-label">${escHtml(f.language)}</span>
          <button class="dl-btn" id="copy-btn-${i}" onclick="copyCode(${i})">📋 Copy</button>
          <button class="dl-btn" onclick="dlFile('${escAttr(f.filename)}')">⬇ Download</button>
        </div>
        <pre class="file-code" id="fc-${i}"></pre>
      </div>`;

    container.appendChild(card);

    // ✅ Write content immediately — it's already in state.files
    const pre = document.getElementById(`fc-${i}`);
    if (f.content) {
      pre.textContent = f.content;
    } else {
      pre.innerHTML = `<span style="color:var(--text-muted);">No content available</span>`;
    }
  });
}

// toggle open/close
window.toggleFile = function(i) {
  const wrapper = $(`fcw-${i}`);
  const card    = $(`fi-${i}`);
  const open    = wrapper.style.display !== 'none';
  wrapper.style.display = open ? 'none' : 'block';
  card.classList.toggle('expanded', !open);
};

// copy to clipboard
window.copyCode = function(i) {
  const pre = $(`fc-${i}`);
  if (!pre) return;
  navigator.clipboard.writeText(pre.textContent).then(() => {
    const btn = $(`copy-btn-${i}`);
    if (btn) { btn.textContent = '✅ Copied!'; setTimeout(() => btn.textContent = '📋 Copy', 1500); }
  });
};

// download single file via API (falls back to data-uri)
window.dlFile = function(filename) {
  if (state.sessionId) {
    const a = document.createElement('a');
    a.href     = `/api/sessions/${state.sessionId}/download/${encodeURIComponent(filename)}`;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return;
  }
  // fallback: data-uri from in-memory content
  const f = state.files[filename];
  if (!f) return;
  const blob = new Blob([f.content], { type: 'text/plain' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

// download all as zip
window.downloadAllZip = function() {
  if (state.sessionId) {
    window.location.href = `/api/sessions/${state.sessionId}/download-zip`;
    return;
  }
  // fallback: create zip client-side (needs JSZip — not loaded, so just alert)
  alert('Session not ready yet. Please wait for the pipeline to finish.');
};

// ── Tests tab ──────────────────────────────────────────────────────────────────
function renderTests(data) {
  state.tests = data.tests || [];
  $('testsContainer').innerHTML = `
    <div style="margin-bottom:12px;font-size:12px;">
      <span style="color:var(--accent-green)">✅ ${data.passed||0} passed</span> &nbsp;
      <span style="color:var(--accent-red)">❌ ${data.failed||0} failed</span> &nbsp;
      <span style="color:var(--text-muted)">Coverage ~${data.coverage||'?'}%</span>
    </div>
    <div class="test-list">
      ${state.tests.map(t => `
        <div class="test-item ${t.passed?'pass':'fail'}">
          <span class="test-icon">${t.passed?'✅':'❌'}</span>
          <div>
            <div class="test-name">${escHtml(t.name)}</div>
            <div class="test-output">${escHtml(t.output||'')}</div>
          </div>
        </div>`).join('')}
    </div>`;
}

// ── Review tab ─────────────────────────────────────────────────────────────────
function renderReview(data) {
  state.review = data;
  const pct = v => `${((v||0)*10).toFixed(0)}%`;
  $('reviewContainer').innerHTML = `
    <div class="review-score-card">
      <div class="score-number">${(data.score||0).toFixed(1)}</div>
      <div class="score-grade">Grade: ${data.grade||'B'}</div>
      <div class="score-label">Overall Score</div>
      <div class="score-bars">
        ${[['Security','security_score'],['Performance','performance_score'],['Maintainability','maintainability_score']].map(([label,key])=>`
          <div class="score-bar-row">
            <span class="score-bar-label">${label}</span>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${pct(data[key])}"></div></div>
            <span class="score-bar-val">${data[key]||'–'}</span>
          </div>`).join('')}
      </div>
    </div>
    ${data.summary?`<p style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">${escHtml(data.summary)}</p>`:''}
    <div class="section-label" style="margin-bottom:8px;">Review Comments</div>
    <div class="review-comments">
      ${(data.comments||[]).map(c=>`
        <div class="review-comment ${c.severity}">
          <div class="comment-file">📁 ${escHtml(c.file)}</div>
          <div class="comment-msg">${escHtml(c.message)}</div>
          <div class="comment-sug">💡 ${escHtml(c.suggestion)}</div>
        </div>`).join('')||'<div style="color:var(--text-muted);font-size:12px;">No major issues.</div>'}
    </div>`;
  switchTab('review');
}

// ── Pipeline complete ──────────────────────────────────────────────────────────
function onPipelineComplete(data) {
  if (state.eventSource) state.eventSource.close();
  state.isRunning = false;
  appendLog('pipeline','pipeline_complete', data.message || '🎉 Done!');

  // Merge any files that arrived in the complete event but weren't in files_generated
  (data.generated_files || []).forEach(f => {
    if (!state.files[f.filename] || !state.files[f.filename].content) {
      state.files[f.filename] = {
        filename:    f.filename,
        language:    f.language   || 'text',
        description: f.description || '',
        content:     f.content    || '',
        lines:       f.lines      || (f.content ? f.content.split('\n').length : 0),
      };
    }
  });

  // Re-render to pick up any new files
  if (Object.keys(state.files).length) renderFileList();

  // Final report
  if (data.final_output) {
    $('outputContainer').innerHTML = `<pre class="final-output">${escHtml(data.final_output)}</pre>`;
  }

  resetRunBtn();
}

// ── Tabs ───────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn =>
  btn.addEventListener('click', () => switchTab(btn.dataset.tab))
);
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b  => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === `tab-${name}`));
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function escHtml(s='') {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s='') { return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"); }
function pad(n) { return String(n).padStart(2,'0'); }
function cap(s) { return s.charAt(0).toUpperCase()+s.slice(1); }

function resetUI() {
  streamLog.innerHTML = '';
  chunkBuf = {};
  state.files = {}; state.tests = []; state.review = null;
  $('filesContainer').innerHTML  = emptyState('📁','Files will appear here once generated');
  $('testsContainer').innerHTML  = emptyState('🧪','Test results will appear here');
  $('reviewContainer').innerHTML = emptyState('⭐','Code review will appear here');
  $('outputContainer').innerHTML = '';
  Object.keys(state.agentStates).forEach(a => { state.agentStates[a]='pending'; setAgentState(a,'pending'); });
  switchTab('agents');
}
function resetRunBtn() {
  runBtn.innerHTML = '▶ Run Pipeline &nbsp;<kbd style="background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.2);padding:1px 5px;border-radius:3px;font-size:11px;">Ctrl+↵</kbd>';
  runBtn.disabled = false; state.isRunning = false;
}
function emptyState(icon,msg) {
  return `<div class="empty-state"><div class="empty-state-icon">${icon}</div><div class="empty-state-msg">${msg}</div></div>`;
}

// ── Injected CSS ───────────────────────────────────────────────────────────────
const style = document.createElement('style');
style.textContent = `
.spin{display:inline-block;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

.dl-btn{
  background:var(--bg-elevated);border:1px solid var(--border-bright);
  color:var(--text-secondary);font-family:var(--font-mono);font-size:10px;
  padding:3px 8px;border-radius:4px;cursor:pointer;transition:all .15s;white-space:nowrap;
}
.dl-btn:hover{border-color:var(--accent-cyan);color:var(--accent-cyan)}
.dl-btn-all{
  background:rgba(0,212,255,.08);border-color:var(--accent-cyan);
  color:var(--accent-cyan);font-size:11px;padding:5px 12px;
}
.file-desc{font-size:10px;color:var(--text-muted);padding:0 14px 8px}
.file-code-wrapper{border-top:1px solid var(--border)}
.code-toolbar{
  display:flex;align-items:center;gap:8px;padding:7px 14px;
  background:var(--bg-void);border-bottom:1px solid var(--border);
}
.code-lang-label{
  font-size:10px;color:var(--accent-cyan);background:rgba(0,212,255,.1);
  padding:2px 7px;border-radius:3px;margin-right:auto;
}
.file-code{
  display:block!important;padding:14px;background:var(--bg-void);
  font-family:var(--font-mono);font-size:11px;color:var(--text-primary);
  white-space:pre;overflow-x:auto;max-height:420px;overflow-y:auto;
  line-height:1.6;tab-size:2;margin:0;
}
`;
document.head.appendChild(style);
