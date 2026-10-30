"""HTML for the web pages. Each page is static and loads its data from the
JSON API in web.py."""

_CSS = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f0f4f8; color: #1a2535; padding: 1.5rem; }
    h1 { font-size: 1.4rem; font-weight: 700; margin-bottom: .4rem; letter-spacing: -.02em; }
    .nav { margin-bottom: 1.2rem; font-size: .85rem; }
    .nav a { color: #2e7dd4; text-decoration: none; margin-right: 1rem; }
    .nav a.here { color: #1a2535; font-weight: 600; }
    .card { background: #fff; border-radius: 12px; padding: 1.2rem 1.4rem; margin-bottom: 1.2rem; box-shadow: 0 1px 4px rgba(0,0,0,.08), 0 4px 12px rgba(0,0,0,.05); }
    .card h2 { font-size: .8rem; color: #7a90a8; text-transform: uppercase; letter-spacing: .06em; font-weight: 600; margin-bottom: .9rem; }
    .scroll { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: .86rem; }
    th { text-align: left; font-size: .7rem; color: #7a90a8; text-transform: uppercase; letter-spacing: .05em; font-weight: 600; padding: .45rem .55rem; border-bottom: 1px solid #e8eef4; white-space: nowrap; }
    td { padding: .45rem .55rem; border-bottom: 1px solid #f0f4f8; vertical-align: top; }
    tr:last-child td { border-bottom: none; }
    tr.link { cursor: pointer; }
    tr.link:hover td { background: #f7fafc; }
    .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .muted { color: #7a90a8; font-size: .8rem; }
    .err { color: #b00; }
    .ok { color: #1d7a50; }
    .hot { color: #b00; font-weight: 600; }
    .badge { font-size: .72rem; padding: .08rem .45rem; border-radius: 999px; white-space: nowrap; background: #eef2f6; color: #4a6080; }
    .badge.local { background: #eef7f1; color: #1d7a50; }
    .badge.error { background: #fdeaea; color: #b00; }
    .badge.running { background: #e8f1fb; color: #2e7dd4; }
    .btn { background: #2e7dd4; color: #fff; border: none; border-radius: 6px; padding: .4rem .9rem; cursor: pointer; font-size: .85rem; }
    .btn:disabled { background: #aabbc8; cursor: default; }
    .btn.secondary { background: #fff; color: #4a6080; border: 1px solid #d0dce8; }
    .btn.danger { background: #fff; color: #b00; border: 1px solid #e8b4b4; }
    input[type=text], select, textarea { padding: .35rem .5rem; border: 1px solid #d0dce8; border-radius: 6px; font-size: .86rem; font-family: inherit; background: #fff; }
    textarea { font-family: ui-monospace, Menlo, monospace; font-size: .8rem; width: 100%; }
    .filters { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin-bottom: 1rem; }
    .filters button { background: #fff; color: #4a6080; border: 1px solid #d0dce8; border-radius: 6px; padding: .35rem .9rem; cursor: pointer; font-size: .85rem; }
    .filters button.active { background: #e07820; color: #fff; border-color: #e07820; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); gap: .8rem; }
    .tile .v { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
    .tile .l { font-size: .72rem; color: #7a90a8; text-transform: uppercase; letter-spacing: .05em; }
    pre { white-space: pre-wrap; word-break: break-word; font-size: .8rem; background: #f7fafc; border-radius: 6px; padding: .7rem; max-height: 22rem; overflow: auto; }
    .actions { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
"""

_JS = """
function showError(msg) {
  let el = document.getElementById('_err');
  if (!el) {
    el = document.createElement('div');
    el.id = '_err';
    el.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#b00;color:#fff;padding:8px 16px;z-index:9999;font-size:14px;text-align:center';
    document.body.prepend(el);
  }
  el.textContent = '\\u26a0 ' + msg;
}
function clearError() { const el = document.getElementById('_err'); if (el) el.remove(); }
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch (e) { /* non-JSON error body; reported below */ }
  if (!r.ok) {
    const notes = data && data.notes && data.notes.length ? ' (' + data.notes.join('; ') + ')' : '';
    throw new Error(((data && data.error) || `HTTP ${r.status} ${r.statusText}`) + notes);
  }
  return data;
}
function sendJSON(url, method, body) {
  return fetchJSON(url, {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtMs(ms) {
  if (ms == null) return '\\u2014';
  return ms < 1000 ? Math.round(ms) + ' ms' : (ms / 1000).toFixed(ms < 10000 ? 2 : 1) + ' s';
}
function fmtNum(n) { return n == null ? '\\u2014' : Number(n).toLocaleString(); }
function temp(c, hotAt) {
  if (c == null) return '\\u2014';
  return `<span class="${hotAt != null && c >= hotAt ? 'hot' : ''}">${Math.round(c)}\\u00b0C</span> <span class="muted">${Math.round(c * 9 / 5 + 32)}\\u00b0F</span>`;
}
function statusBadge(s, error) {
  if (s === 'ok') return '<span class="badge ok">ok</span>';
  if (s === 'running') return '<span class="badge running">running / unfinished</span>';
  return `<span class="badge error" title="${esc(error)}">error</span>`;
}
"""


def _page(title: str, here: str, body: str, script: str, chart: bool = False) -> str:
    links = [("/", "Overview"), ("/tasks", "AI tasks"), ("/services", "Services")]
    nav = "".join(f'<a href="{href}"{" class=here" if href == here else ""}>{label}</a>' for href, label in links)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} &mdash; Service Delegator</title>
  {'<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>' if chart else ''}
  <style>{_CSS}</style>
</head>
<body>
  <h1>{title}</h1>
  <div class="nav">{nav}</div>
  {body}
<script>{_JS}
{script}
</script>
</body>
</html>"""


OVERVIEW = _page("Service Delegator", "/", """
  <div class="filters" id="periods">
    <button data-hours="24">24 hours</button>
    <button data-hours="168" class="active">7 days</button>
    <button data-hours="720">30 days</button>
    <button data-hours="0">All</button>
    <select id="f-project"><option value="">All projects</option></select>
    <select id="f-kind"><option value="">AI and web APIs</option><option value="ai">AI only</option><option value="api">Web APIs only</option></select>
    <select id="f-provider"><option value="">All services</option></select>
  </div>
  <div class="card"><div class="tiles" id="tiles"></div></div>
  <div class="card">
    <h2>By service / model</h2>
    <div class="scroll"><table>
      <thead><tr><th>Service / model</th><th class="num">Calls</th><th class="num">Errors</th><th class="num">Avg time</th><th class="num">Median</th><th class="num">95th %</th><th class="num">Tokens in</th><th class="num">Tokens out</th><th class="num">Tokens/s</th><th class="num">GPU peak</th><th class="num">Power peak</th><th class="num">Fan peak</th></tr></thead>
      <tbody id="by-model"></tbody>
    </table></div>
  </div>
  <div class="card">
    <h2>By project</h2>
    <div class="scroll"><table>
      <thead><tr><th>Project</th><th class="num">Calls</th><th class="num">Errors</th><th class="num">Avg time</th><th class="num">Tokens in</th><th class="num">Tokens out</th><th>Last call</th></tr></thead>
      <tbody id="by-project"></tbody>
    </table></div>
  </div>
  <div class="card">
    <h2>Recent calls</h2>
    <div class="scroll"><table>
      <thead><tr><th>Time</th><th>Project</th><th>Task</th><th>Service / model</th><th></th><th class="num">Duration</th><th class="num">Tokens in / out</th><th class="num">GPU peak</th><th>Prompt / request</th></tr></thead>
      <tbody id="calls"></tbody>
    </table></div>
  </div>
""", """
let hours = 168;
function qs() {
  const p = new URLSearchParams({hours});
  const proj = document.getElementById('f-project').value, prov = document.getElementById('f-provider').value;
  const kind = document.getElementById('f-kind').value;
  if (proj) p.set('project', proj);
  if (prov) p.set('provider', prov);
  if (kind) p.set('kind', kind);
  return p.toString();
}
function tile(v, l) { return `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`; }

async function load() {
  try {
    const [s, c] = await Promise.all([fetchJSON('/api/stats?' + qs()), fetchJSON('/api/calls?limit=100&' + qs())]);
    clearError();
    const t = s.total;
    document.getElementById('tiles').innerHTML = t ? [
      tile(fmtNum(t.calls), 'Calls'), tile(`<span class="${t.errors ? 'err' : ''}">${fmtNum(t.errors)}</span>`, 'Errors'),
      tile(fmtMs(t.avg_ms), 'Avg time'), tile(fmtMs(t.p95_ms), '95th percentile'),
      tile(fmtNum(t.input_tokens), 'Tokens in'), tile(fmtNum(t.output_tokens), 'Tokens out'),
      tile(temp(t.peak_junction, 100), 'GPU peak (local)')].join('')
      : '<div class="muted">No calls in this period.</div>';
    document.getElementById('by-model').innerHTML = s.by_model.map(r => `<tr>
      <td>${esc(r.provider)} <span class="muted">${esc(r.model || '')}</span> ${r.local ? '<span class="badge local">local</span>' : ''}${r.kind === 'api' ? '<span class="badge">web API</span>' : ''}</td>
      <td class="num">${fmtNum(r.calls)}</td><td class="num ${r.errors ? 'err' : ''}">${fmtNum(r.errors)}</td>
      <td class="num">${fmtMs(r.avg_ms)}</td><td class="num">${fmtMs(r.p50_ms)}</td><td class="num">${fmtMs(r.p95_ms)}</td>
      <td class="num">${fmtNum(r.input_tokens)}</td><td class="num">${fmtNum(r.output_tokens)}</td>
      <td class="num">${r.tokens_per_s ?? '\\u2014'}</td>
      <td class="num">${r.local ? temp(r.peak_junction, 100) : ''}</td>
      <td class="num">${r.local && r.peak_power != null ? Math.round(r.peak_power) + ' W' : ''}</td>
      <td class="num">${r.local && r.peak_fan != null ? fmtNum(r.peak_fan) + ' rpm' : ''}</td></tr>`).join('')
      || '<tr><td colspan="12" class="muted">No calls.</td></tr>';
    document.getElementById('by-project').innerHTML = s.by_project.map(r => `<tr>
      <td>${esc(r.project ?? '(none)')}</td><td class="num">${fmtNum(r.calls)}</td>
      <td class="num ${r.errors ? 'err' : ''}">${fmtNum(r.errors)}</td><td class="num">${fmtMs(r.avg_ms)}</td>
      <td class="num">${fmtNum(r.input_tokens)}</td><td class="num">${fmtNum(r.output_tokens)}</td>
      <td class="muted">${esc(r.last_call)}</td></tr>`).join('')
      || '<tr><td colspan="7" class="muted">No calls.</td></tr>';
    document.getElementById('calls').innerHTML = c.calls.map(r => `<tr class="link" data-id="${r.id}">
      <td class="muted">${esc(r.started_at)}</td><td>${esc(r.project ?? '')}</td><td>${esc(r.task ?? '')}</td>
      <td>${esc(r.provider)} <span class="muted">${esc(r.model || '')}</span></td>
      <td>${statusBadge(r.status, r.error)}${r.http_status ? ` <span class="muted">${r.http_status}</span>` : ''}${r.via === 'imported' ? ' <span class="badge">from radioserver</span>' : ''}${r.n_images ? ` <span class="badge">${r.n_images} image${r.n_images > 1 ? 's' : ''}</span>` : ''}</td>
      <td class="num">${fmtMs(r.duration_ms)}</td>
      <td class="num">${r.kind === 'api' ? '' : fmtNum(r.input_tokens) + ' / ' + fmtNum(r.output_tokens)}</td>
      <td class="num">${r.local ? temp(r.gpu_peak_junction, 100) : ''}</td>
      <td class="muted">${esc(r.prompt_preview)}</td></tr>`).join('')
      || '<tr><td colspan="9" class="muted">No calls.</td></tr>';
  } catch (e) {
    showError('Could not load stats: ' + e.message);
  }
}

document.getElementById('periods').addEventListener('click', e => {
  const b = e.target.closest('button[data-hours]');
  if (!b) return;
  hours = +b.dataset.hours;
  document.querySelectorAll('#periods button').forEach(x => x.classList.toggle('active', x === b));
  load();
});
document.getElementById('f-project').addEventListener('change', load);
document.getElementById('f-provider').addEventListener('change', load);
document.getElementById('f-kind').addEventListener('change', load);
document.getElementById('calls').addEventListener('click', e => {
  const tr = e.target.closest('tr[data-id]');
  if (tr) location.href = '/calls/' + tr.dataset.id;
});
fetchJSON('/api/filters').then(f => {
  document.getElementById('f-project').innerHTML += f.projects.map(p => `<option>${esc(p)}</option>`).join('');
  document.getElementById('f-provider').innerHTML += f.providers.map(p => `<option>${esc(p)}</option>`).join('');
}).catch(e => showError('Could not load filters: ' + e.message));
load();
setInterval(load, 30000);
""")


CALL = _page("Call", "", """
  <div class="card"><div class="tiles" id="tiles"></div><div id="error" class="err" style="margin-top:.8rem"></div></div>
  <div class="card" id="gpu-card" style="display:none">
    <h2>GPU and CPU during the call</h2>
    <canvas id="chart" height="90"></canvas>
  </div>
  <div class="card"><h2 id="prompt-title">Prompt</h2><pre id="prompt"></pre></div>
  <div class="card" id="response-card"><h2>Response</h2><pre id="response"></pre></div>
""", """
const CALL_ID = __CALL_ID__;
function tile(v, l) { return `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div></div>`; }
fetchJSON('/api/calls/' + CALL_ID).then(c => {
  document.querySelector('h1').textContent = c.kind === 'api' ? `${c.provider} \\u00b7 ${c.endpoint || ''}` : `${c.provider} \\u00b7 ${c.model || ''}`;
  document.title = `Call ${CALL_ID} \\u2014 Service Delegator`;
  const tiles = [
    tile(statusBadge(c.status, c.error), 'Status'), tile(esc(c.started_at), 'Started'),
    tile(esc(c.project ?? '\\u2014'), 'Project'), tile(esc(c.task ?? '\\u2014'), 'Task'),
    tile(fmtMs(c.duration_ms), 'Duration')];
  if (c.kind === 'api') {
    tiles.push(tile(c.http_status ?? '\\u2014', 'HTTP status'), tile(fmtNum(c.bytes_sent), 'Bytes sent'),
               tile(fmtNum(c.bytes_received), 'Bytes received'));
  } else {
    tiles.push(tile(fmtNum(c.input_tokens), 'Tokens in'), tile(fmtNum(c.output_tokens), 'Tokens out'));
  }
  if (c.cache_read_tokens) tiles.push(tile(fmtNum(c.cache_read_tokens), 'Read from cache'));
  if (c.n_images) tiles.push(tile(c.n_images, 'Images'));
  if (c.local) {
    if (c.load_ms != null) tiles.push(tile(fmtMs(c.load_ms), 'Model load'));
    if (c.prompt_eval_ms != null) tiles.push(tile(fmtMs(c.prompt_eval_ms), 'Reading prompt'));
    if (c.eval_ms != null) tiles.push(tile(fmtMs(c.eval_ms), 'Generating'));
    if (c.eval_ms && c.output_tokens) tiles.push(tile((c.output_tokens / c.eval_ms * 1000).toFixed(1), 'Tokens/s'));
    tiles.push(tile(temp(c.gpu_peak_junction, 100), 'GPU junction peak'), tile(temp(c.gpu_avg_junction, 100), 'Junction avg'),
               tile(temp(c.gpu_peak_edge, 90), 'Edge peak'), tile(temp(c.gpu_peak_mem, 95), 'Memory peak'),
               tile(c.gpu_peak_power != null ? Math.round(c.gpu_peak_power) + ' W' : '\\u2014', 'Power peak'),
               tile(c.gpu_peak_fan != null ? fmtNum(c.gpu_peak_fan) + ' rpm' : '\\u2014', 'Fan peak'),
               tile(temp(c.cpu_peak, 90), 'CPU peak'));
  }
  tiles.push(tile(esc(c.via), 'Sent via'));
  document.getElementById('tiles').innerHTML = tiles.join('');
  document.getElementById('error').textContent = c.error || '';
  document.getElementById('prompt').textContent = c.prompt_preview || '';
  document.getElementById('response').textContent = c.response_preview || '';
  if (c.kind === 'api') {
    document.getElementById('prompt-title').textContent = 'Request';
    document.getElementById('response-card').style.display = c.response_preview ? '' : 'none';
  }
  if (c.samples.length) {
    document.getElementById('gpu-card').style.display = '';
    const line = (label, value, color, axis) => ({label, data: c.samples.map(value), borderColor: color,
      backgroundColor: color, yAxisID: axis, pointRadius: 0, borderWidth: 2, spanGaps: true});
    new Chart(document.getElementById('chart'), {
      type: 'line',
      data: {labels: c.samples.map(s => Math.round(s.t) + 's'), datasets: [
        line('Junction \\u00b0C', s => s.junction, '#e74c3c', 'temp'), line('Edge \\u00b0C', s => s.edge, '#e07820', 'temp'),
        line('Memory \\u00b0C', s => s.mem, '#9b59b6', 'temp'), line('CPU \\u00b0C', s => s.cpu, '#2db37a', 'temp'),
        line('Power W', s => s.power, '#2e7dd4', 'right'),
        line('Fan rpm \\u00f7 20', s => s.fan_rpm == null ? null : s.fan_rpm / 20, '#7f8c8d', 'right')]},
      options: {animation: false, interaction: {mode: 'index', intersect: false},
        plugins: {legend: {position: 'bottom', labels: {boxWidth: 12, font: {size: 11}}}},
        scales: {temp: {position: 'left', title: {display: true, text: '\\u00b0C'}, suggestedMin: 30, suggestedMax: 110},
                 right: {position: 'right', title: {display: true, text: 'W  /  rpm \\u00f7 20'}, grid: {display: false}, suggestedMin: 0}}},
    });
  }
}).catch(e => showError('Could not load call: ' + e.message));
""", chart=True)


TASKS = _page("Tasks", "/tasks", """
  <div class="card">
    <div class="muted">A task is a kind of job a project asks for, like <code>receipt-reader</code> or <code>song-year</code>. Each one is sent to its first provider; if that one fails or has no key, the next is tried. A task a project uses for the first time is created with the default task&rsquo;s providers.</div>
  </div>
  <div id="tasks"></div>
  <div class="card">
    <h2>New task</h2>
    <div class="actions"><input type="text" id="new-name" placeholder="task name, e.g. song-year"><button class="btn" id="new-add">Add</button></div>
  </div>
  <datalist id="ollama-models"></datalist>
""", """
let providers = [], tasks = [];

function routeRow(r) {
  return `<div class="actions route" style="margin-bottom:.4rem">
    <select data-f="provider">${providers.map(p => `<option value="${p.name}"${p.name === r.provider ? ' selected' : ''}>${esc(p.display)}${p.configured ? '' : ' (no key)'}</option>`).join('')}</select>
    <input type="text" data-f="model" value="${esc(r.model || '')}" placeholder="model" list="ollama-models" style="min-width:16rem">
    <button class="btn secondary" data-up title="Try earlier">&uarr;</button>
    <button class="btn danger" data-remove title="Remove">&times;</button></div>`;
}

function taskCard(t) {
  return `<div class="card task" data-name="${esc(t.name)}">
    <h2>${esc(t.name)} <span class="muted" style="text-transform:none;letter-spacing:0">\\u00b7 ${fmtNum(t.calls)} calls</span></h2>
    <div style="margin-bottom:.6rem"><input type="text" data-f="description" value="${esc(t.description || '')}" placeholder="What it's for" style="width:100%"></div>
    <div class="routes">${t.routes.map(routeRow).join('')}</div>
    <div class="actions" style="margin:.4rem 0 .8rem"><button class="btn secondary" data-add-route>+ Fallback provider</button></div>
    <details><summary class="muted" style="cursor:pointer">Options (JSON)</summary>
      <textarea data-f="options" rows="4" style="margin-top:.4rem">${esc(JSON.stringify(t.options, null, 2))}</textarea>
      <div class="muted">e.g. {"max_tokens": 200, "temperature": 0, "extra": {"ollama": {"think": false, "options": {"num_ctx": 8192}}}}. A project&rsquo;s own settings in its request take priority.</div>
    </details>
    <div class="actions" style="margin-top:.8rem">
      <button class="btn" data-save>Save</button>
      <button class="btn secondary" data-test>Test</button>
      ${t.name === 'default' ? '' : '<button class="btn danger" data-delete>Delete task</button>'}
      <span class="status muted"></span></div>
  </div>`;
}

function render() { document.getElementById('tasks').innerHTML = tasks.map(taskCard).join(''); }

async function load() {
  try {
    const [p, t] = await Promise.all([fetchJSON('/api/providers'), fetchJSON('/api/tasks')]);
    clearError();
    providers = p.providers; tasks = t.tasks;
    document.getElementById('ollama-models').innerHTML = p.ollama.models.map(m => `<option value="${esc(m)}">`).join('');
    if (p.ollama.error) showError(p.ollama.error);
    render();
  } catch (e) { showError('Could not load tasks: ' + e.message); }
}

function readCard(card) {
  const routes = [...card.querySelectorAll('.route')].map(r => ({
    provider: r.querySelector('[data-f=provider]').value, model: r.querySelector('[data-f=model]').value.trim()}));
  let options;
  try { options = JSON.parse(card.querySelector('[data-f=options]').value || '{}'); }
  catch (e) { throw new Error('Options aren\\u2019t valid JSON: ' + e.message); }
  return {description: card.querySelector('[data-f=description]').value, routes, options};
}

document.getElementById('tasks').addEventListener('click', async e => {
  const card = e.target.closest('.task');
  if (!card) return;
  const name = card.dataset.name, status = card.querySelector('.status');
  const say = (msg, cls) => { status.className = 'status ' + (cls || 'muted'); status.textContent = msg; };
  if (e.target.matches('[data-remove]')) {
    if (card.querySelectorAll('.route').length > 1) e.target.closest('.route').remove();
    else say('A task needs at least one provider.', 'err');
  } else if (e.target.matches('[data-up]')) {
    const row = e.target.closest('.route');
    if (row.previousElementSibling) row.parentNode.insertBefore(row, row.previousElementSibling);
  } else if (e.target.matches('[data-add-route]')) {
    const p = providers.find(x => x.configured && !x.local) || providers[0];
    card.querySelector('.routes').insertAdjacentHTML('beforeend', routeRow({provider: p.name, model: p.default_model}));
  } else if (e.target.matches('[data-save]')) {
    try {
      await sendJSON('/api/tasks/' + encodeURIComponent(name), 'PUT', readCard(card));
      say('Saved', 'ok');
    } catch (e2) { say('Save failed: ' + e2.message, 'err'); }
  } else if (e.target.matches('[data-test]')) {
    say('Asking\\u2026 (uses the saved settings)');
    try {
      const r = await sendJSON('/api/tasks/' + encodeURIComponent(name) + '/test', 'POST', {});
      say(`${r.provider} (${r.model}) answered \\u201c${r.text}\\u201d in ${fmtMs(r.duration_ms)}` +
          (r.notes.length ? ' \\u00b7 ' + r.notes.join('; ') : ''), 'ok');
    } catch (e2) { say('Test failed: ' + e2.message, 'err'); }
  } else if (e.target.matches('[data-delete]')) {
    if (!confirm(`Delete task ${name}? Projects that use it will get the default providers.`)) return;
    try { await fetchJSON('/api/tasks/' + encodeURIComponent(name), {method: 'DELETE'}); load(); }
    catch (e2) { say('Delete failed: ' + e2.message, 'err'); }
  }
});
document.getElementById('tasks').addEventListener('change', e => {
  if (!e.target.matches('[data-f=provider]')) return;
  const p = providers.find(x => x.name === e.target.value);
  e.target.closest('.route').querySelector('[data-f=model]').value = p ? p.default_model : '';
});
document.getElementById('new-add').addEventListener('click', async () => {
  const name = document.getElementById('new-name').value.trim();
  if (!name) return;
  const d = tasks.find(t => t.name === 'default');
  try {
    await sendJSON('/api/tasks/' + encodeURIComponent(name), 'PUT', {routes: d.routes, options: d.options});
    document.getElementById('new-name').value = '';
    load();
  } catch (e) { showError('Could not add task: ' + e.message); }
});
load();
""")


SERVICES = _page("Services", "/services", """
  <div class="card">
    <h2>AI providers</h2>
    <div class="scroll"><table>
      <thead><tr><th>Provider</th><th>API key</th><th>Default model</th><th>Last error</th><th></th></tr></thead>
      <tbody id="providers"></tbody>
    </table></div>
    <div class="muted" style="margin-top:.8rem">Set a key on the server with <code>service-delegator set-key &lt;provider&gt; &lt;key&gt;</code>, or copy radioserver&rsquo;s keys with <code>service-delegator import-radioserver-keys</code>. Keys are kept in <code>~/.service-delegator.conf</code>.</div>
  </div>
  <div class="card">
    <h2>Local</h2>
    <div id="local"></div>
  </div>
  <div class="card">
    <h2>Web APIs <span class="muted" style="text-transform:none;letter-spacing:0">&middot; last 7 days</span></h2>
    <div class="scroll"><table>
      <thead><tr><th>Service</th><th>Used by</th><th class="num">Calls</th><th class="num">Errors</th><th class="num">Avg time</th><th>Last call</th><th>Proxy URL (replaces the base URL)</th></tr></thead>
      <tbody id="apis"></tbody>
    </table></div>
    <div class="muted" style="margin-top:.8rem">A project sends its requests to the proxy URL instead of the service; they&rsquo;re passed on unchanged (including the project&rsquo;s own API key) and timed. Replace <code>&lt;project&gt;</code> with the project&rsquo;s name.</div>
  </div>
""", """
fetchJSON('/api/services').then(d => {
  document.getElementById('apis').innerHTML = d.services.map(s => `<tr>
    <td>${esc(s.display)}<div class="muted">${esc(s.base_url)}</div>${s.notes ? `<div class="muted">${esc(s.notes)}</div>` : ''}</td>
    <td class="muted">${esc(s.used_by)}</td>
    <td class="num">${fmtNum(s.calls)}</td><td class="num ${s.errors ? 'err' : ''}">${fmtNum(s.errors)}</td>
    <td class="num">${fmtMs(s.avg_ms)}</td>
    <td>${s.last_call ? `<span class="muted">${esc(s.last_call)}</span>` : ''}
      ${s.last_error ? `<div class="err" title="${esc(s.last_error.error)}">Last error ${esc(s.last_error.started_at)}: ${esc((s.last_error.error || '').slice(0, 80))}</div>` : ''}</td>
    <td><code>${esc(location.origin)}/proxy/&lt;project&gt;/${esc(s.name)}</code></td></tr>`).join('');
}).catch(e => showError('Could not load web APIs: ' + e.message));

fetchJSON('/api/providers').then(d => {
  document.getElementById('providers').innerHTML = d.providers.map(p => `<tr data-name="${p.name}">
    <td>${esc(p.display)} ${p.local ? '<span class="badge local">local</span>' : ''}</td>
    <td>${p.local ? '<span class="muted">not needed</span>' : p.configured ? '<span class="ok">set</span>'
         : `<span class="err">missing</span> ${p.key_url ? `<a class="muted" href="${esc(p.key_url)}" target="_blank">get one</a>` : ''}`}</td>
    <td class="muted">${esc(p.default_model)}</td>
    <td>${p.cooling_off ? `<div class="err">${esc(p.cooling_off)}</div>` : p.last_error
         ? `<div class="muted">${esc(p.last_error.started_at)}: ${esc(p.last_error.error.slice(0, 160))}</div>` : ''}</td>
    <td><button class="btn secondary" data-test ${p.configured ? '' : 'disabled'}>Test</button> <span class="status muted"></span></td></tr>`).join('');
  const s = d.sensors;
  document.getElementById('local').innerHTML = `
    <div>Ollama at <code>${esc(d.ollama.url)}</code>: ${d.ollama.error ? `<span class="err">${esc(d.ollama.error)}</span>`
      : `${d.ollama.models.length} models (${d.ollama.models.map(esc).join(', ')})`}</div>
    <div style="margin-top:.4rem">GPU sensors: ${s.gpu ? '<span class="ok">found</span>' : '<span class="err">not found (no AMD GPU readings will be recorded)</span>'}
      \\u00b7 CPU sensors: ${s.cpu ? '<span class="ok">found</span>' : '<span class="err">not found</span>'}</div>
    <div class="muted" style="margin-top:.6rem">Projects can use the proxy instead of Ollama directly: set their Ollama URL to <code>${esc(location.origin)}/ollama/&lt;project-name&gt;</code>.</div>`;
}).catch(e => showError('Could not load providers: ' + e.message));

document.getElementById('providers').addEventListener('click', async e => {
  if (!e.target.matches('[data-test]')) return;
  const tr = e.target.closest('tr'), status = tr.querySelector('.status');
  status.className = 'status muted'; status.textContent = 'Asking\\u2026';
  try {
    const r = await sendJSON(`/api/providers/${tr.dataset.name}/test`, 'POST', {});
    status.className = 'status ok'; status.textContent = `\\u201c${r.text}\\u201d in ${fmtMs(r.duration_ms)}`;
  } catch (e2) { status.className = 'status err'; status.textContent = e2.message; }
});
""")
