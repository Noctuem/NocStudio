/* Studio review page. No framework and no build step: this file, style.css and three.js for models.
   It talks to studio.py over /api, or, when window.STUDIO_STATIC is set, runs on data baked into the page. */
(function () {
  'use strict';

  // ---------------------------------------------------------------- helpers
  const $ = (sel, root) => (root || document).querySelector(sel);
  // the Studio's own addresses, made relative to the page, so it also works under a path such as apps.example.com/studio/
  const rel = (u) => (typeof u === 'string' && /^\/(?!\/)/.test(u) ? u.slice(1) : u);
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'src' || k === 'href') el.setAttribute(k, rel(v));
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
    return el;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, '<code class="i">$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  // a table row's cells: the outer pipes dropped, split on the rest (an escaped \| stays in its cell)
  const cells = (line) => line.trim().replace(/^\|/, '').replace(/(^|[^\\])\|$/, '$1').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
  const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
  function mdTable(head, rule, rows) {
    const align = cells(rule).map((c) => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : ''));
    const row = (tag, line) => h('tr', {}, cells(line).map((c, i) => h(tag, { html: inline(c), style: align[i] ? 'text-align:' + align[i] : null })));
    return h('div', { class: 'tablewrap' }, h('table', {}, h('thead', {}, row('th', head)), h('tbody', {}, rows.map((r) => row('td', r)))));
  }
  function md(text) {
    const out = h('div', { class: 'md' });
    let list = null;
    const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trimEnd();
      const fence = line.match(/^\s*(```|~~~)/);
      if (fence) {  // a fenced block, shown as it is
        const body = [];
        while (++i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i]);
        list = null; out.append(h('pre', { class: 'code' }, body.join('\n')));
        continue;
      }
      if (line.includes('|') && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1]) && lines[i + 1].includes('|')) {
        const rows = [];
        let j = i + 2;
        while (j < lines.length && lines[j].trim() && lines[j].includes('|')) rows.push(lines[j++]);
        list = null; out.append(mdTable(line, lines[i + 1], rows));
        i = j - 1;
        continue;
      }
      const item = line.match(/^\s*[-*] (.*)/);
      if (item) { if (!list) { list = h('ul'); out.append(list); } list.append(h('li', { html: inline(item[1]) })); continue; }
      list = null;
      if (!line.trim()) continue;
      const head = line.match(/^(#{1,3}) (.*)/);
      if (head) out.append(h('h3', { html: inline(head[2]) }));
      else if (line.startsWith('> ')) out.append(h('blockquote', { html: inline(line.slice(2)) }));
      else out.append(h('p', { html: inline(line) }));
    }
    return out;
  }
  function when(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    const mins = Math.round((Date.now() - d) / 60000);
    if (mins >= 0 && mins < 60) return mins <= 1 ? 'just now' : mins + ' min ago';
    if (mins >= 0 && mins < 60 * 24) return Math.round(mins / 60) + ' h ago';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  let toastTimer = 0;
  function toast(msg) {
    document.querySelectorAll('.toast').forEach((t) => t.remove());
    const el = h('div', { class: 'toast', role: 'status' }, msg);
    document.body.append(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.remove(), 2600);
  }
  // a toast with Undo on it: it stays a few seconds, fades, and is gone; hovering over it holds it
  const UNDO_MS = 8000;
  function undoToast(msg, undo) {
    document.querySelectorAll('.toast').forEach((t) => t.remove());
    clearTimeout(toastTimer);
    let left = UNDO_MS, last = Date.now(), held = false;
    const btn = h('button', { class: 'btn small', type: 'button' }, 'Undo');
    const el = h('div', { class: 'toast undo', role: 'status', style: '--undo-ms:' + UNDO_MS + 'ms' }, h('span', {}, msg), btn);
    const tick = () => {
      if (!el.isConnected) return;
      const now = Date.now();
      if (!held) left -= now - last;
      last = now;
      if (left <= 0) { el.remove(); return; }
      el.style.opacity = String(Math.min(1, 0.25 + left / UNDO_MS));
      toastTimer = setTimeout(tick, 100);
    };
    el.addEventListener('mouseenter', () => { held = true; el.style.opacity = '1'; });
    el.addEventListener('mouseleave', () => { held = false; last = Date.now(); });
    btn.addEventListener('click', () => { btn.disabled = true; clearTimeout(toastTimer); el.remove(); undo(); });
    document.body.append(el);
    toastTimer = setTimeout(tick, 100);
  }
  function copyButton(text, label) {
    const btn = h('button', { class: 'btn small', type: 'button' }, label || 'Copy');
    btn.addEventListener('click', () => {
      const done = () => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = label || 'Copy'; }, 1400); };
      try { navigator.clipboard.writeText(text).then(done, () => toast('Select the text and copy it by hand')); }
      catch (e) { toast('Select the text and copy it by hand'); }
    });
    return btn;
  }
  const KIND = { image: 'Pictures', texture: 'Textures', model: 'Models', audio: 'Sounds', video: 'Clips', text: 'Writing', in_app: 'In the app', question: 'Question', mixed: 'Mixed' };
  const GLYPH = { model: '3D', audio: 'Sound', video: 'Clip', text: 'Text', in_app: 'In app', question: '?', mixed: 'Mixed' };
  const CALLS = { pick: [['winner', 'Winner', 'W'], ['keep', 'Keep', 'K'], ['redo', 'Redo', 'R'], ['reject', 'Reject', 'X']],
    rate: [['approve', 'Approve', 'A'], ['redo', 'Redo', 'R'], ['reject', 'Reject', 'X']], question: [['winner', 'Choose this', 'W']] };
  const ACTIONS = { pick: [['ship', 'Ship the winner'], ['ship_and_iterate', 'Ship it, and try for better'], ['another_round', 'Another round'], ['park', 'Park it']],
    rate: [['ship', 'Ship the approved'], ['ship_and_iterate', 'Ship the approved, redo the rest'], ['another_round', 'Redo them all'], ['park', 'Park it']],
    question: [['answer', 'That is my answer'], ['park', 'Park it']] };
  const ACTION_SAID = { ship: 'ship the winner', ship_and_iterate: 'ship, and another round', another_round: 'another round', park: 'parked', answer: 'answered' };
  const SLOT = { needed: 'Needed', placeholder: 'Placeholder', in_review: 'In review', approved: 'Approved', in_use: 'In use', parked: 'Parked' };
  const SAY = 'process my studio verdicts';

  // -------------------------------------------------------------------- api
  const STATIC = window.STUDIO_STATIC || null;
  function b64bytes(dataUri) {
    const bin = atob(dataUri.slice(dataUri.indexOf(',') + 1));
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out.buffer;
  }
  async function call(method, url, body) {
    const res = await fetch(rel(url), { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ('The studio answered ' + res.status));
    return data;
  }
  const API = STATIC ? {
    state: async () => STATIC.state,
    pulse: async () => ({ stamp: STATIC.state.stamp }),
    batch: async (id) => { if (!STATIC.batches[id]) throw new Error('No such batch'); return STATIC.batches[id]; },
    saveDraft: async (id, v) => { const b = STATIC.batches[id]; b.draft = v; if (b.status === 'open') { b.status = 'draft'; sync(b); } },
    submit: async (id, v) => {
      const b = STATIC.batches[id];
      b.verdict = Object.assign({}, v, { submitted: new Date().toISOString() }); b.draft = null; b.status = 'submitted'; sync(b);
      return { pending: STATIC.state.batches.filter((x) => x.status === 'submitted').length };
    },
    reopen: async (id) => { const b = STATIC.batches[id]; b.draft = b.verdict; b.verdict = null; b.status = 'draft'; sync(b); },
    reset: async () => {},
    ui: async () => {},
    setup: async (hidden) => { (STATIC.state.overview || {}).setup_hidden = hidden; },
    addDecision: async (d) => {
      const n = STATIC.state.decisions.length + 1;
      const rec = { id: 'D-' + String(n).padStart(4, '0'), date: new Date().toISOString().slice(0, 10), title: d.title, his_words: d.his_words, ruling: '', source: { type: 'studio', ref: 'written by hand' }, tags: d.tags || [], status: 'active' };
      STATIC.state.decisions.push(rec); return { decision: rec };
    },
    confirm: async (key, confirmed, note) => {
      for (const p of STATIC.state.test_runs) for (const r of p.reports) if (r.key === key) Object.assign(r.triage, { confirmed, confirm_note: note });
    },
    hand: async (id, action, note) => {
      for (const x of ((STATIC.state.overview || {}).hands || [])) if (x.id === id) {
        if (action === 'undo') { Object.assign(x, x.undo || { status: 'open' }); delete x.undo; continue; }
        x.undo = { status: x.status, his_note: x.his_note, answered: x.answered };
        Object.assign(x, { status: { done: 'done', park: 'parked', reopen: 'open' }[action], his_note: note, answered: new Date().toISOString() });
      }
    },
    shares: async () => ({ shares: [], public: false }),
    share: async () => { throw new Error('This is a sample page: nothing here can be shared'); },
    addNote: async () => { throw new Error('This is a sample page: notes are not kept here'); },
    putFile: async () => { throw new Error('This is a sample page: notes are not kept here'); },
    putMarks: async () => {},
    putMark: async () => {},
    editText: async () => { throw new Error('This is a sample page: edits are not kept here'); },
    note: async () => { throw new Error('This is a sample page: notes are not kept here'); },
    src: (url) => STATIC.files[url] || '',
    bytes: async (url) => { if (!STATIC.files[url]) throw new Error('missing'); return b64bytes(STATIC.files[url]); },
  } : {
    state: () => call('GET', '/api/state').then((st) => {  // a page server started before the rename sends the old names
      if (!st.test_runs) Object.assign(st, { test_runs: st.playtests || [], has_test_runs: st.has_playtests });
      for (const s of st.slots || []) for (const f of s.files || []) if (f.from === 'game') f.from = 'repo';
      return st;
    }),
    pulse: () => call('GET', '/api/pulse'),
    live: () => call('GET', '/api/live'),
    batch: (id) => call('GET', '/api/batch/' + encodeURIComponent(id)),
    saveDraft: (id, v) => call('PUT', '/api/batch/' + encodeURIComponent(id) + '/draft', v),
    submit: (id, v) => call('POST', '/api/batch/' + encodeURIComponent(id) + '/submit', v),
    reopen: (id) => call('POST', '/api/batch/' + encodeURIComponent(id) + '/reopen', {}),
    reset: (id) => call('POST', '/api/batch/' + encodeURIComponent(id) + '/reset', {}),
    ui: (v) => call('POST', '/api/ui', v),
    setup: (hidden) => call('POST', '/api/setup', { hidden }),
    addDecision: (d) => call('POST', '/api/decisions', d),
    confirm: (key, confirmed, note) => call('PUT', '/api/triage', { key, confirmed, confirm_note: note }),
    hand: (id, action, note) => call('POST', '/api/hand', { id, action, note }),
    shares: () => call('GET', '/api/shares'),
    share: (body) => call('POST', '/api/share', body),
    addNote: (text, kind) => call('POST', '/api/note', { text, kind }),
    putFile: async (id, file, name) => { // the file as it is, not JSON: any size; the header tells the server the page sent it
      const res = await fetch(rel('/api/note/' + encodeURIComponent(id) + '/file?name=' + encodeURIComponent(name || file.name)), { method: 'PUT', headers: { 'X-Studio-File': '1' }, body: file });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || ('The studio answered ' + res.status));
      return data;
    },
    putMarks: async (id, cid, blob) => { // the marked picture Claude reads; nothing sent takes it away
      const res = await fetch(rel('/api/batch/' + encodeURIComponent(id) + '/marks/' + encodeURIComponent(cid)), { method: 'PUT', headers: { 'X-Studio-File': '1' }, body: blob || new Blob([]) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || ('The studio answered ' + res.status));
      return data;
    },
    putMark: async (id, cid, span, blob) => { // the picture of one mark on a clip or a sound; nothing sent takes it away
      const res = await fetch(rel('/api/batch/' + encodeURIComponent(id) + '/marks/' + encodeURIComponent(cid) + '/' + encodeURIComponent(span)), { method: 'PUT', headers: { 'X-Studio-File': '1' }, body: blob || new Blob([]) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || ('The studio answered ' + res.status));
      return data;
    },
    note: (id, action, extra) => call('POST', '/api/note/' + encodeURIComponent(id), Object.assign({ action }, extra || {})),
    editText: (slot, file, text) => call('POST', '/api/slot/' + encodeURIComponent(slot) + '/text', { file, text }),
    src: (url) => url,
    bytes: async (url) => { const r = await fetch(rel(url)); if (!r.ok) throw new Error('missing'); return r.arrayBuffer(); },
  };
  function sync(b) { // static mode: keep the inbox summary in step with the batch
    const row = STATIC.state.batches.find((x) => x.id === b.id);
    if (!row) return;
    const calls = (b.verdict || {}).candidates || {};
    Object.assign(row, { status: b.status, action: (b.verdict || {}).action || null, submitted: (b.verdict || {}).submitted || null,
      winners: Object.keys(calls).filter((c) => ['winner', 'approve'].includes(calls[c].call)) });
  }
  const fileUrl = (batchId, path) => '/files/' + batchId + '/' + path;

  // ------------------------------------------------------------------ state
  const S = { state: null, batch: null, verdict: null, touched: false, ui: {}, cleanup: [], current: null, cmp: new Set(), over: null,
    opts: { stage: 'dark', tile: false, texScale: 128, clip: '', playing: true, rotate: false, wire: false, ref: true, loop: false, rate: 1 } };
  // a baked motion: "<set>:<clip>" names a clip inside motions/<set>.glb
  function motionOf(ref) {
    const at = String(ref || '').indexOf(':'); if (at < 1) return null;
    const id = ref.slice(0, at), clip = ref.slice(at + 1), set = ((S.state || {}).motions || {})[id];
    if (!set || !set.clips.some((c) => c.name === clip)) return null;
    return { url: '/motions/' + encodeURIComponent(id) + '.glb', clip, seconds: (set.clips.find((c) => c.name === clip) || {}).seconds };
  }
  // a view option can show in two places at once (the page and a closer look): every copy shows the same state
  function showOpts() {
    for (const x of document.querySelectorAll('[data-opt]')) { const on = !!S.opts[x.dataset.opt]; x.classList.toggle('on', on); x.setAttribute('aria-pressed', String(on)); }
    for (const x of document.querySelectorAll('[data-rate]')) x.classList.toggle('on', +x.dataset.rate === S.opts.rate);
    for (const x of document.querySelectorAll('[data-stage]')) x.classList.toggle('on', x.dataset.stage === S.opts.stage);
    for (const x of document.querySelectorAll('select.clipsel')) x.value = S.opts.clip;
    for (const x of document.querySelectorAll('input.texsize')) x.value = S.opts.texScale;
  }
  function rateButtons(apply) {
    return [[1, 'Full speed'], [0.5, 'Half'], [0.25, 'Quarter']].map(([r, label]) =>
      h('button', { class: 'btn small' + (S.opts.rate === r ? ' on' : ''), type: 'button', 'data-rate': r, onclick: () => { S.opts.rate = r; showOpts(); apply(); } }, label));
  }
  // the page's size: the user's choice, kept by the Studio so every window opens the way they left it
  const UI = { scale: 1, synced: false, steps: [0.8, 0.9, 1, 1.1, 1.25, 1.4, 1.5, 1.75, 2] };
  function setScale(k, save) {
    k = Math.min(2, Math.max(0.75, +k || 1)); UI.scale = k;
    const root = document.documentElement;
    root.style.zoom = k === 1 ? '' : String(k); root.style.setProperty('--scale', String(k));
    try { localStorage.setItem('studio.scale', String(k)); } catch (e) { /* private window */ }
    if (save) API.ui({ scale: k }).catch(() => {});
  }
  try { setScale(localStorage.getItem('studio.scale')); } catch (e) { /* private window */ }
  function setTheme(t, save) {
    UI.theme = t === 'light' ? 'light' : 'dark';
    if (UI.theme === 'light') document.documentElement.dataset.theme = 'light'; else delete document.documentElement.dataset.theme;
    try { localStorage.setItem('studio.theme', UI.theme); } catch (e) { /* private window */ }
    if (save) API.ui({ theme: UI.theme }).catch(() => {});
  }
  try { setTheme(localStorage.getItem('studio.theme')); } catch (e) { /* private window */ }
  // framed by a launcher on the same site (an app library): it keeps the phone's notch clear and owns light and dark,
  // so the page starts at the top of its frame and wears the launcher's theme, whatever it was left at here
  const SHELL = (() => { try { return window.self !== window.top ? window.parent.document.documentElement : null; } catch (e) { return null; } })();
  if (SHELL) {
    document.documentElement.classList.add('framed');
    const follow = () => { if (SHELL.dataset.theme) { setTheme(SHELL.dataset.theme); for (const v of GL.views) v.dirty = true; } };
    setTimeout(follow, 0);
    try { new window.parent.MutationObserver(follow).observe(SHELL, { attributes: true, attributeFilter: ['data-theme'] }); } catch (e) { /* a launcher that changes nothing */ }
  }
  function themeControl() {
    if (SHELL) return null;
    const btn = h('button', { class: 'btn small', type: 'button', onclick: () => { setTheme(UI.theme === 'light' ? 'dark' : 'light', true); show(); for (const v of GL.views) v.dirty = true; } });
    const show = () => { btn.textContent = UI.theme === 'light' ? 'Dark' : 'Light'; btn.title = 'Switch to the ' + (UI.theme === 'light' ? 'dark' : 'light') + ' theme'; };
    show(); return btn;
  }
  // inside a zoomed page an element measures itself in its own pixels, the pointer in the window's
  const cz = (el) => (el && el.currentCSSZoom) || 1;
  function scaleControl() {
    const label = h('button', { class: 'btn small pct', type: 'button', title: 'Back to 100%', onclick: () => step(0) });
    const show = () => { label.textContent = Math.round(UI.scale * 100) + '%'; };
    const step = (d) => {
      const i = UI.steps.reduce((best, s, at) => Math.abs(s - UI.scale) < Math.abs(UI.steps[best] - UI.scale) ? at : best, 0);
      setScale(d ? UI.steps[Math.min(UI.steps.length - 1, Math.max(0, i + d))] : 1, true); show();
    };
    show();
    return h('div', { class: 'scale', role: 'group', 'aria-label': 'Page size' }, h('span', {}, 'Size'),
      h('button', { class: 'btn small', type: 'button', 'aria-label': 'Smaller', title: 'Smaller', onclick: () => step(-1) }, '\u2212'), label,
      h('button', { class: 'btn small', type: 'button', 'aria-label': 'Larger', title: 'Larger', onclick: () => step(1) }, '+'));
  }
  // text boxes grow with what is written in them; a browser that cannot do it by itself is helped
  if (!(window.CSS && CSS.supports && CSS.supports('field-sizing', 'content'))) {
    const grow = (t) => { if (!t || t.tagName !== 'TEXTAREA' || !t.offsetParent) return; t.style.height = 'auto'; t.style.height = (t.scrollHeight + 2) + 'px'; };
    const growAll = (root) => { if (root && root.querySelectorAll) root.querySelectorAll('textarea').forEach(grow); };
    document.addEventListener('input', (e) => grow(e.target));
    document.addEventListener('toggle', (e) => growAll(e.target), true);
    window.addEventListener('resize', () => growAll(document));
    new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) { grow(n); growAll(n); } }).observe(document.documentElement, { childList: true, subtree: true });
  }
  function cleanup() { for (const fn of S.cleanup.splice(0)) { try { fn(); } catch (e) { /* already gone */ } } }
  function route() { return (location.hash || '#overview').slice(1) || 'overview'; }
  function go(r) { try { if (location.hash !== '#' + r) { location.hash = r; return; } } catch (e) { /* sandboxed */ } render(r); }
  window.addEventListener('hashchange', () => render(route()));
  function link(r, attrs, ...kids) {
    return h('a', Object.assign({ href: '#' + r, onclick: (e) => { e.preventDefault(); go(r); } }, attrs || {}), ...kids);
  }

  // ---------------------------------------------------------------- 3D view
  const GL = { r: undefined, views: new Set(), raf: 0, last: 0 };
  function renderer3() {
    if (GL.r !== undefined) return GL.r;
    GL.r = null;
    if (!window.THREE || !THREE.GLTFLoader || !THREE.OrbitControls) return null;
    try {
      const r = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      r.outputEncoding = THREE.sRGBEncoding; r.setClearColor(0x000000, 0);
      GL.r = r;
    } catch (e) { GL.r = null; }
    return GL.r;
  }
  function tick3(now) {
    GL.raf = GL.views.size ? requestAnimationFrame(tick3) : 0;
    const dt = Math.min(0.1, (now - GL.last) / 1000); GL.last = now;
    for (const v of GL.views) v.frame(dt);
  }
  function refFigure() {
    const g = new THREE.Group();
    const mat = new THREE.LineBasicMaterial({ color: 0xc9c9d2 });  // the 1.8 m figure is gray: it must never read as part of the model
    const part = (w, hh, d, y) => { const m = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, hh, d)), mat); m.position.y = y; g.add(m); };
    part(0.34, 0.9, 0.2, 0.45); part(0.44, 0.62, 0.24, 1.21); part(0.2, 0.26, 0.22, 1.67);
    const bar = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-0.4, 1.8, 0), new THREE.Vector3(3.2, 1.8, 0)]),
      new THREE.LineDashedMaterial({ color: 0xc9c9d2, dashSize: 0.06, gapSize: 0.05, transparent: true, opacity: 0.7 }));
    bar.computeLineDistances(); g.add(bar);
    return g;
  }
  // the box a piece fills. A skinned mesh is measured in the pose it holds, from a sample of its vertices.
  function bounds3(root) {
    const box = new THREE.Box3(), part = new THREE.Box3(), p = new THREE.Vector3();
    root.updateMatrixWorld(true);
    root.traverse((n) => {
      const pos = n.geometry && n.geometry.attributes.position;
      if (!pos || n.userData.mark) return;
      if (n.isSkinnedMesh) {
        const step = Math.max(1, Math.floor(pos.count / 1500));
        for (let i = 0; i < pos.count; i += step) box.expandByPoint(n.boneTransform(i, p.fromBufferAttribute(pos, i)).applyMatrix4(n.matrixWorld));
      } else {
        if (!n.geometry.boundingBox) n.geometry.computeBoundingBox();
        box.union(part.copy(n.geometry.boundingBox).applyMatrix4(n.matrixWorld));
      }
    });
    return box;
  }
  function modelView(url, opt) {
    opt = opt || {};
    const r = renderer3();
    if (!r) return { el: h('div', { class: 'fallback' }, 'The 3D preview could not start in this browser. The file is ', h('code', { class: 'i' }, url.split('/').pop()), '.'), set() {}, destroy() {} };
    const canvas = h('canvas', { class: 'three', 'aria-label': '3D model. Drag to turn it; double-click to frame it again.' });
    const ctx = canvas.getContext('2d');
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 200);
    const controls = new THREE.OrbitControls(camera, canvas);
    const coarse = window.matchMedia && matchMedia('(pointer: coarse)').matches;
    controls.enableZoom = !!opt.zoom; controls.enablePan = !!opt.zoom;
    if (!opt.zoom && coarse) { controls.enabled = false; canvas.style.touchAction = 'pan-y'; }
    scene.add(new THREE.HemisphereLight(0xffffff, 0x30303a, 0.95));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9); sun.position.set(2.5, 4, 3); scene.add(sun);
    const floor = (cells) => { const g = new THREE.GridHelper(cells, cells, 0x777777, 0x3a3a3a); g.cells = cells; scene.add(g); return g; };
    let grid = floor(10);  // metre squares
    const ref = refFigure(); scene.add(ref);
    const FIGURE = new THREE.Box3(new THREE.Vector3(-0.22, 0, -0.12), new THREE.Vector3(0.22, 1.8, 0.12));
    const v = { el: canvas, dirty: true, mixer: null, clips: [], action: null, w: 0, hh: 0, playing: true, rotate: false, cam: camera, target: controls.target,
      box: new THREE.Box3(new THREE.Vector3(-0.4, 0, -0.2), new THREE.Vector3(0.4, 1.8, 0.2)), fit: { c: new THREE.Vector3(0, 0.9, 0), d: 1 },
      scene, controls, canvas, figure: ref, renderer: r, fixed: opt.clip || '' };
    const small = (box) => { const size = box.getSize(new THREE.Vector3()); return Math.max(size.x, size.y, size.z) < 0.9; };
    // what the view frames: the piece as it stands, or everything it passes through in the motion it plays
    function measure(clip) {
      if (!clip) return bounds3(v.model);
      const box = new THREE.Box3();
      for (let i = 0; i <= 12; i++) { v.mixer.setTime(clip.duration * i / 12); box.union(bounds3(v.model)); }
      v.mixer.setTime(0);
      return box;
    }
    function frame(box) {
      if (box.isEmpty()) return;
      v.box = box;
      const c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
      v.deep = size.z > size.x * 2;  // long and thin, front to back, as a gun is: it is seen from its long side
      // the figure stands on the floor at the piece's side as the camera sees it, never in front of it or behind
      if (v.deep) { ref.position.set(c.x, 0, box.max.z + 0.42); ref.rotation.y = Math.PI / 2; }
      else { ref.position.set(box.min.x - 0.42, 0, c.z); ref.rotation.y = 0; }
      const cells = Math.min(400, Math.max(10, 2 * Math.ceil(1.25 * Math.max(-box.min.x, box.max.x, -box.min.z, box.max.z))));  // the floor runs out past a large piece
      if (cells !== grid.cells) { scene.remove(grid); grid.geometry.dispose(); grid = floor(cells); }
      if (!v.moved) place();
      v.dirty = true;
    }
    // every piece fills the view whatever its size, and stays inside it through a whole turn
    function place() {
      const box = v.box, c = box.getCenter(v.fit.c), foot = (b) => [[b.min.x, b.min.z], [b.min.x, b.max.z], [b.max.x, b.min.z], [b.max.x, b.max.z]];
      const pts = foot(box), from = c.clone(), to = c.clone();
      let lo = box.min.y, hi = box.max.y;
      // a piece near a person's size is framed with the figure beside it; a small one is framed alone, or the figure would shrink it to a speck
      if (ref.visible && !small(box)) {
        ref.updateMatrixWorld(true);
        const fig = FIGURE.clone().applyMatrix4(ref.matrixWorld);
        pts.push(...foot(fig)); fig.getCenter(to); lo = Math.min(lo, fig.min.y); hi = Math.max(hi, fig.max.y);
      }
      // the view turns about the upright line that holds them both in the narrowest circle
      let r = Infinity;
      for (let i = 0; i <= 10; i++) {
        const x = from.x + (to.x - from.x) * i / 20, z = from.z + (to.z - from.z) * i / 20;
        const far = Math.max(...pts.map(([px, pz]) => Math.hypot(px - x, pz - z)));
        if (far < r) { r = far; c.set(x, (lo + hi) / 2, z); }
      }
      const half = (hi - lo) / 2, t = Math.tan(Math.PI * 16 / 180), ce = Math.cos(0.16), se = Math.sin(0.16);
      const d = v.fit.d = 1.06 * Math.max(r / Math.sin(Math.atan(t * Math.max(0.5, camera.aspect))),
        (r * se + half * ce) / t + Math.abs(r * ce - half * se), (half * ce - r * se) / t + r * ce + half * se);
      const turn = v.deep ? Math.PI / 2 - 0.52 : 0.52;
      controls.target.copy(c);
      camera.position.set(c.x + d * Math.sin(turn) * ce, c.y + d * se, c.z + d * Math.cos(turn) * ce);
      camera.near = d / 100; camera.far = d * 100; camera.updateProjectionMatrix();
      controls.minDistance = d / 20; controls.maxDistance = d * 20;
      controls.update(); v.dirty = true;
    }
    controls.addEventListener('change', () => {
      v.dirty = true;
      const grp = opt.group;
      if (grp && !grp.busy) { grp.busy = true; for (const o of grp.views) if (o !== v) o.copyCam(v); grp.busy = false; }
    });
    // a view that follows another takes its angle, zoom and slide, each measured against its own piece, so its own piece stays framed
    v.copyCam = (o) => {
      const k = v.fit.d / o.fit.d;
      controls.target.copy(o.target).sub(o.fit.c).multiplyScalar(k).add(v.fit.c);
      camera.position.copy(o.cam.position).sub(o.target).multiplyScalar(k).add(controls.target);
      controls.update(); v.dirty = true;
    };
    v.frame = (dt) => {
      if (!canvas.isConnected) return;
      const dpr = Math.min(2, (window.devicePixelRatio || 1) * cz(canvas));
      const w = Math.round(canvas.clientWidth * dpr), hh = Math.round(canvas.clientHeight * dpr);
      if (!w || !hh) return;
      if (w !== v.w || hh !== v.hh) {
        const first = !v.w; canvas.width = w; canvas.height = hh; v.w = w; v.hh = hh; camera.aspect = w / hh; camera.updateProjectionMatrix();
        if (first || !v.moved) place(); v.dirty = true;
      }
      if (v.rotate) { controls.autoRotate = true; controls.autoRotateSpeed = 3; controls.update(); }
      if (v.mixer && v.playing && v.action) { v.mixer.update(dt * (v.rate || 1)); v.dirty = true; }
      if (!v.dirty) return;
      v.dirty = false;
      r.setSize(w, hh, false); r.render(scene, camera);
      ctx.clearRect(0, 0, w, hh); ctx.drawImage(r.domElement, 0, 0);
    };
    v.set = (o) => {
      if (o.ref !== undefined && ref.visible !== o.ref) { ref.visible = o.ref; if (!v.moved) place(); }
      if (o.rotate !== undefined) { v.rotate = o.rotate; controls.autoRotate = o.rotate; }
      if (o.playing !== undefined) v.playing = o.playing;
      if (o.wire !== undefined && v.model) v.model.traverse((n) => { if (n.material && !n.userData.mark) n.material.wireframe = o.wire; });
      if (o.rate !== undefined) v.rate = o.rate;
      const want = opt.clip || o.clip;  // a motion candidate plays its own clip whatever the picker says
      if ((opt.clip || o.clip !== undefined) && v.mixer && want !== v.clipName) {
        v.clipName = want;
        v.mixer.stopAllAction(); v.action = null;
        const clip = v.clips.find((c) => c.name === want);
        if (clip) { v.action = v.mixer.clipAction(clip); v.action.reset().play(); }
        else v.mixer.update(0);
        frame(measure(clip));
      }
      v.dirty = true;
    };
    v.destroy = () => { GL.views.delete(v); controls.dispose(); scene.traverse((n) => { if (n.geometry) n.geometry.dispose(); }); };
    canvas.addEventListener('pointerdown', () => { v.moved = true; });
    canvas.addEventListener('dblclick', () => { v.moved = false; place(); });
    API.bytes(url).then((buf) => new Promise((ok, bad) => new THREE.GLTFLoader().parse(buf, '', ok, bad))).then((g) => {
      v.model = g.scene; scene.add(g.scene);
      g.scene.traverse((n) => { if (n.isSkinnedMesh) n.frustumCulled = false; });  // a motion can carry it out of the box it is culled by
      v.clips = g.animations || []; v.mixer = new THREE.AnimationMixer(g.scene);
      v.moved = false; v.clipName = undefined; v.set(Object.assign({}, S.opts));
      if (v.clipName === undefined) frame(measure(null));
      if (opt.ready) opt.ready(v);
    }).catch(() => { canvas.replaceWith(h('div', { class: 'fallback' }, 'This model could not be read.')); v.destroy(); });
    GL.views.add(v);
    if (!GL.raf) { GL.last = performance.now(); GL.raf = requestAnimationFrame(tick3); }
    return v;
  }

  // ------------------------------------------------------------ picture view
  function zoomPane(src, group) {
    const box = h('div', { class: 'zoom' });
    const img = h('img', { src, alt: '', draggable: 'false' });
    const layer = h('div', { class: 'marklayer' });  // marks, moved and scaled with the picture
    box.append(img, layer);
    const t = group.t;
    const pane = { el: box, apply, img, layer, pen: null };
    group.panes.push(pane);
    function dims() { return { bw: box.clientWidth, bh: box.clientHeight, iw: img.naturalWidth, ih: img.naturalHeight }; }
    function apply() {
      const d = dims(); if (!d.bw || !d.iw) return;
      const s = Math.min(d.bw / d.iw, d.bh / d.ih) * t.z;
      img.style.transform = layer.style.transform = 'translate(' + (d.bw / 2 - t.cx * d.iw * s) + 'px,' + (d.bh / 2 - t.cy * d.ih * s) + 'px) scale(' + s + ')';
      layer.style.width = d.iw + 'px'; layer.style.height = d.ih + 'px'; pane.scale = s;
    }
    // where a point on the screen falls on the picture, in its own pixels
    pane.toImage = (x, y) => {
      const d = dims(), r = box.getBoundingClientRect(), k = cz(box), s = Math.min(d.bw / d.iw, d.bh / d.ih) * t.z;
      return [((x - r.left) / k - (d.bw / 2 - t.cx * d.iw * s)) / s, ((y - r.top) / k - (d.bh / 2 - t.cy * d.ih * s)) / s];
    };
    const all = () => group.panes.forEach((p) => p.apply());
    function zoomAt(px, py, factor) {
      const d = dims(); if (!d.iw) return;
      const fit = Math.min(d.bw / d.iw, d.bh / d.ih), s = fit * t.z;
      const u = (px - (d.bw / 2 - t.cx * d.iw * s)) / (d.iw * s), w = (py - (d.bh / 2 - t.cy * d.ih * s)) / (d.ih * s);
      t.z = Math.min(40, Math.max(1, t.z * factor));
      const s2 = fit * t.z;
      t.cx = u + (d.bw / 2 - px) / (d.iw * s2); t.cy = w + (d.bh / 2 - py) / (d.ih * s2);
      if (t.z === 1) { t.cx = 0.5; t.cy = 0.5; }
      all();
    }
    img.addEventListener('load', apply);
    box.addEventListener('wheel', (e) => { e.preventDefault(); const r = box.getBoundingClientRect(), k = cz(box); zoomAt((e.clientX - r.left) / k, (e.clientY - r.top) / k, e.deltaY < 0 ? 1.18 : 1 / 1.18); }, { passive: false });
    box.addEventListener('dblclick', (e) => { const d = dims(); const r = box.getBoundingClientRect(); const fit = Math.min(d.bw / d.iw, d.bh / d.ih), k = cz(box); zoomAt((e.clientX - r.left) / k, (e.clientY - r.top) / k, t.z > 1.01 ? 1 / t.z : Math.max(2, 1 / fit)); });
    const pts = new Map(); let pinch = 0, drawing = null;
    // marking: one pointer paints; a second finger, or the right button, moves the picture as before
    box.addEventListener('pointerdown', (e) => {
      box.setPointerCapture(e.pointerId);
      if (drawing !== null) { pane.pen.cancel(); drawing = null; }
      else if (pane.pen && pane.pen.on && !pts.size && e.button === 0) { drawing = e.pointerId; pane.pen.down(e.clientX, e.clientY); return; }
      pts.set(e.pointerId, [e.clientX, e.clientY]); pinch = 0;
    });
    box.addEventListener('contextmenu', (e) => { if (pane.pen && pane.pen.on) e.preventDefault(); });
    box.addEventListener('pointermove', (e) => {
      if (pane.pen) pane.pen.hover(e.clientX, e.clientY);
      if (e.pointerId === drawing) { pane.pen.move(e.clientX, e.clientY); return; }
      if (!pts.has(e.pointerId)) return;
      const prev = pts.get(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]);
      const d = dims(); if (!d.iw) return;
      const k = cz(box);
      if (pts.size === 1) { const s = Math.min(d.bw / d.iw, d.bh / d.ih) * t.z * k; t.cx -= (e.clientX - prev[0]) / (d.iw * s); t.cy -= (e.clientY - prev[1]) / (d.ih * s); all(); }
      else if (pts.size === 2) {
        const [a, b] = [...pts.values()]; const dist = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const r = box.getBoundingClientRect();
        if (pinch) zoomAt(((a[0] + b[0]) / 2 - r.left) / k, ((a[1] + b[1]) / 2 - r.top) / k, dist / pinch);
        pinch = dist;
      }
    });
    const up = (e) => { if (e.pointerId === drawing) { drawing = null; pane.pen.up(); return; } pts.delete(e.pointerId); pinch = 0; };
    box.addEventListener('pointerleave', () => { if (pane.pen) pane.pen.hover(null); });
    box.addEventListener('pointerup', up); box.addEventListener('pointercancel', up);
    if (window.ResizeObserver) { const ro = new ResizeObserver(apply); ro.observe(box); pane.destroy = () => ro.disconnect(); }
    return pane;
  }

  // ------------------------------------------------------------------ marks
  // The user paints on a picture or over a model's surface in up to five colours, and writes a note for each colour.
  // What Claude gets: the marks as data, a sentence per colour on where they sit, and one picture of it all.
  const MARK = [['red', '#ff453a'], ['yellow', '#ffd60a'], ['green', '#30d158'], ['blue', '#0a84ff'], ['purple', '#bf5af2']];
  const MARK_HEX = Object.fromEntries(MARK);
  const BRUSH = [6, 14, 30];  // the brush's radius on the screen, in pixels: small, medium, large
  const MODEL_POINTS = 8000;  // the stroke points one model keeps; past this the brush lays no more
  function newInk(saved, kind) {
    saved = saved || {};
    const ink = { kind, notes: Object.assign({}, saved.notes || {}), strokes: (saved.strokes || []).map((s) => Object.assign({}, s)),
      faces: {}, meshes: Object.assign({}, saved.meshes || {}), where: Object.assign({}, saved.where || {}), moments: Object.assign({}, saved.moments || {}),
      colour: 'red', size: 1, erase: false, on: false, subs: [] };
    for (const [key, byColour] of Object.entries(saved.faces || {})) {
      const m = ink.faces[key] = new Map();
      for (const [c, list] of Object.entries(byColour || {})) for (const f of list || []) m.set(f, c);
    }
    ink.changed = (what) => ink.subs.forEach((fn) => fn(what));
    return ink;
  }
  // the colours that have something marked in them
  function inkUsed(ink) {
    const used = new Set();
    if (ink.kind === 'image') { for (const s of ink.strokes) if (s.c !== 'erase') used.add(s.c); for (const c of Object.keys(ink.where)) if (!ink.where[c]) used.delete(c); }
    else for (const m of Object.values(ink.faces)) for (const c of m.values()) used.add(c);
    if (ink.kind === 'model') for (const s of ink.strokes) if (s.c !== 'erase' && ink.where[s.c] !== '') used.add(s.c);  // '' is a colour wholly rubbed out
    return MARK.map(([c]) => c).filter((c) => used.has(c));
  }
  // the marks as they are saved: plain lists, nothing the server has to work out
  function inkData(ink) {
    const used = inkUsed(ink);
    if (!used.length && !Object.values(ink.notes).some((x) => x && x.trim())) return null;
    const out = { kind: ink.kind, notes: {}, where: {} };
    for (const c of used) { out.notes[c] = (ink.notes[c] || '').trim(); out.where[c] = ink.where[c] || ''; }
    if (ink.kind === 'image') { out.strokes = ink.strokes; out.size = ink.imageSize || null; }
    else {
      out.faces = {}; out.meshes = {}; out.moments = {};
      const lead = ink.strokes.findIndex((s) => s.c !== 'erase');  // rubbing out with nothing under it is not kept
      if (lead >= 0 && ink.strokes.some((s) => used.includes(s.c))) { out.strokes = ink.strokes.slice(lead); for (const s of out.strokes) out.meshes[s.m] = ink.meshes[s.m] || s.m; }
      for (const c of used) if (ink.moments[c]) out.moments[c] = ink.moments[c];
      for (const [key, m] of Object.entries(ink.faces)) {
        const by = {};
        for (const [f, c] of m) (by[c] = by[c] || []).push(f);
        if (Object.keys(by).length) { for (const c of Object.keys(by)) by[c].sort((a, b) => a - b); out.faces[key] = by; out.meshes[key] = ink.meshes[key] || key; }
      }
    }
    return out;
  }
  const thirds = (f, words) => words[f < 1 / 3 ? 0 : f > 2 / 3 ? 2 : 1];
  const pct = (x) => (x < 0.01 ? 'under 1%' : 'about ' + Math.round(x * 100) + '%');
  // The brush, shared by a picture and a frame of a clip. A stroke is { c: a colour or 'erase', r: its radius, p: [[x, y]] },
  // all in the picture's own pixels. inkLine draws a stroke on a layer from its point `from` on (all of it, or what was
  // just added); q is how many of the layer's pixels make one of the picture's
  function inkLine(ctx, s, from, q) {
    ctx.lineCap = ctx.lineJoin = 'round'; ctx.lineWidth = 2 * s.r * q; ctx.strokeStyle = ctx.fillStyle = s.c === 'erase' ? '#000' : MARK_HEX[s.c];
    ctx.globalCompositeOperation = s.c === 'erase' ? 'destination-out' : 'source-over';
    for (let i = Math.max(0, from); i < s.p.length; i++) {
      const a = s.p[Math.max(0, i - 1)], b = s.p[i];
      ctx.beginPath(); ctx.moveTo(a[0] * q, a[1] * q); ctx.lineTo(b[0] * q, b[1] * q); ctx.stroke();
      ctx.beginPath(); ctx.arc(b[0] * q, b[1] * q, s.r * q, 0, 7); ctx.fill();
    }
  }
  // a stroke begun where the brush comes down, at p on the picture; scale is the screen's pixels to one of the picture's
  const inkStart = (ink, p, scale) => ({ c: ink.erase ? 'erase' : ink.colour, r: Math.max(0.5, Math.round(BRUSH[ink.size] / (scale || 1) * 10) / 10), p: [p.map(Math.round)] });
  // the brush moved to p: the stroke takes the point, unless it has hardly moved
  function inkMore(s, p) {
    p = p.map(Math.round); const last = s.p[s.p.length - 1];
    if (Math.hypot(p[0] - last[0], p[1] - last[1]) < s.r / 3) return false;
    s.p.push(p); return true;
  }
  // where the paint on a layer sits on its picture of iw by ih: its box in the picture's pixels, the part of the
  // picture in words, and its share of the picture. Nothing painted is null
  function inkPlace(layer, iw, ih) {
    const n = 200, k = n / Math.max(iw, ih), w = Math.max(1, Math.round(iw * k)), hh = Math.max(1, Math.round(ih * k));
    const small = h('canvas', { width: w, height: hh }).getContext('2d', { willReadFrequently: true });
    small.drawImage(layer, 0, 0, w, hh);
    const px = small.getImageData(0, 0, w, hh).data;
    let x0 = w, y0 = hh, x1 = -1, y1 = -1, count = 0;
    for (let y = 0; y < hh; y++) for (let x = 0; x < w; x++) if (px[(y * w + x) * 4 + 3] > 40) { count++; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    if (!count) return null;
    const X0 = Math.round(x0 / k), X1 = Math.round((x1 + 1) / k), Y0 = Math.round(y0 / k), Y1 = Math.round((y1 + 1) / k);
    const fx = (X0 + X1) / 2 / iw, fy = (Y0 + Y1) / 2 / ih;
    const pos = fx > 1 / 3 && fx < 2 / 3 && fy > 1 / 3 && fy < 2 / 3 ? 'the middle' : [thirds(fy, ['upper', '', 'lower']), thirds(fx, ['left', 'centre', 'right'])].filter(Boolean).join(' ');
    return { x0: X0, x1: X1, y0: Y0, y1: Y1, pos, share: count / (w * hh) };
  }
  // the ring that shows the brush under the pointer, over `host`; with x null it is hidden
  function inkRing(ring, host, x, y, ink) {
    if (x === null || !ink.on) { ring.hidden = true; return; }
    const r = host.getBoundingClientRect(), k = cz(host), d = 2 * BRUSH[ink.size];
    Object.assign(ring.style, { left: ((x - r.left) / k - d / 2) + 'px', top: ((y - r.top) / k - d / 2) + 'px', width: d + 'px', height: d + 'px' });
    ring.hidden = false; ring.classList.toggle('erase', ink.erase); ring.style.borderColor = ink.erase ? '' : MARK_HEX[ink.colour];
  }

  // painting on a picture shown in a zoom pane
  function markImage(pane, ink) {
    const layers = {};
    let iw = 0, ih = 0, q = 1, stroke = null;
    const brush = h('div', { class: 'brush', hidden: true });
    pane.el.append(brush);
    const ctxOf = (c) => layers[c].getContext('2d');
    function paint(s, from) {
      const targets = s.c === 'erase' ? MARK.map(([c]) => c) : [s.c];
      for (const c of targets) inkLine(ctxOf(c), s, from, q);
    }
    function redraw() { for (const [c] of MARK) ctxOf(c).clearRect(0, 0, layers[c].width, layers[c].height); for (const s of ink.strokes) paint(s, 0); }
    // where each colour sits, read back from what is painted
    function measure() {
      for (const [c] of MARK) {
        const at = inkPlace(layers[c], iw, ih);
        if (!at) { if (ink.strokes.some((s) => s.c === c)) ink.where[c] = ''; else delete ink.where[c]; continue; }
        ink.where[c] = 'x ' + at.x0 + '–' + at.x1 + ', y ' + at.y0 + '–' + at.y1 + ' px of the ' + iw + ' × ' + ih + ' picture (' + at.pos + ', from its top left corner); ' + pct(at.share) + ' of the picture';
      }
    }
    function start() {
      iw = pane.img.naturalWidth; ih = pane.img.naturalHeight;
      if (!iw) return;
      q = Math.min(1, 2048 / Math.max(iw, ih)); ink.imageSize = [iw, ih];
      for (const [c] of MARK) { layers[c] = h('canvas', { width: Math.round(iw * q), height: Math.round(ih * q), class: 'ink' }); pane.layer.append(layers[c]); }
      redraw(); if (ink.strokes.length) measure();
    }
    if (pane.img.complete && pane.img.naturalWidth) start(); else pane.img.addEventListener('load', start, { once: true });
    pane.pen = {
      get on() { return ink.on; },
      down(x, y) { if (!iw) return; stroke = inkStart(ink, pane.toImage(x, y), pane.scale); ink.strokes.push(stroke); paint(stroke, 0); },
      move(x, y) { if (stroke && inkMore(stroke, pane.toImage(x, y))) paint(stroke, stroke.p.length - 1); },
      up() { if (!stroke) return; stroke = null; measure(); ink.changed('marks'); },
      cancel() { if (!stroke) return; ink.strokes.pop(); stroke = null; redraw(); },
      hover(x, y) { inkRing(brush, pane.el, x, y, ink); },
    };
    const api = {
      undo() { if (!ink.strokes.length) return; ink.strokes.pop(); redraw(); measure(); ink.changed('marks'); },
      clear() { ink.strokes = []; redraw(); measure(); ink.changed('marks'); },
      mode(on) { pane.el.classList.toggle('pen', on); if (!on) brush.hidden = true; },
      // the picture Claude reads: the image with the marks over it, at up to 1600 px across
      async picture() {
        if (!iw) return null;
        const k = Math.min(1, 1600 / Math.max(iw, ih)), w = Math.round(iw * k), hh = Math.round(ih * k);
        const out = h('canvas', { width: w, height: hh }), ctx = out.getContext('2d');
        ctx.fillStyle = '#1b1b1f'; ctx.fillRect(0, 0, w, hh);
        try { ctx.drawImage(pane.img, 0, 0, w, hh); } catch (e) { /* drawn without it */ }
        ctx.globalAlpha = 0.5; for (const [c] of MARK) ctx.drawImage(layers[c], 0, 0, w, hh); ctx.globalAlpha = 1;
        return withLegend(out, ink);
      },
    };
    return api;
  }

  // painting on a model in a 3D view, still or moving. The paint is kept as strokes: points on the surface in the
  // model's own space, each with the brush's size and the way to the eye from it, and it is drawn as a see-through
  // layer over the texture, so it moves with a posed body. On a motion the brush stops it, the bar scrubs to the
  // frame, and each colour keeps the clip and the moment it was painted at: "the elbow folds wrong here".
  const PAINT_W = 1024;  // the stroke points sit in a texture this wide: three rows for every 1024 of them
  const PAINT_VS = ['#include <skinning_pars_vertex>', 'varying vec3 vBind;', 'varying vec3 vSide;', 'void main() {',
    '  vBind = position;', '  vSide = normal;', '  #include <skinbase_vertex>', '  #include <begin_vertex>', '  #include <skinning_vertex>', '  #include <project_vertex>', '}'].join('\n');
  // the newest stroke is tried first: paint covers what is under it and rubbing out hides it, each with a soft edge one pixel wide.
  // The loops end by their own tests alone: a continue or a break in them hung the graphics driver under Direct3D
  const PAINT_FS = ['uniform highp sampler2D pts;', 'uniform int count;', 'uniform float opacity;', 'varying vec3 vBind;', 'varying vec3 vSide;',
    'const vec3 COLS[6] = vec3[6](vec3(0.0), ' + MARK.map(([, hex]) => 'vec3(' + [1, 3, 5].map((i) => (parseInt(hex.slice(i, i + 2), 16) / 255).toFixed(4)).join(', ') + ')').join(', ') + ');',
    'vec4 pt(int i, int row) { return texelFetch(pts, ivec2(i & ' + (PAINT_W - 1) + ', (i >> 10) * 3 + row), 0); }',
    'void main() {',
    '  vec3 n = normalize(vSide) * (gl_FrontFacing ? 1.0 : -1.0);',
    '  float px = max(length(dFdx(vBind)), length(dFdy(vBind))) + 1e-9;',
    '  vec3 sum = vec3(0.0);',
    '  float cover = 0.0, through = 1.0;',
    '  for (int k = ((count + 15) >> 4) - 1; k >= 0 && through > 0.01; k--) {',
    '    vec4 ball = pt(k, 2);',
    '    if (distance(vBind, ball.xyz) <= ball.w + px) {',
    '      for (int i = min(count, (k + 1) << 4) - 1; i >= (k << 4) && through > 0.01; i--) {',
    '        vec4 p = pt(i, 0), q = pt(i, 1);',
    '        int code = int(q.w + 0.5);',
    '        vec3 c = p.xyz;',
    '        float side = dot(n, q.xyz);',
    '        if (code >= 8) {',
    '          vec3 a = pt(i - 1, 0).xyz, ab = p.xyz - a;',
    '          c = a + ab * clamp(dot(vBind - a, ab) / max(dot(ab, ab), 1e-12), 0.0, 1.0);',
    '          side = max(side, dot(n, pt(i - 1, 1).xyz));',
    '        }',
    '        float a = clamp((p.w - distance(vBind, c)) / px + 0.5, 0.0, 1.0) * smoothstep(0.1, 0.3, side);',
    '        int col = code & 7;',
    '        if (col > 0) { sum += through * a * COLS[col]; cover += through * a; }',
    '        through *= 1.0 - a;',
    '      }',
    '    }',
    '  }',
    '  if (cover < 0.004) discard;',
    '  gl_FragColor = vec4(sum / cover, opacity * cover);',
    '}'].join('\n');
  // the layer needs WebGL2; without it the brush paints whole faces, as it did before there were strokes
  const paintsFine = () => { const r = renderer3(); return !!(r && r.capabilities.isWebGL2); };
  const modelHint = () => (paintsFine() ? 'Paint over it' : 'Paint faces') + ' · right-drag turns it · scroll zooms';
  function markModel(v, ink) {
    const meshes = [], byKey = {}, overlays = new Map(), drags = [], V = new THREE.Vector3(), M = new THREE.Matrix4(), ray = new THREE.Raycaster(), tri = new THREE.Triangle();
    const fine = paintsFine();
    let ready = false, painting = false, dirty = new Set(), raf = 0, poseKey = null, stale = false, total = 0, drag = null, fullSaid = false;
    const brush = h('div', { class: 'brush', hidden: true });
    const scrub = h('div', { class: 'grp scrub', hidden: true });
    const r3 = (x) => Math.round(x * 1000) / 1000;
    function start() {
      let key = 0;
      v.model.updateMatrixWorld(true);
      v.model.traverse((n) => {
        if (!n.isMesh || n.userData.mark || !n.geometry || !n.geometry.attributes.position) return;
        const k = String(key++), g = n.geometry, pos = g.attributes.position, idx = g.index;
        const count = idx ? idx.count / 3 : pos.count / 3;
        const mats = Array.isArray(n.material) ? n.material : [n.material];
        const m = { key: k, mesh: n, count, vi: (f, j) => (idx ? idx.getX(3 * f + j) : 3 * f + j),
          PW: new Float32Array(pos.count * 3), C: new Float32Array(count * 3), N: new Float32Array(count * 3), A: new Float32Array(count),
          both: mats.some((x) => x && x.side === THREE.DoubleSide), name: n.name || (n.parent && n.parent.name) || 'mesh ' + k,
          // for the strokes: the mesh as the file has it, unposed (its points, the way each faces, its faces), and what the layer draws
          sk: !!n.isSkinnedMesh, P0: new Float32Array(pos.count * 3), NB: new Float32Array(pos.count * 3), ix: new Uint32Array(Math.floor(count) * 3), flag: new Uint8Array(Math.floor(count)),
          flip: 1, box: new THREE.Box3(), n: 0, was: 0, fill: 0, rmin: Infinity, data: null, tex: null, over: null, oi: null, group: null };
        for (let i = 0; i < pos.count; i++) { m.P0[3 * i] = pos.getX(i); m.P0[3 * i + 1] = pos.getY(i); m.P0[3 * i + 2] = pos.getZ(i); }
        for (let i = 0; i < m.ix.length; i++) m.ix[i] = idx ? idx.getX(i) : i;
        sides(m, g.attributes.normal);
        meshes.push(m); byKey[k] = m;
        ink.meshes[k] = m.name;
        if (!ink.faces[k]) ink.faces[k] = new Map();
        dirty.add(k);
      });
      // the primitives of one glTF mesh are separate meshes in one space: paint laid on one goes on them all, so a seam between two materials does not cut it
      const same = (a, b) => a.elements.every((x, i) => Math.abs(x - b.elements[i]) < 1e-6);
      // a mesh a motion moves by itself is never in one space with another, so the meshes go together the same way whatever pose this opened in
      const moved = new Set();
      for (const c of v.clips) for (const t of c.tracks) { const i = t.name.lastIndexOf('.'); if (/^(position|quaternion|scale)$/.test(t.name.slice(i + 1))) moved.add(t.name.slice(0, i)); }
      const own = (x) => moved.has(x.mesh.name || x.mesh.uuid);
      for (const m of meshes) m.group = meshes.filter((o) => o === m || (!own(o) && !own(m) && o.mesh.parent === m.mesh.parent && o.sk === m.sk && (!m.sk || o.mesh.skeleton === m.mesh.skeleton) && same(o.mesh.matrixWorld, m.mesh.matrixWorld)));
      const destroy = v.destroy;
      v.destroy = () => {  // the view drops the geometry; the layers' textures and materials are dropped here
        for (const m of meshes) { if (m.tex) m.tex.dispose(); if (m.over) m.over.material.dispose(); }
        for (const o of overlays.values()) o.material.dispose();
        destroy();
      };
      ready = true; buildScrub(); lay(true); rebuild(); measure();
    }
    // the way the surface faces at each point of a mesh, unposed: the file's own normals, or worked out from the faces when it has none
    function sides(m, na) {
      const N = m.NB, P = m.P0;
      if (na) { for (let i = 0; 3 * i < N.length && i < na.count; i++) { N[3 * i] = na.getX(i); N[3 * i + 1] = na.getY(i); N[3 * i + 2] = na.getZ(i); } return; }
      for (let f = 0; 3 * f < m.ix.length; f++) {
        const a = 3 * m.ix[3 * f], b = 3 * m.ix[3 * f + 1], c = 3 * m.ix[3 * f + 2];
        const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], wx = P[c] - P[a], wy = P[c + 1] - P[a + 1], wz = P[c + 2] - P[a + 2];
        const x = uy * wz - uz * wy, y = uz * wx - ux * wz, z = ux * wy - uy * wx;
        for (const i of [a, b, c]) { N[i] += x; N[i + 1] += y; N[i + 2] += z; }
      }
      for (let i = 0; i < N.length; i += 3) { const l = Math.hypot(N[i], N[i + 1], N[i + 2]) || 1; N[i] /= l; N[i + 1] /= l; N[i + 2] /= l; }
    }
    const moving = () => !!(v.action && v.clips.length);
    // every face where it stands now, in the scene's space: a moving mesh is posed again for each new moment
    function pose() {
      const key = moving() ? v.clipName + '@' + v.action.time.toFixed(4) : 'still';
      if (key === poseKey && !(moving() && v.playing)) return;
      poseKey = key;
      v.model.updateMatrixWorld(true);
      const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), e1 = new THREE.Vector3(), e2 = new THREE.Vector3();
      for (const m of meshes) {
        const pos = m.mesh.geometry.attributes.position, mw = m.mesh.matrixWorld;
        m.flip = mw.determinant() < 0 ? -1 : 1; m.box.makeEmpty();
        for (let i = 0; i < pos.count; i++) {
          V.fromBufferAttribute(pos, i); if (m.mesh.isSkinnedMesh) m.mesh.boneTransform(i, V); V.applyMatrix4(mw);
          m.PW[3 * i] = V.x; m.PW[3 * i + 1] = V.y; m.PW[3 * i + 2] = V.z; m.box.expandByPoint(V);
        }
        for (let f = 0; f < m.count; f++) {
          a.fromArray(m.PW, 3 * m.vi(f, 0)); b.fromArray(m.PW, 3 * m.vi(f, 1)); c.fromArray(m.PW, 3 * m.vi(f, 2));
          m.C[3 * f] = (a.x + b.x + c.x) / 3; m.C[3 * f + 1] = (a.y + b.y + c.y) / 3; m.C[3 * f + 2] = (a.z + b.z + c.z) / 3;
          e1.subVectors(b, a); e2.subVectors(c, a); e1.cross(e2); m.A[f] = e1.length() / 2; e1.normalize();
          m.N[3 * f] = e1.x; m.N[3 * f + 1] = e1.y; m.N[3 * f + 2] = e1.z;
        }
      }
    }
    // the moment shown now, and a way to show another and come back
    const now = () => (moving() ? { clip: v.clipName, t: r3(v.action.time), length: r3(v.action.getClip().duration) } : null);
    function show(mo) {
      if (!mo || !v.mixer) return;
      if (mo.clip !== v.clipName && v.clips.some((c) => c.name === mo.clip)) v.set({ clip: mo.clip });
      if (v.action) { v.action.time = Math.min(mo.t, v.action.getClip().duration); v.mixer.update(0); }
      v.dirty = true; syncScrub();
    }
    function at(mo, fn) {  // do fn with the model in the pose of moment mo (with none: at rest), then put it back
      const was = now(), playing = v.playing, rest = !mo && was && !v.fixed;
      if (mo) { v.set({ playing: false }); show(mo); }
      else if (rest) { v.set({ clip: '' }); poseKey = null; }
      try { return fn(); } finally { if ((mo || rest) && was) { show(was); v.set({ playing }); } else if (mo && !was && v.action) v.set({ clip: '' }); poseKey = null; }
    }
    // where a stroke point sits in the layer's texture: row 0 its place and size, row 1 the way to the eye and its colour, row 2 the balls
    const off = (i, row) => (((i >> 10) * 3 + row) * PAINT_W + (i & (PAINT_W - 1))) * 4;
    // the strokes set out for the layer, mesh by mesh: every point with its size, the way to the eye and its colour, in
    // the order painted; then a ball round each sixteen of them, and the faces near a ball, which are all the layer draws
    function lay(full) {
      stale = false; total = 0;
      for (const m of meshes) { m.was = full ? 0 : m.n; m.n = 0; m.fill = 0; m.rmin = Infinity; }
      const known = (s) => byKey[s.m] && s.p && (s.c === 'erase' || MARK_HEX[s.c]);
      for (const s of ink.strokes) if (known(s)) { total += s.p.length / 6; for (const m of byKey[s.m].group) m.n += s.p.length / 6; }
      for (const m of meshes) {
        const size = 3 * Math.max(1, Math.ceil(m.n / PAINT_W)) * PAINT_W * 4;
        if (m.n && (!m.data || m.data.length !== size)) { m.data = new Float32Array(size); m.was = 0; if (m.tex) m.tex.dispose(); m.tex = null; }
      }
      for (const s of ink.strokes) {
        if (!known(s)) continue;
        const code = s.c === 'erase' ? 0 : 1 + MARK.findIndex(([c]) => c === s.c);
        for (const m of byKey[s.m].group) {
          m.rmin = Math.min(m.rmin, s.r);
          for (let i = 0; i < s.p.length; i += 6) {
            const d = m.data, a = off(m.fill, 0), b = off(m.fill, 1); m.fill++;
            d[a] = s.p[i]; d[a + 1] = s.p[i + 1]; d[a + 2] = s.p[i + 2]; d[a + 3] = s.r;
            d[b] = s.p[i + 3]; d[b + 1] = s.p[i + 4]; d[b + 2] = s.p[i + 5]; d[b + 3] = code + (i ? 8 : 0);  // 8: it joins the point before it
          }
        }
      }
      for (const m of meshes) {
        if (!m.n) { if (m.over) m.over.visible = false; m.flag.fill(0); continue; }
        const d = m.data, P = m.P0, ix = m.ix;
        let grew = full;
        if (full) m.flag.fill(0);
        for (let k = Math.max(0, m.was - 1) >> 4; k < (m.n + 15) >> 4; k++) {
          const lo = k << 4, hi = Math.min(m.n, lo + 16);
          let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity, r = 0;
          for (let i = lo && d[off(lo, 1) + 3] >= 8 ? lo - 1 : lo; i < hi; i++) {
            const a = off(i, 0);
            x0 = Math.min(x0, d[a]); y0 = Math.min(y0, d[a + 1]); z0 = Math.min(z0, d[a + 2]); x1 = Math.max(x1, d[a]); y1 = Math.max(y1, d[a + 1]); z1 = Math.max(z1, d[a + 2]); r = Math.max(r, d[a + 3]);
          }
          const c = off(k, 2), bx = d[c] = (x0 + x1) / 2, by = d[c + 1] = (y0 + y1) / 2, bz = d[c + 2] = (z0 + z1) / 2, R = d[c + 3] = Math.hypot(x1 - x0, y1 - y0, z1 - z0) / 2 + r;
          for (let f = 0; f < m.flag.length; f++) {
            if (m.flag[f]) continue;
            const a = 3 * ix[3 * f], b = 3 * ix[3 * f + 1], e = 3 * ix[3 * f + 2];
            const dx = Math.max(Math.min(P[a], P[b], P[e]) - bx, 0, bx - Math.max(P[a], P[b], P[e]));
            const dy = Math.max(Math.min(P[a + 1], P[b + 1], P[e + 1]) - by, 0, by - Math.max(P[a + 1], P[b + 1], P[e + 1]));
            const dz = Math.max(Math.min(P[a + 2], P[b + 2], P[e + 2]) - bz, 0, bz - Math.max(P[a + 2], P[b + 2], P[e + 2]));
            if (dx * dx + dy * dy + dz * dz <= R * R) { m.flag[f] = 1; grew = true; }
          }
        }
        if (!fine) continue;
        if (!m.over) m.over = overlay(m);
        if (grew) {
          const o = m.oi.array; let j = 0;
          for (let f = 0; f < m.flag.length; f++) if (m.flag[f]) { o[j++] = ix[3 * f]; o[j++] = ix[3 * f + 1]; o[j++] = ix[3 * f + 2]; }
          m.oi.needsUpdate = true; m.over.geometry.setDrawRange(0, j);
        }
        if (!m.tex) m.tex = m.over.material.uniforms.pts.value = new THREE.DataTexture(d, PAINT_W, d.length / (PAINT_W * 4), THREE.RGBAFormat, THREE.FloatType);
        m.tex.needsUpdate = true; m.over.material.uniforms.count.value = m.n; m.over.visible = true;
      }
      v.dirty = true;
    }
    // the layer over one mesh: the mesh's own points drawn again by a shader that colours only what the strokes cover.
    // On a skinned mesh it is skinned too, and the paint is looked up where the point was before posing, so it moves with the body
    function overlay(m) {
      const g = new THREE.BufferGeometry(), src = m.mesh.geometry;
      g.setAttribute('position', src.attributes.position);
      g.setAttribute('normal', src.attributes.normal || new THREE.BufferAttribute(m.NB, 3));
      if (m.sk) { g.setAttribute('skinIndex', src.attributes.skinIndex); g.setAttribute('skinWeight', src.attributes.skinWeight); }
      m.oi = new THREE.BufferAttribute(new Uint32Array(m.ix.length), 1); m.oi.setUsage(THREE.DynamicDrawUsage); g.setIndex(m.oi);
      const mat = new THREE.ShaderMaterial({ uniforms: { pts: { value: null }, count: { value: 0 }, opacity: { value: 0.62 } }, vertexShader: PAINT_VS, fragmentShader: PAINT_FS,
        transparent: true, depthWrite: false, side: m.both ? THREE.DoubleSide : THREE.FrontSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
      const o = m.sk ? new THREE.SkinnedMesh(g, mat) : new THREE.Mesh(g, mat);
      if (m.sk) o.bind(m.mesh.skeleton, m.mesh.bindMatrix);
      o.userData.mark = true; o.frustumCulled = false; o.renderOrder = 3; o.raycast = () => {};
      m.mesh.add(o);
      return o;
    }
    // what shows at a point of a mesh that faces a given way: a colour's number, 0 where it is rubbed out, -1 where nothing was painted. The shader's rule, worked here
    function top(m, x, y, z, nx, ny, nz) {
      const d = m.data;
      for (let k = ((m.n + 15) >> 4) - 1; k >= 0; k--) {
        const c = off(k, 2);
        if ((x - d[c]) * (x - d[c]) + (y - d[c + 1]) * (y - d[c + 1]) + (z - d[c + 2]) * (z - d[c + 2]) > d[c + 3] * d[c + 3]) continue;
        for (let i = Math.min(m.n, (k + 1) << 4) - 1; i >= k << 4; i--) {
          const a = off(i, 0), b = off(i, 1), code = d[b + 3];
          let px = d[a], py = d[a + 1], pz = d[a + 2], side = nx * d[b] + ny * d[b + 1] + nz * d[b + 2];
          if (code >= 8) {
            const a0 = off(i - 1, 0), b0 = off(i - 1, 1), ex = px - d[a0], ey = py - d[a0 + 1], ez = pz - d[a0 + 2];
            const t = Math.min(1, Math.max(0, ((x - d[a0]) * ex + (y - d[a0 + 1]) * ey + (z - d[a0 + 2]) * ez) / (ex * ex + ey * ey + ez * ez || 1e-12)));
            px = d[a0] + ex * t; py = d[a0 + 1] + ey * t; pz = d[a0 + 2] + ez * t;
            side = Math.max(side, nx * d[b0] + ny * d[b0 + 1] + nz * d[b0 + 2]);
          }
          if (side > 0.2 && (x - px) * (x - px) + (y - py) * (y - py) + (z - pz) * (z - pz) < d[a + 3] * d[a + 3]) return code & 7;
        }
      }
      return -1;
    }
    // one see-through mesh per colour over each mesh, holding only the faces painted that colour (marks made before
    // there were strokes, and all marks without WebGL2); on a skinned mesh it is skinned too, so the marks move with the motion
    function rebuild() {
      raf = 0;
      if (stale) lay(false);
      for (const k of dirty) {
        const m = meshes.find((x) => x.key === k); if (!m) continue;
        const lists = {};
        for (const [f, c] of ink.faces[k]) (lists[c] = lists[c] || []).push(f);
        for (const [c, hex] of MARK) {
          const id = k + ':' + c, list = lists[c] || [];
          let o = overlays.get(id);
          if (!list.length) { if (o) o.visible = false; continue; }
          if (!o) {
            const g = new THREE.BufferGeometry(), src = m.mesh.geometry;
            g.setAttribute('position', src.attributes.position);
            if (m.mesh.isSkinnedMesh) { g.setAttribute('skinIndex', src.attributes.skinIndex); g.setAttribute('skinWeight', src.attributes.skinWeight); }
            const mat = new THREE.MeshBasicMaterial({ color: hex, transparent: true, opacity: 0.8, depthWrite: false, side: m.both ? THREE.DoubleSide : THREE.FrontSide,
              polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
            o = m.mesh.isSkinnedMesh ? new THREE.SkinnedMesh(g, mat) : new THREE.Mesh(g, mat);
            if (m.mesh.isSkinnedMesh) o.bind(m.mesh.skeleton, m.mesh.bindMatrix);
            o.userData.mark = true; o.frustumCulled = false; o.renderOrder = 2; o.raycast = () => {};
            m.mesh.add(o); overlays.set(id, o);
          }
          const ix = new Uint32Array(list.length * 3);
          list.forEach((f, i) => { ix[3 * i] = m.vi(f, 0); ix[3 * i + 1] = m.vi(f, 1); ix[3 * i + 2] = m.vi(f, 2); });
          o.geometry.setIndex(new THREE.BufferAttribute(ix, 1)); o.visible = true;
        }
      }
      dirty = new Set(); v.dirty = true;
    }
    // the surface the strokes cover, found by trying points on every face near them, closer together than the smallest
    // brush used: for each one painted, its mesh, its face, where on the face, its colour and its share of the face
    function covered() {
      const out = [];
      const cuts = (m, f) => {
        const P = m.P0, a = 3 * m.ix[3 * f], b = 3 * m.ix[3 * f + 1], c = 3 * m.ix[3 * f + 2], edge = (i, j) => Math.hypot(P[i] - P[j], P[i + 1] - P[j + 1], P[i + 2] - P[j + 2]);
        return Math.min(512, Math.max(1, Math.ceil(1.5 * Math.max(edge(a, b), edge(b, c), edge(c, a)) / m.rmin)));
      };
      let want = 0;
      for (const m of meshes) if (m.n) for (let f = 0; f < m.flag.length; f++) if (m.flag[f]) want += cuts(m, f) ** 2;
      const less = want > 300000 ? Math.sqrt(300000 / want) : 1;  // a very large face under a very small brush is tried more thinly
      for (const m of meshes) {
        if (!m.n) continue;
        const P = m.P0, N = m.NB;
        for (let f = 0; f < m.flag.length; f++) {
          if (!m.flag[f]) continue;
          const a = 3 * m.ix[3 * f], b = 3 * m.ix[3 * f + 1], c = 3 * m.ix[3 * f + 2], n = Math.max(1, Math.floor(cuts(m, f) * less));
          for (let i = 0; i < n; i++) for (let j = 0; j < 2 * (n - i) - 1; j++) {  // the face cut into n × n small triangles; the middle of each is tried
            const t = (j % 2 ? 2 : 1) / 3, u = (i + t) / n, w = ((j >> 1) + t) / n, w0 = 1 - u - w;
            const x = w0 * P[a] + u * P[b] + w * P[c], y = w0 * P[a + 1] + u * P[b + 1] + w * P[c + 1], z = w0 * P[a + 2] + u * P[b + 2] + w * P[c + 2];
            let nx = w0 * N[a] + u * N[b] + w * N[c], ny = w0 * N[a + 1] + u * N[b + 1] + w * N[c + 1], nz = w0 * N[a + 2] + u * N[b + 2] + w * N[c + 2];
            const l = Math.hypot(nx, ny, nz) || 1; nx /= l; ny /= l; nz /= l;
            let code = top(m, x, y, z, nx, ny, nz);
            if (code < 1 && m.both) code = top(m, x, y, z, -nx, -ny, -nz);
            if (code > 0) out.push(m, f, u, w, code, 1 / (n * n));
          }
        }
      }
      return out;
    }
    // the face of these meshes nearest a point in the model's own space, and where on it
    function locate(group, x, y, z) {
      const p = new THREE.Vector3(x, y, z), q = new THREE.Vector3(), bary = new THREE.Vector3();
      let best = null;
      for (const m of group) for (let f = 0; f < m.flag.length; f++) {
        if (!m.flag[f]) continue;
        tri.a.fromArray(m.P0, 3 * m.ix[3 * f]); tri.b.fromArray(m.P0, 3 * m.ix[3 * f + 1]); tri.c.fromArray(m.P0, 3 * m.ix[3 * f + 2]);
        const d = tri.closestPointToPoint(p, q).distanceToSquared(p);
        if (!best || d < best.d) { tri.getBarycoord(q, bary); best = { m, f, d, u: bary.y, w: bary.z, stretch: m.A[f] / (tri.getArea() || 1) }; }
      }
      return best;
    }
    // where each colour sits, measured in the pose it was painted in: Y is up, the model's front faces +Z
    function measure() {
      ink.where = {};
      const used = new Set(), cover = covered();
      for (const m of meshes) for (const c of ink.faces[m.key].values()) used.add(c);
      for (const st of ink.strokes) if (st.c !== 'erase' && MARK_HEX[st.c] && byKey[st.m]) used.add(st.c);
      for (const c of used) at(ink.moments[c], () => {
        pose();
        const box = v.box, size = box.getSize(new THREE.Vector3()), code = 1 + MARK.findIndex(([x]) => x === c);
        const s = { area: 0, total: 0, sum: new THREE.Vector3(), box: new THREE.Box3(), names: new Set() };
        const add = (m, a, pad) => { s.area += a; s.sum.addScaledVector(V, a || 1e-9); s.box.expandByPoint(V); s.names.add(m.name); if (pad) { s.box.expandByPoint(V.addScalar(pad)); s.box.expandByPoint(V.addScalar(-2 * pad)); } };
        // a point of a face as it stands now, from where it is on the face
        const spot = (m, f, u, w) => { const W = m.PW, a = 3 * m.ix[3 * f], b = 3 * m.ix[3 * f + 1], e = 3 * m.ix[3 * f + 2], w0 = 1 - u - w; return V.set(w0 * W[a] + u * W[b] + w * W[e], w0 * W[a + 1] + u * W[b + 1] + w * W[e + 1], w0 * W[a + 2] + u * W[b + 2] + w * W[e + 2]); };
        for (const m of meshes) {
          for (let f = 0; f < m.count; f++) s.total += m.A[f];
          for (const [f, col] of ink.faces[m.key]) if (col === c) { V.fromArray(m.C, 3 * f); add(m, m.A[f]); }  // marks made by faces count too
        }
        for (let i = 0; i < cover.length; i += 6) if (cover[i + 4] === code) { spot(cover[i], cover[i + 1], cover[i + 2], cover[i + 3]); add(cover[i], cover[i].A[cover[i + 1]] * cover[i + 5]); }
        // a dab too small for the points tried, on a very large face: measured from the stroke's own points, where they still show
        if (!s.names.size) for (const st of ink.strokes) {
          const home = byKey[st.m]; if (st.c !== c || !home || !st.p) continue;
          for (let i = 0; i < st.p.length; i += 6) {
            // a point's last three numbers are the way to its eye, not the surface's facing: top() is asked with the facing of the face under it
            const on = locate(home.group, st.p[i], st.p[i + 1], st.p[i + 2]); if (!on) continue;
            const N = on.m.NB, a = 3 * on.m.ix[3 * on.f], b = 3 * on.m.ix[3 * on.f + 1], e = 3 * on.m.ix[3 * on.f + 2], w0 = 1 - on.u - on.w;
            let nx = w0 * N[a] + on.u * N[b] + on.w * N[e], ny = w0 * N[a + 1] + on.u * N[b + 1] + on.w * N[e + 1], nz = w0 * N[a + 2] + on.u * N[b + 2] + on.w * N[e + 2];
            const l = Math.hypot(nx, ny, nz) || 1; nx /= l; ny /= l; nz /= l;
            let shows = top(home, st.p[i], st.p[i + 1], st.p[i + 2], nx, ny, nz);
            if (shows < 1 && on.m.both) shows = top(home, st.p[i], st.p[i + 1], st.p[i + 2], -nx, -ny, -nz);
            if (shows !== code) continue;
            spot(on.m, on.f, on.u, on.w); add(on.m, Math.PI * st.r * st.r * on.stretch, st.r * Math.sqrt(on.stretch));
          }
        }
        if (!s.names.size) { ink.where[c] = ''; return; }  // every stroke of it is rubbed out or painted over
        const mid = s.sum.divideScalar(s.area || 1e-9), span = s.box.getSize(new THREE.Vector3()), f2 = (x) => x.toFixed(2);
        const fx = size.x ? (mid.x - box.min.x) / size.x : 0.5, fy = size.y ? (mid.y - box.min.y) / size.y : 0.5, fz = size.z ? (mid.z - box.min.z) / size.z : 0.5;
        const place = [thirds(fy, ['low', 'at mid height', 'high']), thirds(fz, ['toward the back', '', 'toward the front']),
          thirds(fx, ['on the left as seen from the front', 'centred left to right', 'on the right as seen from the front'])].filter(Boolean).join(', ');
        const mo = ink.moments[c];
        ink.where[c] = (mo ? 'in the motion "' + mo.clip + '" at ' + mo.t.toFixed(2) + ' s of ' + mo.length.toFixed(2) + ' s (' + Math.round(100 * mo.t / (mo.length || 1)) + '% through); ' : '') +
          'on ' + [...s.names].map((x) => '"' + x + '"').join(', ') + '; ' + place +
          '; centre at (' + f2(mid.x) + ', ' + f2(mid.y) + ', ' + f2(mid.z) + ') m in the model\'s space (Y up, its front faces +Z)' + (mo ? ', in that pose' : '') +
          '; spans ' + f2(span.x) + ' × ' + f2(span.y) + ' × ' + f2(span.z) + ' m; ' + pct(s.area / (s.total || 1)) + ' of its surface';
      });
    }
    // a colour painted on a moving model keeps the moment of its last stroke; the one before is kept for Undo
    function moment() {
      if (ink.erase) return;
      const mo = now();
      if (!drag.mo) drag.mo = [ink.colour, ink.moments[ink.colour]];
      if (mo) ink.moments[ink.colour] = mo; else delete ink.moments[ink.colour];
    }
    // what is under a point on the screen: the nearest face the line of sight meets as the model stands now, and where on it
    function cast(x, y, r) {
      ray.setFromCamera(V.set((x - r.left) / r.width * 2 - 1, 1 - (y - r.top) / r.height * 2, 0), v.cam);
      const o = ray.ray.origin, d = ray.ray.direction;
      let best = null;
      for (const m of meshes) {
        const P = m.PW, ix = m.ix;
        for (let f = 0; f < m.flag.length; f++) {
          const a = 3 * ix[3 * f], b = 3 * ix[3 * f + 1], c = 3 * ix[3 * f + 2];
          const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], wx = P[c] - P[a], wy = P[c + 1] - P[a + 1], wz = P[c + 2] - P[a + 2];
          const px = d.y * wz - d.z * wy, py = d.z * wx - d.x * wz, pz = d.x * wy - d.y * wx, det = ux * px + uy * py + uz * pz;
          if (!det || (!m.both && det * m.flip < 0)) continue;  // a face seen from behind is not there to paint
          const tx = o.x - P[a], ty = o.y - P[a + 1], tz = o.z - P[a + 2], u = (tx * px + ty * py + tz * pz) / det;
          if (u < 0 || u > 1) continue;
          const qx = ty * uz - tz * uy, qy = tz * ux - tx * uz, qz = tx * uy - ty * ux, w = (d.x * qx + d.y * qy + d.z * qz) / det;
          if (w < 0 || u + w > 1) continue;
          const t = (wx * qx + wy * qy + wz * qz) / det;
          if (t > 0 && (!best || t < best.t)) best = { m, f, u, w, t, back: det * m.flip < 0 };
        }
      }
      return best;
    }
    // one touch of the brush where the line of sight meets the model. The mesh it lands on takes the paint, and so does
    // any other mesh the brush reaches there, so a figure built of separate parts is not cut at each part's edge
    function dab(x, y, r, rad) {
      const hit = cast(x, y, r);
      if (!hit) { drag.recs.clear(); return; }
      const depth = hit.t * ray.ray.direction.dot(v.cam.getWorldDirection(V)), size = rad * 2 * depth * Math.tan(THREE.MathUtils.degToRad(v.cam.fov) / 2) / (r.height || 1);
      const here = ray.ray.at(hit.t, new THREE.Vector3()), eye = ray.ray.origin, q = new THREE.Vector3(), bary = new THREE.Vector3(), done = new Set([hit.m.group[0]]);
      const sight = new THREE.Vector3().subVectors(eye, here);
      put(hit.m, hit.f, hit.u, hit.w, size, hit.back, sight);
      for (const m of meshes) {
        const home = m.group[0];
        if (done.has(home) || m !== home) continue;
        let best = null;
        for (const o of m.group) {
          if (o.box.distanceToPoint(here) > size) continue;
          for (let f = 0; f < o.flag.length; f++) {
            const side = o.flip * (o.N[3 * f] * (eye.x - o.C[3 * f]) + o.N[3 * f + 1] * (eye.y - o.C[3 * f + 1]) + o.N[3 * f + 2] * (eye.z - o.C[3 * f + 2]));
            if (!o.both && side <= 0) continue;  // it faces away
            if (Math.abs(o.N[3 * f] * (here.x - o.C[3 * f]) + o.N[3 * f + 1] * (here.y - o.C[3 * f + 1]) + o.N[3 * f + 2] * (here.z - o.C[3 * f + 2])) > size) continue;
            tri.a.fromArray(o.PW, 3 * o.ix[3 * f]); tri.b.fromArray(o.PW, 3 * o.ix[3 * f + 1]); tri.c.fromArray(o.PW, 3 * o.ix[3 * f + 2]);
            const d = tri.closestPointToPoint(here, q).distanceTo(here);
            if (d < 0.95 * size && (!best || d < best.d)) { tri.getBarycoord(q, bary); best = { o, f, d, u: bary.y, w: bary.z, back: side < 0 }; }  // a mesh the brush only grazes is left alone
          }
        }
        if (best) { done.add(home); put(best.o, best.f, best.u, best.w, Math.sqrt(size * size - best.d * best.d), best.back, sight); }
      }
      for (const home of [...drag.recs.keys()]) if (!done.has(home)) drag.recs.delete(home);  // the brush has left that mesh: its stroke ends there
    }
    // the way from a point on a face to the eye, carried into the mesh's own space, unposed: what faces the eye on the screen faces
    // this way there, so paint does not go round a rounded part to the side that faced away. Where the surface is seen nearly
    // edge on, it leans toward the way the surface faces (nx, ny, nz), just far enough that the point under the brush takes the paint
    function toEye(m, a, b, c, sight, nx, ny, nz) {
      const q = new THREE.Vector3();
      if (!m.sk) q.copy(sight).transformDirection(M.copy(m.mesh.matrixWorld).invert());
      else {  // a posed body: through the face's own frame, its two edges and the way it faces, as it stands now and unposed
        const e1 = new THREE.Vector3(), e2 = new THREE.Vector3(), np = new THREE.Vector3(), E1 = new THREE.Vector3(), E2 = new THREE.Vector3(), nu = new THREE.Vector3();
        e1.fromArray(m.PW, b).sub(q.fromArray(m.PW, a)); e2.fromArray(m.PW, c).sub(q); np.crossVectors(e1, e2);
        E1.fromArray(m.P0, b).sub(q.fromArray(m.P0, a)); E2.fromArray(m.P0, c).sub(q); nu.crossVectors(E1, E2);
        const lp = np.lengthSq(), lu = nu.lengthSq(), t1 = sight.dot(e1), t2 = sight.dot(e2), d11 = e1.dot(e1), d12 = e1.dot(e2), d22 = e2.dot(e2);
        q.set(0, 0, 0);
        if (lp > 0 && lu > 0) q.addScaledVector(E1, (t1 * d22 - t2 * d12) / lp).addScaledVector(E2, (t2 * d11 - t1 * d12) / lp).addScaledVector(nu, sight.dot(np) / lp * m.flip * Math.pow(lp / lu, 0.25)).normalize();
      }
      const dn = q.x * nx + q.y * ny + q.z * nz, lean = 0.35;
      if (dn >= lean) return q;
      q.x -= dn * nx; q.y -= dn * ny; q.z -= dn * nz;
      const l = q.length(), k = Math.sqrt(1 - lean * lean) / l;
      return l > 1e-9 ? q.set(lean * nx + k * q.x, lean * ny + k * q.y, lean * nz + k * q.z) : q.set(nx, ny, nz);
    }
    // a point of a stroke on one mesh: on a face, at a place on it, with the brush's size in the scene. It is kept in
    // the mesh's own space, unposed, with the way to the eye from there
    function put(m, f, u, w, size, back, sight) {
      const home = m.group[0], P = m.P0, N = m.NB, a = 3 * m.ix[3 * f], b = 3 * m.ix[3 * f + 1], c = 3 * m.ix[3 * f + 2], w0 = 1 - u - w;
      const mix = (A, i) => w0 * A[a + i] + u * A[b + i] + w * A[c + i];
      const area = (A) => { const ux = A[b] - A[a], uy = A[b + 1] - A[a + 1], uz = A[b + 2] - A[a + 2], wx = A[c] - A[a], wy = A[c + 1] - A[a + 1], wz = A[c + 2] - A[a + 2]; return Math.hypot(uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx) / 2; };
      // the brush's size in the mesh's own units: a posed or scaled mesh is measured by how far the face has stretched
      const flat = area(P), posed = area(m.PW);
      if (flat > 0 && posed > 0) size *= Math.sqrt(flat / posed);
      if (!(size > 0)) return;
      let nx = mix(N, 0), ny = mix(N, 1), nz = mix(N, 2);
      const l = Math.hypot(nx, ny, nz) * (back ? -1 : 1) || 1; nx /= l; ny /= l; nz /= l;
      const way = toEye(m, a, b, c, sight, nx, ny, nz);
      const full = () => { if (!fullSaid) toast('This model holds no more paint. Undo or Clear all to make room.'); fullSaid = true; drag.recs.delete(home); };
      let rec = drag.recs.get(home), carry = null;
      if (rec) {
        const q = rec.p, n = q.length;
        if (Math.hypot(mix(P, 0) - q[n - 6], mix(P, 1) - q[n - 5], mix(P, 2) - q[n - 4]) > 3 * Math.max(rec.r, size)) rec = null;  // a jump across a gap: a new stroke
        else if (Math.abs(size - rec.r) > 0.2 * rec.r) { carry = q.slice(n - 6); rec = null; }  // nearer or further, so the brush is another size there
      }
      if (!rec) {
        if (total >= MODEL_POINTS) { full(); return; }
        rec = { c: ink.erase ? 'erase' : ink.colour, r: +size.toPrecision(3), m: home.key, p: carry || [] };
        if (drag.n++) rec.j = 1;  // more of the same drag: Undo takes it all
        drag.recs.set(home, rec); ink.strokes.push(rec); total += rec.p.length / 6;
      }
      const q = rec.p, n = q.length, k = Math.pow(10, Math.min(7, Math.max(0, 2 - Math.floor(Math.log10(rec.r))))), r2 = (z) => Math.round(z * 100) / 100;
      const pt = [Math.round(mix(P, 0) * k) / k, Math.round(mix(P, 1) * k) / k, Math.round(mix(P, 2) * k) / k, r2(way.x), r2(way.y), r2(way.z)];
      // points closer than about half the brush's width are thinned: the last one goes on with the brush until it is far
      // enough from the one before. When the brush turns back the last point stays, so paint already laid is not pulled away
      const gap = (i) => Math.hypot(pt[0] - q[i], pt[1] - q[i + 1], pt[2] - q[i + 2]);
      const reach = n >= 12 ? Math.hypot(q[n - 6] - q[n - 12], q[n - 5] - q[n - 11], q[n - 4] - q[n - 10]) : Infinity;
      if (reach < 0.8 * rec.r && gap(n - 12) >= reach) q.splice(n - 6, 6, ...pt);
      else if (n && gap(n - 6) < (reach < 0.8 * rec.r ? rec.r / 4 : rec.r / 20)) { /* it has hardly moved: nothing new */ }
      else { if (total >= MODEL_POINTS) { full(); return; } q.push(...pt); total++; }
      // rubbing out takes marks made by faces too: the face under the brush, and any whose middle is inside it
      if (ink.erase) for (const o of home.group) {
        for (const [g, col] of ink.faces[o.key]) {
          const i0 = 3 * o.ix[3 * g], i1 = 3 * o.ix[3 * g + 1], i2 = 3 * o.ix[3 * g + 2], Q = o.P0;
          if (!(o === m && g === f) && Math.hypot((Q[i0] + Q[i1] + Q[i2]) / 3 - pt[0], (Q[i0 + 1] + Q[i1 + 1] + Q[i2 + 1]) / 3 - pt[1], (Q[i0 + 2] + Q[i1 + 2] + Q[i2 + 2]) / 3 - pt[2]) > rec.r) continue;
          ink.faces[o.key].delete(g); drag.faces.push([o.key, g, col]); dirty.add(o.key);
        }
      }
    }
    // the brush over the texture: where it passes is laid as a stroke, tried often enough that a quick hand leaves no gaps
    function strokeAt(e) {
      pose(); v.cam.updateMatrixWorld();
      const r = v.canvas.getBoundingClientRect(), rad = BRUSH[ink.size] * (r.width / (v.canvas.clientWidth || r.width));
      const to = [e.clientX, e.clientY], from = drag.last || to, steps = Math.min(32, Math.max(1, Math.ceil(Math.hypot(to[0] - from[0], to[1] - from[1]) / (rad / 2))));
      for (let i = 1; i <= steps; i++) dab(from[0] + (to[0] - from[0]) * i / steps, from[1] + (to[1] - from[1]) * i / steps, r, rad);
      drag.last = to;
      if (drag.n) moment();
      stale = true;
      if (!raf) raf = requestAnimationFrame(rebuild);
    }
    // without WebGL2, the faces under the brush: the nearest face under it sets the depth, and only faces that face you count
    function facesAt(e) {
      pose();
      const r = v.canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top, rad = BRUSH[ink.size] * (r.width / (v.canvas.clientWidth || r.width));
      M.multiplyMatrices(v.cam.projectionMatrix, v.cam.matrixWorldInverse);
      const q = M.elements, eye = v.cam.position, hits = [];
      let near = null;
      for (const m of meshes) {
        for (let f = 0; f < m.count; f++) {
          const x = m.C[3 * f], y = m.C[3 * f + 1], z = m.C[3 * f + 2];
          const w = q[3] * x + q[7] * y + q[11] * z + q[15]; if (w <= 0) continue;
          const sx = ((q[0] * x + q[4] * y + q[8] * z + q[12]) / w * 0.5 + 0.5) * r.width, sy = (0.5 - (q[1] * x + q[5] * y + q[9] * z + q[13]) / w * 0.5) * r.height;
          if ((sx - px) * (sx - px) + (sy - py) * (sy - py) > rad * rad) continue;
          if (!m.both && m.N[3 * f] * (x - eye.x) + m.N[3 * f + 1] * (y - eye.y) + m.N[3 * f + 2] * (z - eye.z) > 0) continue;
          const d = Math.hypot(x - eye.x, y - eye.y, z - eye.z);
          hits.push([m, f, d]); if (!near || d < near[2]) near = [m, f, d];
        }
      }
      if (!near) return;
      const R = rad * 2 * near[2] * Math.tan(THREE.MathUtils.degToRad(v.cam.fov) / 2) / (r.height || 1);
      const nx = near[0].C[3 * near[1]], ny = near[0].C[3 * near[1] + 1], nz = near[0].C[3 * near[1] + 2];
      for (const [m, f] of hits) {
        if (Math.hypot(m.C[3 * f] - nx, m.C[3 * f + 1] - ny, m.C[3 * f + 2] - nz) > Math.max(R, 1e-6)) continue;  // behind what you are painting
        const map = ink.faces[m.key], was = map.get(f);
        if (ink.erase ? !was : was === ink.colour) continue;
        drag.faces.push([m.key, f, was]); dirty.add(m.key);
        if (ink.erase) map.delete(f); else map.set(f, ink.colour);
      }
      moment();
      if (dirty.size && !raf) raf = requestAnimationFrame(rebuild);
    }
    const brushAt = (e) => (fine ? strokeAt(e) : facesAt(e));
    // the bar under the tools for a model that moves: which motion, play or hold, and the frame
    let rng = null, label = null, pick = null, play = null;
    function buildScrub() {
      if (!v.clips.length) return;
      const fixed = !!v.fixed || v.clips.length === 1;  // a motion candidate plays its own clip only
      pick = fixed ? null : h('select', { 'aria-label': 'Motion to mark', onchange: () => { v.set({ clip: pick.value, playing: false }); poseKey = null; syncScrub(); } },
        h('option', { value: '' }, 'Still'), v.clips.map((c) => h('option', { value: c.name }, c.name)));
      play = h('button', { class: 'btn small', type: 'button', onclick: () => { if (!v.action) return; v.set({ playing: !v.playing }); syncScrub(); } }, 'Play');
      const step = (k) => h('button', { class: 'btn small', type: 'button', title: k < 0 ? 'A frame back' : 'A frame on', onclick: () => {
        if (!v.action) return; v.set({ playing: false }); const d = v.action.getClip().duration;
        v.action.time = Math.min(d, Math.max(0, v.action.time + k / 30)); v.mixer.update(0); v.dirty = true; syncScrub(); } }, k < 0 ? '◀' : '▶');
      rng = h('input', { type: 'range', min: 0, max: 1, step: 0.001, value: 0, 'aria-label': 'Moment in the motion', oninput: () => {
        if (!v.action) return; v.set({ playing: false }); v.action.time = +rng.value * v.action.getClip().duration; v.mixer.update(0); v.dirty = true; syncScrub(); } });
      label = h('span', { class: 'mono t' });
      scrub.replaceChildren(...[h('span', { class: 'hint' }, 'Motion'), pick, play, step(-1), rng, step(1), label].filter(Boolean));  // a motion candidate has no picker
      scrub.hidden = false; syncScrub();
      (function tick() { if (!scrub.isConnected && ready && tickN++ > 50) return; if (v.playing) syncScrub(); requestAnimationFrame(tick); })();
    }
    let tickN = 0;
    function syncScrub() {
      if (!rng) return;
      const on = moving();
      if (pick) pick.value = v.clipName || '';
      rng.disabled = play.disabled = !on;
      play.textContent = on && v.playing ? 'Hold' : 'Play';
      const d = on ? v.action.getClip().duration : 0;
      rng.value = on && d ? String(v.action.time / d) : '0';
      label.textContent = on ? v.action.time.toFixed(2) + ' / ' + d.toFixed(2) + ' s' : 'rest pose';
    }
    // the brush takes the left button and one finger; the right button turns the model, the wheel zooms
    const down = (e) => {
      if (!ink.on || !ready || e.button !== 0 || painting) return;
      e.stopImmediatePropagation(); e.preventDefault();
      if (moving() && v.playing) { v.set({ playing: false }); syncScrub(); }  // a moving model is marked on a held frame
      v.canvas.setPointerCapture(e.pointerId); painting = e.pointerId; v.moved = true;
      drag = { n: 0, faces: [], recs: new Map(), last: null, mo: null };  // what this drag lays or takes away, so Undo can put it back
      brushAt(e);
    };
    const move = (e) => {
      if (ink.on) hover(e);
      if (e.pointerId !== painting) return;
      e.stopImmediatePropagation(); brushAt(e);
    };
    const up = (e) => {
      if (e.pointerId !== painting) return;
      painting = false; e.stopImmediatePropagation();
      if (drag && (drag.n || drag.faces.length)) drags.push(drag);
      drag = null; rebuild(); measure(); ink.changed('marks');
    };
    function hover(e) {
      const host = v.canvas.parentElement; if (!host) return;
      if (!brush.isConnected) { host.style.position = host.style.position || 'relative'; host.append(brush); }
      if (!e) { brush.hidden = true; return; }
      const r = host.getBoundingClientRect(), k = cz(host), d = 2 * BRUSH[ink.size];
      Object.assign(brush.style, { left: ((e.clientX - r.left) / k - d / 2) + 'px', top: ((e.clientY - r.top) / k - d / 2) + 'px', width: d + 'px', height: d + 'px' });
      brush.hidden = false; brush.classList.toggle('erase', ink.erase); brush.style.borderColor = ink.erase ? '' : MARK_HEX[ink.colour];
    }
    v.canvas.addEventListener('pointerdown', down, { capture: true });
    v.canvas.addEventListener('pointermove', move, { capture: true });
    v.canvas.addEventListener('pointerup', up, { capture: true });
    v.canvas.addEventListener('pointercancel', up, { capture: true });
    v.canvas.addEventListener('pointerleave', () => { brush.hidden = true; });
    v.canvas.addEventListener('contextmenu', (e) => { if (ink.on) e.preventDefault(); });
    let tries = 0;
    (function wait() { if (v.model) start(); else if (tries++ < 300) setTimeout(wait, 100); })();  // the model is still loading
    // the picture Claude reads. A still model: the user's view, then front, right, back, left and top. Marks made in a
    // motion: a row for each moment, posed as it was then, with the colours painted at it named on the row
    function shots() {
      const used = inkUsed(ink), moments = [];
      for (const c of used) {
        const mo = ink.moments[c] || null, same = moments.find((x) => (x.mo && mo) ? x.mo.clip === mo.clip && Math.abs(x.mo.t - mo.t) < 0.0005 : !x.mo && !mo);
        if (same) same.colours.push(c); else moments.push({ mo, colours: [c] });
      }
      if (!moments.some((x) => x.mo)) return [{ mo: null, label: '', views: [['Your view', null], ['Front', [0, 0, 1]], ['Right side', [1, 0, 0]], ['Back', [0, 0, -1]], ['Left side', [-1, 0, 0]], ['Top', [0, 1, 0]]], cols: 3 }];
      return moments.slice(0, 5).map((x) => ({ mo: x.mo, cols: 4, label: x.colours.join(', ') + (x.mo ? ' · "' + x.mo.clip + '" at ' + x.mo.t.toFixed(2) + ' s of ' + x.mo.length.toFixed(2) + ' s' : ' · rest pose'),
        views: [['Your view', null], ['Front', [0, 0, 1]], ['Right side', [1, 0, 0]], ['Back', [0, 0, -1]]] }));
    }
    return {
      scrub,
      // the last drag of the brush is taken back: what it laid, what it rubbed out, and the moment its colour had before
      undo() {
        if (!ready || painting) return;
        const d = drags.pop();
        if (d) {
          ink.strokes.splice(ink.strokes.length - d.n, d.n);
          for (const [key, f, c] of d.faces.reverse()) { if (c) ink.faces[key].set(f, c); else ink.faces[key].delete(f); dirty.add(key); }
          if (d.mo) { if (d.mo[1]) ink.moments[d.mo[0]] = d.mo[1]; else delete ink.moments[d.mo[0]]; }
        } else if (ink.strokes.length) { while (ink.strokes.pop().j && ink.strokes.length); }  // paint from an earlier sitting: its last stroke goes
        else return;
        lay(true); rebuild(); measure(); ink.changed('marks');
      },
      clear() {
        for (const m of meshes) { ink.faces[m.key].clear(); dirty.add(m.key); }
        ink.strokes = []; ink.moments = {}; drags.length = 0; fullSaid = false;
        lay(true); rebuild(); measure(); ink.changed('marks');
      },
      mode(on) {
        v.canvas.classList.toggle('pen', on); if (!on) brush.hidden = true;
        v.controls.mouseButtons.RIGHT = on ? THREE.MOUSE.ROTATE : THREE.MOUSE.PAN;
        v.set({ rotate: false });
      },
      goto(mo) { if (!mo) return; v.set({ playing: false }); show(mo); poseKey = null; },
      async picture() {
        if (!ready) return null;
        rebuild();  // the paint is all on the model before it is drawn
        const rows = shots(), T = rows[0].cols === 3 ? 400 : 300, band = rows[0].label ? 30 : 0;
        const perRow = rows[0].cols === 3 ? 2 : 1, H = rows.length * perRow * T + rows.length * band;
        const r = v.renderer, out = h('canvas', { width: T * rows[0].cols, height: H }), ctx = out.getContext('2d');
        ctx.fillStyle = '#1b1b1f'; ctx.fillRect(0, 0, out.width, out.height);
        const cam = new THREE.PerspectiveCamera(32, 1, 0.01, 1000), figure = v.figure.visible;
        r.setSize(T, T, false);
        let y0 = 0;
        for (const row of rows) {
          at(row.mo, () => {
            v.model.updateMatrixWorld(true);
            const box = row.mo ? bounds3(v.model) : v.box, c = box.getCenter(new THREE.Vector3()), rad = box.getSize(new THREE.Vector3()).length() / 2 || 1;
            const d = rad / Math.sin(THREE.MathUtils.degToRad(16)) * 1.02;
            if (band) { ctx.fillStyle = '#26262c'; ctx.fillRect(0, y0, out.width, band); ctx.fillStyle = '#fff'; ctx.font = '600 15px system-ui, sans-serif'; ctx.fillText(row.label, 10, y0 + 20); }
            row.views.forEach(([name, dir], i) => {
              v.figure.visible = !dir && figure;
              if (dir) { cam.up.set(0, dir[1] ? 0 : 1, dir[1] ? -1 : 0); cam.position.set(c.x + dir[0] * d, c.y + dir[1] * d, c.z + dir[2] * d); cam.near = d / 100; cam.far = d * 100; cam.lookAt(c); cam.updateProjectionMatrix(); r.render(v.scene, cam); }
              else { const own = v.cam.clone(); own.aspect = 1; own.updateProjectionMatrix(); r.render(v.scene, own); }
              const x = (i % row.cols) * T, y = y0 + band + Math.floor(i / row.cols) * T;
              ctx.drawImage(r.domElement, x, y, T, T);
              ctx.fillStyle = 'rgba(0,0,0,0.6)'; ctx.fillRect(x, y, 110, 24); ctx.fillStyle = '#fff'; ctx.font = '600 13px system-ui, sans-serif'; ctx.fillText(name, x + 8, y + 17);
              ctx.strokeStyle = '#333'; ctx.strokeRect(x + 0.5, y + 0.5, T - 1, T - 1);
            });
            y0 += band + perRow * T;
          });
        }
        v.figure.visible = figure; v.dirty = true;  // the next frame draws the view at its own size again
        return withLegend(out, ink);
      },
    };
  }

  // under a marked picture: each colour, its note, and where it is; so the picture reads on its own
  function withLegend(top, ink) {
    const used = inkUsed(ink), W = Math.max(top.width, 800), pad = 14, line = 20;
    const meas = h('canvas').getContext('2d'); meas.font = '15px system-ui, sans-serif';
    const wrap = (text, width) => { const out = []; let cur = ''; for (const w of String(text).split(/\s+/)) { const t2 = cur ? cur + ' ' + w : w; if (meas.measureText(t2).width > width && cur) { out.push(cur); cur = w; } else cur = t2; } if (cur) out.push(cur); return out.length ? out : ['']; };
    const rows = used.map((c) => ({ c, lines: wrap(ink.notes[c] && ink.notes[c].trim() ? '“' + ink.notes[c].trim() + '”' : '(no note for this colour)', W - 2 * pad - 110) }));
    const legendH = rows.length ? pad + rows.reduce((n, r) => n + r.lines.length * line + 8, 0) + pad : 0;
    const out = h('canvas', { width: W, height: top.height + legendH }), ctx = out.getContext('2d');
    ctx.fillStyle = '#111114'; ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(top, Math.round((W - top.width) / 2), 0);
    let y = top.height + pad;
    for (const r of rows) {
      ctx.fillStyle = MARK_HEX[r.c]; ctx.fillRect(pad, y + 3, 16, 16);
      ctx.fillStyle = '#fff'; ctx.font = '600 15px system-ui, sans-serif'; ctx.fillText(r.c, pad + 24, y + 16);
      ctx.font = '15px system-ui, sans-serif'; ctx.fillStyle = '#e6e6ea';
      r.lines.forEach((l, i) => ctx.fillText(l, pad + 110, y + 16 + i * line));
      y += r.lines.length * line + 8;
    }
    return new Promise((ok) => out.toBlob((b) => ok(b), 'image/png'));
  }

  // the tools: mark on or off, a colour, the brush, rub out, undo, clear; and a note for each colour used
  function markTools(ink, live) {
    const marker = { undo: () => live().undo(), clear: () => live().clear(), mode: (on) => live().mode(on) };
    const swatches = MARK.map(([c, hex]) => h('button', { class: 'swatch', type: 'button', title: c, 'aria-label': 'Mark in ' + c, style: '--sw:' + hex,
      onclick: () => { ink.colour = c; ink.erase = false; if (!ink.on) toggle(true); draw(); } }));
    const sizes = ['S', 'M', 'L'].map((label, i) => h('button', { class: 'btn small', type: 'button', title: ['Small', 'Medium', 'Large'][i] + ' brush', onclick: () => { ink.size = i; draw(); } }, label));
    const pen = h('button', { class: 'btn small', type: 'button', title: 'Paint on it. Right-drag turns or moves it; the wheel zooms.', onclick: () => toggle(!ink.on) }, 'Mark');
    const rub = h('button', { class: 'btn small', type: 'button', onclick: () => { ink.erase = !ink.erase; if (!ink.on) toggle(true); draw(); } }, 'Rub out');
    const undo = ink.kind === 'image' || ink.kind === 'model' ? h('button', { class: 'btn small', type: 'button', onclick: () => marker.undo() }, 'Undo') : null;
    const clear = h('button', { class: 'btn small', type: 'button', onclick: () => { if (inkUsed(ink).length) marker.clear(); } }, 'Clear all');
    function toggle(on) { ink.on = on; marker.mode(on); draw(); }
    function draw() {
      pen.classList.toggle('on', ink.on); pen.setAttribute('aria-pressed', String(ink.on));
      swatches.forEach((b, i) => { const on = ink.on && !ink.erase && MARK[i][0] === ink.colour; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
      sizes.forEach((b, i) => b.classList.toggle('on', i === ink.size)); rub.classList.toggle('on', ink.on && ink.erase);
    }
    draw();
    return h('div', { class: 'grp marktools' }, pen, h('span', { class: 'swatches' }, swatches), h('span', { class: 'sizes' }, sizes), rub, undo, clear, live().scrub || null);
  }
  function markNotes(ink, editableNow, goto) {
    const box = h('div', { class: 'marknotes' }), fields = {};
    function draw() {
      const used = inkUsed(ink);
      for (const c of Object.keys(fields)) if (!used.includes(c)) { fields[c].row.remove(); delete fields[c]; }
      used.forEach((c, i) => {
        if (!fields[c]) {
          const t = h('textarea', { class: 'field', rows: 1, placeholder: 'What the ' + c + ' marks are about', 'aria-label': 'Note for the ' + c + ' marks', value: ink.notes[c] || '',
            oninput: () => { ink.notes[c] = t.value; ink.changed('notes'); } });
          t.disabled = !editableNow();
          const when = h('button', { class: 'btn small moment', type: 'button', title: 'Show the model at this moment', onclick: (e) => { e.preventDefault(); if (goto) goto(ink.moments[c]); } });
          fields[c] = { row: h('div', { class: 'marknote', style: '--sw:' + MARK_HEX[c] }, h('span', { class: 'sw' }), t, when), t, when };
        }
        const mo = ink.moments && ink.moments[c];
        fields[c].when.hidden = !mo; if (mo) fields[c].when.textContent = mo.clip + ' ' + mo.t.toFixed(2) + ' s';
        box.insertBefore(fields[c].row, box.children[i] || null);
      });
      box.hidden = !used.length;
    }
    ink.subs.push((what) => { if (what === 'marks') draw(); });
    draw();
    return box;
  }

  // -------------------------------------------------------------- sound view
  const players = new Set();
  function wavPeaks(buf, n) {
    const dv = new DataView(buf);
    if (dv.byteLength < 44 || dv.getUint32(0, false) !== 0x52494646) return null;
    let pos = 12, fmt = null, data = null;
    while (pos + 8 <= dv.byteLength) {
      const id = dv.getUint32(pos, false), size = dv.getUint32(pos + 4, true);
      if (id === 0x666d7420) fmt = { ch: dv.getUint16(pos + 10, true), rate: dv.getUint32(pos + 12, true), bits: dv.getUint16(pos + 22, true) };
      if (id === 0x64617461) { data = { at: pos + 8, size: Math.min(size, dv.byteLength - pos - 8) }; break; }
      pos += 8 + size + (size % 2);
    }
    if (!fmt || !data || fmt.bits !== 16) return null;
    const frames = Math.floor(data.size / (2 * fmt.ch)), peaks = new Float32Array(n);
    let top = 0;
    for (let i = 0; i < frames; i++) {
      const val = Math.abs(dv.getInt16(data.at + i * 2 * fmt.ch, true)) / 32768;
      const k = Math.min(n - 1, Math.floor(i * n / frames));
      if (val > peaks[k]) peaks[k] = val;
      if (val > top) top = val;
    }
    if (top > 0) for (let i = 0; i < n; i++) peaks[i] /= top;
    return { peaks, seconds: frames / fmt.rate };
  }
  const ICON_PLAY = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5z"/></svg>';
  const ICON_STOP = '<svg viewBox="0 0 14 14" aria-hidden="true"><rect x="2.5" y="2.5" width="9" height="9"/></svg>';
  function audioPlayer(url, label) {
    const a = new Audio(); a.preload = 'auto'; a.src = rel(API.src(url));
    const btn = h('button', { class: 'play', type: 'button', 'aria-label': 'Play ' + (label || 'sound'), html: ICON_PLAY });
    const wave = h('canvas', { class: 'wave' }); const time = h('span', { class: 't' }, '');
    const el = h('div', { class: 'player' }, btn, wave, time);
    let peaks = null, seconds = 0, raf = 0;
    function draw() {
      const dpr = Math.min(2, (window.devicePixelRatio || 1) * cz(wave)), w = Math.round(wave.clientWidth * dpr), hh = Math.round(wave.clientHeight * dpr);
      if (!w || !hh) return;
      if (wave.width !== w || wave.height !== hh) { wave.width = w; wave.height = hh; }
      const c = wave.getContext('2d'); c.clearRect(0, 0, w, hh);
      const css = getComputedStyle(wave), played = css.getPropertyValue('--accent-fg').trim() || '#ff5f6b', ahead = css.getPropertyValue('--faint').trim() || '#7d7d88';
      const dur = seconds || a.duration || 0, at = dur ? Math.min(1, a.currentTime / dur) : 0;
      const bars = Math.max(1, Math.floor(w / (3 * dpr)));
      for (let i = 0; i < bars; i++) {
        const p = peaks ? peaks[Math.floor(i * peaks.length / bars)] : 0.04;
        const bh = Math.max(dpr, p * hh * 0.92);
        c.fillStyle = (i / bars) < at ? played : ahead;
        c.fillRect(i * 3 * dpr, (hh - bh) / 2, 2 * dpr, bh);
      }
      time.textContent = dur ? (a.paused && !a.currentTime ? dur.toFixed(2) + ' s' : a.currentTime.toFixed(2)) : '';
    }
    const loop = () => { draw(); raf = a.paused ? 0 : requestAnimationFrame(loop); };
    a.addEventListener('play', () => { el.classList.add('playing'); btn.innerHTML = ICON_STOP; loop(); });
    const stopped = () => { el.classList.remove('playing'); btn.innerHTML = ICON_PLAY; draw(); };
    a.addEventListener('pause', stopped); a.addEventListener('ended', () => { a.currentTime = 0; stopped(); });
    a.addEventListener('loadedmetadata', draw);
    const p = {
      el,
      play() { for (const o of players) if (o !== p) o.stop(); a.loop = S.opts.loop; a.currentTime = 0; return a.play().catch(() => toast('The browser would not play this file')); },
      stop() { a.pause(); a.currentTime = 0; },
      toggle() { if (a.paused) p.play(); else p.stop(); },
      done: () => new Promise((ok) => { const fin = () => { a.removeEventListener('ended', fin); a.removeEventListener('pause', fin); ok(); }; a.addEventListener('ended', fin); a.addEventListener('pause', fin); }),
      destroy() { a.pause(); a.removeAttribute('src'); players.delete(p); cancelAnimationFrame(raf); },
    };
    btn.addEventListener('click', (e) => { e.stopPropagation(); seq.token++; p.toggle(); });
    wave.addEventListener('click', (e) => { const r = wave.getBoundingClientRect(); const dur = seconds || a.duration || 0; if (dur) { a.currentTime = dur * (e.clientX - r.left) / r.width; draw(); } });
    API.bytes(url).then((buf) => { const w = wavPeaks(buf, 240); if (w) { peaks = w.peaks; seconds = w.seconds; } draw(); }).catch(draw);
    players.add(p); setTimeout(draw, 0);
    return p;
  }
  // ----------------------------------------------------- marks on a timeline
  // On a sound or a clip a mark is a moment or a stretch of time with its own note, a colour, and a kind: Change, Cut
  // or Keep. What Claude gets: the marks as data, a sentence for each on where it is, and a picture of them all.
  // The sound view and the clip view share these parts: the marks (newSpans), the list of them beside the media
  // (spanList), their tools and keys (spanTools, spanKeys), the playing (transport), dragging marks along a lane
  // (spanLane), and how they are drawn (paintSpans, paintRuler, spanLegend).
  const TAGS = [['change', 'Change'], ['cut', 'Cut'], ['keep', 'Keep']];
  const SPAN_MAX = 40;
  const sec3 = (x) => Math.round(x * 1000) / 1000;
  // a time as it is written for the user and for Claude: 0:03.20
  function clock(t) { const c = Math.round(Math.max(0, t || 0) * 100); return Math.floor(c / 6000) + ':' + ((c % 6000) / 100).toFixed(2).padStart(5, '0'); }
  // the bar and the beat a time falls in, counted from the tempo the sound was filed with
  function barAt(tempo, t) {
    const pos = (t - tempo.first) * tempo.bpm / 60 + 1e-6;
    return pos < 0 ? null : { bar: Math.floor(pos / tempo.beats) + 1, beat: Math.floor(pos % tempo.beats) + 1 };
  }
  const barText = (tempo, t) => { const at = barAt(tempo, t); return at ? 'bar ' + at.bar + ' beat ' + at.beat : 'before bar 1'; };
  // the bars a mark covers: "bar 2 beat 3 to bar 3 beat 3", or "in bar 2 beat 3" when it starts and ends in one beat;
  // a stretch that ends before the first beat is "before bar 1"
  const barSpan = (tempo, s) => { const a = barText(tempo, s.t0), b = barText(tempo, s.t1); return !(s.t1 > s.t0) ? a : a !== b ? a + ' to ' + b : a.startsWith('bar') ? 'in ' + a : a; };
  const spanWhen = (s) => (s.t1 > s.t0 ? clock(s.t0) + ' to ' + clock(s.t1) + ' (' + (s.t1 - s.t0).toFixed(2) + ' s)' : 'at ' + clock(s.t0));
  const tagWord = (s) => (s.tag === 'keep' ? 'KEEP' : s.tag === 'cut' ? 'CUT' : 'change');
  // what a mark's play button loops: the stretch itself, or the second around a moment
  const spanRange = (s, len) => (s.t1 > s.t0 ? [s.t0, s.t1] : [Math.max(0, s.t0 - 0.5), Math.min(len || s.t0 + 0.5, s.t0 + 0.5)]);
  // whether marks on a timeline say anything by themselves: a note, a Cut or a Keep
  const spansSay = (mk) => !!(mk && (mk.spans || []).some((s) => (s.note && s.note.trim()) || s.tag === 'cut' || s.tag === 'keep'));

  // the marks on one sound or clip: add, move, stretch, take away, undo; numbered in time order, coloured in turn
  function newSpans(saved, kind) {
    saved = saved && saved.kind === kind ? saved : {};
    const tl = { kind, file: saved.file || '', length: saved.length || 0, fps: saved.fps || 0, size: saved.size || null, tempo: saved.tempo || null,
      spans: (saved.spans || []).map((s) => Object.assign({}, s)), chosen: null, subs: [], past: [], describe: null };
    let next = tl.spans.reduce((n, s) => Math.max(n, +String(s.id).slice(1) || 0), 0) + 1;  // a mark's name is given once and never again
    const told = new Map(tl.spans.map((s) => [s.id, s.t0 + '|' + s.t1]));  // the times each mark's "where" was written for
    const order = (a, b) => a.t0 - b.t0 || a.t1 - b.t1 || +a.id.slice(1) - +b.id.slice(1);
    tl.changed = (what) => tl.subs.slice().forEach((fn) => fn(what));  // 'marks', 'moved' (while dragging), 'notes', 'chosen'
    tl.sorted = () => tl.spans.slice().sort(order);
    tl.get = (id) => tl.spans.find((s) => s.id === id) || null;
    tl.fit = (t) => sec3(Math.min(tl.length || Infinity, Math.max(0, +t || 0)));
    // remember the marks as they are, so that the change about to be made can be undone
    tl.keep = () => { tl.past.push(JSON.stringify(tl.spans)); if (tl.past.length > 60) tl.past.shift(); };
    tl.add = (t0, t1, more) => {
      if (tl.spans.length >= SPAN_MAX) { toast('One ' + (kind === 'video' ? 'clip' : 'sound') + ' takes ' + SPAN_MAX + ' marks at most'); return null; }
      if (t1 === undefined) t1 = t0;
      tl.keep();
      const s = Object.assign({ id: 'm' + next, c: MARK[(next - 1) % MARK.length][0], tag: 'change', t0: tl.fit(Math.min(t0, t1)), t1: tl.fit(Math.max(t0, t1)), note: '', where: '' }, more || {});
      next++; tl.spans.push(s); tl.chosen = s.id; tl.changed('marks');
      return s;
    };
    // while a mark is dragged: call keep() once before the first move, and changed('marks') when it is let go
    tl.move = (s, t0, t1) => { s.t0 = tl.fit(Math.min(t0, t1)); s.t1 = tl.fit(Math.max(t0, t1)); tl.changed('moved'); };
    tl.set = (s, fields) => { tl.keep(); Object.assign(s, fields); tl.changed('marks'); };
    tl.remove = (s) => { const i = tl.spans.indexOf(s); if (i < 0) return; tl.keep(); tl.spans.splice(i, 1); if (tl.chosen === s.id) tl.chosen = null; tl.changed('marks'); };
    tl.clear = () => { if (!tl.spans.length) return; tl.keep(); tl.spans = []; tl.chosen = null; tl.changed('marks'); };
    // back to before the last change; a note typed since stays with its mark
    tl.undo = () => {
      if (!tl.past.length) return false;
      const now = new Map(tl.spans.map((s) => [s.id, s]));
      tl.spans = JSON.parse(tl.past.pop()).map((s) => (now.has(s.id) ? Object.assign(s, { note: now.get(s.id).note }) : s));
      if (!tl.get(tl.chosen)) tl.chosen = null;
      tl.changed('marks');
      return true;
    };
    tl.choose = (s) => { const id = s ? s.id : null; if (tl.chosen === id) return; tl.chosen = id; tl.changed('chosen'); };
    // the mark before or after the chosen one; with none chosen, before or after a time
    tl.beside = (d, t) => {
      const list = tl.sorted(), i = list.findIndex((s) => s.id === tl.chosen);
      if (i >= 0) return list[i + d] || null;
      return d > 0 ? list.find((s) => s.t0 > t + 1e-4) || null : list.filter((s) => s.t0 < t - 1e-4).pop() || null;
    };
    // the sentence Claude reads for a mark, written again by the view (tl.describe) when its times have changed
    tl.where = (s) => {
      const key = s.t0 + '|' + s.t1;
      if (tl.describe && told.get(s.id) !== key) { const d = tl.describe(s) || {}; s.where = d.where || ''; if (d.facts) s.facts = d.facts; else delete s.facts; told.set(s.id, key); }
      return s.where || '';
    };
    tl.stale = (s) => { if (s) told.delete(s.id); else told.clear(); };
    // the marks as they are saved: in time order, nothing the server has to work out
    tl.data = () => {
      if (!tl.spans.length) return null;
      const out = { kind, file: tl.file, length: sec3(tl.length) };
      if (kind === 'video') { if (tl.fps) out.fps = tl.fps; if (tl.size) out.size = tl.size; }
      if (tl.tempo) out.tempo = tl.tempo;
      out.spans = tl.sorted().map((s) => {
        const o = { id: s.id, c: s.c, tag: s.tag, t0: s.t0, t1: s.t1, note: (s.note || '').trim(), where: tl.where(s) };
        if (s.facts) o.facts = s.facts;
        if (s.strokes && s.strokes.length) o.strokes = s.strokes;
        if (s.box) o.box = s.box;  // on a clip: a part of the picture, in shares of the frame
        return o;
      });
      return out;
    };
    return tl;
  }

  // the volume of the sound and clip views, kept on this PC (by the Studio, for every project, and in this browser to start
  // with) so the next file and the next visit play as loud. level is
  // from 0 (silent) to 1 (full); muted keeps the level, so the sound comes back where it was; back is the level the
  // slider was last left at above silent, for the speaker to bring back after it was taken to 0. With no storage it plays at full
  const VOL = (() => {
    const v = { level: 1, muted: false, back: 1 }, subs = new Set(), KEY = 'nocstudio.volume';
    const take = (o) => {
      if (!o || typeof o !== 'object') return;
      const n = (x) => (typeof x === 'number' && isFinite(x) ? Math.min(1, Math.max(0, x)) : null);
      if (n(o.level) !== null) v.level = n(o.level);
      v.muted = o.muted === true;
      v.back = n(o.back) || (v.level > 0 ? v.level : 1);
    };
    try { take(JSON.parse(localStorage.getItem(KEY) || 'null')); } catch (e) { /* no storage: full volume */ }
    const tell = () => subs.forEach((fn) => fn());
    window.addEventListener('storage', (e) => { if (e.key === KEY) { try { take(JSON.parse(e.newValue || 'null')); } catch (x) { /* as above */ } tell(); } });  // another tab moved it
    const save = () => { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* as above */ } tell(); };
    const keep = () => API.ui({ volume: { level: v.level, muted: v.muted, back: v.back } }).catch(() => {});  // once it is let go, not on every step of a drag
    return {
      v,
      // the level the Studio kept, which every project and address on this PC shares
      use(o) { take(o); save(); },
      on(fn) { subs.add(fn); return () => subs.delete(fn); },
      // the slider: a level from 0 to 1; moving it while muted brings the sound back at that level
      level(x) { v.level = Math.min(1, Math.max(0, +x || 0)); v.muted = false; save(); },
      // the slider let go: where it was left, or where it was taken from when it was taken down to silent
      settle(from) { if (v.level > 0) v.back = v.level; else if (from > 0) v.back = from; save(); keep(); },
      // the speaker: mute, or bring the sound back at the level before
      toggle() { if (v.muted || v.level <= 0) { v.muted = false; if (v.level <= 0) v.level = v.back || 1; } else v.muted = true; save(); keep(); },
      silent: () => v.muted || v.level <= 0,
    };
  })();
  const ICON_VOL = '<svg viewBox="0 0 16 14" aria-hidden="true"><path d="M1.5 4.5h3l4-3.5v12l-4-3.5h-3z"/><path class="w1" d="M10.6 4.6a3.2 3.2 0 0 1 0 4.8"/><path class="w2" d="M12.4 2.6a6 6 0 0 1 0 8.8"/><path class="x" d="M10.5 4.5l4.5 5M15 4.5l-4.5 5"/></svg>';

  // playing a sound or a clip: play and hold that keep the place, seek, speed, loop all of it, or loop one stretch by
  // watching the time each frame. `el` is an <audio> or a <video>; opts.length() gives the length when the page knows it
  // better; opts.snap(t) moves a time it is sent to (a clip goes to the middle of a frame). It plays at the kept volume
  // (VOL), and volumeBar() draws the speaker and slider for the play bar
  function transport(el, opts) {
    opts = opts || {};
    const subs = [], me = { stop: () => el.pause() }, bars = [];
    const loud = () => { el.volume = VOL.v.level; el.muted = VOL.v.muted; bars.forEach((fn) => fn()); };  // a new file on the same element keeps both
    const quiet = VOL.on(loud); loud();
    let raf = 0, loop = null;  // loop: { id, range() -> [from, to] in seconds, or null once the mark is gone }
    const tell = (what) => subs.slice().forEach((fn) => fn(what));
    const range = () => { const r = loop && loop.range(); if (loop && !r) { loop = null; tell('state'); } return r || null; };
    const tick = () => {
      raf = 0;
      const r = range();
      if (r && (el.currentTime >= r[1] || el.currentTime < r[0] - 0.05)) el.currentTime = r[0];
      tell('time');
      if (!el.paused && !el.ended) raf = requestAnimationFrame(tick);
    };
    const tp = {
      el,
      on(fn) { subs.push(fn); },  // fn('time') each frame while it plays and on a seek, fn('state') on play, hold and loop, fn('length')
      length: () => (opts.length && opts.length()) || (isFinite(el.duration) ? el.duration : 0) || 0,
      time: () => el.currentTime || 0,
      playing: () => !el.paused && !el.ended,
      looping: () => (loop ? loop.id : null),
      play() {
        for (const o of players) if (o !== me) o.stop();  // one sound at a time
        seq.token++;
        const d = tp.length(), r = range();
        if (r && (el.currentTime < r[0] - 0.05 || el.currentTime >= r[1])) el.currentTime = r[0];
        else if (!r && d && el.currentTime >= d - 0.01) el.currentTime = 0;
        return Promise.resolve(el.play()).catch(() => toast('The browser would not play this file'));
      },
      hold() { el.pause(); },
      toggle() { if (tp.playing()) tp.hold(); else tp.play(); },
      // go to a time; going outside a looping stretch ends its loop, unless `stay` is set
      seek(t, stay) {
        const d = tp.length(), r = range();
        t = Math.min(d || Math.max(0, t), Math.max(0, t));
        if (opts.snap) t = opts.snap(t);  // a clip goes to the middle of a frame, so the frame shown is the frame named
        if (r && !stay && (t < r[0] - 1e-3 || t > r[1] + 1e-3)) { loop = null; tell('state'); }
        try { if (Math.abs((el.currentTime || 0) - t) > 1e-4) el.currentTime = t; } catch (e) { /* not loaded yet */ }  // going where it already is can end a clip on its last frame
        tell('time');
      },
      rate(r) { el.defaultPlaybackRate = el.playbackRate = r || 1; },  // an <audio> or <video> keeps its pitch when slowed; a file loaded later starts at the default speed, so that is set as well
      loopAll(on) { el.loop = !!on; },
      // play one stretch round and round: id names it, range() says where it is now (it may be dragged meanwhile)
      loopSpan(id, rangeFn) { loop = id ? { id, range: rangeFn } : null; tell('state'); },
      // the speaker that mutes and brings the sound back, and the slider from silent to full, for the play bar
      volumeBar() {
        const btn = h('button', { class: 'btn small vol', type: 'button', html: ICON_VOL, onclick: (e) => { e.currentTarget.blur(); VOL.toggle(); } });
        let from = VOL.v.level, held = false;  // the level when the slider was taken hold of, by the pointer or by the keys
        const take = () => { from = VOL.v.muted ? 0 : VOL.v.level; };
        const bar = h('input', { type: 'range', class: 'volume', min: 0, max: 100, step: 1, 'aria-label': 'Volume', oninput: () => VOL.level(bar.value / 100), onchange: () => VOL.settle(from),
          onpointerdown: () => { held = true; take(); window.addEventListener('pointerup', letGo, { once: true }); }, onfocus: () => { if (!held) take(); },
          onkeydown: (e) => { if (e.key === ' ') { e.preventDefault(); bar.blur(); if (!e.repeat) tp.toggle(); } } });  // Space on the slider plays, and the keys go back to the view
        function letGo() { held = false; bar.blur(); }  // let go of the slider, here or past its end, and Space plays again, as after a button
        const show = () => {
          const v = VOL.v, off = VOL.silent(), pct = Math.round(100 * v.level);
          bar.value = String(v.muted ? 0 : pct);
          btn.classList.toggle('off', off); btn.classList.toggle('low', !off && v.level < 0.5);
          btn.setAttribute('aria-pressed', String(v.muted));
          const say = off ? 'Bring the sound back' + (v.muted ? ' at ' + pct + '%' : '') : 'Mute; the level is kept';
          btn.title = say; btn.setAttribute('aria-label', say);
          bar.title = 'Volume ' + (v.muted ? 'muted, kept at ' + pct + '%' : pct + '%');
        };
        bars.push(show); show();
        return h('span', { class: 'grp volbar' }, btn, bar);
      },
      destroy() { cancelAnimationFrame(raf); raf = 0; loop = null; el.pause(); players.delete(me); subs.length = 0; quiet(); bars.length = 0; },
    };
    el.addEventListener('play', () => { tell('state'); if (!raf) raf = requestAnimationFrame(tick); });
    el.addEventListener('pause', () => tell('state'));
    el.addEventListener('ended', () => { const r = range(); if (r) { el.currentTime = r[0]; el.play().catch(() => {}); } else tell('state'); });
    el.addEventListener('seeked', () => tell('time'));
    el.addEventListener('loadedmetadata', () => tell('length'));
    el.addEventListener('durationchange', () => tell('length'));
    players.add(me);
    return tp;
  }

  // the list beside the media: every mark in time order with its number, colour, time, kind, its own note, and
  // what Claude is told about where it is. opts: editable(), when(span) -> text, goto(span), loop(span), looping() -> id,
  // none() -> the line shown while there are no marks
  function spanList(tl, opts) {
    const box = h('div', { class: 'timemarks' }), rows = new Map();
    const none = h('p', { class: 'hint' });
    function make(id) {
      const get = () => tl.get(id);
      const num = h('span', { class: 'num' });
      const sw = h('button', { class: 'swatch', type: 'button', title: 'Change its colour', 'aria-label': 'Change its colour', onclick: () => {
        const s = get(); if (!s || !opts.editable()) return;
        tl.set(s, { c: MARK[(MARK.findIndex(([c]) => c === s.c) + 1) % MARK.length][0] });
      } });
      const when = h('button', { class: 'when', type: 'button', title: 'Go to it', onclick: () => { const s = get(); if (s) { tl.choose(s); opts.goto(s); } } });
      const tags = TAGS.map(([tag, label]) => h('button', { class: 'btn small', type: 'button', 'data-tag': tag,
        title: { change: 'This part must change', cut: 'This stretch goes', keep: 'This part must stay as it is' }[tag],
        onclick: () => { const s = get(); if (s && opts.editable() && s.tag !== tag) tl.set(s, { tag }); } }, label));
      const play = h('button', { class: 'play', type: 'button', 'aria-label': 'Play it round and round', title: 'Play it round and round', html: ICON_PLAY, onclick: () => { const s = get(); if (s) { tl.choose(s); opts.loop(s); } } });
      const del = h('button', { class: 'btn small', type: 'button', title: 'Take this mark away (Delete)', 'aria-label': 'Take this mark away', onclick: () => { const s = get(); if (s && opts.editable()) tl.remove(s); } }, '×');
      const note = h('textarea', { class: 'field', rows: 1, placeholder: 'What about this part', 'aria-label': 'Note for this mark',
        oninput: () => { const s = get(); if (s) { s.note = note.value; tl.changed('notes'); } },
        onfocus: () => tl.choose(get()),
        onkeydown: (e) => { if (e.key === 'Escape') { note.blur(); e.preventDefault(); e.stopPropagation(); } } });  // Esc leaves the box; the next one closes the closer look
      const told = h('div', { class: 'told', title: 'What Claude is told about where this mark is' });
      const el = h('div', { class: 'timemark', 'data-id': id }, h('div', { class: 'head' }, play, num, sw, when, del), h('div', { class: 'tags' }, tags), note, told);
      return { el, num, sw, when, tags, play, del, note, told };
    }
    function draw(what) {
      const list = tl.sorted(), can = opts.editable(), looping = opts.looping ? opts.looping() : null;
      for (const [id, r] of rows) if (!tl.get(id)) { r.el.remove(); rows.delete(id); }
      list.forEach((s, i) => {
        let r = rows.get(s.id);
        if (!r) { r = make(s.id); rows.set(s.id, r); }
        r.num.textContent = String(i + 1);
        r.el.style.setProperty('--sw', MARK_HEX[s.c] || MARK_HEX.red); r.sw.style.setProperty('--sw', MARK_HEX[s.c] || MARK_HEX.red);
        r.when.textContent = opts.when(s);
        r.tags.forEach((b) => { const on = b.dataset.tag === s.tag; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); b.disabled = !can; });
        r.sw.disabled = r.del.disabled = r.note.disabled = !can; r.del.hidden = !can;
        if (document.activeElement !== r.note && r.note.value !== (s.note || '')) r.note.value = s.note || '';
        if (what !== 'moved') r.told.textContent = tl.where(s);  // measured once the mark is let go, not at every step of a drag
        r.el.classList.toggle('on', s.id === tl.chosen);
        r.play.classList.toggle('on', s.id === looping); r.play.innerHTML = s.id === looping ? ICON_STOP : ICON_PLAY;
        if (box.children[i] !== r.el) box.insertBefore(r.el, box.children[i] || null);
      });
      if (!list.length) { none.textContent = opts.none ? opts.none() : 'No marks yet.'; box.append(none); } else none.remove();
      if ((what === 'chosen' || what === 'marks') && rows.get(tl.chosen)) rows.get(tl.chosen).el.scrollIntoView({ block: 'nearest' });
    }
    tl.subs.push((what) => { if (what !== 'notes') draw(what); });
    draw();
    return { el: box, draw, focus(id) { const r = rows.get(id); if (r && !r.note.disabled) r.note.focus(); } };
  }

  // the tools over the media: drop a moment where the playhead is, undo, clear. can() is the view's own word on whether
  // its marks can be changed now, as for the keys and the lane; canClear() is asked for Clear all, which also works
  // while the marks are on another file than the one on screen
  function spanTools(tl, tp, can, canClear) {
    const act = (label, title, ok, fn) => h('button', { class: 'btn small', type: 'button', title, onclick: (e) => { e.currentTarget.blur(); if (ok()) fn(); } }, label);
    return h('div', { class: 'grp marktools' },
      act('Moment', 'Mark the moment the playhead is at (M)', can, () => tl.add(tp.time())),
      act('Undo', 'Undo the last change to the marks (Ctrl+Z)', can, () => { if (!tl.undo()) toast('Nothing to undo'); }),
      act('Clear all', 'Take every mark away', canClear || can, () => tl.clear()));
  }

  // the keys both views share: Space plays and holds, Home and End, M drops a moment, [ and ] step through the marks,
  // Enter writes the chosen mark's note, Delete takes it away, Ctrl+Z undoes. It answers true when the key was its own.
  // opts: editable(), note(id) focuses a mark's note box, more(e, key) for a view's own keys
  function spanKeys(tl, tp, opts) {
    return (e) => {
      const tag = (e.target || {}).tagName || '';
      if (/^(TEXTAREA|INPUT|SELECT)$/.test(tag)) return false;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key, can = opts.editable();
      const mine = () => { if (tag === 'BUTTON') e.target.blur(); e.preventDefault(); return true; };  // a button in focus must not take the key as a click
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && key === 'z') { if (can && !tl.undo()) toast('Nothing to undo'); return mine(); }
      if (e.ctrlKey || e.metaKey || e.altKey) return false;
      if (opts.more && opts.more(e, key)) return mine();
      if (key === ' ') { if (!e.repeat) tp.toggle(); return mine(); }  // a key held down plays or marks once
      if (key === 'Home') { tp.seek(0); return mine(); }
      if (key === 'End') { tp.seek(tp.length()); return mine(); }
      if (key === 'm') { if (can && !e.repeat) tl.add(tp.time()); return mine(); }
      if (key === '[' || key === ']') { const s = tl.beside(key === ']' ? 1 : -1, tp.time()); if (s) { tl.choose(s); tp.seek(s.t0); } return mine(); }
      if (key === 'Delete' || key === 'Backspace') { const s = tl.get(tl.chosen); if (s && can) tl.remove(s); return mine(); }
      if (key === 'Enter' && tl.chosen && opts.note) { opts.note(tl.chosen); return mine(); }
      return false;
    };
  }

  // dragging on a lane of marks: across empty time makes a stretch, a mark's edge stretches it, its middle moves it
  // (Shift makes a new one there instead), a click moves the playhead, a double click drops a moment.
  // map.time(clientX) -> seconds and map.x(seconds) -> clientX say where the lane's times are on the screen.
  // opts: editable(), seek(t), drag(on) is told when a drag starts and ends, fixed(span) gives the words to say when
  // a mark's start must stay where it is (a clip's paint lies on its first frame): then only its end drags
  function spanLane(host, tl, map, opts) {
    let d = null;
    // what of which mark is under the pointer: the chosen mark first, then the shortest
    function hit(cx) {
      const list = tl.spans.slice().sort((a, b) => (b.id === tl.chosen) - (a.id === tl.chosen) || (a.t1 - a.t0) - (b.t1 - b.t0));
      for (const s of list) {
        const a = map.x(s.t0), b = map.x(s.t1);
        if (!(s.t1 > s.t0)) { if (Math.abs(cx - a) <= 7) return { s, part: 'move' }; continue; }
        const da = Math.abs(cx - a), db = Math.abs(cx - b);
        if (Math.min(da, db) <= 6) return { s, part: da <= db ? 'start' : 'end' };
        if (cx > a && cx < b) return { s, part: 'move' };
      }
      return null;
    }
    const down = (e) => {
      if (e.button !== 0 || d) return;
      host.setPointerCapture(e.pointerId);
      const at = opts.editable() && !e.shiftKey ? hit(e.clientX) : null;
      d = { id: e.pointerId, x: e.clientX, t: map.time(e.clientX), part: at ? at.part : 'new', span: at ? at.s.id : null, a: at ? at.s.t0 : 0, b: at ? at.s.t1 : 0, moved: false };
    };
    const move = (e) => {
      if (!d) { const at = opts.editable() ? hit(e.clientX) : null; host.style.cursor = at ? (at.part === 'move' ? 'grab' : 'ew-resize') : ''; return; }
      if (e.pointerId !== d.id || d.part === 'held') return;
      const t = map.time(e.clientX);
      if (!d.moved) {
        if (Math.abs(e.clientX - d.x) < 4 || !opts.editable()) return;
        const why = (d.part === 'start' || d.part === 'move') && opts.fixed ? opts.fixed(tl.get(d.span)) : '';
        if (why) { d.part = 'held'; toast(why); return; }  // said once; the press still ends as a click on the mark
        d.moved = true; if (opts.drag) opts.drag(true);
        if (d.part === 'new') { const s = tl.add(d.t, t); if (!s) { d = null; return; } d.span = s.id; d.a = d.b = tl.fit(d.t); d.part = 'end'; }
        else { tl.keep(); tl.choose(tl.get(d.span)); }
      }
      const s = tl.get(d.span); if (!s) return;
      if (d.part === 'start') tl.move(s, t, d.b);
      else if (d.part === 'end') tl.move(s, d.a, opts.fixed && opts.fixed(s) ? Math.max(d.a, t) : t);  // the end of a mark whose start is fixed does not cross it
      else { const len = d.b - d.a, top = (tl.length || Infinity) - len, a = Math.min(top, Math.max(0, d.a + t - d.t)); tl.move(s, a, a + len); }
    };
    const up = (e) => {
      if (!d || e.pointerId !== d.id) return;
      const was = d; d = null;
      if (was.moved) { if (opts.drag) opts.drag(false); tl.changed('marks'); return; }
      const at = was.part === 'held' ? { s: tl.get(was.span) } : hit(e.clientX);  // a mark that would not drag is chosen all the same
      tl.choose(at ? at.s : null); opts.seek(was.t);
    };
    const twice = (e) => { if (!opts.editable()) return; const at = hit(e.clientX); if (at && !(at.s.t1 > at.s.t0)) return; tl.add(map.time(e.clientX)); };
    host.addEventListener('pointerdown', down); host.addEventListener('pointermove', move);
    host.addEventListener('pointerup', up); host.addEventListener('pointercancel', up); host.addEventListener('dblclick', twice);
    return { hit, destroy() { host.removeEventListener('pointerdown', down); host.removeEventListener('pointermove', move); host.removeEventListener('pointerup', up); host.removeEventListener('pointercancel', up); host.removeEventListener('dblclick', twice); } };
  }

  // the marks drawn along a lane: a band for a stretch, a line for a moment, each with its number on a flag.
  // x(seconds) gives the place across the canvas; opts.scale makes it larger for a picture
  function paintSpans(ctx, tl, x, top, height, opts) {
    const k = (opts && opts.scale) || 1, fh = 16 * k;
    ctx.save(); ctx.textBaseline = 'middle'; ctx.font = '600 ' + (11 * k) + 'px system-ui, sans-serif';
    tl.sorted().forEach((s, i) => {
      const hex = MARK_HEX[s.c] || MARK_HEX.red, a = x(s.t0), b = x(s.t1), on = s.id === tl.chosen, lw = (on ? 3 : 2) * k;
      ctx.fillStyle = hex;
      if (s.t1 > s.t0) { ctx.globalAlpha = on ? 0.38 : 0.22; ctx.fillRect(a, top, Math.max(1, b - a), height); ctx.globalAlpha = 1; ctx.fillRect(b - lw / 2, top, lw, height); }
      ctx.fillRect(a - lw / 2, top, lw, height);
      const label = (i + 1) + (s.tag === 'change' ? '' : ' ' + s.tag), fw = ctx.measureText(label).width + 10 * k, fy = top + 2 * k + (i % 3) * (fh + 2 * k);
      ctx.fillRect(a, fy, fw, fh);
      if (on) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5 * k; ctx.strokeRect(a + 0.75 * k, fy + 0.75 * k, fw - 1.5 * k, fh - 1.5 * k); }
      ctx.fillStyle = '#111'; ctx.fillText(label, a + 5 * k, fy + fh / 2 + k);
    });
    ctx.restore();
  }

  // the bars that fall in a view, when there is a tempo: each with its number, and whether it gets a label
  function barsIn(v, tempo, w) {
    const bar = 60 / tempo.bpm * tempo.beats, px = bar / v.span * w, every = [1, 2, 4, 8, 16, 32, 64, 128].find((n) => n * px >= 46) || 256, out = [];
    for (let n = Math.max(0, Math.floor((v.t0 - tempo.first) / bar)); tempo.first + n * bar <= v.t0 + v.span + 1e-9 && out.length < 4000; n++) {
      const t = tempo.first + n * bar;
      if (t >= v.t0 - 1e-9 && (n % every === 0 || px >= 6)) out.push({ t, n: n + 1, named: n % every === 0 });
    }
    return out;
  }
  const RULER = 24, RULER_BARS = 20;  // the height of the seconds row, and of the bars row under it
  // the ruler over a timeline: seconds, and under them bars and beats when there is a tempo. v is { t0, span } in seconds
  function paintRuler(ctx, w, v, tempo, col) {
    const steps = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];
    const step = steps.find((s) => s / v.span * w >= 72) || 3600, places = step >= 1 ? 0 : step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3, minor = step / 5;
    const x = (t) => Math.round((t - v.t0) / v.span * w);
    const label = (t) => { const c = Math.round(t * 1000), s = (c % 60000) / 1000; return Math.floor(c / 60000) + ':' + s.toFixed(places).padStart(places ? places + 3 : 2, '0'); };
    ctx.save(); ctx.font = '11px system-ui, sans-serif'; ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = col.line; ctx.fillRect(0, RULER - 1, w, 1);
    for (let i = Math.ceil(v.t0 / minor - 1e-6); i * minor <= v.t0 + v.span + 1e-9; i++) {
      const major = i % 5 === 0, px = x(i * minor);
      ctx.fillStyle = col.line; ctx.fillRect(px, major ? 10 : 18, 1, major ? RULER - 10 : RULER - 18);
      if (major && px + 4 + ctx.measureText(label(i * minor)).width <= w) { ctx.fillStyle = col.text; ctx.fillText(label(i * minor), px + 4, 12); }
    }
    if (tempo) {
      const beat = 60 / tempo.bpm, beatPx = beat / v.span * w, bars = barsIn(v, tempo, w);
      ctx.fillStyle = col.line; ctx.fillRect(0, RULER + RULER_BARS - 1, w, 1);
      bars.forEach((b, i) => {
        ctx.fillStyle = b.named ? col.bar : col.line; ctx.fillRect(x(b.t), RULER + (b.named ? 2 : 10), 1, RULER_BARS - (b.named ? 2 : 10));
        if (b.named) ctx.fillText((bars.findIndex((o) => o.named) === i ? 'bar ' : '') + b.n, x(b.t) + 4, RULER + 14);
        if (beatPx >= 10) for (let j = 1; j < tempo.beats; j++) { ctx.fillStyle = col.line; ctx.fillRect(x(b.t + j * beat), RULER + 14, 1, RULER_BARS - 14); }
      });
    }
    ctx.restore();
  }

  // under a picture of marks on a timeline: each mark's number in its colour, its kind, when, and its note
  function spanLegend(top, tl, when) {
    const W = Math.max(top.width, 800), pad = 16, line = 20, list = tl.sorted();
    const meas = h('canvas').getContext('2d');
    const wrap = (text, width) => { const out = []; let cur = ''; for (const w of String(text).split(/\s+/)) { const t2 = cur ? cur + ' ' + w : w; if (meas.measureText(t2).width > width && cur) { out.push(cur); cur = w; } else cur = t2; } if (cur) out.push(cur); return out.length ? out : ['']; };
    meas.font = '600 15px system-ui, sans-serif';
    const heads = list.map((s) => tagWord(s) + '  ' + when(s)), headW = Math.min(W / 2, Math.max(0, ...heads.map((t) => meas.measureText(t).width)));
    const noteX = pad + 44 + headW + 18;
    meas.font = '15px system-ui, sans-serif';
    const rows = list.map((s, i) => ({ s, head: heads[i], lines: wrap(s.note && s.note.trim() ? '“' + s.note.trim() + '”' : '(no note)', W - noteX - pad) }));
    const legendH = rows.length ? pad + rows.reduce((n, r) => n + r.lines.length * line + 8, 0) + pad : 0;
    const out = h('canvas', { width: W, height: top.height + legendH }), ctx = out.getContext('2d');
    ctx.fillStyle = '#111114'; ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(top, Math.round((W - top.width) / 2), 0);
    let y = top.height + pad;
    rows.forEach((r, i) => {
      ctx.fillStyle = MARK_HEX[r.s.c] || MARK_HEX.red; ctx.fillRect(pad, y + 1, 34, 20);
      ctx.fillStyle = '#111'; ctx.font = '600 14px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.fillText(String(i + 1), pad + 17, y + 16); ctx.textAlign = 'left';
      ctx.fillStyle = '#fff'; ctx.font = '600 15px system-ui, sans-serif'; ctx.fillText(r.head, pad + 44, y + 16, headW);
      ctx.font = '15px system-ui, sans-serif'; ctx.fillStyle = '#e6e6ea';
      r.lines.forEach((l, j) => ctx.fillText(l, noteX, y + 16 + j * line));
      y += r.lines.length * line + 8;
    });
    return new Promise((ok) => out.toBlob((b) => ok(b), 'image/png'));
  }

  // a mark's play button: play its stretch round and round, or stop when it is the one playing
  const spanLoop = (tl, tp) => (s) => {
    if (tp.looping() === s.id && tp.playing()) { tp.loopSpan(null); tp.hold(); return; }
    tp.loopSpan(s.id, () => { const x = tl.get(s.id); return x ? spanRange(x, tp.length()) : null; });
    tp.seek(spanRange(s, tp.length())[0], true); tp.play();
  };
  // a canvas of a timeline made ready to draw on: sized to its place on the page, sharp on any screen, and wiped
  function laneCanvas(c) {
    const dpr = Math.min(2, (window.devicePixelRatio || 1) * cz(c)), w = c.clientWidth, hh = c.clientHeight;
    if (!w || !hh) return null;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(hh * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(hh * dpr); }
    const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, hh);
    return { ctx, w, h: hh, cols: c.width };
  }
  // the colours a timeline is drawn in, read from the theme where `el` stands
  function laneColours(el) { const css = getComputedStyle(el), get = (n, d) => css.getPropertyValue(n).trim() || d; return { text: get('--muted', '#b3b3bd'), line: get('--line', '#2f2f37'), bar: get('--fg', '#f1f1f4'), wave: get('--faint', '#7d7d88') }; }

  // ----------------------------------------------------- a sound, to mark it
  const WAVE_BLOCK = 256, FFT_N = 2048;
  const BANDS = [[60, 'under 60 Hz'], [250, 'between 60 and 250 Hz'], [2000, 'between 250 Hz and 2 kHz'], [6000, 'between 2 and 6 kHz'], [Infinity, 'over 6 kHz']];
  const dB = (x) => Math.round((x > 0 ? Math.max(-120, 20 * Math.log10(x)) : -120) * 10) / 10;
  const hertz = (f) => (f >= 1000 ? String(Math.round(f / 100) / 10) + ' kHz' : Math.round(f) + ' Hz');
  let fftTab = null;
  // the power at each frequency, averaged over windows of 2048 samples across a stretch (at most 400 of them)
  function spectrum(mono, i0, i1) {
    const N = FFT_N, half = N / 2;
    if (!fftTab) {
      const rev = new Uint16Array(N), cos = new Float32Array(half), sin = new Float32Array(half), hann = new Float32Array(N);
      for (let i = 0, bits = Math.log2(N); i < N; i++) { let r = 0; for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b); rev[i] = r; hann[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (N - 1)); }
      for (let i = 0; i < half; i++) { cos[i] = Math.cos(2 * Math.PI * i / N); sin[i] = Math.sin(2 * Math.PI * i / N); }
      fftTab = { rev, cos, sin, hann };
    }
    const { rev, cos, sin, hann } = fftTab, re = new Float32Array(N), im = new Float32Array(N), pow = new Float64Array(half);
    const len = i1 - i0, count = len <= N ? 1 : Math.min(400, Math.floor((len - N) / half) + 1), stride = count > 1 ? (len - N) / (count - 1) : 0;
    for (let w = 0; w < count; w++) {
      const at = i0 + Math.floor(w * stride);
      for (let k = 0; k < N; k++) { const j = at + k; re[rev[k]] = j < i1 ? mono[j] * hann[k] : 0; }
      im.fill(0);
      for (let size = 2; size <= N; size <<= 1) {
        const h2 = size >> 1, step = N / size;
        for (let s = 0; s < N; s += size) for (let k = 0; k < h2; k++) {
          const c = cos[k * step], sn = sin[k * step], a = s + k, b = a + h2;
          const tr = re[b] * c + im[b] * sn, ti = im[b] * c - re[b] * sn;
          re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
        }
      }
      for (let k = 0; k < half; k++) pow[k] += re[k] * re[k] + im[k] * im[k];
    }
    return pow;
  }
  // what the page can measure between two samples of a sound: peak and RMS in dBFS, whether it clips, the share of its
  // energy in five bands and its spectral centre. All channels mixed; nothing is guessed
  function soundFacts(snd, i0, i1) {
    i0 = Math.max(0, Math.min(snd.n, i0)); i1 = Math.max(i0, Math.min(snd.n, i1));
    let peak = 0, sum = 0, clips = false;
    for (let i = i0; i < i1; i++) { const x = snd.mono[i], a = x < 0 ? -x : x; if (a > peak) peak = a; sum += x * x; }
    for (const ch of snd.chans) { let run = 0; for (let i = i0; i < i1 && !clips; i++) { run = (ch[i] >= 0.999 || ch[i] <= -0.999) ? run + 1 : 0; if (run >= 3) clips = true; } }
    const out = { peak: dB(peak), rms: dB(i1 > i0 ? Math.sqrt(sum / (i1 - i0)) : 0), clips, rough: (i1 - i0) / snd.rate < 0.1 };
    if (peak > 0) {
      const p = spectrum(snd.mono, i0, i1), per = snd.rate / FFT_N, bands = BANDS.map(() => 0);
      let all = 0, weight = 0, band = 0;
      for (let k = 1; k < p.length; k++) { const f = k * per; while (f >= BANDS[band][0]) band++; all += p[k]; weight += f * p[k]; bands[band] += p[k]; }
      if (all > 0) { out.bands = bands.map((x) => Math.round(1000 * x / all) / 10); out.centre = Math.round(weight / all); }
    }
    return out;
  }
  // read a sound file into samples the page can draw and measure: any kind the browser plays, not only 16-bit WAV
  async function decodeSound(url) {
    const buf = await API.bytes(url);
    let rate = 44100, own = false;  // a WAV is read at its own rate, so its samples are measured as they are; `own` says the rate is the file's
    try {
      const dv = new DataView(buf);
      if (dv.byteLength > 44 && dv.getUint32(0, false) === 0x52494646) for (let pos = 12; pos + 16 <= dv.byteLength;) {
        const id = dv.getUint32(pos, false), size = dv.getUint32(pos + 4, true);
        if (id === 0x666d7420) { rate = dv.getUint32(pos + 12, true); own = true; break; }
        pos += 8 + size + (size % 2);
      }
    } catch (e) { /* not a WAV */ }
    if (!(rate >= 8000 && rate <= 96000)) { rate = 44100; own = false; }
    const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Ctx) throw new Error('this browser cannot read a sound into samples');
    const ab = await new Ctx(1, 1, rate).decodeAudioData(buf), n = ab.length, chans = [];
    for (let c = 0; c < ab.numberOfChannels; c++) chans.push(ab.getChannelData(c));
    let mono = chans[0];
    if (chans.length > 1) { mono = new Float32Array(n); for (const ch of chans) for (let i = 0; i < n; i++) mono[i] += ch[i] / chans.length; }
    // the smallest and the largest sample in each block of 256, worked out once: a long sound is drawn from these
    const nb = Math.ceil(n / WAVE_BLOCK), lo = new Float32Array(nb), hi = new Float32Array(nb);
    let top = 0;
    for (let b = 0; b < nb; b++) {
      let a = 1, z = -1;
      for (let i = b * WAVE_BLOCK, end = Math.min(n, i + WAVE_BLOCK); i < end; i++) { const x = mono[i]; if (x < a) a = x; if (x > z) z = x; }
      lo[b] = a; hi[b] = z; top = Math.max(top, -a, z);
    }
    const snd = { rate: ab.sampleRate, own: own && ab.sampleRate === rate, n, seconds: n / ab.sampleRate, channels: chans.length, chans, mono, lo, hi, top };
    snd.whole = soundFacts(snd, 0, n);
    return snd;
  }
  // a sound's wave between two times, one line a column from its smallest sample there to its largest; it is drawn
  // to fill the height (the numbers say how loud it is). cols is the count of columns across the width w
  function paintWave(ctx, snd, v, w, hgt, cols, colour) {
    const mid = hgt / 2, cw = w / cols;
    ctx.save(); ctx.fillStyle = ctx.strokeStyle = colour;
    if (!snd || !snd.top) { ctx.fillRect(0, mid - cw / 2, w, cw); ctx.restore(); return; }
    const amp = (hgt / 2 - 2) / snd.top, per = v.span * snd.rate / cols;
    if (per < 1) {  // closer than a sample a column: a line through the samples themselves
      const i0 = Math.max(0, Math.floor(v.t0 * snd.rate)), i1 = Math.min(snd.n - 1, Math.ceil((v.t0 + v.span) * snd.rate));
      ctx.lineWidth = Math.max(1, 1.5 * cw); ctx.beginPath();
      for (let i = i0; i <= i1; i++) { const px = (i / snd.rate - v.t0) / v.span * w, py = mid - snd.mono[i] * amp; if (i === i0) ctx.moveTo(px, py); else ctx.lineTo(px, py); }
      ctx.stroke(); ctx.restore(); return;
    }
    for (let c = 0; c < cols; c++) {
      let i0 = Math.floor((v.t0 + c / cols * v.span) * snd.rate), i1 = Math.floor((v.t0 + (c + 1) / cols * v.span) * snd.rate);
      if (i1 <= i0) i1 = i0 + 1;
      if (i0 >= snd.n || i1 <= 0) continue;
      i0 = Math.max(0, i0); i1 = Math.min(snd.n, i1);
      let a = 1, z = -1;
      if (i1 - i0 >= 2 * WAVE_BLOCK) for (let k = Math.floor(i0 / WAVE_BLOCK), end = Math.ceil(i1 / WAVE_BLOCK); k < end; k++) { if (snd.lo[k] < a) a = snd.lo[k]; if (snd.hi[k] > z) z = snd.hi[k]; }
      else for (let i = i0; i < i1; i++) { const x = snd.mono[i]; if (x < a) a = x; if (x > z) z = x; }
      ctx.fillRect(c * cw, mid - z * amp, cw, Math.max(cw, (z - a) * amp));
    }
    ctx.restore();
  }
  // the sentence Claude reads for one mark on a sound: when, the bar and beat, and what the page measured there
  function soundWhere(s, tl, snd) {
    const moment = !(s.t1 > s.t0), parts = [spanWhen(s)];
    if (!moment) parts[0] = parts[0].replace(/^at /, '');
    if (tl.tempo) parts.push(barSpan(tl.tempo, s));
    if (moment || !snd) return { where: parts.join('; ') };
    const f = soundFacts(snd, Math.round(s.t0 * snd.rate), Math.round(s.t1 * snd.rate)), w = snd.whole;
    const facts = { peak: f.peak, rms: f.rms, whole_peak: w.peak, whole_rms: w.rms, clips: f.clips, rough: f.rough };
    if (f.peak <= -120) parts.push('silent');
    else {
      const d = Math.round((f.rms - w.rms) * 10) / 10;
      parts.push('peak ' + f.peak.toFixed(1) + ' dBFS, RMS ' + f.rms.toFixed(1) + ' dBFS, ' + (Math.abs(d) < 0.5 ? 'as loud as the whole sound' : Math.abs(d).toFixed(1) + ' dB ' + (d > 0 ? 'louder' : 'quieter') + ' than the whole sound'));
      if (f.clips) parts.push('it clips');
      if (f.bands) {
        const i = f.bands.indexOf(Math.max(...f.bands));
        parts.push((f.bands[i] >= 50 ? 'most of its energy is ' : 'the largest share of its energy is ') + BANDS[i][1] + ' (' + Math.round(f.bands[i]) + '%' + (w.bands ? ', the whole sound ' + Math.round(w.bands[i]) + '%' : '') + ')');
        parts.push('spectral centre ' + hertz(f.centre) + (w.centre ? ' (the whole sound ' + hertz(w.centre) + ')' : ''));
        Object.assign(facts, { bands: f.bands, centre: f.centre }, w.bands ? { whole_bands: w.bands, whole_centre: w.centre } : {});
      }
    }
    if (f.rough) parts.push('too short to measure well');
    return { where: parts.join('; '), facts };
  }

  // a sound, large: its wave under a ruler, zoom in time, a playhead, the marks along it and the list of them beside it.
  // files: [{ url, label, name }]; opts.tempo counts bars. attach(marks, { editable }) puts a set of marks on it
  function soundView(files, opts) {
    opts = opts || {};
    const a = new Audio(); a.preload = 'auto';
    let cur = null, snd = null, tl = null, list = null, lane = null, alive = true, editable = () => false, hover = null, busy = false, thin = false, pan = null, grab = null, flush = null;
    const v = { t0: 0, span: 1 };  // the stretch of time on screen: where it starts, and how many seconds it shows
    const tp = transport(a, { length: () => (snd ? snd.seconds : 0) });
    const len = () => tp.length(), inside = () => tp.time() >= v.t0 - 1e-6 && tp.time() <= v.t0 + v.span + 1e-6;
    let seen = true;  // whether the playhead was on screen when last looked at
    const ruler = h('canvas', { class: 'timeruler' + (opts.tempo ? ' bars' : '') }), wave = h('canvas'), over = h('canvas');
    const strip = h('div', { class: 'timelane' }, wave, over), head = h('div', { class: 'timehead', hidden: true });
    const box = h('div', { class: 'timewave' }, ruler, strip, head);
    const thumb = h('div', { class: 'thumb' }), ticks = h('div', {}), scroll = h('div', { class: 'timescroll', title: 'Drag to move along the sound' }, ticks, thumb);
    const playBtn = h('button', { class: 'btn small', type: 'button', title: 'Play or hold (Space)', onclick: (e) => { e.currentTarget.blur(); tp.toggle(); } }, 'Play');
    const time = h('span', { class: 't' }), status = h('span', { class: 'hint' });
    const rates = [[1, 'Full speed'], [0.5, 'Half']].map(([r, label]) => h('button', { class: 'btn small' + (S.opts.rate === r ? ' on' : ''), type: 'button', 'data-rate': r,
      title: r === 1 ? 'Play at its own speed' : 'Play at half speed; the pitch stays', onclick: (e) => { e.currentTarget.blur(); S.opts.rate = r; showOpts(); tp.rate(r); } }, label));
    const loopBtn = h('button', { class: 'btn small' + (S.opts.loop ? ' on' : ''), type: 'button', 'data-opt': 'loop', 'aria-pressed': String(!!S.opts.loop), title: 'Play the whole sound round and round, to hear its seam',
      onclick: (e) => { e.currentTarget.blur(); S.opts.loop = !S.opts.loop; showOpts(); tp.loopAll(S.opts.loop); } }, 'Loop');
    const zoomBtn = (label, title, fn) => h('button', { class: 'btn small', type: 'button', title, 'aria-label': title, onclick: (e) => { e.currentTarget.blur(); fn(); } }, label);
    const pick = files.length > 1 ? h('div', { class: 'timefiles' }, files.map((f) => h('button', { class: 'btn small', type: 'button', onclick: (e) => { e.currentTarget.blur(); if (f !== cur) load(f); } }, f.label || f.name))) : null;
    const side = h('div', { class: 'timeside' });
    const el = h('div', { class: 'timeview' }, h('div', { class: 'timemain' }, pick, box, scroll,
      h('div', { class: 'timebar' }, playBtn, time, h('span', { class: 'grp' }, rates), loopBtn, tp.volumeBar(),
        h('span', { class: 'grp' }, zoomBtn('−', 'Show more time (-)', () => zoomAt(centre(), 1 / 1.6)), zoomBtn('+', 'Show less time, closer (+)', () => zoomAt(centre(), 1.6)), zoomBtn('Whole', 'Show the whole sound', () => setView(0, len()))),
        status)), side);
    const map = { time: (cx) => { const r = strip.getBoundingClientRect(); return v.t0 + (cx - r.left) / (r.width || 1) * v.span; },
      x: (t) => { const r = strip.getBoundingClientRect(); return r.left + (t - v.t0) / v.span * r.width; } };
    // whether the marks are on the file on screen: a candidate's marks sit on one of its files
    const mine = () => !!tl && (!tl.spans.length || !tl.file || tl.file === cur.name);
    const fit = laneCanvas, colours = () => laneColours(box);
    function drawBase() {
      const col = colours(), r = fit(ruler), w = fit(wave);
      if (r) paintRuler(r.ctx, r.w, v, opts.tempo, col);
      if (!w) return;
      if (opts.tempo) { w.ctx.fillStyle = col.line; for (const b of barsIn(v, opts.tempo, w.w)) if (b.named) w.ctx.fillRect(Math.round((b.t - v.t0) / v.span * w.w), 0, 1, w.h); }
      paintWave(w.ctx, snd, v, w.w, w.h, w.cols, col.wave);
    }
    function drawMarks() {
      const m = fit(over);
      if (m && tl && mine()) paintSpans(m.ctx, tl, (t) => (t - v.t0) / v.span * m.w, 0, m.h);
      const d = len() || 1;
      ticks.replaceChildren(...(tl && mine() ? tl.spans.map((s) => h('i', { style: '--sw:' + (MARK_HEX[s.c] || MARK_HEX.red) + ';left:' + (100 * s.t0 / d) + '%;width:' + (100 * (s.t1 - s.t0) / d) + '%' })) : []));
      thumb.style.left = (100 * v.t0 / d) + '%'; thumb.style.width = (100 * Math.min(1, v.span / d)) + '%';
    }
    function drawHead() {
      const t = tp.time(), d = len(), f = (t - v.t0) / v.span;
      head.hidden = !d || f < 0 || f > 1; head.style.left = (100 * f) + '%';
      playBtn.textContent = tp.playing() ? 'Hold' : 'Play';
      time.textContent = d ? clock(t) + ' / ' + clock(d) + (opts.tempo ? ' · ' + barText(opts.tempo, t) : '') : '';
    }
    const drawAll = () => { drawBase(); drawMarks(); drawHead(); };
    function setView(t0, span) {
      const d = len(); if (!d) return;
      v.span = Math.min(d, Math.max(Math.min(d, 0.01), span)); v.t0 = Math.min(d - v.span, Math.max(0, t0));
      seen = inside(); drawAll();
    }
    function zoomAt(t, k) { const span = Math.min(len(), Math.max(0.01, v.span / k)); setView(t - (t - v.t0) * span / v.span, span); }
    // what a zoom by key or button holds still: the pointer when it is over the wave, else the playhead, else the middle
    const centre = () => (hover !== null ? hover : (tp.time() >= v.t0 && tp.time() <= v.t0 + v.span) ? tp.time() : v.t0 + v.span / 2);
    function say() {
      const w = snd && snd.whole, n = tl && !mine() ? 'The marks are on ' + tl.file + '. Take them away to mark this file instead.' : '';
      // the rate is said only when it is the file's own: any sound but a WAV is read at 44.1 kHz whatever its rate
      status.textContent = n || (snd ? 'peak ' + w.peak.toFixed(1) + ' dBFS · RMS ' + w.rms.toFixed(1) + ' dBFS' + (snd.own ? ' · ' + (snd.rate / 1000) + ' kHz' : '') + (snd.channels > 1 ? ' · ' + snd.channels + ' channels, mixed' : '') + ' · the wave is drawn to its full height, however quiet the sound is'
        : busy ? 'Reading the sound' : cur ? 'The browser could not read this file to draw it. It may still play, and marks keep their times.' : '');
    }
    // the length is known: from the samples, or from the player when the file could not be read into samples
    function ready() {
      const d = len(); if (!d) return;
      if (tl && tl.spans.length && mine()) { tl.file = cur.name; tl.length = sec3(d); }  // with no marks yet, the first one made takes the file on screen (attach)
      setView(0, d); say();
      if (list) list.draw();
      if (snd && thin && tl && tl.spans.length && editable()) { thin = false; tl.stale(); tl.changed('marks'); }  // marks made before the samples were in get their numbers now
      if (flush && !busy && tl && tl.spans.length && mine()) flush();  // a picture that waited for this file to be read can be made now
    }
    function load(f) {
      if (cur && cur !== f && flush) flush();  // the picture of the marks is drawn from the file on screen: it is sent before that changes
      cur = f; snd = null; busy = true; tp.hold(); tp.loopSpan(null);
      a.src = rel(API.src(f.url)); v.t0 = 0; v.span = 1;
      if (pick) [...pick.children].forEach((b, i) => b.classList.toggle('on', files[i] === f));
      say(); drawAll();
      decodeSound(f.url).then((d) => { if (alive && cur === f) { snd = d; busy = false; ready(); } }, () => { if (alive && cur === f) { busy = false; say(); ready(); } });
    }
    tp.on((what) => {
      if (what === 'length') { if (!snd) ready(); return; }
      if (what === 'state' && list) list.draw();
      // the view follows the playhead when it runs off the edge or is sent somewhere; not when the user has moved the view away from it
      if (!inside() && (seen || !tp.playing()) && !pan && !grab && len()) setView(tp.playing() ? tp.time() - v.span * 0.04 : tp.time() - v.span / 2, v.span);
      else { if (inside()) seen = true; drawHead(); }
    });
    // the wheel zooms in time around the pointer; with Shift, or sideways, it moves along
    box.addEventListener('wheel', (e) => {
      e.preventDefault(); if (!len()) return;
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) setView(v.t0 + (e.deltaX || e.deltaY) / (box.clientWidth || 1) * v.span, v.span);
      else zoomAt(map.time(e.clientX), e.deltaY < 0 ? 1.25 : 1 / 1.25);
    }, { passive: false });
    strip.addEventListener('pointermove', (e) => { hover = map.time(e.clientX); });
    strip.addEventListener('pointerleave', () => { hover = null; });
    // the ruler: a click moves the playhead, a drag moves along the sound
    ruler.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; ruler.setPointerCapture(e.pointerId); pan = { x: e.clientX, t0: v.t0, moved: false }; });
    ruler.addEventListener('pointermove', (e) => { if (!pan) return; const dx = e.clientX - pan.x; if (!pan.moved && Math.abs(dx) < 4) return; pan.moved = true; setView(pan.t0 - dx / (ruler.getBoundingClientRect().width || 1) * v.span, v.span); });
    const panEnd = (e) => { if (pan && !pan.moved) tp.seek(map.time(e.clientX)); pan = null; };
    ruler.addEventListener('pointerup', panEnd); ruler.addEventListener('pointercancel', () => { pan = null; });
    // the bar under the wave: all of the sound, the part on screen as a handle to drag
    scroll.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !len()) return;
      scroll.setPointerCapture(e.pointerId);
      const r = scroll.getBoundingClientRect();
      if (e.target !== thumb) setView((e.clientX - r.left) / r.width * len() - v.span / 2, v.span);
      grab = { x: e.clientX, t0: v.t0 };
    });
    scroll.addEventListener('pointermove', (e) => { if (grab) setView(grab.t0 + (e.clientX - grab.x) / (scroll.getBoundingClientRect().width || 1) * len(), v.span); });
    const grabEnd = () => { grab = null; };
    scroll.addEventListener('pointerup', grabEnd); scroll.addEventListener('pointercancel', grabEnd);
    const ro = window.ResizeObserver ? new ResizeObserver(drawAll) : null;
    if (ro) ro.observe(box);
    // the picture Claude reads: the whole wave with every mark coloured and numbered on it, the ruler, and a legend
    function picture() {
      if (!alive) return Promise.resolve(undefined);  // thrown away: there is nothing to send
      if (!tl || !tl.spans.length) return Promise.resolve(null);
      if (!mine() || !len()) return Promise.resolve(undefined);  // the marks are on another file, or the length is not known: no picture of them can be made now
      if (!snd && busy) thin = true;  // drawn before the samples are in: it is made again with the wave once they are (ready)
      const W = 1600, pad = 16, title = 34, rh = RULER + (opts.tempo ? RULER_BARS : 0), wh = 300, w = W - 2 * pad, all = { t0: 0, span: len() };
      const top = h('canvas', { width: W, height: title + rh + wh + 8 }), ctx = top.getContext('2d');
      ctx.fillStyle = '#111114'; ctx.fillRect(0, 0, W, top.height);
      ctx.fillStyle = '#fff'; ctx.font = '600 15px system-ui, sans-serif';
      ctx.fillText([cur.name, clock(all.span) + ' long', opts.tempo ? opts.tempo.bpm + ' beats a minute, ' + opts.tempo.beats + ' to the bar' : '',
        snd ? 'peak ' + snd.whole.peak.toFixed(1) + ' dBFS, RMS ' + snd.whole.rms.toFixed(1) + ' dBFS (the wave is drawn to fill the height)' : 'the wave could not be drawn'].filter(Boolean).join(' · '), pad, 22, w);
      ctx.translate(pad, title);
      paintRuler(ctx, w, all, opts.tempo, { text: '#e6e6ea', line: '#55555e', bar: '#fff' });
      ctx.translate(0, rh);
      ctx.fillStyle = '#1b1b1f'; ctx.fillRect(0, 0, w, wh);
      if (opts.tempo) { ctx.fillStyle = '#34343c'; for (const b of barsIn(all, opts.tempo, w)) if (b.named) ctx.fillRect(Math.round(b.t / all.span * w), 0, 1, wh); }
      paintWave(ctx, snd, all, w, wh, w, '#9a9aa6');
      const was = tl.chosen; tl.chosen = null;
      paintSpans(ctx, tl, (t) => t / all.span * w, 0, wh, { scale: 1.25 });
      tl.chosen = was;
      return spanLegend(top, tl, (s) => spanWhen(s) + (opts.tempo ? '  ·  ' + barSpan(opts.tempo, s) : ''));
    }
    const api = {
      el, kind: 'sound', tp, keys: null, picture,
      can: () => editable(),  // whether the marks can be changed now: the batch takes them, they are on the file on screen, and its length is known
      shown: () => alive && mine() && !!len(),  // whether a picture of the marks can be made now
      hint: ['Drag across the wave: a stretch · ', h('kbd', {}, 'M'), ' or a double click: a moment · ', h('kbd', {}, 'Space'), ' plays · ', h('kbd', {}, '['), ' ', h('kbd', {}, ']'),
        ' step · ', h('kbd', {}, 'Enter'), ' its note · ', h('kbd', {}, 'Del'), ' takes it away · scroll or ', h('kbd', {}, '+'), ' ', h('kbd', {}, '−'), ' zooms'],
      // put a set of marks on the sound: they are drawn on the wave, listed beside it, and the keys work them
      attach(marks, o) {
        if (lane) lane.destroy();
        tl = marks; editable = () => !!(o.editable() && mine() && len()); flush = o.flush || null;  // o.flush() sends a picture of the marks that is waiting to go
        tl.tempo = opts.tempo || null;
        // the first mark of an empty set is made on the file on screen: the set takes that file and its length, and the
        // marks of another file can no longer be brought back by Undo, where they would be saved as this file's
        const add = tl.add;
        tl.add = (t0, t1, more) => {
          if (!tl.spans.length && cur) { if (tl.file && tl.file !== cur.name) { tl.past.length = 0; tl.stale(); } tl.file = cur.name; tl.length = sec3(len()); }
          return add(t0, t1, more);
        };
        tl.describe = (s) => { if (!snd) thin = true; return soundWhere(s, tl, snd); };
        list = spanList(tl, { editable, when: spanWhen, goto: (s) => tp.seek(s.t0), loop: spanLoop(tl, tp), looping: () => tp.looping(),
          none: () => (o.editable() ? 'No marks yet. Drag across the wave to mark a stretch, or press M to mark the moment the playhead is at.' : 'No marks on this sound.') });
        side.replaceChildren(list.el);
        lane = spanLane(strip, tl, map, { editable, seek: (t) => tp.seek(t) });
        tl.subs.push((what) => {
          if (what === 'marks' && tl.spans.length && !mine()) { const on = files.find((f) => f.name === tl.file); if (on) load(on); }  // Undo brought back marks made on another file: the view goes to that file
          if (what !== 'notes') drawMarks();
          if (what === 'marks') say();
        });
        api.keys = spanKeys(tl, tp, { editable, note: (id) => list.focus(id),
          more: (e, key) => { if (key === '+' || key === '=') { zoomAt(centre(), 1.6); return true; } if (key === '-' || key === '_') { zoomAt(centre(), 1 / 1.6); return true; } return false; } });
        const on = tl.spans.length && files.find((f) => f.name === tl.file);
        if (on && on !== cur) load(on); else if (len()) ready(); else say();
      },
      set() { tp.rate(S.opts.rate === 0.5 ? 0.5 : 1); tp.loopAll(S.opts.loop); },
      destroy() { alive = false; if (ro) ro.disconnect(); if (lane) lane.destroy(); tp.destroy(); a.removeAttribute('src'); snd = null; },
    };
    api.set(); load(files[0]);
    return api;
  }

  // ------------------------------------------------------ a clip, to mark it
  const CLIP_RATES = [10, 12, 12.5, 15, 20, 23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 90, 100, 120];  // the usual frames a second
  const CLIP_ROWS = 12;  // the marks that get a row on the sheet and a picture of their own
  const CLIP_EDGE = 1920;  // the long side of a frame kept as a picture, at most
  const CLIP_KEPT = 24e6;  // the pixels of large frames kept at one time; the last 400 small copies are kept beside them

  // a second copy of a clip, never seen, that hands out its frames as pictures, so the clip on screen is never moved.
  // A frame is asked for by a time in the middle of it: the copy goes there, waits until that frame is the one shown,
  // and draws it. The asking waits in a queue, one frame at a time, and a frame once drawn is kept
  function clipFrames(src) {
    const v = h('video', { src, playsinline: true, preload: 'auto' });
    v.muted = true;
    const full = new Map(), small = new Map();
    let queue = Promise.resolve(), alive = true, at = null, kept = 0;
    const ready = new Promise((ok) => {
      if (v.readyState >= 2) { ok(true); return; }
      v.addEventListener('loadeddata', () => ok(true), { once: true }); v.addEventListener('error', () => ok(false), { once: true });
      setTimeout(() => ok(v.readyState >= 2), 20000);
    });
    // go to a time and wait until its frame is shown: the seek has ended, and a frame has come up since it was asked.
    // `near` is how far, in seconds, that frame's own time may be from the time asked for
    const go = (t, near) => new Promise((ok) => {
      let seeked = false, shown = !v.requestVideoFrameCallback, late = 0;
      const cap = setTimeout(end, 3000);
      function end() { clearTimeout(cap); clearTimeout(late); v.removeEventListener('seeked', onSeeked); ok(); }
      function onSeeked() { seeked = true; if (shown) end(); else late = setTimeout(end, 300); }
      function onFrame(now, meta) {
        if (near && Math.abs(meta.mediaTime - t) > near) { v.requestVideoFrameCallback(onFrame); return; }  // a frame from before, still coming up
        shown = true; if (seeked) end();
      }
      if (!shown) v.requestVideoFrameCallback(onFrame);
      v.addEventListener('seeked', onSeeked);
      try { v.currentTime = t; } catch (e) { end(); }
    });
    // the frame the copy shows now, drawn at the clip's own size (1920 on its long side at most), and a small copy of it
    function still(key) {
      const k = Math.min(1, CLIP_EDGE / Math.max(v.videoWidth, v.videoHeight)), w = Math.max(1, Math.round(v.videoWidth * k)), hh = Math.max(1, Math.round(v.videoHeight * k));
      const c = h('canvas', { width: w, height: hh });
      c.getContext('2d').drawImage(v, 0, 0, w, hh);
      const ks = Math.min(1, 480 / Math.max(w, hh));
      let less = c;
      if (ks < 1) { less = h('canvas', { width: Math.round(w * ks), height: Math.round(hh * ks) }); less.getContext('2d').drawImage(c, 0, 0, less.width, less.height); }
      small.set(key, less); full.set(key, c); kept += w * hh;
      if (small.size > 400) small.delete(small.keys().next().value);
      for (const [old, o] of full) { if (kept <= CLIP_KEPT || old === key) break; full.delete(old); kept -= o.width * o.height; }
      return c;
    }
    return {
      // the frame at a time, as a canvas: 'small' for a sheet, else at the clip's own size. Nothing when it cannot be read
      frame(t, size, near) {
        const key = Math.round(t * 1000), have = (size === 'small' && small.get(key)) || full.get(key);
        if (have) return Promise.resolve(have);
        const job = queue.then(async () => {
          if (!alive || !(await ready) || !v.videoWidth) return null;
          let c = full.get(key);
          if (!c) {
            if (at !== key) { await go(t, near); at = key; }
            if (!alive) return null;
            c = still(key);
          }
          return size === 'small' ? small.get(key) : c;
        }).catch(() => null);
        queue = job;
        return job;
      },
      // the frames a second, when the file's facts do not say: the copy plays for a second, the times of the frames it
      // shows are read, and the gap between them is taken to the nearest usual rate. 0 when it cannot be told
      measure() {
        const job = queue.then(async () => {
          if (!alive || !(await ready) || !v.requestVideoFrameCallback) return 0;
          const times = [];
          let on = true;
          const tick = (now, meta) => { if (!on) return; times.push(meta.mediaTime); v.requestVideoFrameCallback(tick); };
          v.requestVideoFrameCallback(tick);
          try { await v.play(); } catch (e) { on = false; return 0; }
          await new Promise((ok) => setTimeout(ok, 1100));
          on = false; v.pause(); at = null;
          const gaps = [];
          for (let i = 1; i < times.length; i++) { const d = times[i] - times[i - 1]; if (d > 0.0005) gaps.push(d); }
          if (gaps.length < 4) return 0;
          gaps.sort((a, b) => a - b);
          const raw = 1 / gaps[gaps.length >> 1], usual = CLIP_RATES.reduce((a, b) => (Math.abs(b - raw) < Math.abs(a - raw) ? b : a));
          return Math.abs(usual - raw) / raw < 0.02 ? usual : Math.round(raw * 100) / 100;
        }).catch(() => 0);
        queue = job;
        return job;
      },
      destroy() { alive = false; v.pause(); v.removeAttribute('src'); try { v.load(); } catch (e) { /* already gone */ } full.clear(); small.clear(); },
    };
  }

  // a clip, large: the clip itself with the browser's controls off, a bar to scrub along with the marks under it, steps
  // of one frame, paint on a frame, and the list of marks beside it. file: { url, label, name }; opts.facts is what the
  // file check read from the clip (seconds, fps, frames). attach(marks, { editable }) puts a set of marks on it.
  // What Claude gets as pictures: picture() is the sheet (the whole clip in eight frames, a row of frames for each
  // mark, a legend) and shots() is each mark's own first frame at the clip's size, with its paint
  function clipView(file, opts) {
    opts = opts || {};
    const facts = opts.facts || {}, src = API.src(file.url);
    const video = h('video', { src, playsinline: true, preload: 'auto' });
    let copy = null;  // the second copy of the clip, made when a frame is first wanted: a clip only looked at is read once
    const frames = () => copy || (copy = clipFrames(src));
    let tl = null, list = null, lane = null, alive = true, editable = () => false, takes = () => false, broke = null;  // takes: the marks can be changed, once the clip is read
    let bad = '', lost = false;  // bad: why the clip cannot be marked, once that is known; lost: its file does not say how long it is
    let fps = facts.fps > 0 ? facts.fps : 0, measured = false, asked = false, vw = 0, vh = 0, shown = 1, seen = null, pin = null;
    let stroke = null, drawing = null, scrub = false, press = null, inkKey = '';
    let boxing = false, boxDrag = null, boxKey = '';  // the Box tool is on; a box being drawn, moved or sized; what the boxes on screen show
    const boxSeen = new Map(), hadBox = new Set();  // the box each mark's "where" was last written for; marks that had a box when they were put on the clip
    const pen = { on: false, size: 1, erase: false, colour: '' };  // the brush: what newInk keeps for a picture
    const layers = new Map();  // the paint of each mark on a layer of its own: id -> { sig, c }
    const sent = new Map(), bare = new Set();  // what each mark's own picture last showed, and the marks known to have none
    const tp = transport(video, { length: () => facts.seconds || 0, snap });
    const len = () => tp.length();
    // Seconds are the truth; a frame's number is worked out from them. Frames count from 0: frame n starts at n / fps
    // seconds. With no frame rate known a step is 1/30 s and no frame is named. A time is taken to the millisecond, as a
    // mark keeps it, so the frame the playhead is on and the frame of a mark made there are always the same one
    const count = () => (!fps ? 0 : facts.frames && facts.fps === fps ? facts.frames : Math.max(1, Math.round(len() * fps)));
    const frameOf = (t) => { const c = count(), n = Math.max(0, Math.floor(sec3(t) * (fps || 30) + 1e-3)); return c ? Math.min(c - 1, n) : n; };
    const mid = (n) => (n + 0.5) / (fps || 30);  // the middle of a frame: going there shows that frame and no other
    function snap(t) { return fps && len() ? Math.min(len(), mid(frameOf(t))) : t; }
    // the frame on screen: the one last shown when the browser says which, else the one the time falls in
    const nowFrame = () => (fps && seen !== null && !video.seeking && seen <= video.currentTime + 1e-3 && video.currentTime - seen < 1.2 / fps ? frameOf(seen + 0.5 / fps) : frameOf(tp.time()));
    const secs = (t) => t.toFixed(2) + ' s';

    const ink = h('canvas', { class: 'ink' }), brush = h('div', { class: 'brush', hidden: true }), boxes = h('div', { class: 'boxes' });
    const stage = h('div', { class: 'clipframe' }, video, ink, boxes, brush);
    const ruler = h('canvas', { class: 'timeruler' }), over = h('canvas');
    const strip = h('div', { class: 'timelane' }, over), head = h('div', { class: 'timehead', hidden: true });
    const track = h('div', { class: 'timewave track' }, ruler, strip, head);
    const btn = (label, title, fn, name) => h('button', { class: 'btn small', type: 'button', title, 'aria-label': name || null, onclick: (e) => { e.currentTarget.blur(); fn(); } }, label);
    const playBtn = btn('Play', 'Play or hold (Space)', () => tp.toggle());
    const time = h('span', { class: 't' }), status = h('span', { class: 'hint' });
    const loopBtn = h('button', { class: 'btn small' + (S.opts.loop ? ' on' : ''), type: 'button', 'data-opt': 'loop', 'aria-pressed': String(!!S.opts.loop), title: 'Play the clip round and round',
      onclick: (e) => { e.currentTarget.blur(); S.opts.loop = !S.opts.loop; showOpts(); tp.loopAll(S.opts.loop); } }, 'Loop');
    const side = h('div', { class: 'timeside' });
    const el = h('div', { class: 'timeview clip' }, h('div', { class: 'timemain' }, stage, track,
      h('div', { class: 'timebar' }, playBtn, h('span', { class: 'grp' }, btn('◀', 'A frame back (,); with Shift, ten', () => step(-1), 'A frame back'), btn('▶', 'A frame on (.); with Shift, ten', () => step(1), 'A frame on')),
        time, h('span', { class: 'grp' }, rateButtons(() => tp.rate(S.opts.rate))), loopBtn, tp.volumeBar(), status)), side);
    // the brush: Paint on or off, its size, Rub out. Undo and Clear all are the marks' own
    const penBtn = btn('Paint', 'Paint on the frame, in the colour of its mark (B). Painting holds the clip', () => setPen(!pen.on));
    const sizes = ['S', 'M', 'L'].map((label, i) => btn(label, ['Small', 'Medium', 'Large'][i] + ' brush', () => { pen.size = i; showPen(); }));
    const rub = btn('Rub out', 'Rub paint out of the mark on this frame', () => { pen.erase = !(pen.on && pen.erase); setPen(true); });
    // the Box tool: a box on the picture that stays on screen for the whole of its mark, and the button that takes it away
    const boxBtn = btn('Box', 'Draw a box round a part of the picture: it stays on screen for the whole of its mark (R)', () => setBox(!boxing));
    const unbox = btn('No box', 'Take the box away from this mark (Delete while Box is on)', () => dropBox());
    unbox.hidden = true;
    const tools = h('div', { class: 'grp marktools' }, penBtn, h('span', { class: 'sizes' }, sizes), rub, boxBtn, unbox);
    function showPen() {
      penBtn.classList.toggle('on', pen.on); penBtn.setAttribute('aria-pressed', String(pen.on));
      sizes.forEach((b, i) => b.classList.toggle('on', i === pen.size)); rub.classList.toggle('on', pen.on && pen.erase);
      boxBtn.classList.toggle('on', boxing); boxBtn.setAttribute('aria-pressed', String(boxing));
      stage.classList.toggle('pen', pen.on); stage.classList.toggle('boxing', boxing);
      if (!pen.on) brush.hidden = true;
      if (!boxing) stage.style.cursor = '';
      drawBoxes();
    }
    function setPen(on) { pen.on = !!on && editable(); if (!pen.on) pen.erase = false; else boxing = false; showPen(); }
    // the Box tool on or off. Turned on with a mark chosen that the playhead is not inside, the playhead goes to the
    // mark's start, so the box drawn is that mark's and shows at once
    function setBox(on) {
      if (boxDrag && boxDrag.moved) boxUp({ pointerId: boxDrag.id });  // a box being drawn, moved or sized is kept as it is
      boxing = !!on && editable(); boxDrag = null;
      if (boxing) { pen.on = false; pen.erase = false; const c = tl.get(tl.chosen); if (c && !inside(c, nowFrame())) { const to = snap(c.t0); if (tp.playing()) { pin = to; tp.hold(); } tp.seek(to); } }
      showPen();
    }

    const map = { time: (cx) => { const r = strip.getBoundingClientRect(); return (cx - r.left) / (r.width || 1) * len(); },
      x: (t) => { const r = strip.getBoundingClientRect(); return r.left + t / (len() || 1) * r.width; } };
    // a mark's time as the list shows it, and as the sheet does
    const listWhen = (s) => (s.t1 > s.t0 ? s.t0.toFixed(2) + ' to ' + secs(s.t1) + (fps ? ' · frames ' + frameOf(s.t0) + ' to ' + frameOf(s.t1) : '') : secs(s.t0) + (fps ? ' · frame ' + frameOf(s.t0) : '')) + (s.box ? ' · box' : '');
    const sheetWhen = (s) => (s.t1 > s.t0 ? secs(s.t0) + ' to ' + secs(s.t1) + ' (' + secs(s.t1 - s.t0) + (fps ? ', frames ' + frameOf(s.t0) + ' to ' + frameOf(s.t1) : '') + ')' : 'at ' + secs(s.t0) + (fps ? ' (frame ' + frameOf(s.t0) + ')' : ''));

    // the paint of one mark, drawn on its layer again only when its strokes have changed
    const sigOf = (s) => { const k = s.strokes || [], last = k.length ? k[k.length - 1] : null; return s.c + ':' + k.length + ':' + k.reduce((n, x) => n + x.p.length, 0) + ':' + (last ? last.p[last.p.length - 1].join(',') : ''); };
    const quality = () => Math.min(1, 2048 / Math.max(vw, vh));
    function layerOf(s) {
      if (!vw || !s.strokes || !s.strokes.length) { layers.delete(s.id); return null; }
      const sig = sigOf(s), q = quality();
      let L = layers.get(s.id);
      if (L && L.sig === sig) return L.c;
      if (!L) { L = { c: h('canvas', { width: Math.round(vw * q), height: Math.round(vh * q) }) }; layers.set(s.id, L); }
      const ctx = L.c.getContext('2d');
      ctx.globalCompositeOperation = 'source-over'; ctx.clearRect(0, 0, L.c.width, L.c.height);
      for (const k of s.strokes) inkLine(ctx, k, 0, q);
      L.sig = sig;
      return L.c;
    }
    // the paint on screen: that of every mark the playhead is inside, over the frame
    function drawInk() {
      if (!vw || !tl) return;
      const n = frameOf(tp.time()), on = tl.spans.filter((s) => s.strokes && s.strokes.length && frameOf(s.t0) <= n && n <= frameOf(s.t1));
      const key = on.map((s) => s.id + '=' + sigOf(s)).join(' ');
      if (key === inkKey) return;
      inkKey = key;
      const ctx = ink.getContext('2d'); ctx.clearRect(0, 0, ink.width, ink.height);
      for (const s of on) { const c = layerOf(s); if (c) ctx.drawImage(c, 0, 0, ink.width, ink.height); }
    }
    function drawLane() {
      const d = len(), r = laneCanvas(ruler), m = laneCanvas(over);
      if (r && d) paintRuler(r.ctx, r.w, { t0: 0, span: d }, null, laneColours(track));
      if (m && tl && d) paintSpans(m.ctx, tl, (t) => t / d * m.w, 0, m.h);
    }
    function drawHead() {
      const d = len(), t = Math.min(tp.time(), d || 0);
      head.hidden = !d; head.style.left = (d ? 100 * t / d : 0) + '%';
      playBtn.textContent = tp.playing() ? 'Hold' : 'Play';
      time.textContent = d ? secs(t) + ' / ' + secs(d) + (fps ? ' · frame ' + frameOf(t) + ' of ' + count() : '') : '';
      drawInk(); drawBoxes();
    }
    // the layer of paint lies over the clip's picture, wherever that sits in its box
    function place() {
      const bw = stage.clientWidth, bh = stage.clientHeight;
      if (!bw || !bh || !vw) return;
      shown = Math.min(bw / vw, bh / vh);
      const at = { left: (bw - vw * shown) / 2 + 'px', top: (bh - vh * shown) / 2 + 'px', width: vw * shown + 'px', height: vh * shown + 'px' };
      Object.assign(ink.style, at); Object.assign(boxes.style, at);
    }
    function say() {
      status.textContent = bad || (!vw ? (lost ? 'This clip does not say how long it is. Play it through once and marks can be made on it.' : 'Reading the clip') : vw + ' x ' + vh + (fps ? ' · ' + fps + ' frames a second' + (measured ? ', measured here' : '') : asked === 'busy' ? ' · measuring its frames a second' : ' · its frames a second are not known: a step is 1/30 s'));
    }
    // the clip cannot be read (the browser gave up on it, or it has no picture): the status line and the list say so
    // plainly, and the tools and the hint that tell the user to mark it are taken away
    function unread() {
      if (!alive || bad || vw) return;
      bad = 'The browser could not read this clip, so marks cannot be made on it.';
      say(); if (list) list.draw(); if (broke) broke();
    }
    video.addEventListener('error', unread);
    // a clip whose file does not say how long it is (one a browser recorded): sent far past its end, the browser finds
    // the length, and the clip is put back at its start
    video.addEventListener('loadedmetadata', () => {
      if (!alive) return;
      if (!video.videoWidth) { unread(); return; }
      if (lost || len()) return;
      lost = true; say();
      const back = () => { if (!isFinite(video.duration)) return; video.removeEventListener('durationchange', back); if (alive) video.currentTime = 0; };
      video.addEventListener('durationchange', back);
      try { video.currentTime = 1e101; } catch (e) { /* its length stays unknown: the status line says what to do */ }
    });
    // the clip's size and length are known: the marks take them, and everything is drawn
    function ready() {
      if (!alive || !video.videoWidth || !len()) return;
      if (vw !== video.videoWidth || vh !== video.videoHeight) {
        vw = video.videoWidth; vh = video.videoHeight; layers.clear(); inkKey = '';
        ink.width = Math.round(vw * quality()); ink.height = Math.round(vh * quality());
      }
      if (tl) { if (!fps && tl.fps) { fps = tl.fps; measured = true; } Object.assign(tl, { file: file.name, length: sec3(len()), fps, size: [vw, vh] }); }
      if (!fps && !asked) {
        asked = 'busy';
        frames().measure().then((r) => {
          asked = true; if (!alive) return;
          if (r && !fps) { fps = r; measured = true; if (tl) { tl.fps = fps; tl.stale(); if (tl.spans.length && editable()) tl.changed('marks'); } }
          ready();
        });
      }
      place(); drawLane(); drawHead(); say();
      if (list) list.draw();
    }
    // a step of frames: the clip is held, and goes to the middle of the frame so many on or back
    function step(d) {
      if (!len()) return;
      const n = nowFrame() + d, to = mid(Math.max(0, fps ? Math.min(count() - 1, n) : n));  // with no frame rate known, the middle of a frame of 1/30 s
      if (tp.playing()) { pin = to; tp.hold(); }
      tp.seek(to);
    }
    // I and O: the start or the end of the chosen mark comes to the playhead. With no mark chosen, or the playhead
    // past its end (for I) or before its start (for O), a new mark starts there
    function edge(start) {
      const t = tl.fit(snap(tp.time())), s = tl.get(tl.chosen);
      if (!s || (start ? t > s.t1 : t < s.t0)) { tl.add(t); return; }
      if ((start ? s.t0 : s.t1) === t) return;
      if (start && frameOf(t) !== frameOf(s.t0) && pinned(s)) { toast(pinned(s)); return; }
      tl.keep(); tl.move(s, start ? t : s.t0, start ? s.t1 : t); tl.changed('marks');
    }
    // whether a mark has paint that shows (paint rubbed out again is none); looked at once for each change to its strokes
    function painted(s) {
      const c = s ? layerOf(s) : null, L = c && layers.get(s.id);
      if (!L) return false;
      if (L.looked !== L.sig) { L.looked = L.sig; L.any = !!inkPlace(c, vw, vh); }
      return L.any;
    }
    // paint lies on the frame its mark starts at, and that is the frame Claude is shown it on: the start of a painted
    // mark stays where it is. These are the words said when the user tries to move it; nothing for a mark with no paint
    const pinned = (s) => (painted(s) ? 'Its paint is on its first frame, so its start stays where it is. Rub the paint out to move it.' : '');
    // the mark the brush paints on: the chosen one when the playhead is on its first frame, else one that starts on this frame
    function target(n) {
      const c = tl.get(tl.chosen);
      if (c && frameOf(c.t0) === n) return c;
      const here = tl.sorted().filter((s) => frameOf(s.t0) === n);
      return here.find((s) => s.strokes && s.strokes.length) || here[0] || null;
    }
    const toFrame = (x, y) => { const r = ink.getBoundingClientRect(); return [(x - r.left) / (r.width || 1) * vw, (y - r.top) / (r.height || 1) * vh]; };
    function penDown(x, y) {
      const n = nowFrame(), t = fps ? mid(n) : tp.time();
      if (tp.playing()) { pin = t; tp.hold(); }
      let s = target(n);
      if (pen.erase) { if (!s || !s.strokes || !s.strokes.length) { toast('There is no paint on this frame to rub out'); return; } tl.keep(); }
      else if (s) tl.keep();
      else { s = tl.add(t, t, { strokes: [] }); if (!s) return; }
      if (!s.strokes) s.strokes = [];
      tl.choose(s); pen.colour = s.c;
      stroke = inkStart(pen, toFrame(x, y), shown); s.strokes.push(stroke); drawing = s.id;
      drawInk();
    }
    function penMove(x, y) {
      const s = tl.get(drawing), L = s && layers.get(s.id);
      if (!L || !inkMore(stroke, toFrame(x, y))) return;
      inkLine(L.c.getContext('2d'), stroke, stroke.p.length - 1, quality()); L.sig = sigOf(s);
      drawInk();
    }
    function penUp() {
      const s = tl.get(drawing);
      stroke = null; drawing = null;
      if (s) { tl.stale(s); tl.changed('marks'); }
    }
    // the ring under the pointer wears the colour of the mark it would paint on; white when the paint would start a new one
    function ring(x, y) {
      if (x !== null && pen.on && tl && !stroke) { const s = target(nowFrame()); pen.colour = s ? s.c : ''; }
      inkRing(brush, stage, x, y, pen);
      if (!pen.erase && !MARK_HEX[pen.colour]) brush.style.borderColor = '';
    }

    // A box is kept in shares of the frame from its top left corner: { left, top, width, height }, so the clip's size
    // does not matter. It is on screen while the playhead is inside its mark, from its first frame to its last
    const boxSig = (s) => (s.box ? [s.box.left, s.box.top, s.box.width, s.box.height].join(',') : '');
    const share4 = (x) => Math.round(x * 1e4) / 1e4;
    const inside = (s, n) => frameOf(s.t0) <= n && n <= frameOf(s.t1);
    // the mark the Box tool works on: the chosen one when the playhead is inside it, else one the playhead is inside
    // that has a box, else the shortest one it is inside
    function boxTarget(n) {
      const c = tl.get(tl.chosen);
      if (c && inside(c, n)) return c;
      const here = tl.spans.filter((s) => inside(s, n)).sort((a, b) => (a.t1 - a.t0) - (b.t1 - b.t0));
      return here.find((s) => s.box) || here[0] || null;
    }
    // the boxes on screen, each with the mark's number in time order
    const shownBoxes = (n) => tl.sorted().map((s, i) => [s, i + 1]).filter(([s]) => s.box && inside(s, n));
    // the boxes over the picture: every mark's the playhead is inside, in its colour with its number and note; with the
    // Box tool on, the one it works on has handles on its corners and edges
    function drawBoxes() {
      if (!vw || !tl) { if (boxKey) { boxes.replaceChildren(); boxKey = ''; } return; }
      const n = frameOf(tp.time()), live = boxing && editable() ? boxTarget(n) : null, on = shownBoxes(n);
      unbox.hidden = !(live && live.box);
      const key = on.map(([s, k]) => [s.id, k, s.c, boxSig(s), s.note || ''].join('|')).join(' ') + '/' + (live ? live.id : '');
      if (key === boxKey) return;
      boxKey = key;
      boxes.replaceChildren(...on.map(([s, k]) => {
        const b = s.box, note = (s.note || '').trim().split('\n')[0];
        return h('div', { class: 'clipbox' + (s === live ? ' edit' : '') + (b.top < 0.08 ? ' low' : ''), 'data-id': s.id,
          style: '--sw:' + (MARK_HEX[s.c] || MARK_HEX.red) + ';left:' + b.left * 100 + '%;top:' + b.top * 100 + '%;width:' + b.width * 100 + '%;height:' + b.height * 100 + '%' },
        h('span', { class: 'lab' }, String(k) + (note ? ' ' + note : '')),
        s === live ? ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].map((p) => h('i', { class: 'hd ' + p })) : null);
      }));
    }
    const toShare = (x, y) => { const r = ink.getBoundingClientRect(); return [Math.min(1, Math.max(0, (x - r.left) / (r.width || 1))), Math.min(1, Math.max(0, (y - r.top) / (r.height || 1)))]; };
    // the part of a box a point on the picture is on: a corner or an edge ('nw', 'n'...), the inside ('move'), or none
    function boxPart(b, p) {
      const r = ink.getBoundingClientRect(), tx = Math.min(7 / (r.width || 1), b.width / 4), ty = Math.min(7 / (r.height || 1), b.height / 4);
      const x1 = b.left + b.width, y1 = b.top + b.height;
      if (p[0] < b.left - tx || p[0] > x1 + tx || p[1] < b.top - ty || p[1] > y1 + ty) return '';
      return ((Math.abs(p[1] - b.top) <= ty ? 'n' : Math.abs(p[1] - y1) <= ty ? 's' : '') + (Math.abs(p[0] - b.left) <= tx ? 'w' : Math.abs(p[0] - x1) <= tx ? 'e' : '')) || 'move';
    }
    const BOX_CURSOR = { n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize', move: 'move' };
    // the mark a point on the picture works on, and the part of its box there: the box of the mark the Box tool works
    // on, else another box on screen under the point, else the mark the Box tool works on, to draw its box again
    function boxHit(n, p) {
      const s = boxTarget(n), part = s && s.box ? boxPart(s.box, p) : '';
      if (part || !s) return [s, part];
      const hit = shownBoxes(n).reverse().find(([x]) => x !== s && boxPart(x.box, p));
      return hit ? [hit[0], boxPart(hit[0].box, p)] : [s, ''];
    }
    // a press with the Box tool on: on a box, ready to move or size it; elsewhere, ready to draw the box of the mark
    // the tool works on again (with Shift, or with the playhead in no mark, a new moment here gets the box).
    // Nothing changes until the pointer moves; the clip is held
    function boxDown(e) {
      const n = nowFrame(), p = toShare(e.clientX, e.clientY);
      if (tp.playing()) { pin = fps ? mid(n) : tp.time(); tp.hold(); }
      const [s, part] = e.shiftKey ? [null, ''] : boxHit(n, p);
      boxDrag = { id: e.pointerId, x: e.clientX, y: e.clientY, p, n, t: fps ? mid(n) : tp.time(), span: s ? s.id : null, part: part || 'new', from: s && s.box ? Object.assign({}, s.box) : null, moved: false };
    }
    function boxMove(e) {
      const d = boxDrag;
      if (!d || e.pointerId !== d.id) return;
      if (!d.moved) {
        if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4) return;
        d.moved = true;
        let s = tl.get(d.span);
        if (s) { tl.keep(); tl.choose(s); } else { s = tl.add(d.t, d.t); if (!s) { boxDrag = null; return; } d.span = s.id; }
      }
      const s = tl.get(d.span), b = d.from, p = toShare(e.clientX, e.clientY);
      if (!s) return;
      let x0, y0, x1, y1;
      if (d.part === 'new') { [x0, y0] = d.p; [x1, y1] = p; }
      else if (d.part === 'move') {  // the whole box goes with the pointer, and stays inside the frame
        x0 = b.left + Math.min(1 - b.left - b.width, Math.max(-b.left, p[0] - d.p[0])); y0 = b.top + Math.min(1 - b.top - b.height, Math.max(-b.top, p[1] - d.p[1]));
        x1 = x0 + b.width; y1 = y0 + b.height;
      } else {  // the edges under the pointer go with it; dragged past the other side, the box turns over
        x0 = b.left; y0 = b.top; x1 = b.left + b.width; y1 = b.top + b.height;
        if (d.part.includes('w')) x0 = p[0]; if (d.part.includes('e')) x1 = p[0]; if (d.part.includes('n')) y0 = p[1]; if (d.part.includes('s')) y1 = p[1];
      }
      s.box = { left: share4(Math.min(x0, x1)), top: share4(Math.min(y0, y1)), width: share4(Math.abs(x1 - x0)), height: share4(Math.abs(y1 - y0)) };
      drawBoxes();
    }
    // let go: the box is kept, unless it is too small to see; a click with no drag chooses the mark of the box under it
    function boxUp(e) {
      const d = boxDrag;
      if (!d || e.pointerId !== d.id) return;
      boxDrag = null;
      if (!d.moved) { const hit = shownBoxes(d.n).reverse().find(([s]) => boxPart(s.box, d.p)); if (hit) tl.choose(hit[0]); return; }
      const s = tl.get(d.span);
      if (s && s.box && (s.box.width < 0.01 || s.box.height < 0.01)) { tl.undo(); toast('Drag across the part of the picture the box goes round'); return; }
      if (s) { tl.stale(s); tl.changed('marks'); }
    }
    // the box comes off the mark the Box tool works on; the mark stays
    function dropBox() {
      const s = tl && editable() ? boxTarget(nowFrame()) : null;
      if (!s || !s.box) return false;
      tl.keep(); delete s.box; tl.stale(s); tl.changed('marks');
      return true;
    }
    stage.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      if (pen.on && editable()) { stage.setPointerCapture(e.pointerId); e.preventDefault(); press = null; penDown(e.clientX, e.clientY); return; }
      if (boxing && editable()) { stage.setPointerCapture(e.pointerId); e.preventDefault(); press = null; boxDown(e); return; }
      press = [e.clientX, e.clientY];
    });
    stage.addEventListener('pointermove', (e) => {
      ring(e.clientX, e.clientY);
      if (stroke) penMove(e.clientX, e.clientY);
      else if (boxDrag) boxMove(e);
      else if (boxing && tl && vw) stage.style.cursor = BOX_CURSOR[boxHit(nowFrame(), toShare(e.clientX, e.clientY))[1]] || 'crosshair';
    });
    const lift = (e) => {
      if (boxDrag) { boxUp(e); return; }
      if (stroke) penUp();
      else if (press && e.type === 'pointerup' && Math.hypot(e.clientX - press[0], e.clientY - press[1]) < 5) tp.toggle();  // a click on the clip plays or holds it
      press = null;
    };
    stage.addEventListener('pointerup', lift); stage.addEventListener('pointercancel', lift);
    stage.addEventListener('pointerleave', () => ring(null, null));
    // the bar: a click goes to that time, a drag scrubs along the clip
    ruler.addEventListener('pointerdown', (e) => { if (e.button !== 0 || !len()) return; ruler.setPointerCapture(e.pointerId); scrub = true; tp.seek(map.time(e.clientX)); });
    ruler.addEventListener('pointermove', (e) => { if (scrub) tp.seek(map.time(e.clientX)); });
    const scrubEnd = () => { scrub = false; };
    ruler.addEventListener('pointerup', scrubEnd); ruler.addEventListener('pointercancel', scrubEnd);
    // when the clip is held it goes to the middle of the frame it shows, so the frame named is the frame seen
    video.addEventListener('pause', () => { const to = pin; pin = null; if (alive && fps && !video.ended) tp.seek(to !== null ? to : mid(nowFrame()), true); });
    if (video.requestVideoFrameCallback) { const each = (now, meta) => { seen = meta.mediaTime; if (alive) video.requestVideoFrameCallback(each); }; video.requestVideoFrameCallback(each); }
    tp.on((what) => {
      if (what === 'length') { ready(); return; }
      if (what === 'state' && list) list.draw();
      drawHead();
    });
    const ro = window.ResizeObserver ? new ResizeObserver(() => { place(); drawLane(); }) : null;
    if (ro) { ro.observe(stage); ro.observe(track); }

    // the sentence Claude reads for one mark on a clip: when, which frames, and where its paint sits on the frame
    function clipWhere(s) {
      const c = count(), rate = fps ? ', ' + fps + ' fps' : '', parts = [];
      if (s.t1 > s.t0) parts.push('from ' + secs(s.t0) + ' to ' + secs(s.t1) + (fps ? ' (frames ' + frameOf(s.t0) + ' to ' + frameOf(s.t1) + ' of ' + c + rate + ')' : '') + ', ' + secs(s.t1 - s.t0) + ' long');
      else parts.push('at ' + secs(s.t0) + (fps ? ' (frame ' + frameOf(s.t0) + ' of ' + c + rate + ')' : ''));
      const L = layerOf(s), at = L ? inkPlace(L, vw, vh) : null;
      if (at) parts.push('paint ' + (s.t1 > s.t0 ? 'on its first frame, ' : '') + (at.pos === 'the middle' ? 'in the middle' : /^(left|right)$/.test(at.pos) ? 'on the ' + at.pos : 'in the ' + at.pos)
        + ' (x ' + at.x0 + ' to ' + at.x1 + ', y ' + at.y0 + ' to ' + at.y1 + ' of ' + vw + ' x ' + vh + '), ' + pct(at.share) + ' of the frame');
      if (s.box) {  // a box: where it is in words, in shares and in pixels, and that it is up for the whole mark
        const b = s.box, fx = b.left + b.width / 2, fy = b.top + b.height / 2, p100 = (x) => Math.round(x * 100) + '%';
        const pos = fx > 1 / 3 && fx < 2 / 3 && fy > 1 / 3 && fy < 2 / 3 ? 'in the middle' : ((w) => (/^(left|right)$/.test(w) ? 'on the ' + w : 'in the ' + w))([thirds(fy, ['upper', '', 'lower']), thirds(fx, ['left', 'centre', 'right'])].filter(Boolean).join(' '));
        parts.push('a box ' + pos + ' (left ' + p100(b.left) + ', top ' + p100(b.top) + ', ' + p100(b.width) + ' wide and ' + p100(b.height) + ' high; x ' + Math.round(b.left * vw) + ' to ' + Math.round((b.left + b.width) * vw)
          + ', y ' + Math.round(b.top * vh) + ' to ' + Math.round((b.top + b.height) * vh) + ' of ' + vw + ' x ' + vh + '), on screen ' + (s.t1 > s.t0 ? 'for the whole of the mark' : 'on that frame only'));
      }
      return { where: parts.join('; ') };
    }
    // a mark's paint burned into a picture: at half strength, so the fault shows through, with a thin light line and a
    // dark one round it, so it also shows on a frame of its own colour
    function burn(ctx, layer, x, y, w, hh) {
      const c = h('canvas', { width: w, height: hh }), k = c.getContext('2d'), d = Math.max(1, w / 500);
      for (const [r, colour] of [[2 * d, '#000'], [d, '#fff']]) {
        k.globalCompositeOperation = 'source-over'; k.clearRect(0, 0, w, hh);
        for (let a = 0; a < 8; a++) k.drawImage(layer, r * Math.cos(a * Math.PI / 4), r * Math.sin(a * Math.PI / 4), w, hh);
        k.globalCompositeOperation = 'destination-out'; k.drawImage(layer, 0, 0, w, hh);
        k.globalCompositeOperation = 'source-in'; k.fillStyle = colour; k.fillRect(0, 0, w, hh);
        ctx.drawImage(c, x, y);
      }
      ctx.globalAlpha = 0.5; ctx.drawImage(layer, x, y, w, hh); ctx.globalAlpha = 1;
    }
    // a mark's box drawn into a picture of one of its frames at x, y, w by hh: a line in its colour with a dark one
    // round it, so it shows on any picture, and the mark's number on a flag at its corner
    function boxDraw(ctx, s, num, x, y, w, hh) {
      const b = s.box, hex = MARK_HEX[s.c] || MARK_HEX.red, lw = Math.max(2, Math.round(w / 400));
      const bx = x + b.left * w, by = y + b.top * hh, bw = b.width * w, bh = b.height * hh;
      ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, hh); ctx.clip();
      ctx.strokeStyle = 'rgba(0, 0, 0, 0.8)'; ctx.lineWidth = lw * 3; ctx.strokeRect(bx, by, bw, bh);
      ctx.strokeStyle = hex; ctx.lineWidth = lw; ctx.strokeRect(bx, by, bw, bh);
      const fs = Math.max(11, Math.round(w / 70)), fh = Math.round(fs * 1.4);
      ctx.font = '600 ' + fs + 'px system-ui, sans-serif';
      const fw = ctx.measureText(String(num)).width + fs, fy = by - fh - lw >= y ? by - fh - lw / 2 : by + lw / 2;  // over the box, or just inside it at the top of the frame
      ctx.fillStyle = hex; ctx.fillRect(bx - lw / 2, fy, fw, fh);
      ctx.fillStyle = '#111'; ctx.textBaseline = 'middle'; ctx.fillText(String(num), bx - lw / 2 + fs / 2, fy + fh / 2 + 1);
      ctx.restore();
    }
    // the sheet Claude reads: the whole clip in eight frames with the time under each, then for each of the first twelve
    // marks a band (its number, kind and time) over its frame, or over the frames at its start, middle and end, the
    // paint on the first at half strength; then the legend with the notes. 1600 across
    function picture() {
      if (!alive) return Promise.resolve(undefined);  // thrown away: there is nothing to send, where a sheet of frames that could not be read would be worse
      if (!tl || !tl.spans.length) return Promise.resolve(null);
      if (!len() || !vw) return Promise.resolve(undefined);
      const c = count(), near = fps ? 1.01 / fps : 0, get = (t) => frames().frame(fps ? mid(frameOf(t)) : t, 'small', near);
      const whole = Array.from({ length: 8 }, (_, i) => (c ? mid(Math.round(i * (c - 1) / 7)) : (i + 0.5) / 8 * len()));
      const cells = tl.sorted().slice(0, CLIP_ROWS).map((s) => { const ts = s.t1 > s.t0 ? [s.t0, (s.t0 + s.t1) / 2, s.t1] : [s.t0]; return { s, ts, got: ts.map(get), layer: layerOf(s), box: s.box ? { c: s.c, box: Object.assign({}, s.box) } : null }; });
      return Promise.all([Promise.all(whole.map(get)), Promise.all(cells.map((x) => Promise.all(x.got)))]).then(([top8, rows]) => {
        if (!alive) return undefined;  // thrown away while its frames were read
        const W = 1600, pad = 16, gap = 6, title = 34, cap = 20, band = 26;
        const sw = Math.floor((W - 2 * pad - 7 * gap) / 8), sh = Math.round(sw * vh / vw);
        const k = Math.min(356 / vw, 220 / vh), fw = Math.round(vw * k), fh = Math.round(vh * k);
        let x = pad, y = title + sh + cap + 14;
        const places = cells.map((cell) => {  // a cell for each mark; they run across and wrap
          const w = Math.max(330, cell.ts.length * fw + (cell.ts.length - 1) * 4);  // wide enough for the words on its band
          if (x > pad && x + w > W - pad) { x = pad; y += band + fh + cap + 12; }
          const at = { x, y, w }; x += w + 14;
          return at;
        });
        const top = h('canvas', { width: W, height: y + (cells.length ? band + fh + cap : 0) + 4 }), ctx = top.getContext('2d');
        ctx.fillStyle = '#111114'; ctx.fillRect(0, 0, W, top.height);
        ctx.fillStyle = '#fff'; ctx.font = '600 15px system-ui, sans-serif';
        ctx.fillText([file.name, secs(len()) + ' long', vw + ' x ' + vh, fps ? fps + ' frames a second, ' + count() + ' frames counted from 0' : 'frames a second not known',
          'the top row is the whole clip; then each mark'].join(' · '), pad, 22, W - 2 * pad);
        const put = (img, px, py, w, hh) => {
          if (img) ctx.drawImage(img, px, py, w, hh);
          else { ctx.fillStyle = '#26262c'; ctx.fillRect(px, py, w, hh); ctx.fillStyle = '#b3b3bd'; ctx.font = '12px system-ui, sans-serif'; ctx.fillText('this frame could not be read', px + 8, py + 18, w - 16); }
          ctx.strokeStyle = '#34343c'; ctx.lineWidth = 1; ctx.strokeRect(px + 0.5, py + 0.5, w - 1, hh - 1);
        };
        const under = (t, px, py, w, lead) => {  // under a frame: its time and number, or the number alone where the frame is narrow
          ctx.fillStyle = '#b3b3bd'; ctx.font = '12px system-ui, sans-serif';
          const all = (lead || '') + secs(t) + (fps ? ' · frame ' + frameOf(t) : '');
          ctx.fillText(ctx.measureText(all).width <= w - 6 || !fps ? all : 'frame ' + frameOf(t), px, py + 14, w - 6);
        };
        top8.forEach((img, i) => { const px = pad + i * (sw + gap); put(img, px, title, sw, sh); under(whole[i], px, title + sh, sw); });
        cells.forEach((cell, i) => {
          const at = places[i], s = cell.s;
          ctx.fillStyle = '#26262c'; ctx.fillRect(at.x, at.y, at.w, band);
          ctx.fillStyle = MARK_HEX[s.c] || MARK_HEX.red; ctx.fillRect(at.x, at.y, 30, band);
          ctx.fillStyle = '#111'; ctx.font = '600 14px system-ui, sans-serif'; ctx.textAlign = 'center'; ctx.fillText(String(i + 1), at.x + 15, at.y + 18); ctx.textAlign = 'left';
          ctx.fillStyle = '#fff'; ctx.fillText(tagWord(s) + ' · ' + sheetWhen(s), at.x + 38, at.y + 18, at.w - 44);
          cell.ts.forEach((t, j) => {
            const px = at.x + j * (fw + 4), py = at.y + band;
            put(rows[i][j], px, py, fw, fh);
            if (j === 0 && cell.layer) burn(ctx, cell.layer, px, py, fw, fh);
            if (cell.box) boxDraw(ctx, cell.box, i + 1, px, py, fw, fh);  // the box is up on every frame of its mark
            under(t, px, py + fh, fw, cell.ts.length > 1 ? ['start ', 'middle ', 'end '][j] : '');
          });
        });
        return spanLegend(top, tl, sheetWhen);
      });
    }
    // the frames a mark's own pictures show: its first; with a box on a stretch, its middle and last as well, where
    // those are other frames. Each is [the end of the picture's name, a time in the middle of the frame]
    function ownFrames(s) {
      const at = (t) => (fps ? mid(frameOf(t)) : t), out = [['', at(s.t0)]];
      if (!s.box || !(s.t1 > s.t0)) return out;
      const f0 = frameOf(s.t0), f1 = frameOf(s.t1), half = (s.t0 + s.t1) / 2, fm = frameOf(half);
      if (fm !== f0 && fm !== f1) out.push(['-middle', at(half)]);
      if (f1 !== f0) out.push(['-end', at(s.t1)]);
      return out;
    }
    // each mark's own pictures, for the first twelve: the frame at its start at the clip's own size, its paint burned
    // in and its box drawn on, and with a box the middle and last frames with the box. Only those that changed since
    // they were last asked for, or with `all` every one; nothing for a picture takes it away. A view thrown away
    // answers with nothing at all
    function shots(all) {
      if (!alive) return Promise.resolve(undefined);
      if (!tl || !len() || !vw) return Promise.resolve([]);
      const jobs = [], near = fps ? 1.01 / fps : 0;
      tl.sorted().forEach((s, i) => {
        const want = i < CLIP_ROWS ? ownFrames(s) : [];
        for (const part of ['', '-middle', '-end']) {  // a picture no longer wanted is taken away: the box's ones only when it was sent, or may be left from an earlier visit
          const name = s.id + part;
          if (want.some(([p]) => p === part) || bare.has(name) || (part && !sent.has(name) && !hadBox.has(s.id))) continue;
          bare.add(name); sent.delete(name); jobs.push(Promise.resolve([name, null]));
        }
        const box = s.box ? { c: s.c, box: Object.assign({}, s.box) } : null;
        want.forEach(([part, t]) => {
          const name = s.id + part, sig = Math.round(t * 1000) + '|' + sigOf(s) + (box ? '|' + boxSig(s) + '|' + (i + 1) : '');
          bare.delete(name);
          if (!all && sent.get(name) === sig) return;
          sent.set(name, sig);
          const layer = part ? null : layerOf(s);  // paint is on the first frame only
          jobs.push(frames().frame(t, 'full', near).then((img) => {
            if (!img) { sent.delete(name); return null; }
            const out = h('canvas', { width: img.width, height: img.height }), ctx = out.getContext('2d');
            ctx.drawImage(img, 0, 0);
            if (layer) burn(ctx, layer, 0, 0, out.width, out.height);
            if (box) boxDraw(ctx, box, i + 1, 0, 0, out.width, out.height);
            return new Promise((ok) => out.toBlob((blob) => { if (!blob) sent.delete(name); ok(blob ? [name, blob] : null); }, 'image/png'));
          }));
        });
      });
      return Promise.all(jobs).then((made) => (alive ? made.filter(Boolean) : undefined));
    }
    const api = {
      el, kind: 'video', tp, keys: null, tools, picture, shots,
      can: () => editable(),  // whether the marks can be changed now: the batch takes them, and the clip has been read
      shown: () => alive && !!len() && !!vw,  // whether pictures of the marks can be made now
      unsent(id) { sent.delete(id); bare.delete(id); },  // a mark's own picture did not arrive: it is made again at the next send
      slow: true,  // its pictures are frames read from the clip: it must not be thrown away until they are sent
      hint: ['Drag along the lane: a stretch · ', h('kbd', {}, 'M'), ' a moment · ', h('kbd', {}, 'I'), ' ', h('kbd', {}, 'O'), ' its start and end · ', h('kbd', {}, ','), ' ', h('kbd', {}, '.'),
        ' a frame, with Shift ten · ', h('kbd', {}, 'B'), ' paints · ', h('kbd', {}, 'R'), ' a box · ', h('kbd', {}, 'Space'), ' plays · ', h('kbd', {}, '['), ' ', h('kbd', {}, ']'), ' step · ', h('kbd', {}, 'Enter'), ' its note · ', h('kbd', {}, 'Del'), ' takes it away'],
      // put a set of marks on the clip: they are drawn on the lane, listed beside it, painted on, and the keys work them
      attach(marks, o) {
        if (lane) lane.destroy();
        tl = marks; takes = o.editable; editable = () => !!(takes() && len() && vw); broke = o.broken || null;
        tl.describe = clipWhere;
        hadBox.clear(); boxSeen.clear(); boxKey = '';
        for (const s of tl.spans) { boxSeen.set(s.id, boxSig(s)); if (s.box) hadBox.add(s.id); }
        list = spanList(tl, { editable, when: listWhen, goto: (s) => tp.seek(s.t0), loop: spanLoop(tl, tp), looping: () => tp.looping(),
          none: () => bad || (o.editable() ? 'No marks yet. Press M to mark the frame the clip is on, I and O for the start and end of a stretch, or drag along the lane under the bar.' : 'No marks on this clip.') });
        side.replaceChildren(list.el);
        lane = spanLane(strip, tl, map, { editable, seek: (t) => tp.seek(t), fixed: pinned });
        tl.subs.push((what) => {
          if (what === 'notes') { drawBoxes(); return; }  // a box shows its mark's note
          if (what === 'marks') {
            for (const s of tl.spans) for (const k of s.strokes || []) if (k.c !== 'erase' && k.c !== s.c) k.c = s.c;  // paint wears its mark's colour
            for (const id of [...sent.keys()]) if (!tl.get(id.split('-')[0])) sent.delete(id);
            for (const id of [...layers.keys()]) if (!tl.get(id)) layers.delete(id);
            let moved = false;  // a box changed by Undo: what Claude is told of its mark is written again
            for (const s of tl.spans) { const k = boxSig(s); if (boxSeen.has(s.id) && boxSeen.get(s.id) !== k) { tl.stale(s); moved = true; } boxSeen.set(s.id, k); }
            if (moved && list) list.draw();
            if (tl.spans.length && editable()) frames();  // pictures will be wanted: the second copy starts to load
          }
          drawLane(); drawInk(); drawBoxes();
        });
        api.keys = spanKeys(tl, tp, { editable, note: (id) => list.focus(id), more: (e, key) => {
          if (e.code === 'Comma' || key === ',' || key === '<') { step(e.shiftKey ? -10 : -1); return true; }
          if (e.code === 'Period' || key === '.' || key === '>') { step(e.shiftKey ? 10 : 1); return true; }
          if (key === 'i' || key === 'o') { if (editable() && !e.repeat) edge(key === 'i'); return true; }
          if (key === 'b') { if (!e.repeat) setPen(!pen.on); return true; }
          if (key === 'r') { if (bad || !takes()) return false; if (!e.repeat) setBox(!boxing); return true; }  // R is the Box tool; on a clip that takes no marks it sets Redo
          if ((key === 'Delete' || key === 'Backspace') && boxing) return dropBox();  // with the Box tool on, Delete takes the box away and leaves the mark; with no box there, the mark
          return false;
        } });
        if (bad && broke) broke();
        ready();
      },
      set() { tp.rate(S.opts.rate); tp.loopAll(S.opts.loop); },
      destroy() { alive = false; if (ro) ro.disconnect(); if (lane) lane.destroy(); tp.destroy(); video.removeAttribute('src'); try { video.load(); } catch (e) { /* already gone */ } if (copy) copy.destroy(); layers.clear(); },
    };
    showPen(); say(); api.set();
    return api;
  }


  // the pictures of marks on sounds and clips go to the server one after another, in the order they were made
  let markSends = Promise.resolve();
  // marks on a sound or a clip in the closer look: kept on the verdict, with a picture of them beside the batch for Claude
  function markTimed(cand, m, el, bar) {
    const b = S.batch, view = m.timed, tl = newSpans(entry(cand.id).marks, view.kind);
    let timer = 0, pending = false, tools = null;
    const failed = (e) => { pending = true; toast('The picture of the marks was not saved: ' + e.message); };  // it goes again with the next send, not on a timer
    // send the pictures of the marks as they are now. They are made at once, from the view as it is: it may be closed, or
    // show another file, before they have gone. They go to the server after any that are still on their way. What is
    // handed back settles once every picture asked for so far has arrived, also when this call had nothing new to
    // send: a clip is held until then, and so is Submit
    const send = () => {
      clearTimeout(timer); timer = 0;
      if (!pending || (tl.spans.length && !view.shown())) return markSends;  // marks the view cannot draw now (another file is on screen, or it is gone) wait for a later send
      pending = false;
      const sheet = tl.spans.length ? view.picture() : null, shots = view.shots ? view.shots() : null;
      return (markSends = markSends.then(async () => {
        const pic = await sheet, own = await shots;
        if (pic === undefined) return;  // the view was thrown away under its pictures: nothing is sent, where a sheet of empty frames would be
        await API.putMarks(b.id, cand.id, pic).catch(failed);
        for (const [id, blob] of own || []) await API.putMark(b.id, cand.id, id, blob).catch((e) => { if (view.unsent) view.unsent(id); failed(e); });  // a mark's own picture; none takes it away
      }).catch(failed));
    };
    el.classList.toggle('boxkey', view.kind === 'video' && editable());  // R draws a box on a clip, so the Redo call shows no key
    view.attach(tl, { editable, flush: send, broken: () => { if (tools) tools.hidden = true; el.classList.remove('boxkey'); } });
    tl.subs.push((what) => {
      // a change can come late, from a clip held after its closer look was closed (its frames a second, measured then): it
      // is dropped once the page has gone to another batch or another closer look has opened, which may be of this same clip
      if ((what !== 'marks' && what !== 'notes') || S.batch !== b || S.markFlush !== send || !editable()) return;
      entry(cand.id).marks = tl.data(); changed(cand.id);
      pending = true; clearTimeout(timer); timer = setTimeout(send, 1500);
    });
    S.markFlush = send;
    if (editable()) bar.after(tools = h('div', { class: 'tools overtools' }, spanTools(tl, view.tp, () => view.can(), editable), view.tools || null, h('span', { class: 'hint' }, view.hint)));
    return null;
  }

  // marks on a sound or a clip in the Library: they go to Claude as a note, a line for each mark, with the picture of
  // them on it and, for a clip, the picture of each mark's own frame
  function markTimedOver(f, s) {
    const prev = $('.over.marking'); if (prev) prev.remove();
    const clip = f.kind === 'video', named = { url: f.url, label: f.label, name: String(f.url).split('/').pop() };  // the address is not encoded: its last part is the file's name as it is
    const view = clip ? clipView(named, {}) : soundView([named], {});
    const tl = newSpans(null, view.kind);
    let busy = false, tools = null;  // busy: the note is being sent
    view.attach(tl, { editable: () => true, broken: () => { if (tools) tools.hidden = true; } });
    const words = h('textarea', { class: 'field', rows: 2, placeholder: 'Anything else about it (optional)', 'aria-label': 'A note on the whole thing' });
    // while the note is being sent the view stays: a clip's pictures are frames read from the clip itself
    const close = () => {
      if (busy) { toast('Still sending the note'); return; }
      document.removeEventListener('keydown', key); view.destroy(); el.remove(); document.body.style.overflow = '';
    };
    const key = (e) => {
      if (e.key === 'Escape') { if (!/^(TEXTAREA|INPUT)$/.test((e.target || {}).tagName || '') || e.target.type === 'range') { close(); e.stopPropagation(); } return; }  // the volume slider is not a place to type
      if (view.keys && view.keys(e)) e.stopPropagation();
    };
    const send = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      const data = tl.data();
      if (!data) { toast('Mark something first'); return; }
      busy = true; send.disabled = true;
      try {
        const sheet = view.picture(), each = view.shots ? view.shots(true) : null;  // both start now, so a clip's frames are read in one go; every note carries each mark's own picture
        const blob = await sheet, own = new Map(((await each) || []).filter(([, pic]) => pic));
        if (blob === undefined) throw new Error('The pictures of the marks could not be made, so the note was not sent');
        const BOXED = [['-middle', 'middle'], ['-end', 'last']];  // the pictures of a box on a stretch besides its first frame
        const ownName = (i, part) => 'marks ' + s.id + ' mark ' + (i + 1) + (part ? ' ' + BOXED.find(([p]) => p === part)[1] : '') + '.png';
        const boxed = (m, i) => BOXED.filter(([p]) => own.has(m.id + p)).map(([p, at]) => 'the box on its ' + at + ' frame: ' + ownName(i, p)).join(', ');
        const lines = ['Marks on ' + s.title + ' (' + s.id + ', ' + f.label + '), ' + (clip ? 'a clip ' + tl.length.toFixed(2) + ' s' : 'a sound ' + clock(tl.length)) + ' long. The picture of them is attached; each mark is quoted with when it is. KEEP: that part must stay as it is. CUT: that stretch goes.'];
        if (words.value.trim()) lines.push('', words.value.trim());
        lines.push('');
        data.spans.forEach((m, i) => lines.push('- ' + (i + 1) + '. ' + tagWord(m) + ' (' + m.c + '): ' + (m.note ? '"' + m.note + '"' : '(no note)') + (m.where ? '. Where: ' + m.where : '') + (own.has(m.id) ? '. Its own picture: ' + ownName(i) : '') + (boxed(m, i) ? '; ' + boxed(m, i) : '')));
        const files = blob ? [new File([blob], 'marks ' + s.id + '.png', { type: 'image/png' })] : [];
        data.spans.forEach((m, i) => { for (const p of ['', ...BOXED.map(([x]) => x)]) if (own.has(m.id + p)) files.push(new File([own.get(m.id + p)], ownName(i, p), { type: 'image/png' })); });
        const made = (await API.addNote(lines.join('\n'), '', false)).note;
        await sendFiles(made.id, files);
        busy = false; close(); await afterNote(files.length > 1 ? 'Noted, with the pictures of the marks' : 'Noted, with the picture of the marks');
      } catch (e) { toast(e.message); busy = false; send.disabled = false; }
    } }, 'Send as a note');
    const bar = h('div', { class: 'bar' }, h('h3', {}, 'Mark ' + s.title), h('span', { class: 'hint' }, f.label),
      h('button', { class: 'btn small', type: 'button', onclick: close }, 'Close (Esc)'));
    const el = h('div', { class: 'over marking', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Mark ' + s.title }, bar,
      tools = h('div', { class: 'tools overtools' }, spanTools(tl, view.tp, () => view.can(), () => true), view.tools || null, h('span', { class: 'hint' }, view.hint)),
      h('div', { class: 'panes' }, h('div', { class: 'pane' }, view.el)),
      h('div', { class: 'side marking' }, h('div', {}, h('p', { class: 'hint' }, 'Each mark has its own note, in the list beside the ' + (clip ? 'clip' : 'wave') + '.')), h('div', {}, words, h('div', { class: 'jf' }, send))));
    document.body.append(el); document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', key);
  }
  const seq = { token: 0 };

  // ------------------------------------------------------------------- shell
  function top(r) {
    const st = S.state, mine = st.batches.filter((b) => b.status === 'open' || b.status === 'draft').length;
    const confirmQ = st.test_runs.reduce((n, p) => n + p.reports.filter((x) => x.triage.status === 'fixed' && x.triage.confirmed == null).length, 0);
    const noteQ = notesOf().filter((n) => n.waits === 'you').length;
    const tab = (id, label, count, hot) => link(id, { class: (r === id || (id === 'inbox' && (r.startsWith('b.') || r === 'samples')) || (id === 'library' && r.startsWith('s.'))) ? 'on' : '' }, label,
      count ? h('span', { class: 'count' + (hot ? ' hot' : '') }, String(count)) : null);
    return h('header', { class: 'top' },
      h('div', { class: 'brand' }, link('overview', { class: 'name' }, h('b', {}, 'Noc'), 'Studio'),
        st.hub ? h('a', { class: 'proj', href: st.hub, title: 'Your other projects' }, st.project || '', h('span', { 'aria-hidden': 'true' }, ' ▾'))
          : h('small', {}, st.project || '')),
      h('nav', { class: 'nav', 'aria-label': 'Sections' }, tab('overview', 'Overview'), tab('inbox', 'Inbox', mine, true), tab('notes', 'Notes', noteQ, true), st.static || st.site ? null : tab('talk', 'Talk'), tab('library', 'Library'), tab('decisions', 'Decisions', st.decisions.length), tab('build', 'Build'), st.has_test_runs === false ? null : tab('test_runs', 'Test runs', confirmQ, true)),
      h('span', { class: 'spacer' }),
      syncChip(st.sync),
      usageChip(),
      st.launch ? h('button', { class: 'btn small primary launch-btn', type: 'button', onclick: toggleLaunch }, 'Start Claude') : null,
      wakeChip(),
      st.static ? null : h('button', { class: 'btn small', type: 'button', title: 'N', onclick: openNotePop }, 'Note'),
      st.hub ? h('a', { class: 'btn small allp', href: st.hub }, 'All projects') : null, scaleControl(), themeControl(),
      st.static ? h('span', { class: 'sample' }, 'Sample data') : null);
  }
  // Send verdicts: tells a session sitting idle at its prompt that there are verdicts for it to check (studiolib/wake.py)
  const WK = { data: null, busy: false, timer: 0 };
  async function wakeLoad() {
    if (document.hidden && WK.data) return;
    try { WK.data = await call('GET', '/api/wake'); WK.old = false; } catch (e) { WK.old = /no such route/.test(e.message); if (!WK.old) return; }
    for (const b of document.querySelectorAll('.wake-btn')) b.replaceWith(wakeButton());
    if ($('.wakepop')) drawWakePop();
  }
  function wakeWhy(d) {
    if (WK.old) return 'Restart the NocStudio app';
    if (!d) return 'Checking…';
    if (!d.waiting) return 'No verdicts waiting';
    if (!d.sessions.length) return d.hooks ? 'No idle session' : 'Run studio.py hooks install';
    return d.unseen ? '' : 'Already sent';
  }
  function wakeButton() {
    const d = WK.old ? null : WK.data, can = !!(d && d.waiting && d.sessions.length), armed = can && d.unseen > 0;
    return h('button', { class: 'btn small wake-btn' + (armed ? ' primary' : ''), type: 'button', disabled: !can || WK.busy, title: wakeWhy(d) || null, onclick: toggleWake },
      WK.busy ? 'Sending…' : 'Send verdicts', armed ? h('span', { class: 'count' }, String(d.unseen)) : null);
  }
  function wakeChip() {
    if (S.state.static || S.state.site) return null;
    if (!WK.timer) { WK.timer = setInterval(wakeLoad, 5000); wakeLoad(); }
    return wakeButton();
  }
  async function wakeSend(s) {
    closeWake(); WK.busy = true;
    for (const b of document.querySelectorAll('.wake-btn')) b.replaceWith(wakeButton());
    try { await call('POST', '/api/wake', { session: s.id }); toast('Sent to ' + s.title); }
    catch (e) { toast(e.message); }
    WK.busy = false; wakeLoad();
  }
  function closeWake() { const el = $('.wakepop'); if (el) el.remove(); document.removeEventListener('keydown', wakeKey); }
  function wakeKey(e) { if (e.key === 'Escape') { closeWake(); e.stopPropagation(); } }
  function toggleWake() {
    const d = WK.data;
    if ($('.wakepop')) { closeWake(); return; }
    if (!d || !d.sessions.length) return;
    if (d.sessions.length === 1) { wakeSend(d.sessions[0]); return; }
    document.body.append(h('div', { class: 'notepop wakepop', role: 'dialog', 'aria-label': 'Send verdicts' }));
    document.addEventListener('keydown', wakeKey);
    drawWakePop();
  }
  function drawWakePop() {
    const el = $('.wakepop'), d = WK.data || { sessions: [] };
    if (!el) return;
    const ago = (s) => s < 90 ? 'just now' : s < 5400 ? Math.round(s / 60) + ' min' : Math.round(s / 3600) + ' h';
    el.replaceChildren(...[
      h('div', { class: 'jh' }, h('h2', { class: 'grow' }, 'Send verdicts to'), h('button', { class: 'btn small', type: 'button', onclick: closeWake }, 'Close (Esc)')),
      ...d.sessions.map((s) => h('button', { class: 'trow', type: 'button', onclick: () => wakeSend(s) },
        h('span', { class: 'tt' }, s.title), h('span', { class: 'd' }, [s.where, s.talk ? 'Talk' : '', 'idle ' + ago(s.quiet || 0)].filter(Boolean).join(' · ')))),
      d.sessions.length ? null : h('div', { class: 'muted' }, wakeWhy(d))].filter(Boolean));
  }

  // the plan's usage: Claude Code's own /usage, read on the PC (it calls no model, so reading it costs nothing)
  const U = { data: null, err: '', at: 0, busy: false };
  async function usageLoad(fresh) {
    if (U.busy) return;
    U.busy = true; drawUsagePop();
    try { U.data = await call('GET', '/api/usage' + (fresh ? '?fresh=1' : '')); U.err = ''; } catch (e) { U.err = e.message; }
    U.busy = false; U.at = Date.now();
    for (const b of document.querySelectorAll('.usage-btn')) b.replaceWith(usageButton());
    drawUsagePop();
  }
  function usageTop() { const l = (U.data || {}).limits || []; return l.length ? l.reduce((a, b) => (b.pct > a.pct ? b : a)) : null; }
  function usageButton() {
    const t = usageTop();
    return h('button', { class: 'btn small usage-btn' + (t && t.pct >= 80 ? ' hot' : ''), type: 'button', onclick: toggleUsage }, t ? 'Usage ' + Math.round(t.pct) + '%' : 'Usage');
  }
  function usageChip() {
    if (S.state.static || S.state.site) return null;
    if (!U.at || Date.now() - U.at > 5 * 60000) usageLoad(false);
    return usageButton();
  }
  function closeUsage() { const el = $('.usagepop'); if (el) el.remove(); document.removeEventListener('keydown', usageKey); }
  function usageKey(e) { if (e.key === 'Escape') { closeUsage(); e.stopPropagation(); } }
  function toggleUsage() {
    if ($('.usagepop')) { closeUsage(); return; }
    document.body.append(h('div', { class: 'notepop usagepop', role: 'dialog', 'aria-label': 'Usage' }));
    document.addEventListener('keydown', usageKey);
    if (!U.at || Date.now() - U.at > 60000) usageLoad(true); else drawUsagePop();
  }
  function drawUsagePop() {
    const el = $('.usagepop'), d = U.data || {};
    if (!el) return;
    el.replaceChildren(...[  // replaceChildren writes a null out as the word: keep only what is there
      h('div', { class: 'jh' }, h('h2', { class: 'grow' }, 'Usage'),
        h('button', { class: 'btn small', type: 'button', disabled: U.busy, onclick: () => usageLoad(true) }, U.busy ? 'Reading…' : 'Check again'),
        h('button', { class: 'btn small', type: 'button', onclick: closeUsage }, 'Close (Esc)')),
      ...(d.limits || []).map((l) => h('div', { class: 'ubar' + (l.pct >= 80 ? ' hot' : '') },
        h('div', { class: 'jh' }, h('b', { class: 'grow' }, l.name), h('span', {}, Math.round(l.pct) + '% used')),
        h('div', { class: 'um' }, h('span', { style: 'width:' + Math.max(0, Math.min(100, l.pct)) + '%' })),
        l.resets ? h('div', { class: 'muted' }, 'Resets ' + l.resets) : null)),
      U.err ? h('div', { class: 'tline bad' }, U.err) : null,
      d.text ? h('details', {}, h('summary', {}, 'Full text'), h('pre', { class: 'utext' }, d.text)) : U.busy ? h('div', { class: 'muted' }, 'Reading…') : null,
      d.at ? h('div', { class: 'muted' }, 'Read ' + when(d.at)) : null].filter(Boolean));
  }

  // a server copy's Start Claude: asks the launcher beside it (Ignition) to wake the PC and start `claude remote-control`
  // in this project's folder, then the Claude app's Code tab picks the session up. Same address and sign-in as the page.
  const LA = { job: null, err: '', busy: false, desk: null, poll: 0 };
  async function launchCall(method, path, body) {
    const res = await fetch(S.state.launch.url + path, { method, credentials: 'same-origin', cache: 'no-store',
      headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    let data = {};
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (res.status === 401) throw new Error('The launcher answers only behind the sign-in: open this page through the site.');
    if (!res.ok && res.status !== 202) throw new Error(data.error || data.detail || ('The launcher answered ' + res.status));
    return data;
  }
  function closeLaunch() { const el = $('.launchpop'); if (el) el.remove(); document.removeEventListener('keydown', launchKey); }
  function launchKey(e) { if (e.key === 'Escape') { closeLaunch(); e.stopPropagation(); } }
  function toggleLaunch() {
    if ($('.launchpop')) { closeLaunch(); return; }
    document.body.append(h('div', { class: 'notepop launchpop', role: 'dialog', 'aria-label': 'Start Claude' }));
    document.addEventListener('keydown', launchKey);
    drawLaunch();
    if (!LA.busy) launchCall('GET', 'status').then((d) => { LA.desk = d; drawLaunch(); }).catch(() => {});
  }
  async function launchStart(fresh) {
    const lc = S.state.launch;
    LA.busy = true; LA.err = ''; LA.job = { status: 'running', log: 'Asking the launcher…' }; drawLaunch();
    try {
      const made = await launchCall('POST', 'launch', { tool: 'claude', repo: lc.repo, fresh: !!fresh });
      clearTimeout(LA.poll);
      const step = async () => {
        try { LA.job = await launchCall('GET', 'launch/' + encodeURIComponent(made.id)); } catch (e) { LA.err = e.message; LA.busy = false; drawLaunch(); return; }
        if (LA.job.status === 'running') { drawLaunch(); LA.poll = setTimeout(step, 2000); return; }
        LA.busy = false; drawLaunch();
        if (!$('.launchpop')) toast(LA.job.status === 'failed' ? 'Claude did not start: ' + (LA.job.result || 'see Start Claude') : 'Claude is ready');
      };
      await step();
    } catch (e) { LA.err = e.message; LA.busy = false; LA.job = null; drawLaunch(); }
  }
  function drawLaunch() {
    const el = $('.launchpop'), lc = S.state.launch, j = LA.job, d = LA.desk;
    if (!el || !lc) return;
    const lines = j && j.log ? String(j.log).trim().split('\n').slice(-4) : [];
    const ready = j && (j.status === 'launched' || j.status === 'already-running');
    el.replaceChildren(...[
      h('div', { class: 'jh' }, h('h2', { class: 'grow' }, 'Start Claude'), h('button', { class: 'btn small', type: 'button', onclick: closeLaunch }, 'Close (Esc)')),
      d ? h('div', { class: 'muted' }, d.desktop === 'down' ? 'PC asleep' : d.desktop === 'up' ? 'PC awake' : 'PC not known') : null,
      lc.repo ? h('div', { class: 'btns' },
        h('button', { class: 'btn small primary', type: 'button', disabled: LA.busy, onclick: () => launchStart(false) }, LA.busy ? 'Starting…' : 'Carry on'),
        h('button', { class: 'btn small', type: 'button', disabled: LA.busy, onclick: () => launchStart(true) }, 'New conversation'))
        : h('div', { class: 'tline bad' }, lc.why),
      lines.length ? h('pre', { class: 'utext' }, lines.join('\n')) : null,
      ready ? h('div', { class: 'tline ok' }, (j.status === 'already-running' ? 'Already running: ' : 'Started: ') + lc.folder + ' (claude)') : null,
      j && j.status === 'failed' ? h('div', { class: 'tline bad' }, j.result || 'It did not start.') : null,
      LA.err ? h('div', { class: 'tline bad' }, LA.err) : null].filter(Boolean));
  }

  // a Studio kept in step with another copy (sync.py): quiet while it goes through, plain when it does not
  function syncChip(sy) {
    if (!sy) return null;
    const stale = !sy.ok || Date.now() - new Date(sy.ok) > 10 * 60000;
    const tip = [sy.error || sy.waiting, sy.ok ? 'last ' + when(sy.ok) : ''].filter(Boolean).join('. ');
    const bad = sy.error || stale, said = bad ? 'Not synced' : sy.waiting ? 'Sync waiting' : 'Synced';
    return h('button', { class: 'chip sync ' + (bad ? 'bad' : 'ok'), type: 'button', title: tip, 'aria-label': said,
      onclick: () => toast(said + (tip ? '. ' + tip : '')) }, h('span', {}, said));
  }
  async function render(r, keep) { // keep: the same page drawn again with new facts, so the user stays where they were
    cleanup(); closeOver();
    r = r || route();
    const app = $('#app'), rail = keep && $('.rail'), railAt = rail ? rail.scrollTop : 0;
    try {
      if (!S.state) S.state = await API.state();
      if (!UI.synced) { UI.synced = true; const ui = S.state.ui || {}; if (ui.scale) setScale(ui.scale); if (ui.theme && !SHELL) setTheme(ui.theme); if (ui.volume) VOL.use(ui.volume); }
      if (/^(ask|note)\./.test(r)) r = focusOn(r);
      let page;
      if (r.startsWith('b.')) page = await batchPage(r.slice(2));
      else if (r.startsWith('s.')) page = slotPage(r.slice(2));
      else if (r === 'inbox') page = inboxPage();
      else if (r === 'samples') page = samplesPage();
      else if (r === 'library') page = libraryPage();
      else if (r === 'decisions') page = decisionsPage();
      else if (r === 'test_runs') page = testRunsPage();
      else if (r === 'notes') page = notesPage();
      else if (r === 'talk') page = talkPage();
      else if (r === 'build') page = buildPage();
      else page = overviewPage();
      app.replaceChildren(top(r), page);
      if (!keep) window.scrollTo(0, 0);
      else if (railAt && $('.rail')) $('.rail').scrollTop = railAt;
      if (S.focus) reveal();
    } catch (err) {
      app.replaceChildren(S.state ? top(r) : '', h('main', {}, h('div', { class: 'empty' }, String(err.message || err), ' ', link('inbox', {}, 'Back to the inbox'))));
    }
  }

  // ---------------------------------------------------------------- overview
  const MSTONE = { done: 'Done', current: 'In hand', next: 'Next', later: 'Later', parked: 'Parked' };
  const ORDER = ['needed', 'placeholder', 'in_review', 'approved', 'in_use', 'parked'];
  const STEP = { planned: 'Planned', building: 'Being built', built: 'Built', tested: 'Tested', done: 'Done', parked: 'Parked', dropped: 'Dropped' };
  const BAR = ['done', 'tested', 'built', 'building'];
  const ASK = { action: 'To do', decision: 'Decide', play: 'Try it', info: 'To know' };
  const LIVE = { working: 'Working', waiting: 'Waiting for you', asking: 'Needs your OK', background: 'Background work running', stuck: 'Stopped on an error', ended: 'Ended' };
  const LANE = { building: 'Building', testing: 'Testing', waiting: 'Waiting', stuck: 'Stuck' };
  const EVENT = { start: 'Start', done: 'Landed', merge: 'Merge', publish: 'Publish', setback: 'Setback', note: 'Note' };
  const PLAN_SAY = 'plan this project in its Studio';

  // what the user left open or closed stays so through live updates and the next visit
  const OPEN = (() => {
    let map = {};
    try { map = JSON.parse(localStorage.getItem('nocstudio.open') || '{}'); } catch (e) { /* no storage: nothing is remembered */ }
    const key = (k) => ((S.state || {}).project || '') + '|' + k;
    return { get: (k, d) => (key(k) in map ? map[key(k)] : d),
      set: (k, v) => { map[key(k)] = v; try { localStorage.setItem('nocstudio.open', JSON.stringify(map)); } catch (e) { /* as above */ } } };
  })();
  function fold(key, open, cls, summary, ...body) {
    const el = h('details', { class: cls, open: OPEN.get(key, open), 'data-fold': key }, h('summary', {}, summary), body);
    el.addEventListener('toggle', () => OPEN.set(key, el.open));
    return el;
  }
  const dayName = (iso) => { const d = new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')); return isNaN(d) ? iso : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); };
  const span = (sec) => (sec < 90 ? Math.max(1, Math.round(sec)) + ' s' : sec < 5400 ? Math.round(sec / 60) + ' min' : Math.round(sec / 3600) + ' h');
  const pctText = (n) => Math.round(n) + '%';
  const split = (text) => { const at = String(text).indexOf(' :: '); return at < 0 ? [String(text), ''] : [text.slice(0, at), text.slice(at + 4)]; };

  // a button a session filed: the click runs its line on the PC, or opens its file. Only the ask's id goes to the server.
  // the button sits on the row that shows the line, or the path of the file it opens, beside Copy
  function buttonBox(x) {
    const can = !!x.can_run && (x.status === 'open' || x.status === 'later') && !S.state.static && !S.state.site;
    let ran = x.ran || null, timer = 0;
    const press = h('button', { class: 'btn small primary bpress', type: 'button', disabled: !can,
      title: can ? null : 'Only on the PC',
      onclick: (e) => { e.preventDefault(); e.stopPropagation(); go('press'); } }, (x.open ? '\u2197 ' : '\u25B6 ') + x.button);
    const stopBtn = h('button', { class: 'btn small', type: 'button', hidden: true, onclick: () => go('stop') }, 'Stop');
    const status = h('span', { class: 'bstatus' });
    const out = h('pre', { class: 'bout', hidden: true, 'aria-label': 'Output' });
    const what = h('div', { class: 'bwhat' }, h('span', { class: 'grow' }, x.open ? h('code', { class: 'i' }, x.open)
      : [h('code', { class: 'i' }, x.run), x.cwd ? h('span', { class: 'muted' }, ' in ' + x.cwd) : null]), press, copyButton(x.open || x.run));
    const how = h('div', { class: 'brow', hidden: true }, stopBtn, status);
    const box = h('div', { class: 'bbox' }, how, what, out);
    function draw() {
      const running = !!ran && ran.state === 'running';
      press.disabled = !can || running;
      stopBtn.hidden = !running;
      how.hidden = !ran;
      if (!ran) { status.replaceChildren(); out.hidden = true; return; }
      const ok = ran.state === 'done' && ran.code === 0, bad = ran.state === 'done' && ran.code !== 0;
      const chip = { running: 'Running', opened: 'Opened', stopped: 'Stopped', lost: 'Not known', done: ok ? 'Done' : 'Failed' }[ran.state] || ran.state;
      const said = ran.state === 'running' ? 'since ' + when(ran.started)
        : ran.state === 'lost' ? 'started ' + when(ran.started)
        : ran.state === 'opened' ? when(ran.started)
        : (ran.code != null && ran.state === 'done' ? 'exit ' + ran.code + ' \u00b7 ' : '') + when(ran.ended);
      status.replaceChildren(h('span', { class: 'chip ' + (ran.state === 'running' ? 'accent' : ok || ran.state === 'opened' ? 'ok' : bad ? 'bad' : '') }, chip), ' ', h('span', { class: 'sub' }, said));
      if (ran.tail) { out.textContent = ran.tail.length ? ran.tail.join('\n') : '(it printed nothing)'; out.hidden = false; out.scrollTop = out.scrollHeight; }
    }
    async function look() {
      if (!box.isConnected) { clearInterval(timer); timer = 0; return; }
      try {
        ran = (await call('GET', '/api/button/' + encodeURIComponent(x.id))).ran; draw();
        if (!ran || ran.state !== 'running') { clearInterval(timer); timer = 0; }
      } catch (e) { /* the server is restarting; the next beat tries again */ }
    }
    function watch() { if (!timer) timer = setInterval(look, 1000); look(); }
    async function go(action) {
      try {
        ran = Object.assign({}, ran, (await call('POST', '/api/button', { id: x.id, action })).ran); draw();
        if (ran.kind === 'run') watch(); else toast('Opened');
      } catch (e) { toast(e.message); }
    }
    draw();
    if (can && ran && ran.kind === 'run') setTimeout(watch, 0); // the last lines, and more while it runs
    return { el: box };
  }

  function askRow(x) {
    S.notes = S.notes || {};
    const open = x.status === 'open' || x.status === 'later', decide = x.kind === 'decision';
    const note = h('textarea', { class: 'field', rows: 1, placeholder: decide ? 'Your answer' : 'Note', 'aria-label': 'Note on ' + x.title,
      value: S.notes[x.id] || '', oninput: (e) => { S.notes[x.id] = e.target.value; } });
    const send = async (action, text) => {
      const typed = note.value;
      try {
        await API.hand(x.id, action, text === undefined ? typed : text); delete S.notes[x.id]; S.state = await API.state(); render(null, true);
        const said = { done: decide ? 'Answered' : 'Marked done', park: 'Set aside', reopen: 'Open again' }[action];
        if (action === 'reopen') { toast(said); return; }
        undoToast(said + ': ' + x.title, async () => {  // as it was before: open, with what they had typed still in the box
          try { await API.hand(x.id, 'undo'); if (typed) S.notes[x.id] = typed; OPEN.set('ask:' + x.id, true); S.state = await API.state(); render(null, true); toast('Back in Needs you'); }
          catch (e) { toast(e.message); }
        });
      }
      catch (e) { toast(e.message); }
    };
    const fact = (label, text) => (text ? h('div', { class: 'fact' }, h('span', {}, label), h('span', { html: inline(text) })) : null);
    const bb = x.button ? buttonBox(x) : null;
    const body = h('div', { class: 'askbody' },
      x.detail ? h('p', { html: inline(x.detail) }) : null,
      fact('Blocks', x.gates), fact('If you say nothing', x.default), fact('Takes you', x.time), fact('Waiting since', when(x.created)),
      bb ? bb.el : x.run ? h('div', { class: 'runline' }, h('code', { class: 'i' }, x.run), copyButton(x.run)) : null,
      !open && x.his_note ? h('blockquote', {}, x.his_note) : null,
      open ? [note, h('div', { class: 'btns' },
        decide ? h('button', { class: 'btn small primary', type: 'button', onclick: () => (note.value.trim() ? send('done') : toast('Write your answer first')) }, 'Answer') : h('button', { class: 'btn small primary', type: 'button', onclick: () => send('done') }, 'Mark done'),
        decide && x.default ? h('button', { class: 'btn small', type: 'button', onclick: () => send('done', 'Use the default: ' + x.default) }, 'Use the default') : null,
        x.status === 'open' ? h('button', { class: 'btn small', type: 'button', onclick: () => send('park') }, 'Not now') : null)]
        : h('div', { class: 'btns' }, h('button', { class: 'btn small', type: 'button', onclick: () => send('reopen') }, 'Open again')));
    return fold('ask:' + x.id, !!x.urgent, 'need' + (x.urgent && open ? ' urgent' : ''),
      [h('span', { class: 'chip' + (open ? ' accent' : '') }, open ? (ASK[x.kind] || 'To do') : (x.status === 'done' ? 'Done' : 'Set aside')),
        h('span', { class: 'grow' }, x.title), x.urgent && open ? h('span', { class: 'chip bad' }, 'Urgent') : null], body);
  }

  // what moves by the second: the lanes Claude reports and the sessions the hooks see
  function runningBody(live, hooks) {
    const sessions = live.sessions || [], lanes = live.lanes || [], seen = new Set(), out = [];
    const sessionLine = (s) => {
      const bits = [LIVE[s.state] || s.state];
      if (s.state === 'working' && s.quiet > 240) bits.push('quiet for ' + span(s.quiet));
      else if (s.since) bits.push('for ' + span(Math.max(1, (Date.now() - new Date(s.since)) / 1000)));
      return bits.join(' · ');
    };
    const sessionBits = (s) => [
      s.doing ? h('div', { class: 'doing' }, s.doing) : (s.state !== 'working' && s.said ? h('div', { class: 'doing said' }, s.said) : null),
      (s.agents || []).length ? h('div', { class: 'agents' }, s.agents.map((a) => h('div', {}, h('span', { class: 'dot live' }), h('b', {}, a.type), a.doing ? ' · ' + a.doing : ''))) : null,
      (s.background || []).length ? h('div', { class: 'agents' }, s.background.map((b) => h('div', {}, h('span', { class: 'dot live' }), h('b', {}, b.type), b.what ? ' · ' + b.what : ''))) : null,
      s.tasks && s.tasks.of ? h('div', { class: 'tasks' }, h('div', { class: 'bar-status' }, h('i', { class: 'sp-done', style: 'width:' + (100 * s.tasks.done / s.tasks.of) + '%' })), h('span', {}, s.tasks.done + ' of ' + s.tasks.of + ' tasks')) : null];
    for (const lane of lanes) {
      const s = sessions.find((x) => x.id === lane.session);
      if (s) seen.add(s.id);
      const moving = (lane.state === 'building' || lane.state === 'testing') && (!s || s.state === 'working' || s.state === 'background');
      out.push(h('div', { class: 'pill ' + lane.state + (s && s.state === 'asking' ? ' asking' : '') },
        h('div', { class: 'pillhead' }, h('span', { class: 'dot' + (moving ? ' live' : '') }), h('b', { class: 'grow' }, lane.name),
          lane.eta ? h('span', { class: 'chip' }, 'ETA ' + lane.eta) : null),
        h('div', { class: 'sub' }, [lane.milestone || '', s ? sessionLine(s) : (LANE[lane.state] || lane.state) + (lane.updated ? ' · updated ' + when(lane.updated) : '')].filter(Boolean).join(' · ')),
        lane.note ? h('div', { class: 'lanenote', html: inline(lane.note) }) : null, s ? sessionBits(s) : null));
    }
    for (const s of sessions) {
      if (seen.has(s.id)) continue;
      out.push(h('div', { class: 'pill session ' + s.state },
        h('div', { class: 'pillhead' }, h('span', { class: 'dot' + (s.state === 'working' || s.state === 'background' ? ' live' : '') }),
          h('b', { class: 'grow' }, s.title || s.prompt || (s.agent === 'codex' ? 'A Codex session' : 'A Claude Code session')),
          s.agent === 'codex' ? h('span', { class: 'chip' }, 'Codex') : null, s.where ? h('span', { class: 'chip' }, s.where) : null),
        h('div', { class: 'sub' }, sessionLine(s)), sessionBits(s)));
    }
    if (!out.length) return [h('div', { class: 'empty' }, 'Nothing running.')];
    return [h('div', { class: 'pills' }, out)];
  }

  function dayChart(days) {
    const W = 920, H = 190, L = 34, R = 10, T = 14, B = 24, n = days.length;
    const top = Math.min(100, Math.max(20, Math.ceil(Math.max(...days.map((d) => d.pct)) / 10) * 10 + 10));
    const most = Math.max(3, ...days.map((d) => d.landed));
    const x = (i) => L + (n === 1 ? 0.5 : i / (n - 1)) * (W - L - R), y = (p) => T + (1 - p / top) * (H - T - B);
    const ns = 'http://www.w3.org/2000/svg';
    const el = (tag, attrs, text) => { const e = document.createElementNS(ns, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text) { const t = document.createElementNS(ns, 'title'); t.textContent = text; e.append(t); } return e; };
    const svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'chart', role: 'img', 'aria-label': 'Progress by day, from ' + pctText(days[0].pct) + ' to ' + pctText(days[n - 1].pct) });
    for (const p of [0, top / 2, top]) {
      svg.append(el('line', { x1: L, x2: W - R, y1: y(p), y2: y(p), class: 'cgrid' }));
      const label = el('text', { x: L - 6, y: y(p) + 4, class: 'axis', 'text-anchor': 'end' }); label.textContent = Math.round(p); svg.append(label);
    }
    const bw = Math.max(3, Math.min(18, (W - L - R) / n * 0.5));
    days.forEach((d, i) => {
      if (d.landed) svg.append(el('rect', { x: x(i) - bw / 2, width: bw, y: y(0) - (d.landed / most) * (H - T - B) * 0.45, height: (d.landed / most) * (H - T - B) * 0.45, class: 'landed' },
        dayName(d.date) + ': ' + d.landed + (d.landed === 1 ? ' step landed' : ' steps landed')));
    });
    svg.append(el('path', { d: days.map((d, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(d.pct).toFixed(1)).join(' '), class: 'cline' }));
    days.forEach((d, i) => {
      svg.append(el('circle', { cx: x(i), cy: y(d.pct), r: n > 30 ? 2 : 3, class: 'cpt' }, dayName(d.date) + ': ' + pctText(d.pct)));
      if (d.setbacks) svg.append(el('path', { d: 'M' + (x(i) - 5) + ' ' + (T - 8) + ' h10 l-5 9 z', class: 'setback' }, dayName(d.date) + ': ' + d.setbacks + (d.setbacks === 1 ? ' setback' : ' setbacks')));
    });
    for (const i of [...new Set([0, Math.floor((n - 1) / 2), n - 1])]) {
      const label = el('text', { x: x(i), y: H - 6, class: 'axis', 'text-anchor': i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle' }); label.textContent = dayName(days[i].date); svg.append(label);
    }
    return svg;
  }

  function overviewPage() {
    const st = S.state, ov = st.overview || {}, now = ov.now || {}, game = ov.repo || ov.game || {}, hands = ov.hands || [];
    const board = ov.board || { pct: 0, share: {}, counts: {}, milestones: ov.milestones || [], days: [], pace: {}, events: [], lanes: [] };
    const ms = board.milestones || [], cur = ms.find((m) => m.status === 'current');
    const mine = st.batches.filter((b) => b.status === 'open' || b.status === 'draft');
    const sent = st.batches.filter((b) => b.status === 'submitted');
    const confirms = st.test_runs.reduce((n, p) => n + p.reports.filter((x) => x.triage.status === 'fixed' && x.triage.confirmed == null).length, 0);
    const openHands = hands.filter((x) => x.status === 'open').sort((a, b) => (b.urgent ? 1 : 0) - (a.urgent ? 1 : 0));
    const laterHands = hands.filter((x) => x.status === 'later'), oldHands = hands.filter((x) => x.status === 'done' || x.status === 'parked')
      .sort((a, b) => String(b.answered || b.updated || '').localeCompare(String(a.answered || a.updated || '')));  // the last one answered first
    const myNotes = notesOf().filter((n) => n.waits === 'you');
    const owed = mine.length + (confirms ? 1 : 0) + openHands.length + myNotes.length;
    const col = h('div', { class: 'hudmain' });

    // a project that has not been planned yet says so, and says how; the user can hide it, and a link under the milestones brings it back
    const todo = (ov.setup || []).filter((x) => !x.optional), left = todo.filter((x) => !x.done);
    const setupShown = async (hidden) => {
      try { await API.setup(hidden); S.state = await API.state(); render(null, true); } catch (e) { toast(e.message); }
    };
    const hideSetup = h('button', { class: 'btn small', type: 'button',
      onclick: (e) => { e.preventDefault(); e.stopPropagation(); setupShown(true); } }, 'Hide');
    if (left.length && !ov.setup_hidden) col.append(fold('setup', true, 'setup',
      [h('span', { class: 'grow' }, 'Getting organised'), h('span', { class: 'chip accent' }, (todo.length - left.length) + ' of ' + todo.length), hideSetup],
      h('ul', { class: 'ticks' }, (ov.setup || []).map((x) => h('li', { class: x.done ? 'done' : '' }, h('span', { class: 'tick' }, x.done ? '✓' : ''), x.title))),
      // one line covers the whole list: the guide in the tool's docs folder walks the agent through every line of it
      ((say) => h('div', { class: 'say' }, h('code', { style: 'overflow-wrap:anywhere;min-width:0' }, say), copyButton(say)))(
        ov.move_in ? 'Read ' + ov.move_in + ' and move this project into NocStudio.' : PLAN_SAY)));

    // how far along, in one number
    const done = board.milestones_done || 0;
    col.append(h('section', { class: 'gauge' },
      h('div', { class: 'gaugetop' },
        h('div', { class: 'big num' }, pctText(board.pct || 0)),
        h('div', { class: 'grow' }, h('h1', { class: (now.headline || '').length > 110 ? 'long' : '' }, now.headline || st.project || 'Overview'), now.goal ? h('p', { class: 'muted', html: inline(now.goal) }) : null)),
      h('div', { class: 'bar-status tall', role: 'img', 'aria-label': BAR.map((k) => STEP[k] + ' ' + Math.round((board.share || {})[k] || 0) + '%').join(', ') },
        BAR.filter((k) => (board.share || {})[k]).map((k) => h('i', { class: 'sp-' + k, style: 'width:' + board.share[k] + '%', title: STEP[k] + ': ' + ((board.counts || {})[k] || 0) }))),
      h('div', { class: 'legend' }, BAR.concat(['planned']).map((k) => h('span', {}, h('span', { class: 'dot sp-' + k }), STEP[k] + ' ', h('b', {}, String((board.counts || {})[k] || 0)))),
        h('span', { class: 'muted' }, board.steps ? board.steps + ' steps' : 'No steps yet')),
      ms.length ? h('div', { class: 'track', role: 'img', 'aria-label': ms.map((m) => m.id + ' ' + MSTONE[m.status]).join(', ') },
        ms.map((m) => h('div', { class: 'seg ' + m.status, title: m.name + ': ' + MSTONE[m.status] + (m.steps ? ', ' + pctText(m.pct) : '') }, h('b', {}, m.id), h('span', {}, m.name)))) : null,
      ms.length || (left.length && ov.setup_hidden) ? h('p', { class: 'muted' }, ms.length ? done + ' of ' + ms.length + ' milestones complete' : null,
        left.length && ov.setup_hidden ? [ms.length ? ' · ' : null, h('a', { href: '#', class: 'setuplink', title: left.length + ' left',
          onclick: (e) => { e.preventDefault(); setupShown(false); } }, 'Set up')] : null) : null));

    // the few facts worth a glance
    const tile = (label, value, sub, href) => h(href ? 'a' : 'div', { class: 'stat', href: href || null }, h('span', { class: 'label' }, label), h('span', { class: 'value' }, value), sub ? h('span', { class: 'sub' }, sub) : null);
    const pace = board.pace || {};
    const tiles = [
      cur ? tile('In hand', cur.id + ' · ' + cur.name, [cur.unplanned ? 'no steps yet' : pctText(cur.pct), cur.eta ? 'ETA ' + cur.eta : ''].filter(Boolean).join(' · ')) : null,
      pace.finish ? tile('Done at this pace', dayName(pace.finish), '+' + pace.per_day + ' points a day over ' + pace.over_days + (pace.over_days === 1 ? ' day' : ' days'))
        : (board.days || []).length > 1 ? tile('Done at this pace', 'No telling', 'still for ' + (pace.over_days || 7) + ' days') : null,
      now.finish ? tile('Claude\'s estimate', now.finish) : null,
      (now.counters || []).map((c) => tile(c.name, c.have + ' / ' + c.of)),
      now.build || game.version ? tile('Build', now.build || game.version, game.since_now ? game.since_now + (game.since_now === 1 ? ' commit' : ' commits') + ' since' : (now.gate || ''), '#build') : null];
    if (tiles.flat().filter(Boolean).length) col.append(h('div', { class: 'tiles' }, tiles));

    // running now: redrawn by itself every few seconds
    const running = h('div', { class: 'runbody' }, runningBody(ov.live || {}, ov.hooks));
    col.append(h('section', {}, h('div', { class: 'sec-head' }, h('h2', {}, 'Running now')), running));
    if (!STATIC && API.live) {
      const timer = setInterval(async () => { try { const live = await API.live(); (S.state.overview || {}).live = live; running.replaceChildren(...runningBody(live, ov.hooks)); } catch (e) { /* next beat */ } }, 3000);
      S.cleanup.push(() => clearInterval(timer));
    }

    // day by day
    const days = board.days || [];
    if (days.length > 1) col.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Day by day')), dayChart(days)));

    // the road, and the steps of each stretch
    if (ms.length) col.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Milestones')),
      h('div', { class: 'rows' }, ms.map((m) => fold('ms:' + m.id, false, 'ms ' + m.status,
        [h('span', { class: 'mid' }, m.id), h('span', { class: 'grow' }, h('span', { class: 'title' }, m.name), m.note ? h('span', { class: 'sub' }, ' · ' + m.note) : null),
          m.eta && m.status !== 'done' ? h('span', { class: 'chip' }, 'ETA ' + m.eta) : null,
          h('span', { class: 'mbar' }, h('span', { class: 'bar-status' }, h('i', { class: 'sp-done', style: 'width:' + m.pct + '%' })), h('span', { class: 'num' }, m.unplanned ? '–' : pctText(m.pct))),
          h('span', { class: 'status' }, h('span', { class: 'dot ms-' + m.status }), MSTONE[m.status] || m.status)],
        h('div', { class: 'msbody' }, m.goal ? h('p', { html: inline(m.goal) }) : null,
          m.question ? h('p', { class: 'muted' }, h('i', {}, m.question)) : null,
          (m.steps || []).length ? h('ul', { class: 'steps' }, m.steps.map((s) => h('li', { class: 'st ' + s.status }, h('span', { class: 'dot sp-' + s.status }), h('span', { class: 'grow' }, s.name, s.note ? h('span', { class: 'muted' }, ' · ' + s.note) : null),
            h('span', { class: 'sub' }, STEP[s.status] + (s.date ? ' · ' + dayName(s.date) : '')))))
            : (m.status === 'done' ? null : h('p', { class: 'muted' }, 'No steps yet.'))))))));

    // the log
    const log = board.events || [];
    if (log.length) {
      const row = (e) => h('div', { class: 'row ev ' + e.kind }, h('span', { class: 'chip ' + ({ setback: 'bad', merge: 'ok', publish: 'ok', done: 'keep' }[e.kind] || '') }, EVENT[e.kind] || e.kind),
        h('div', { class: 'grow' }, h('span', { html: inline(e.text) }), e.milestone ? h('span', { class: 'muted' }, ' · ' + e.milestone) : null), h('span', { class: 'sub' }, when(e.ts)));
      col.append(h('section', {}, h('div', { class: 'sec-head' }, h('h2', {}, 'Log')),
        h('div', { class: 'rows' }, log.slice(0, 10).map(row)),
        log.length > 10 ? fold('log', false, 'brief', 'Earlier (' + (log.length - 10) + ')', h('div', { class: 'rows', style: 'margin-top:8px' }, log.slice(10).map(row))) : null));
    }

    if (!ms.length && !hands.length && !st.batches.length && !left.length) col.append(h('div', { class: 'empty' }, 'Nothing here yet.'));

    // the rail: everything that waits on the user, and what comes next
    const asks = h('div', { class: 'asks' });
    for (const b of mine) asks.append(link('b.' + b.id, { class: 'need go' },
      h('span', { class: 'chip accent' }, b.status === 'draft' ? 'Started' : (b.mode === 'question' ? 'Answer' : 'Judge ' + b.count)), h('span', { class: 'grow' }, b.title), h('span', { class: 'chip' }, KIND[b.kind] || b.kind)));
    if (confirms) asks.append(link('test_runs', { class: 'need go' }, h('span', { class: 'chip accent' }, 'Confirm'), h('span', { class: 'grow' }, confirms === 1 ? 'One fix to confirm' : confirms + ' fixes to confirm')));
    for (const n of myNotes) asks.append(link('notes', { class: 'need go' },
      h('span', { class: 'chip accent' }, n.choice_at !== null && n.choice_at !== undefined ? 'Pick' : n.status === 'confirm' ? 'Confirm' : 'Reply'), h('span', { class: 'grow', html: inline(clip(n.status === 'confirm' ? n.reading || n.text : n.text, 110)) }), h('span', { class: 'chip' }, 'Note')));
    for (const x of openHands) asks.append(askRow(x));
    const setAll = (open) => { asks.querySelectorAll('details').forEach((d) => { d.open = open; OPEN.set(d.dataset.fold, open); }); };
    const next = (now.next || []).map(split);
    const rail = h('aside', { class: 'rail', 'aria-label': 'Needs you' },
      h('div', { class: 'railhead' }, h('h2', {}, 'Needs you'), owed ? h('span', { class: 'count hot' }, String(owed)) : null, h('span', { class: 'grow' }), notifySwitch(),
        openHands.length > 1 ? [h('button', { class: 'btn small', type: 'button', onclick: () => setAll(true) }, 'Open all'), h('button', { class: 'btn small', type: 'button', onclick: () => setAll(false) }, 'Close all')] : null),
      owed ? asks : h('div', { class: 'empty' }, 'Nothing waiting.'),
      sent.length ? h('div', { class: 'say' }, h('span', {}, sent.length + ' waiting on Claude'), h('code', {}, SAY), copyButton(SAY)) : null,
      laterHands.length ? fold('later', false, 'brief', 'Later (' + laterHands.length + ')', h('div', { class: 'asks' }, laterHands.map(askRow))) : null,
      oldHands.length ? fold('answered', false, 'brief', 'Answered (' + oldHands.length + ')', h('div', { class: 'asks' }, oldHands.map(askRow))) : null,
      next.length ? [h('h2', { class: 'railsub' }, 'Next up'), h('ul', { class: 'nextup' }, next.map(([text, eta]) => h('li', {}, h('span', { html: inline(text) }), eta ? h('span', { class: 'sub' }, eta) : null)))] : null);
    return h('main', { class: 'hud' }, col, rail);
  }

  // ------------------------------------------------------------ the build in hand
  function buildPage() {
    const st = S.state, ov = st.overview || {}, now = ov.now || {}, game = ov.repo || ov.game || {}, main = h('main', {});
    const list = (title, items, cls) => ((items || []).length ? h('div', { class: 'ovcol' }, h('h3', {}, title), h('ul', { class: cls || 'look' }, items.map((x) => h('li', { html: inline(split(x)[0]) })))) : null);
    const commits = game.commits || [];
    main.append(h('section', {},
      h('h1', {}, now.build ? 'Build ' + now.build : 'The build in hand'),
      h('div', { class: 'meta', style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
        now.gate ? h('span', { class: 'chip ok' }, 'Gate ' + now.gate) : null,
        game.branch ? h('span', { class: 'chip' }, game.branch + ' @ ' + game.head) : null,
        now.spec ? h('span', { class: 'chip' }, now.spec) : null,
        now.updated ? h('span', { class: 'sub muted' }, 'written ' + when(now.updated)) : null,
        game.since_now ? h('span', { class: 'chip redo' }, game.since_now + ' commit' + (game.since_now === 1 ? '' : 's') + ' since') : null)));
    if (!(now.built || []).length && !(now.start || []).length && !commits.length) main.append(h('div', { class: 'empty' }, 'No build yet.'));
    main.append(h('section', {}, h('div', { class: 'ovgrid' }, list('In the build', now.built), list('Next', now.next)),
      (now.start || []).length ? h('div', { class: 'ovcol' }, h('h3', {}, 'Start it'), now.start.map((line) => h('div', { class: 'runline' }, h('code', { class: 'i' }, line), copyButton(line)))) : null,
      (now.known || []).length ? fold('known', false, 'brief', 'Known (' + now.known.length + ')', h('ul', { class: 'plain' }, now.known.map((x) => h('li', { html: inline(x) })))) : null,
      commits.length ? fold('commits', false, 'brief', 'Latest commits',
        h('div', { class: 'rows', style: 'margin-top:8px' }, commits.map((c) => h('div', { class: 'row' }, h('span', { class: 'mono muted' }, c.sha), h('div', { class: 'grow' }, c.subject), h('span', { class: 'sub' }, when(c.date)))))) : null));

    // what the project still lacks
    const slots = st.slots || [];
    if (slots.length) {
      const groups = {}; slots.forEach((s) => { const g = groups[s.group || 'Other'] = groups[s.group || 'Other'] || { n: 0 }; g.n++; g[s.status] = (g[s.status] || 0) + 1; });
      const lack = (g) => (g.needed || 0) + (g.placeholder || 0);
      const names = Object.keys(groups).sort((a, b) => lack(groups[b]) - lack(groups[a]) || a.localeCompare(b));
      const missing = slots.filter((s) => s.status === 'needed' || s.status === 'placeholder').length;
      main.append(h('section', {},
        h('div', { class: 'sec-head' }, h('h2', {}, 'What the project still lacks'), h('p', {}, missing + ' missing · ' + slots.filter((x) => x.status === 'in_review').length + ' in review · ' + slots.length + ' in all'), link('library', {}, 'Library')),
        h('div', { class: 'legend' }, ORDER.map((s) => h('span', {}, h('span', { class: 'dot st-' + s }), SLOT[s]))),
        h('div', { class: 'rows' }, names.map((name) => { const g = groups[name]; return link('library', { class: 'row lack', onclick: (e) => { e.preventDefault(); S.libGroup = name; go('library'); } },
          h('div', { class: 'gname' }, name),
          h('div', { class: 'bar-status grow' }, ORDER.filter((s) => g[s]).map((s) => h('i', { class: 'st-' + s, style: 'width:' + (100 * g[s] / g.n) + '%', title: g[s] + ' ' + SLOT[s] }))),
          h('div', { class: 'sub gcount' }, [g.needed ? g.needed + ' needed' : '', g.placeholder ? g.placeholder + ' stand-in' + (g.placeholder === 1 ? '' : 's') : '', g.in_review ? g.in_review + ' in review' : ''].filter(Boolean).join(' · ') || 'all ' + g.n + ' settled')); }))));
    }
    return main;
  }

  // -------------------------------------------------------------- one asset
  function slotPage(id) {
    const s = (S.state.slots || []).find((x) => x.id === id);
    if (!s) throw new Error('No such asset: ' + id);
    const main = h('main', {}), cur = s.current, files = s.files || [];
    const openBatch = s.open_batch && S.state.batches.find((b) => b.id === s.open_batch);
    main.append(h('section', { class: 'bhead' },
      h('div', { class: 'crumb' }, link('library', {}, 'Library'), h('span', {}, '/'), h('span', {}, s.group || 'Other'), h('span', { class: 'mono muted' }, s.id)),
      h('h1', {}, s.title),
      h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center' }, h('span', { class: 'status', style: 'width:auto' }, h('span', { class: 'dot st-' + s.status }), SLOT[s.status] || s.status),
        s.kind ? h('span', { class: 'chip' }, KIND[s.kind] || s.kind) : null, s.needed_by ? h('span', { class: 'chip' }, 'For ' + s.needed_by) : null,
        openBatch ? link('b.' + openBatch.id, { class: 'btn small on' }, openBatch.status === 'open' || openBatch.status === 'draft' ? 'Waiting for your verdict' : 'See its batch') : null,
        cur && cur.batch && S.state.batches.some((b) => b.id === cur.batch) ? link('b.' + cur.batch, { class: 'btn small' }, 'The batch it came from') : null),
      s.notes ? h('p', { class: 'muted', style: 'max-width:80ch' }, s.notes) : null,
      cur ? h('div', { class: 'closed' }, h('h3', {}, (cur.working || cur.edited_by_user ? 'Latest: v' : 'Approved: v') + cur.version + (cur.title ? ' · ' + cur.title : '') + (cur.score ? ' · ' + cur.score + '/10' : '')),
        cur.note ? h('blockquote', {}, cur.note) : null,
        h('p', { class: 'sub muted' }, [cur.date ? String(cur.date).slice(0, 10) : '', cur.source || ''].filter(Boolean).join(' · '))) : null,
      s.project_path ? h('p', { class: 'mono muted' }, 'Used at ' + s.project_path) : null));

    S.opts.clip = ''; S.opts.rotate = false; S.opts.wire = false; S.opts.loop = false; S.opts.rate = 1;
    const show = (f) => {
      const stage = h('div', { class: 'stage' });
      if (f.kind === 'model') {
        const sel = h('select', { 'aria-label': 'Motion' }, h('option', { value: '' }, 'Still'));
        const v = modelView(f.url, { zoom: true, clip: f.clip, ready: (view) => { if (f.clip) return; for (const c of view.clips) sel.append(h('option', { value: c.name }, c.name)); sel.hidden = !view.clips.length; } });
        sel.hidden = true; sel.addEventListener('change', () => v.set({ clip: sel.value, playing: true }));
        const tog = (label, key) => { let on = key === 'ref' || key === 'playing'; const btn = h('button', { class: 'btn small' + (on ? ' on' : ''), type: 'button', onclick: () => { on = !on; btn.classList.toggle('on', on); v.set({ [key]: on }); } }, label); return btn; };
        S.cleanup.push(() => v.destroy && v.destroy());
        v.el.classList.add('tall'); stage.append(v.el);
        return h('article', { class: 'tile wide' }, h('div', { class: 'thead' }, h('h3', {}, f.label), sel,
          f.clip ? [tog('Play', 'playing'), rateButtons(() => v.set({ rate: S.opts.rate }))] : null,
          tog('Turntable', 'rotate'), f.clip ? null : tog('Wireframe', 'wire'), tog('1.8 m figure', 'ref'), STATIC ? null : markButton(f)), stage);
      }
      if (f.kind === 'audio') {
        const p = audioPlayer(f.url, f.label); S.cleanup.push(() => p.destroy());
        stage.append(p.el);
        return h('article', { class: 'tile' }, h('div', { class: 'thead' }, h('span', { class: 'mono muted grow', style: 'overflow-wrap:anywhere' }, f.label),
          STATIC ? null : h('button', { class: 'btn small', type: 'button', title: 'Mark moments and stretches of it, with a note for each, and send them to Claude', onclick: () => { p.stop(); markTimedOver(f, s); } }, 'Mark')), stage);
      }
      let facts = null;
      if (f.kind === 'video') {  // with its sound: a cut is judged heard; the first frame shows before it plays, and its length and size by its name
        const v = h('video', { class: 'media', src: f.url + '#t=0.001', controls: true, playsinline: true, preload: 'metadata' });
        facts = h('span', { class: 'sub muted' });
        v.addEventListener('loadedmetadata', () => { const s = v.duration, m = Math.floor(s / 60), sec = Math.round(s - m * 60);
          facts.textContent = (isFinite(s) ? m + ':' + String(sec).padStart(2, '0') : '') + (v.videoWidth ? ' · ' + v.videoWidth + ' × ' + v.videoHeight : ''); });
        stage.append(v);
      }
      else if (f.kind === 'text') {
        const holder = h('div', { class: 'option' }, 'Loading'), mine = f.from === 'library' && cur && !STATIC;
        API.bytes(f.url).then((buf) => { const t = new TextDecoder().decode(buf); if (mine) holder.replaceWith(libText(s, f, t)); else holder.replaceChildren(md(t)); }).catch(() => holder.replaceChildren('Could not read the file.'));
        stage.className = ''; stage.append(holder);
        if (mine) return h('article', { class: 'tile' }, stage);
      }
      else stage.append(h('img', { class: 'fit', src: f.url, alt: f.label, loading: 'lazy', onclick: (e) => shot(e.target.src) }));
      return h('article', { class: 'tile' }, stage, h('div', { class: 'thead' }, h('span', { class: 'mono muted grow', style: 'overflow-wrap:anywhere' }, f.label), facts,
        (f.kind === 'image' || f.kind === 'texture') && !STATIC ? markButton(f) : null,
        f.kind === 'video' && !STATIC ? h('button', { class: 'btn small', type: 'button', title: 'Mark moments and stretches of it, paint on a frame, with a note for each mark, and send them to Claude',
          onclick: () => { const v = $('video', stage); if (v) v.pause(); markTimedOver(f, s); } }, 'Mark') : null));
    };
    function markButton(f) { return h('button', { class: 'btn small', type: 'button', title: 'Mark parts of it in colours, with a note for each, and send it to Claude', onclick: () => markOver(f, s) }, 'Mark'); }
    const mo = motionOf(s.motion);
    if (mo) main.append(h('section', {}, h('h2', {}, 'The motion, looping in place'),
      h('p', { class: 'muted', style: 'max-width:80ch' }, 'Baked from the project\'s own drawing of it' + (mo.seconds ? ', ' + mo.seconds.toFixed(2) + ' s a loop' : '') + '. The light here is the page\'s, not the hall\'s.'),
      h('div', { class: 'grid', style: '--tile:760px' }, show({ kind: 'model', url: mo.url, label: mo.clip.replace(/_/g, ' '), clip: mo.clip }))));
    for (const [from, title] of [['repo', 'In the project today'], ['library', cur && (cur.working || cur.edited_by_user) ? 'In the Studio' : 'The approved master']]) {
      const rows = files.filter((f) => f.from === from).sort((a, b) => (b.kind === s.kind) - (a.kind === s.kind));
      if (!rows.length) continue;
      const wide = rows.some((f) => f.kind === 'model') || rows.length === 1;
      const panel = from === 'library' && !STATIC ? sharePanel(rows, s.title + (cur && cur.version ? ' v' + cur.version : '')) : null;
      main.append(h('section', {}, h('div', { class: 'sechead' }, h('h2', {}, title + (rows.length > 1 ? ' · ' + rows.length + ' files' : '')), panel ? panel.button : null),
        panel ? panel.el : null,
        h('div', { class: 'grid', style: '--tile:' + (wide ? 760 : rows[0].kind === 'audio' ? 380 : 420) + 'px' }, rows.map(show))));
    }
    if (!files.length && !mo) main.append(h('div', { class: 'empty' }, s.status === 'needed' ? 'Nothing exists for this yet.' : 'This has no file you can open here: it lives in the project as numbers or motion data' + (s.kind === 'in_app' ? ', and is judged in the running project.' : '.')));
    const past = (s.history || []).slice(0, -1).reverse();
    if (past.length) main.append(h('section', {}, h('h2', {}, 'Earlier versions'), h('div', { class: 'rows' }, past.map((v) => h('div', { class: 'row' },
      h('span', { class: 'mono muted' }, 'v' + v.version), h('div', { class: 'grow' }, v.title || v.candidate || ''), h('span', { class: 'sub' }, v.date ? String(v.date).slice(0, 10) : ''))))));
    return main;
  }

  // ------------------------------------------------------------ share links
  const SHARE_TIMES = [['1h', '1 hour'], ['12h', '12 hours'], ['1d', '1 day'], ['3d', '3 days'], ['7d', '7 days'], ['30d', '30 days'], ['90d', '90 days']];
  const whenEnds = (iso) => new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const isClip = (url) => /\.(mp4|webm|mov|m4v)$/i.test(String(url || ''));
  // one frame of a clip for a chat's preview of the link: about a second in (the middle of a shorter clip), as JPEG at most 1280 px on its long side; null when the clip will not give one
  function grabStill(url) {
    return new Promise((done) => {
      let over = false, timer = null;
      const v = h('video', { muted: true, playsinline: true, preload: 'auto' });
      const end = (out) => { if (over) return; over = true; clearTimeout(timer); v.removeAttribute('src'); v.load(); done(out); };
      timer = setTimeout(() => end(null), 8000);
      v.addEventListener('error', () => end(null));
      v.addEventListener('loadedmetadata', () => { const d = v.duration; v.currentTime = isFinite(d) && d > 0 ? (d >= 2 ? 1 : d / 2) : 1; });
      v.addEventListener('seeked', () => {
        try {
          const w = v.videoWidth, hh = v.videoHeight;
          if (!w || !hh) { end(null); return; }
          const k = Math.min(1, 1280 / Math.max(w, hh));
          const c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(hh * k));
          c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
          const fits = (s) => s.startsWith('data:image/jpeg;base64,') && (s.length - 23) * 3 / 4 <= 1024 * 1024;
          let out = c.toDataURL('image/jpeg', 0.85);
          if (!fits(out)) out = c.toDataURL('image/jpeg', 0.6);
          end(fits(out) ? out : null);
        } catch (e) { end(null); }
      });
      v.src = rel(url);
    });
  }
  function shareResult(rec, onStop) {
    const box = h('div', { class: 'shareout' });
    // a new link reaches the server with the next sync: the PC's server asks the public address every few seconds, for three minutes at most
    const live = h('p', { class: 'muted', role: 'status' }, 'On its way to the server. A new link opens in a minute or two; this says when it works.');
    let tries = 0;
    const ask = async () => {
      if (rec.state !== 'live' || (tries && !box.isConnected)) return;
      tries++;
      let res = null;
      try { res = await API.share({ action: 'check', id: rec.id }); } catch (e) { res = null; }
      if (rec.state !== 'live') return;
      if (res && !res.public) { live.hidden = true; return; }
      if (res && res.live) { live.textContent = 'It works now: the link opens for anyone who has it.'; return; }
      if (tries >= 36) { live.textContent = 'Not on the server after three minutes. The Studio\'s sync may be held up; the link opens once a sync goes through.'; return; }
      setTimeout(ask, 5000);
    };
    const draw = () => {
      if (rec.state !== 'live') { box.replaceChildren(h('p', { class: 'muted' }, 'Stopped. The link no longer works (on the phone copy within a minute or two).')); return; }
      const stopBtn = h('button', { class: 'btn small', type: 'button', onclick: async () => {
        stopBtn.disabled = true;
        try { rec = (await API.share({ action: 'stop', id: rec.id })).share; draw(); if (onStop) onStop(rec); } catch (e) { toast(e.message); stopBtn.disabled = false; }
      } }, 'Stop sharing');
      const field = (url, label) => h('input', { class: 'field mono', readonly: true, value: url, 'aria-label': label, onfocus: (e) => e.target.select() });
      box.replaceChildren(...[
        rec.url ? h('div', { class: 'shareline' }, field(rec.url, 'The link'), copyButton(rec.url, 'Copy link'))
          : h('p', { class: 'muted' }, 'Made, but no public address is set yet, so there is no link to send. It is the [share] url setting.'),
        rec.url ? live : null,
        rec.clip_url ? h('div', { class: 'shareline' }, h('span', { class: 'muted' }, 'Link straight to the clip'), field(rec.clip_url, 'Link straight to the clip'), copyButton(rec.clip_url, 'Copy')) : null,
        rec.url && rec.clip ? h('p', { class: 'muted' }, (rec.still ? 'In Discord the link shows a still of the ' + (rec.files.length > 1 ? 'first ' : '') + 'clip and plays it.' : 'No still could be taken of the clip, so Discord shows the link as a plain card.')
          + (rec.clip_url ? ' The link straight to the clip plays in the chat by itself.' : '')) : null,
        h('p', { class: 'muted' }, 'Anyone with the link sees ' + (rec.files.length === 1 ? 'this one file' : 'these ' + rec.files.length + ' files') + ' and nothing else, until ' + whenEnds(rec.expires) + '.'),
        h('div', {}, stopBtn)].filter(Boolean));
    };
    draw();
    if (rec.url && rec.state === 'live') ask();
    return box;
  }
  // `items` in place of ticks: a batch or one candidate of it, shared whole, with `said` for what they will see and `lead` for the file the link opens with
  function sharePanel(files, title, items, said, lead) {
    const el = h('div', { class: 'sharepanel', hidden: true });
    const button = h('button', { class: 'btn small', type: 'button', 'aria-expanded': 'false', onclick: () => { el.hidden = !el.hidden; button.setAttribute('aria-expanded', String(!el.hidden)); if (!el.hidden) draw(); } }, 'Share');
    function draw() {
      const ticks = items ? [] : files.map((f) => { const box = h('input', { type: 'checkbox', checked: true }); box.dataset.path = f.url.replace(/^\//, ''); return { box, f }; });
      const name = h('input', { class: 'field', value: title, maxlength: 120, 'aria-label': 'What the page they open is called' });
      const time = h('select', { 'aria-label': 'How long the link works' }, SHARE_TIMES.map(([v, label]) => h('option', { value: v, selected: v === '7d' }, label)));
      const out = h('div', {});
      const make = h('button', { class: 'btn small primary', type: 'button', onclick: async () => {
        const chosen = items || ticks.filter((t) => t.box.checked).map((t) => t.box.dataset.path);
        if (!chosen.length) { toast('Tick at least one file'); return; }
        make.disabled = true;
        const first = items ? lead : (ticks.find((t) => t.box.checked) || {}).f;  // a clip first: one frame of it goes with the link, for a chat's preview
        let still = null;
        if (first && isClip(first.url)) { make.textContent = 'Taking a still of the clip'; still = await grabStill(first.url); }
        make.textContent = 'Making the link';
        try { const rec = (await API.share({ files: chosen, title: name.value, time: time.value, still })).share; out.replaceChildren(shareResult(rec)); make.textContent = 'Make another link'; }
        catch (e) { toast(e.message); out.replaceChildren(h('p', { class: 'muted' }, e.message.charAt(0).toUpperCase() + e.message.slice(1) + '.')); make.textContent = 'Make the link'; }
        make.disabled = false;
      } }, 'Make the link');
      el.replaceChildren(...[
        h('p', { class: 'muted' }, said || 'A link for someone outside: they see only the files ticked here, and only until it runs out.'),
        files.length > 1 && !items ? h('div', { class: 'sharefiles' }, ticks.map((t) => h('label', {}, t.box, ' ' + (t.f.label || t.f.url.split('/').pop())))) : null,
        h('div', { class: 'shareline' }, h('label', {}, 'Called ', name), h('label', {}, 'Works for ', time), make),
        out].filter(Boolean));
    }
    return { el, button };
  }
  // Share on a batch in the Inbox, or on one candidate of it: its files alone, never the verdict, notes or marks; none on a sample
  function inboxShare(b, cand) {
    const n = (cand ? [cand] : b.candidates).reduce((t, c) => t + (c.files || []).length, 0);
    if (STATIC || b.sample || !n) return null;
    const said = 'A link for someone outside: they see and hear ' + (n === 1 ? 'this one file' : 'these ' + n + ' files') + (cand ? ' of ' + cand.title : ', under each candidate\'s name')
      + ', and nothing else: no verdict, notes or marks. It works until it runs out.';
    const f = (cand ? [cand] : b.candidates).flatMap((c) => c.files || [])[0];
    const panel = sharePanel([], b.title, [b.id + (cand ? '/' + cand.id : '')], said, f && { url: fileUrl(b.id, f.path) });
    panel.button.title = cand ? 'A link to ' + cand.title + '\'s files, for someone outside' : 'A link to every candidate\'s files, for someone outside';
    return panel;
  }
  function sharesSection() {
    const sec = h('section', { hidden: true });
    if (STATIC) return sec;
    API.shares().then(({ shares }) => {
      if (!shares.length) return;
      const live = shares.filter((x) => x.state === 'live'), ended = shares.filter((x) => x.state !== 'live');
      const row = (x) => h('div', { class: 'row' },
        h('div', { class: 'grow' }, h('div', { class: 'title' }, x.title), h('div', { class: 'sub' }, (x.files.length === 1 ? '1 file' : x.files.length + ' files') + ((x.batches || []).length ? ' from the Inbox (' + [...new Set(x.files.map((f) => f.group).filter(Boolean))].join(', ') + ')' : '') + ' · ' + (x.state === 'live' ? 'until ' + whenEnds(x.expires) : x.state === 'expired' ? 'ran out ' + whenEnds(x.expires) : 'stopped'))),
        x.state === 'live' && x.url ? copyButton(x.url, 'Copy link') : null,
        x.state === 'live' && x.clip_url ? copyButton(x.clip_url, 'Copy clip link') : null,
        x.state === 'live' ? h('button', { class: 'btn small', type: 'button', onclick: async (e) => {
          e.target.disabled = true;
          try { await API.share({ action: 'stop', id: x.id }); toast('Stopped'); render(); } catch (err) { toast(err.message); e.target.disabled = false; }
        } }, 'Stop sharing') : null);
      sec.replaceChildren(...[h('h2', {}, 'Shared links' + (live.length ? ' · ' + live.length + ' working' : '')),
        live.length ? h('div', { class: 'rows' }, live.map(row)) : h('p', { class: 'muted' }, 'None working now.'),
        ended.length ? h('details', {}, h('summary', {}, 'Ended · ' + ended.length), h('div', { class: 'rows' }, ended.slice(0, 40).map(row))) : null].filter(Boolean));
      sec.hidden = false;
    }).catch(() => {});
    return sec;
  }

  // ------------------------------------------------------------------- inbox
  function strip(b) {
    if (b.thumb) return h('div', { class: 'strip' }, h('img', { src: API.src(fileUrl(b.id, b.thumb)), alt: '', loading: 'lazy' }));
    return h('div', { class: 'strip' }, h('span', { class: 'glyph' }, GLYPH[b.kind] || b.kind));
  }
  function bcard(b) {
    return link('b.' + b.id, { class: 'bcard' }, strip(b), h('div', { class: 'body' },
      h('div', { class: 'meta' }, h('span', { class: 'chip' }, KIND[b.kind] || b.kind),
        h('span', { class: 'chip' }, b.mode === 'question' ? b.count + ' options' : b.count + ' to judge'),
        b.round > 1 ? h('span', { class: 'chip' }, 'Round ' + b.round) : null,
        b.status === 'draft' ? h('span', { class: 'chip accent' }, 'Started') : null,
        b.status === 'submitted' ? h('span', { class: 'chip accent' }, 'Verdict sent') : null),
      h('h3', {}, b.title), h('p', { class: 'ask' }, b.ask)));
  }
  // the inbox holds two lists: what truly waits, and made-up batches to try the page on
  function inboxSwitch(on) {
    const st = S.state; if (st.static) return null;
    const n = (st.samples || []).length;
    return h('div', { class: 'switch', role: 'tablist', 'aria-label': 'Which batches' },
      link('inbox', { class: 'btn small' + (on === 'inbox' ? ' on' : ''), role: 'tab', 'aria-selected': String(on === 'inbox') }, 'Waiting on you'),
      link('samples', { class: 'btn small' + (on === 'samples' ? ' on' : ''), role: 'tab', 'aria-selected': String(on === 'samples') }, 'Samples' + (n ? ' (' + n + ')' : '')));
  }
  function samplesPage() {
    const st = S.state, all = st.samples || [], held = st.samples_held || [];
    const main = h('main', {});
    main.append(h('section', {}, inboxSwitch('samples'),
      h('h1', {}, 'Samples'),
      h('p', { class: 'lede' }, 'Made-up batches, one for each thing you can be asked to judge. Mark them, score them and submit as you would a real one: nothing here is counted, recorded or acted on, and Start over on a sample clears your marks.'),
      all.length ? h('div', { class: 'batches' }, all.map(bcard))
        : h('div', { class: 'empty' }, 'No samples here yet. Say to Claude Code: ', h('code', { class: 'i' }, 'make the studio samples'))));
    if (held.length) main.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Held back by the checks'), h('p', {}, 'What a batch looks like when it breaks a rule a script can test: you are told it exists and why you were not shown it.')),
      h('div', { class: 'rows' }, held.map((b) => h('div', { class: 'row' },
        h('div', { class: 'grow' }, h('div', { class: 'title' }, b.title), h('div', { class: 'sub' }, b.errors.join(' \u00b7 '))),
        h('span', { class: 'chip bad' }, 'Held'))))));
    return main;
  }
  function inboxPage() {
    const st = S.state;
    const mine = st.batches.filter((b) => b.status === 'open' || b.status === 'draft');
    const sent = st.batches.filter((b) => b.status === 'submitted');
    const closed = st.batches.filter((b) => b.status === 'processed');
    const main = h('main', {});
    main.append(h('section', {}, inboxSwitch('inbox'),
      h('h1', {}, mine.length ? (mine.length === 1 ? 'One batch waits for you' : mine.length + ' batches wait for you') : 'Nothing waits for you'),
      mine.length ? h('div', { class: 'batches' }, mine.map(bcard))
        : h('div', { class: 'empty' }, 'When Claude Code files candidates or a question, they show up here.')));
    if (sent.length) main.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Waiting on Claude'), h('p', {}, 'You have judged these. Nothing happens until you tell Claude Code.')),
      h('div', { class: 'say' }, h('span', {}, 'Say to Claude Code:'), h('code', {}, SAY), copyButton(SAY)),
      h('div', { class: 'rows' }, sent.map((b) => link('b.' + b.id, { class: 'row' },
        h('div', { class: 'grow' }, h('div', { class: 'title' }, b.title), h('div', { class: 'sub' }, 'You said: ' + (ACTION_SAID[b.action] || b.action) + (b.winners.length ? ' (' + b.winners.join(', ').toUpperCase() + ')' : ''))),
        h('span', { class: 'sub' }, when(b.submitted)))))));
    if ((st.held || []).length) main.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Held back by the checks'), h('p', {}, 'Made, but not shown to you: each broke a rule a script can test. Claude fixes these first.')),
      h('div', { class: 'rows' }, st.held.map((b) => h('div', { class: 'row' },
        h('div', { class: 'grow' }, h('div', { class: 'title' }, b.title), h('div', { class: 'sub' }, b.errors.join(' · '))),
        h('span', { class: 'chip bad' }, 'Held'))))));
    if (closed.length) main.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Closed'), h('p', {}, 'Judged and acted on.')),
      h('div', { class: 'rows' }, closed.map((b) => link('b.' + b.id, { class: 'row' },
        h('div', { class: 'grow' }, h('div', { class: 'title' }, b.title), h('div', { class: 'sub' }, (ACTION_SAID[b.action] || '') + (b.winners.length ? ': ' + b.winners.join(', ').toUpperCase() : '') + (b.next_batch ? ' · next round filed' : ''))),
        h('span', { class: 'sub' }, when(b.processed)))))));
    return main;
  }

  // ------------------------------------------------------------- the verdict
  function entry(cid) { return S.verdict.candidates[cid] || (S.verdict.candidates[cid] = { call: null, score: null, note: '' }); }
  function editable() { return S.batch.status === 'open' || S.batch.status === 'draft'; }
  let saveTimer = 0;
  function changed(cid) {
    if (cid) (S.ui[cid] || []).forEach((fn) => fn());
    if (!S.touched) autoAction();
    if (S.ui._bar) S.ui._bar();
    clearTimeout(saveTimer);
    const id = S.batch.id, v = JSON.parse(JSON.stringify(S.verdict));
    saveTimer = setTimeout(() => { API.saveDraft(id, v).catch((e) => toast('Not saved: ' + e.message)); }, 500);
  }
  function autoAction() {
    const calls = Object.values(S.verdict.candidates).map((c) => c.call);
    const chosen = calls.some((c) => c === 'winner' || c === 'approve'), again = calls.some((c) => c === 'redo');
    if (S.batch.mode === 'question') S.verdict.action = (chosen || S.verdict.answer) ? 'answer' : null;
    else if (S.batch.mode === 'rate') S.verdict.action = chosen ? (again ? 'ship_and_iterate' : 'ship') : (again ? 'another_round' : null);
    else S.verdict.action = chosen ? 'ship' : (calls.some((c) => c === 'redo' || c === 'keep' || c === 'reject') ? 'another_round' : null);
  }
  function setCall(cid, callName) {
    if (!editable()) return;
    const e = entry(cid), b = S.batch;
    if (e.call === callName) e.call = null;
    else {
      if (callName === 'winner') {
        const max = b.max_winners || 1, others = b.candidates.filter((c) => c.id !== cid && entry(c.id).call === 'winner');
        if (max === 1) others.forEach((c) => { entry(c.id).call = null; (S.ui[c.id] || []).forEach((fn) => fn()); });
        else if (others.length >= max) { toast('This batch takes ' + max + ' winners. Unmark one first.'); return; }
      }
      e.call = callName;
    }
    changed(cid);
  }
  function setScore(cid, n) { if (!editable()) return; const e = entry(cid); e.score = e.score === n ? null : n; changed(cid); }
  function problem() {
    const b = S.batch, v = S.verdict, calls = Object.values(v.candidates);
    const chosen = calls.filter((c) => c.call === 'winner' || c.call === 'approve').length;
    if (!v.action) return b.mode === 'question' ? 'Choose an option or write your own answer.' : 'Mark the candidates, then choose what happens next.';
    if (b.mode === 'question') return (v.action === 'answer' && !chosen && !v.answer) ? 'Pick an option or write your own answer.' : '';
    if ((v.action === 'ship' || v.action === 'ship_and_iterate') && !chosen) return 'Nothing is marked to ship. Mark a winner, or choose another round.';
    const marked = (c) => c.marks && (Object.values(c.marks.notes || {}).some((x) => x && x.trim()) || spansSay(c.marks));
    if ((v.action === 'another_round' || v.action === 'ship_and_iterate') && !v.note && !calls.some((c) => c.note || marked(c) || c.call === 'keep' || c.call === 'redo'))
      return 'Another round needs a direction: write a note, or mark a Keep or a Redo.';
    return '';
  }
  function controls(cand, compact) {
    const b = S.batch, cid = cand.id;
    const callBtns = CALLS[b.mode].map(([name, label, key]) => h('button', { class: 'call', type: 'button', 'data-call': name, onclick: () => setCall(cid, name) }, label, h('kbd', {}, key)));
    const scoreBtns = b.mode === 'question' ? [] : Array.from({ length: 10 }, (_, i) => h('button', { type: 'button', 'aria-label': 'Score ' + (i + 1), onclick: () => setScore(cid, i + 1) }, String(i + 1)));
    const note = h('textarea', { class: 'field', rows: compact ? 2 : 1, placeholder: b.mode === 'question' ? 'Why, or a change you want' : 'Note for the maker, in your own words', 'aria-label': 'Note on ' + cand.title,
      oninput: () => { entry(cid).note = note.value; changed(null); (S.ui[cid] || []).forEach((fn) => fn(note)); } });
    const wrap = h('div', { class: 'tverdict' }, h('div', { class: 'calls' }, callBtns), scoreBtns.length ? h('div', { class: 'scores' }, scoreBtns) : null, note);
    const update = (skip) => {
      const e = entry(cid);
      callBtns.forEach((btn) => { const on = btn.dataset.call === e.call; btn.classList.toggle('on', on); btn.setAttribute('aria-pressed', on); btn.disabled = !editable(); });
      scoreBtns.forEach((btn, i) => { btn.classList.toggle('on', e.score === i + 1); btn.classList.toggle('lit', !!e.score && i + 1 < e.score); btn.disabled = !editable(); });
      if (skip !== note && document.activeElement !== note) note.value = e.note || '';
      note.disabled = !editable();
    };
    (S.ui[cid] = S.ui[cid] || []).push(update); update();
    wrap.noteField = note;
    return wrap;
  }
  function factsLine(cand) {
    const f = cand.facts || {}, parts = [];
    if (f.triangles !== undefined) parts.push(f.triangles + ' tris');
    if (f.height_m !== undefined) parts.push(f.height_m.toFixed(2) + ' m tall');
    if (f.clips && f.clips.length) parts.push(f.clips.length + ' motions');
    if (f.seconds !== undefined) parts.push(f.seconds.toFixed(2) + ' s');
    if (f.peak_dbfs !== undefined) parts.push(f.peak_dbfs.toFixed(1) + ' dBFS');
    if (f.sample_rate) parts.push((f.sample_rate / 1000) + ' kHz');
    if (f.width && f.height) parts.push(f.width + ' x ' + f.height);
    if (f.fps) parts.push(f.fps + ' fps');
    if (cand.tempo) parts.push(cand.tempo.bpm + ' bpm');
    return parts.join(' · ');
  }
  const primary = (cand) => (cand.files || []).find((f) => f.role === 'primary') || (cand.files || [])[0] || null;
  function markChip(cid) {
    const el = h('div', { class: 'markchip', hidden: true });
    const upd = () => {
      const mk = entry(cid).marks, used = mk ? Object.keys(mk.notes || {}) : [];
      if (mk && mk.spans) {  // a sound or a clip: its marks are moments and stretches
        el.hidden = !mk.spans.length;
        el.replaceChildren(...mk.spans.map((s) => h('span', { class: 'sw', style: '--sw:' + (MARK_HEX[s.c] || MARK_HEX.red), title: s.tag })), ' ' + mk.spans.length + ' mark' + (mk.spans.length === 1 ? '' : 's') + ' on it; open it to see');
        return;
      }
      el.hidden = !used.length;
      el.replaceChildren(...used.map((c) => h('span', { class: 'sw', style: '--sw:' + MARK_HEX[c], title: c })), used.length ? ' Marked in ' + used.join(', ') + '; open it to see' : '');
    };
    (S.ui[cid] = S.ui[cid] || []).push(upd); upd();
    return el;
  }

  // what a candidate looks like, small (in the grid) or large (in the overlay)
  function media(cand, big, group) {
    const b = S.batch, file = primary(cand), views = [];
    const stage = h('div', { class: 'stage' + (S.opts.stage === 'checker' ? ' checker' : '') });
    const paint = () => { stage.classList.toggle('checker', S.opts.stage === 'checker'); stage.style.background = { dark: '', grey: '#777', white: '#f4f4f4', checker: '' }[S.opts.stage]; };
    paint();
    const api = { el: stage, set() { paint(); views.forEach((v) => v.set && v.set(S.opts)); }, destroy() { views.forEach((v) => v.destroy && v.destroy()); }, play: null, view: null };
    const mo = b.kind === 'in_app' ? motionOf(cand.motion) : null;
    if (mo) {
      const v = modelView(mo.url, { zoom: big, group: group && group.cam, clip: mo.clip });
      if (group && group.cam && v.copyCam) group.cam.views.push(v);
      views.push(v); api.view = v; stage.append(v.el);
      if (!big) stage.append(h('div', { class: 'word under' }, h('b', {}, cand.label || cand.title), h('span', {}, b.sample ? 'Made-up motion, to show the viewer' : 'Baked from the project. Confirm it in the running project, under these words')));
    } else if (b.kind === 'in_app') {
      stage.append(h('div', { class: 'word' }, h('b', {}, cand.label || cand.title), h('span', {}, 'Look for these words over it in the running project')));
    } else if (b.kind === 'question' || (!file && cand.body)) {
      stage.classList.remove('stage'); stage.className = 'option'; stage.append(md(cand.body || cand.summary || ''));
    } else if (!file) {
      stage.append(h('div', { class: 'fallback' }, 'No file.'));
    } else if (file.kind === 'model') {
      const v = modelView(fileUrl(b.id, file.path), { zoom: big, group: group && group.cam, ready: group && group.ready });
      if (group && group.cam && v.copyCam) group.cam.views.push(v);
      views.push(v); api.view = v; stage.append(v.el);
    } else if (file.kind === 'audio' && big) {
      const v = api.timed = soundView(cand.files.filter((x) => x.kind === 'audio').map((f) => ({ url: fileUrl(b.id, f.path), label: f.label, name: f.path.split('/').pop() })), { tempo: cand.tempo });
      views.push(v); stage.classList.add('timed'); stage.append(v.el);
    } else if (file.kind === 'video' && big) {
      const v = api.timed = clipView({ url: fileUrl(b.id, file.path), label: file.label, name: file.path.split('/').pop() }, { facts: file.facts || cand.facts });
      views.push(v); stage.classList.add('timed'); stage.append(v.el);
    } else if (file.kind === 'audio') {
      for (const f of cand.files.filter((x) => x.kind === 'audio')) {
        const p = audioPlayer(fileUrl(b.id, f.path), f.label);
        if (!api.play) api.play = p;
        views.push(p); stage.append(p.el);
      }
    } else if (file.kind === 'video') {
      stage.append(h('video', { class: 'media', src: API.src(fileUrl(b.id, file.path)), controls: true, loop: true, muted: true, playsinline: true, preload: 'auto' }));
    } else if (file.kind === 'text') {
      const holder = h('div', { class: 'option' }, 'Loading');
      API.bytes(fileUrl(b.id, file.path)).then((buf) => holder.replaceWith(textCard(cand, new TextDecoder().decode(buf)))).catch(() => holder.replaceChildren('Could not read the file.'));
      stage.className = ''; stage.append(holder);
    } else {
      const src = API.src(fileUrl(b.id, file.path));
      const tex = file.kind === 'texture';
      const build = () => {
        stage.replaceChildren();
        if (tex && S.opts.tile) {
          const div = h('div', { class: 'tex', role: 'img', 'aria-label': cand.title + ', tiled' });
          div.style.backgroundImage = 'url("' + src + '")'; div.style.backgroundSize = S.opts.texScale + 'px';
          stage.append(div);
        } else if (big) { stage.style.flex = '1'; stage.style.minHeight = '0'; api.pane = zoomPane(src, group.zoom); stage.append(api.pane.el); if (api.onPane) api.onPane(api.pane); }
        else stage.append(h('img', { class: 'fit', src, alt: cand.title, loading: 'lazy' }));
      };
      api.pane = null; build(); api.set = () => { api.pane = null; paint(); build(); if (!api.pane && api.onPane) api.onPane(null); };
      if (big) { stage.style.flex = '1'; stage.style.minHeight = '0'; }
    }
    return api;
  }

  // a markdown or text candidate the user can edit on the card; their version is what ships
  function textCard(cand, first) {
    const cid = cand.id;
    const mine = () => { const e = S.verdict.candidates[cid]; return e && typeof e.edited === 'string' ? e.edited : null; };
    let editing = false, showFirst = false;
    const view = h('div', { class: 'option' });
    const area = h('textarea', { class: 'field mdedit', spellcheck: 'true', 'aria-label': 'Edit the text of ' + cand.title,
      oninput: () => { const e = entry(cid); if (area.value === first) delete e.edited; else e.edited = area.value; fit(); changed(cid); chip.hidden = backBtn.hidden = mine() === null; } });
    const fit = () => { area.style.height = 'auto'; area.style.height = Math.max(area.scrollHeight + 2, 240) + 'px'; };
    const chip = h('span', { class: 'chip redo' }, 'Your edits');
    const editBtn = h('button', { class: 'btn small primary', type: 'button', onclick: () => {
      editing = !editing; showFirst = false; paint();
      if (editing) { area.value = mine() ?? first; fit(); area.focus(); }
    } });
    const firstBtn = h('button', { class: 'btn small', type: 'button', onclick: () => { showFirst = !showFirst; paint(); } });
    const backBtn = h('button', { class: 'btn small', type: 'button', onclick: () => {
      const was = mine(); if (was === null) return;
      delete entry(cid).edited; editing = false; changed(cid);
      undoToast('Put back the first draft', () => { entry(cid).edited = was; changed(cid); });
    } }, 'Put back the first draft');
    function paint() {
      const ed = mine() !== null, can = editable();
      if (!can) editing = false;
      chip.hidden = !ed;
      editBtn.hidden = !can; editBtn.textContent = editing ? 'Done editing' : 'Edit';
      firstBtn.hidden = !ed || editing; firstBtn.textContent = showFirst ? 'Show your version' : 'Show the first draft';
      backBtn.hidden = !ed || !can;
      area.hidden = !editing; view.hidden = editing;
      if (!editing) view.replaceChildren(md(showFirst ? first : (mine() ?? first)));
    }
    const upd = () => { if (document.activeElement !== area) paint(); };
    (S.ui[cid] = S.ui[cid] || []).push(upd);
    paint();
    return h('div', { class: 'mdcard' }, h('div', { class: 'mdbar' }, chip, h('span', { style: 'flex:1' }), firstBtn, backBtn, editBtn), view, area);
  }

  // a text in the Library the user edits in place; saving makes a new version, and the sessions are told of it
  function libText(s, f, first) {
    const name = f.url.split('/').pop();
    let editing = false;
    const view = h('div', { class: 'option' }, md(first));
    const area = h('textarea', { class: 'field mdedit', spellcheck: 'true', 'aria-label': 'Edit ' + name, oninput: () => { fit(); save.disabled = area.value === first; } });
    const fit = () => { area.style.height = 'auto'; area.style.height = Math.max(area.scrollHeight + 2, 240) + 'px'; };
    const save = h('button', { class: 'btn small primary', type: 'button', onclick: async () => {
      save.disabled = true;
      try {
        const res = await API.editText(s.id, name, area.value);
        S.state = await API.state(); toast(res.unchanged ? 'No change' : 'Saved as v' + res.version); render();
      } catch (e) { save.disabled = false; toast(e.message); }
    } }, 'Save');
    const cancel = h('button', { class: 'btn small', type: 'button', onclick: () => {
      if (area.value !== first && !confirm('Throw away what you typed?')) return; editing = false; paint();
    } }, 'Cancel');
    const edit = h('button', { class: 'btn small primary', type: 'button', onclick: () => { editing = true; area.value = first; paint(); fit(); area.focus(); } }, 'Edit');
    const seen = (s.edits || []).some((e) => !e.seen && e.version === (s.current || {}).version);
    const chip = h('span', { class: 'chip redo' }, seen ? 'Your edit · not picked up yet' : 'Your edit');
    function paint() {
      chip.hidden = !(s.current || {}).edited_by_user;
      edit.hidden = editing; save.hidden = cancel.hidden = !editing; save.disabled = true;
      area.hidden = !editing; view.hidden = editing;
    }
    paint();
    return h('div', { class: 'mdcard' }, h('div', { class: 'mdbar' }, h('span', { class: 'mono muted' }, name), chip, h('span', { style: 'flex:1' }), cancel, save, edit), view, area);
  }

  // -------------------------------------------------------------- batch page
  async function batchPage(id) {
    const b = S.batch = await API.batch(id);
    S.ui = {}; S.cmp = new Set(); S.current = b.candidates.length ? b.candidates[0].id : null; S.touched = false;
    const from = b.verdict || b.draft || {};
    S.verdict = { action: from.action || null, note: from.note || '', answer: from.answer || '', candidates: JSON.parse(JSON.stringify(from.candidates || {})) };
    if (from.action) S.touched = true;
    Object.assign(S.opts, { clip: (b.candidates.map((c) => (c.facts || {}).clips).find((c) => c && c.length) || [{ name: '' }])[0].name, tile: false, rotate: false, wire: false, playing: true, rate: 1 });
    const moving = b.kind === 'in_app' && b.candidates.some((c) => motionOf(c.motion));
    const timed = b.kind === 'audio' || b.kind === 'video';  // a sound or a clip: its closer look opens from Mark and from Enter, not from a click on its player
    const visual = S.visual = ['image', 'texture', 'model'].includes(b.kind) || moving || timed;
    const main = h('main', {});
    const medias = {};
    S.cleanup.push(() => { Object.values(medias).forEach((m) => m.destroy()); seq.token++; clearTimeout(saveTimer); document.removeEventListener('keydown', onKey); });

    // head
    const parent = b.parent ? S.state.batches.find((x) => x.id === b.parent) : null;
    const bshare = inboxShare(b, null);
    main.append(h('section', { class: 'bhead' },
      h('div', { class: 'crumb' }, link('inbox', {}, 'Inbox'), h('span', {}, '/'), b.sample ? [link('samples', {}, 'Samples'), h('span', {}, '/')] : null, h('span', { class: 'chip' }, KIND[b.kind] || b.kind),
        b.round > 1 ? h('span', { class: 'chip' }, 'Round ' + b.round) : null,
        parent ? link('b.' + parent.id, {}, 'See round ' + parent.round) : null,
        b.slot ? h('span', { class: 'mono muted' }, b.slot) : null),
      bshare ? h('div', { class: 'sechead' }, h('h1', {}, b.title), bshare.button) : h('h1', {}, b.title), bshare ? bshare.el : null, b.ask ? h('p', { class: 'ask' }, b.ask) : null,
      (b.look_at || []).length ? h('ul', { class: 'look', 'aria-label': 'What to look at' }, b.look_at.map((x) => h('li', {}, x))) : null,
      b.brief ? h('details', { class: 'brief' }, h('summary', {}, b.mode === 'question' ? 'Where this comes from' : 'What the makers were told'), md(b.brief)) : null,
      (b.context || []).length ? h('div', { class: 'refs', 'aria-label': 'References' }, b.context.map((c) => (c.kind === 'image' || c.kind === 'texture')
        ? h('figure', {}, h('img', { src: API.src(fileUrl(b.id, c.path)), alt: c.label || 'Reference', loading: 'lazy', onclick: (e) => shot(e.target.src) }), h('figcaption', {}, 'Reference: ' + (c.label || '')))
        : h('span', { class: 'chip' }, 'Reference: ' + (c.label || c.path)))) : null));

    // closed states
    const startOver = async () => { try { clearTimeout(saveTimer); await API.reset(b.id); S.state = await API.state(); toast('Cleared'); render(); } catch (e) { toast(e.message); } };
    if (b.sample) main.append(h('section', {}, h('div', { class: 'samplebar' },
      h('span', {}, h('b', {}, 'A sample.'), ' Made up, to try the page on. Nothing you do here is counted, recorded or acted on.'),
      b.status === 'draft' || b.status === 'submitted' ? h('button', { class: 'btn small', type: 'button', onclick: startOver }, 'Start over') : null)));
    if (b.sample && b.status === 'submitted') main.append(h('section', {}, h('div', { class: 'closed' },
      h('h3', {}, 'Your verdict is in: ' + (ACTION_SAID[b.verdict.action] || b.verdict.action)),
      h('p', { class: 'muted' }, 'On a real batch this is where the page tells you to say "' + SAY + '" to Claude Code. A sample ends here.'),
      h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' },
        h('button', { class: 'btn', type: 'button', onclick: async () => { try { await API.reopen(b.id); S.state = await API.state(); render(); } catch (e) { toast(e.message); } } }, 'Change my verdict'),
        h('button', { class: 'btn', type: 'button', onclick: startOver }, 'Start over')))));
    else if (b.status === 'submitted') main.append(h('section', {}, h('div', { class: 'closed' },
      h('h3', {}, 'Your verdict is in: ' + (ACTION_SAID[b.verdict.action] || b.verdict.action)),
      h('div', { class: 'say' }, h('span', {}, 'Nothing happens until you say to Claude Code:'), h('code', {}, SAY), copyButton(SAY)),
      h('div', {}, h('button', { class: 'btn', type: 'button', onclick: async () => { try { await API.reopen(b.id); S.state = await API.state(); render(); } catch (e) { toast(e.message); } } }, 'Change my verdict')))));
    if (b.status === 'processed') {
      const res = b.result || {};
      main.append(h('section', {}, h('div', { class: 'closed' },
        h('h3', {}, 'Closed: ' + (ACTION_SAID[res.action] || res.action || '')),
        (res.imported || []).length ? h('p', { class: 'muted' }, 'In the library: ' + res.imported.map((r) => r.candidate.toUpperCase() + (r.slot ? ' as ' + r.slot + ' v' + r.version : '')).join(', ')) : null,
        (res.imported || []).some((r) => (r.dest || []).length) ? h('p', { class: 'muted mono' }, 'project: ' + res.imported.flatMap((r) => r.dest || []).join(', ')) : null,
        h('div', { class: 'line', style: 'display:flex;gap:10px;flex-wrap:wrap' },
          res.decision ? link('decisions', { class: 'btn small' }, 'Decision ' + res.decision) : null,
          res.next_batch ? link('b.' + res.next_batch, { class: 'btn small' }, 'Go to the next round') : null))));
    }

    // tools
    const tools = h('div', { class: 'tools' });
    const apply = () => Object.values(medias).forEach((m) => m.set()), overApply = () => { if (S.over && S.over.apply) S.over.apply(); };
    const toggle = (label, key) => h('button', { class: 'btn small' + (S.opts[key] ? ' on' : ''), type: 'button', 'data-opt': key, 'aria-pressed': String(!!S.opts[key]),
      onclick: () => { S.opts[key] = !S.opts[key]; showOpts(); apply(); overApply(); } }, label);
    const hasMedia = ['image', 'texture', 'model', 'video', 'mixed'].includes(b.kind) || moving;
    // how the candidates are shown: on the page, and again at the top of a closer look (`at` keeps the ids apart)
    const viewTools = (at) => {
      const out = [];
      if (hasMedia) {
        const sw = [['dark', '#0b0b0c'], ['grey', '#777'], ['white', '#f4f4f4'], ['checker', 'conic-gradient(#555 25%, #222 0 50%, #555 0 75%, #222 0)']].map(([name, css]) =>
          h('button', { class: 'swatch' + (S.opts.stage === name ? ' on' : ''), type: 'button', 'data-stage': name, title: 'Background: ' + name, 'aria-label': 'Background ' + name, style: 'background:' + css,
            onclick: () => { S.opts.stage = name; showOpts(); apply(); overApply(); } }));
        out.push(h('div', { class: 'grp' }, h('label', {}, 'Behind it'), sw));
      }
      if (b.kind === 'texture') {
        const size = h('input', { type: 'range', class: 'texsize', min: 48, max: 320, step: 8, value: S.opts.texScale, id: 'tex-scale' + at, 'aria-label': 'Tile size',
          oninput: () => { S.opts.texScale = +size.value; showOpts(); if (S.opts.tile) { apply(); overApply(); } } });
        out.push(h('div', { class: 'grp' }, toggle('Tile', 'tile'), h('label', { for: 'tex-scale' + at }, 'Tile size'), size));
      }
      if (b.kind === 'model') {
        const names = [...new Set(b.candidates.flatMap((c) => ((c.facts || {}).clips || []).map((x) => x.name)))];
        const sel = h('select', { class: 'clipsel', id: 'clip' + at, 'aria-label': 'Motion', onchange: () => { S.opts.clip = sel.value; showOpts(); apply(); overApply(); } },
          h('option', { value: '' }, 'Still'), names.map((n) => h('option', { value: n, selected: n === S.opts.clip }, n)));
        out.push(h('div', { class: 'grp' }, h('label', { for: 'clip' + at }, 'Motion'), sel, toggle('Play', 'playing'), names.length ? rateButtons(() => { apply(); overApply(); }) : null),
          h('div', { class: 'grp' }, toggle('Turntable', 'rotate'), toggle('Wireframe', 'wire'), toggle('1.8 m figure', 'ref')));
      }
      if (moving) out.push(h('div', { class: 'grp' }, toggle('Play', 'playing'), rateButtons(() => { apply(); overApply(); })),
        h('div', { class: 'grp' }, toggle('Turntable', 'rotate'), toggle('1.8 m figure', 'ref')));
      return out;
    };
    tools.append(...viewTools(''));
    S.viewTools = (b.kind === 'model' || moving) ? () => viewTools('-over') : null;
    if (b.kind === 'audio') {
      const turn = h('button', { class: 'btn small', type: 'button', onclick: async () => {
        const my = ++seq.token;
        for (const c of b.candidates) {
          const m = medias[c.id]; if (!m || !m.play) continue;
          setCurrent(c.id, true); const done = m.play.done(); await m.play.play(); await done;
          if (my !== seq.token) return;
          await new Promise((ok) => setTimeout(ok, 420));
          if (my !== seq.token) return;
        }
      } }, 'Play them in turn');
      tools.append(h('div', { class: 'grp' }, turn, toggle('Loop', 'loop')));
    }
    if (b.kind === 'in_app' && b.launch) tools.append(h('div', { class: 'grp' }, h('label', {}, 'Start it with'), h('code', { class: 'i' }, b.launch), copyButton(b.launch)));
    const cmpBtn = h('button', { class: 'btn small', type: 'button', hidden: true, onclick: () => openOver([...S.cmp]) }, 'Compare');
    const canCompare = visual && !timed && b.candidates.length > 1;
    if (canCompare) tools.append(h('span', { style: 'flex:1' }), h('div', { class: 'grp' }, cmpBtn,
      h('button', { class: 'btn small', type: 'button', onclick: () => openOver(b.candidates.slice(0, 4).map((c) => c.id)) }, b.candidates.length > 4 ? 'Compare the first four' : 'Compare all')));
    const refreshCmp = () => { cmpBtn.hidden = S.cmp.size < 2; cmpBtn.textContent = 'Compare the ' + S.cmp.size + ' ticked'; };

    // grid
    const tileW = moving ? 340 : ({ image: 440, texture: 300, model: 340, audio: 380, in_app: 300, question: 380, text: 560 }[b.kind] || 380);
    const grid = h('div', { class: 'grid', style: '--tile:' + tileW + 'px' });
    const tiles = {};
    for (const cand of b.candidates) {
      const m = medias[cand.id] = media(cand, false, null);
      const checks = (cand.checks || []).filter((c) => c.level !== 'ok');
      const box = canCompare ? h('input', { type: 'checkbox', 'aria-label': 'Tick to compare ' + cand.title, onchange: () => { if (box.checked) { if (S.cmp.size >= 4) { box.checked = false; toast('Compare takes four at most'); return; } S.cmp.add(cand.id); } else S.cmp.delete(cand.id); refreshCmp(); } }) : null;
      const ctl = controls(cand, false), cshare = inboxShare(b, cand);
      const tile = tiles[cand.id] = h('article', { class: 'tile', 'data-cid': cand.id, 'aria-label': 'Candidate ' + cand.id.toUpperCase() + ': ' + cand.title },
        h('div', { class: 'thead' }, h('span', { class: 'letter' }, cand.id.length <= 2 ? cand.id : cand.id[0]), h('h3', {}, cand.title),
          cand.recommended ? h('span', { class: 'chip accent' }, 'Suggested') : null,
          cand.carried_from ? h('span', { class: 'chip keep', title: 'You kept this in an earlier round' }, 'From last round') : null,
          timed ? h('button', { class: 'btn small', type: 'button', title: editable() ? 'Open it large and mark moments and stretches of it, with a note for each (Enter)' : 'Open it large, with the marks on it (Enter)',
            onclick: () => { seq.token++; if (m.play) m.play.stop(); const v = $('video', m.el); if (v) v.pause(); openOver([cand.id]); } }, editable() ? 'Mark' : 'Look closer') : null,
          cshare ? cshare.button : null,
          box ? h('label', { class: 'cmp' }, box, 'Compare') : null),
        cshare ? cshare.el : null,
        m.el,
        h('div', { class: 'tinfo' }, cand.summary && b.kind !== 'question' ? h('p', { class: 'sum' }, cand.summary) : null, markChip(cand.id),
          factsLine(cand) ? h('div', { class: 'facts' }, factsLine(cand)) : null,
          checks.length ? h('div', { class: 'checks' }, checks.map((c) => h('span', { class: c.level }, (c.level === 'error' ? 'Broken rule: ' : 'Note: ') + c.msg))) : null),
        ctl);
      tile.noteField = ctl.noteField; tile.box = box;
      tile.addEventListener('pointerenter', () => setCurrent(cand.id, false));
      tile.addEventListener('focusin', () => setCurrent(cand.id, false));
      if (visual && !timed) {
        let down = null;
        m.el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
        m.el.addEventListener('pointerup', (e) => { if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) openOver([cand.id]); down = null; });
      }
      (S.ui[cand.id] = S.ui[cand.id] || []).push(() => { const call = entry(cand.id).call; tile.className = 'tile' + (S.current === cand.id ? ' current' : '') + (call ? ' call-' + call : ''); });
      grid.append(tile);
    }
    main.append(h('section', {}, tools.childNodes.length ? tools : null, grid,
      b.mode !== 'question' && window.matchMedia && matchMedia('(pointer: fine)').matches ? h('p', { class: 'hint' }, 'Keys: ', h('kbd', {}, '←'), ' ', h('kbd', {}, '→'), ' move · ', h('kbd', {}, '1'), '–', h('kbd', {}, '0'), ' score · ',
        CALLS[b.mode].map(([, label, key]) => [h('kbd', {}, key), ' ' + label.toLowerCase() + ' · ']), h('kbd', {}, 'N'), ' note · ', h('kbd', {}, 'Enter'), ' look closer',
        b.kind === 'audio' ? [' · ', h('kbd', {}, 'Space'), ' play'] : null, canCompare ? [' · ', h('kbd', {}, 'C'), ' tick to compare'] : null) : null));

    function setCurrent(cid, scroll) {
      if (S.current === cid && !scroll) return;
      S.current = cid;
      for (const c of b.candidates) tiles[c.id].classList.toggle('current', c.id === cid);
      if (scroll) tiles[cid].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
    S.setCurrent = setCurrent; S.tiles = tiles; S.medias = medias;

    // verdict bar
    if (editable()) {
      const tally = h('div', { class: 'line' });
      const note = h('textarea', { class: 'field', id: 'batch-note', rows: 1, 'aria-label': 'Note on the whole batch',
        placeholder: b.mode === 'question' ? 'Or answer in your own words' : 'Anything about the batch as a whole, or what the next round should change',
        oninput: () => { if (b.mode === 'question') S.verdict.answer = note.value; else S.verdict.note = note.value; changed(null); } });
      note.value = b.mode === 'question' ? S.verdict.answer : S.verdict.note;
      const acts = ACTIONS[b.mode].map(([name, label]) => h('button', { class: 'btn small', type: 'button', 'data-act': name, onclick: () => { S.verdict.action = name; S.touched = true; changed(null); } }, label));
      const why = h('div', { class: 'why', role: 'status' });
      const send = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
        send.disabled = true;
        try { if (S.markFlush) await S.markFlush(); clearTimeout(saveTimer); await API.submit(b.id, S.verdict); S.state = await API.state(); toast('Verdict sent'); render(); }
        catch (e) { toast(e.message); send.disabled = false; }
      } }, 'Submit verdict');
      S.ui._bar = () => {
        const groups = {};
        for (const c of b.candidates) { const call = entry(c.id).call || 'none'; (groups[call] = groups[call] || []).push(c.id.toUpperCase()); }
        const chip = (call, label, cls) => groups[call] ? h('span', { class: 'chip ' + cls }, label + ' ' + groups[call].join(' ')) : null;
        tally.replaceChildren(...[chip('winner', b.mode === 'question' ? 'Chosen' : 'Winner', 'win'), chip('approve', 'Approved', 'win'), chip('keep', 'Keep', 'keep'), chip('redo', 'Redo', 'redo'), chip('reject', 'Reject', 'reject'),
          groups.none && b.mode !== 'question' ? h('span', { class: 'chip' }, groups.none.length + ' not marked') : null].filter(Boolean));
        acts.forEach((btn) => { const on = btn.dataset.act === S.verdict.action; btn.classList.toggle('on', on); btn.setAttribute('aria-pressed', on); });
        const p = problem(); why.textContent = p; send.disabled = !!p;
      };
      main.append(h('div', { class: 'vbar' }, h('div', { class: 'tally' }, tally, note), h('div', { class: 'acts', role: 'group', 'aria-label': 'What happens next' }, acts), h('div', { class: 'send' }, send, why)));
      S.ui._bar();
    }
    for (const c of b.candidates) (S.ui[c.id] || []).forEach((fn) => fn());
    document.addEventListener('keydown', onKey);
    return main;
  }

  function onKey(e) {
    const b = S.batch; if (!b) return;
    const typing = /^(TEXTAREA|INPUT|SELECT)$/.test((e.target || {}).tagName || '');
    if (e.key === 'Escape') { if (S.over) { closeOver(); e.preventDefault(); } else if (typing) e.target.blur(); return; }
    if (S.over && S.over.keys && S.over.keys(e)) return;  // a sound or a clip: Space, M, [ ], Delete and the rest are its own
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (S.over && !S.over.ids.length) return;  // a screenshot or reference is open: nothing to judge
    const ids = S.over ? S.over.ids : b.candidates.map((c) => c.id), i = ids.indexOf(S.current);
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (key === 'ArrowRight' || key === 'ArrowLeft') {
      const all = b.candidates.map((c) => c.id), at = all.indexOf(S.current), next = all[(at + (key === 'ArrowRight' ? 1 : all.length - 1)) % all.length];
      if (S.over && S.over.ids.length === 1) openOver([next]); else if (!S.over) S.setCurrent(next, true); else S.current = ids[(i + (key === 'ArrowRight' ? 1 : ids.length - 1)) % ids.length], S.over.mark();
      e.preventDefault(); return;
    }
    if (!S.current) return;
    if (/^[0-9]$/.test(key) && b.mode !== 'question') { setScore(S.current, key === '0' ? 10 : +key); e.preventDefault(); return; }
    const hit = CALLS[b.mode].find(([, , k]) => k.toLowerCase() === key) || (key === 'w' && b.mode === 'rate' ? CALLS.rate[0] : null);
    if (hit) { setCall(S.current, hit[0]); e.preventDefault(); return; }
    if (key === 'n') { const f = S.over && S.over.note ? S.over.note : S.tiles[S.current].noteField; if (f) { f.focus(); e.preventDefault(); } return; }
    if (key === 'Enter' && !S.over && S.visual) { openOver([S.current]); e.preventDefault(); return; }
    if (key === 'c' && !S.over && S.tiles[S.current].box) { S.tiles[S.current].box.click(); e.preventDefault(); return; }
    if (key === ' ') {
      const m = S.medias[S.current];
      if (m && m.play) { seq.token++; m.play.toggle(); e.preventDefault(); }
    }
  }

  // ---------------------------------------------------- look closer, compare
  function closeOver() {
    if (!S.over) return;
    const flush = S.markFlush, sent = flush ? flush() : null;
    // a clip's pictures are frames read from the clip itself: it is held until those on their way have gone. A change made
    // meanwhile (its frames a second, measured late) is then sent from the clip while it still stands, and only then is
    // the clip thrown away
    if (S.over.keep && sent && sent.then) { const gone = S.over.destroy, last = () => flush(); S.over.keep(); sent.then(last, last).then(gone, gone); S.over.destroy = () => {}; }
    S.over.destroy(); S.over.el.remove(); S.over = null;
    document.body.style.overflow = '';
    if (S.batch) for (const c of S.batch.candidates) S.ui[c.id] = (S.ui[c.id] || []).filter((fn) => !fn.over);
  }
  function openOver(ids) {
    closeOver();
    const b = S.batch, cands = ids.map((id) => b.candidates.find((c) => c.id === id)).filter(Boolean);
    if (!cands.length) return;
    const one = cands.length === 1;
    const group = { zoom: { t: { z: 1, cx: 0.5, cy: 0.5 }, panes: [] }, cam: { views: [], busy: false } };
    const medias = [], caps = {};
    const panes = h('div', { class: 'panes' });
    for (const cand of cands) {
      const m = media(cand, true, group); medias.push(m);
      const chip = h('span', { class: 'chip' });
      const cap = h('div', { class: 'cap' }, h('span', { class: 'letter' }, cand.id.length <= 2 ? cand.id : cand.id[0]), h('span', {}, cand.title), chip);
      const pane = h('div', { class: 'pane', 'data-cid': cand.id }, cap, m.el);
      pane.addEventListener('pointerenter', () => { S.current = cand.id; mark(); });
      caps[cand.id] = { pane, chip };
      const upd = () => { const e = entry(cand.id); chip.hidden = !e.call && !e.score; chip.className = 'chip ' + ({ winner: 'win', approve: 'win', keep: 'keep', redo: 'redo', reject: 'reject' }[e.call] || ''); chip.textContent = [e.call, e.score ? e.score + '/10' : ''].filter(Boolean).join(' '); };
      upd.over = true; (S.ui[cand.id] = S.ui[cand.id] || []).push(upd); upd();
      panes.append(pane);
    }
    function mark() { for (const id of Object.keys(caps)) caps[id].pane.style.outline = (!one && id === S.current) ? '2px solid var(--accent-fg)' : ''; }
    const oshare = one ? inboxShare(b, cands[0]) : null;
    const bar = h('div', { class: 'bar' },
      h('h3', {}, one ? cands[0].title : 'Comparing ' + cands.map((c) => c.id.toUpperCase()).join(', ')),
      h('span', { class: 'hint' }, one ? [h('kbd', {}, '←'), ' ', h('kbd', {}, '→'), ' next · scroll or pinch to zoom · double-click for full size']
        : ['Zoom and turn one, the others follow · point at one, then score or mark it with the keys']),
      oshare ? oshare.button : null,
      h('button', { class: 'btn small', type: 'button', onclick: closeOver }, 'Close (Esc)'));
    const opts = S.viewTools ? S.viewTools() : [];  // play, speed and the rest, kept in sight while looking closer at a model or a motion
    const el = h('div', { class: 'over', role: 'dialog', 'aria-modal': 'true', 'aria-label': one ? cands[0].title : 'Compare' }, bar,
      opts.length ? h('div', { class: 'tools overtools' }, opts) : null, panes);
    let noteField = null;
    if (one) {
      const ctl = controls(cands[0], true);
      S.ui[cands[0].id][S.ui[cands[0].id].length - 1].over = true;
      noteField = ctl.noteField;
      const info = h('div', {}, cands[0].summary ? h('p', { class: 'muted' }, cands[0].summary) : null, h('div', { class: 'facts' }, factsLine(cands[0])));
      const kids = [...ctl.children];
      const marking = markCandidate(cands[0], medias[0], el, bar);
      el.append(h('div', { class: 'side' }, h('div', {}, kids[0], kids.length > 2 ? kids[1] : null), info, h('div', {}, kids[kids.length - 1], marking)));
    }
    if (oshare) bar.after(oshare.el);  // under the bar, above the mark tools
    S.current = cands.some((c) => c.id === S.current) ? S.current : cands[0].id;
    S.over = { el, ids: cands.map((c) => c.id), note: noteField, mark, apply: () => medias.forEach((m) => m.set()), destroy: () => medias.forEach((m) => m.destroy()) };
    if (one && medias[0].el.classList.contains('timed')) {  // a sound or a clip: its own hint, and its own keys once it takes marks
      const view = medias[0].timed;
      if (view) Object.assign(S.over, { keys: (e) => !!view.keys && view.keys(e), keep: view.slow ? () => view.tp.hold() : null });
      bar.querySelector('.hint').replaceChildren(h('kbd', {}, '←'), ' ', h('kbd', {}, '→'), ' next' + (view ? ' · each mark has its own note, in the list beside it' : ''));
    }
    document.body.append(el); document.body.style.overflow = 'hidden';
    mark();
  }

  // marks on a candidate, in the closer look: kept on the verdict, with a picture beside the batch for Claude
  function markCandidate(cand, m, el, bar) {
    const b = S.batch, file = primary(cand);
    if (m.timed) return markTimed(cand, m, el, bar);  // a sound or a clip: marks along its time
    const isModel = !!(m.view && m.view.canvas);  // a model, or a motion baked from the project
    if (!isModel && !(file && b.kind !== 'in_app' && (file.kind === 'image' || file.kind === 'texture') && m.pane !== undefined)) return null;
    const ink = newInk(entry(cand.id).marks, isModel ? 'model' : 'image');
    let marker = null;
    const attach = (pane) => { marker = pane ? markImage(pane, ink) : null; if (marker) marker.mode(ink.on); };
    if (isModel) marker = markModel(m.view, ink);
    else { m.onPane = attach; if (m.pane) attach(m.pane); }
    const live = () => marker || { undo() {}, clear() {}, mode() {}, picture: async () => null };
    let timer = 0, pending = false;
    const send = async () => {
      clearTimeout(timer); timer = 0;
      if (!pending) return;
      pending = false;
      const blob = inkUsed(ink).length ? await live().picture() : null;
      await API.putMarks(b.id, cand.id, blob).catch((e) => toast('The marked picture was not saved: ' + e.message));
    };
    ink.subs.push(() => {
      if (!editable()) return;
      entry(cand.id).marks = inkData(ink); changed(cand.id);
      pending = true; clearTimeout(timer); timer = setTimeout(send, 1500);
    });
    S.markFlush = send;
    if (editable()) bar.after(h('div', { class: 'tools overtools' }, markTools(ink, live),
      h('span', { class: 'hint' }, isModel ? modelHint() + ' · a motion holds on its frame while you paint' : 'Paint areas · right-drag moves it · scroll zooms')));
    return markNotes(ink, editable, (mo) => live().goto && live().goto(mo));
  }

  // marks on something in the Library: they go to Claude as a note, with the marked picture on it
  function markOver(f, s) {
    const prev = $('.over.marking'); if (prev) prev.remove();
    const isModel = f.kind === 'model';
    const ink = newInk(null, isModel ? 'model' : 'image');
    ink.on = true;  // here the point is to mark: the brush is ready
    let marker = null, view = null, pane = null;
    const stage = h('div', { class: 'pane' });
    if (isModel) { view = modelView(f.url, { zoom: true, clip: f.clip }); stage.append(view.el); marker = markModel(view, ink); }
    else { pane = zoomPane(f.url, { t: { z: 1, cx: 0.5, cy: 0.5 }, panes: [] }); stage.append(pane.el); marker = markImage(pane, ink); }
    const words = h('textarea', { class: 'field', rows: 2, placeholder: 'Anything else about it (optional)', 'aria-label': 'A note on the whole thing' });
    const close = () => { document.removeEventListener('keydown', key); if (view) view.destroy(); if (pane && pane.destroy) pane.destroy(); el.remove(); document.body.style.overflow = ''; };
    const key = (e) => { if (e.key === 'Escape' && !/^(TEXTAREA|INPUT)$/.test((e.target || {}).tagName || '')) { close(); e.stopPropagation(); } };
    const send = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      const used = inkUsed(ink);
      if (!used.length) { toast('Mark something first'); return; }
      send.disabled = true;
      try {
        const lines = ['Marks on ' + s.title + ' (' + s.id + ', ' + f.label + '). The marked picture is attached; each colour is quoted with where it is.'];
        if (words.value.trim()) lines.push('', words.value.trim());
        lines.push('');
        for (const c of used) lines.push('- ' + c + ': ' + (ink.notes[c] && ink.notes[c].trim() ? '"' + ink.notes[c].trim() + '"' : '(no note)') + (ink.where[c] ? '. Where: ' + ink.where[c] : ''));
        const blob = await marker.picture();
        const made = (await API.addNote(lines.join('\n'), '', false)).note;
        if (blob) { const file = new File([blob], 'marks ' + s.id + '.png', { type: 'image/png' }); await sendFiles(made.id, [file]); }
        close(); await afterNote('Noted, with the marked picture');
      } catch (e) { toast(e.message); send.disabled = false; }
    } }, 'Send as a note');
    const bar = h('div', { class: 'bar' }, h('h3', {}, 'Mark ' + s.title), h('span', { class: 'hint' }, f.label),
      h('button', { class: 'btn small', type: 'button', onclick: close }, 'Close (Esc)'));
    const el = h('div', { class: 'over marking', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Mark ' + s.title }, bar,
      h('div', { class: 'tools overtools' }, markTools(ink, () => marker), h('span', { class: 'hint' }, isModel ? modelHint() : 'Paint areas · right-drag moves it · scroll zooms')),
      h('div', { class: 'panes' }, stage),
      h('div', { class: 'side marking' }, h('div', {}, markNotes(ink, () => true, (mo) => marker.goto && marker.goto(mo))), h('div', {}, words, h('div', { class: 'jf' }, send))));
    document.body.append(el); document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', key);
    marker.mode(true);
  }

  // ----------------------------------------------------------------- library
  function libraryPage() {
    const slots = S.state.slots, order = ['needed', 'placeholder', 'in_review', 'approved', 'in_use', 'parked'];
    const counts = {}; slots.forEach((s) => { counts[s.status] = (counts[s.status] || 0) + 1; });
    let filter = '', group = S.libGroup || '';
    S.libGroup = '';
    const list = h('div', { style: 'display:flex;flex-direction:column;gap:22px' });
    const names = [...new Set(slots.map((s) => s.group || 'Other'))].sort();
    const gsel = h('select', { 'aria-label': 'Group', onchange: () => { group = gsel.value; draw(); } }, h('option', { value: '' }, 'Every group'), names.map((n) => h('option', { value: n, selected: n === group }, n)));
    const find = h('input', { class: 'field', type: 'search', placeholder: 'Find an asset', 'aria-label': 'Find an asset', style: 'max-width:280px', oninput: () => draw() });
    const chips = [['', 'All ' + slots.length]].concat(order.filter((s) => counts[s]).map((s) => [s, SLOT[s] + ' ' + counts[s]])).map(([val, label]) => {
      const btn = h('button', { class: 'btn small' + (val === '' ? ' on' : ''), type: 'button', onclick: () => { filter = val; chips.forEach((c) => c.classList.toggle('on', c === btn)); draw(); } }, label); return btn;
    });
    function draw() {
      const groups = {};
      const q = find.value.trim().toLowerCase();
      slots.filter((s) => (!filter || s.status === filter) && (!group || (s.group || 'Other') === group) && (!q || (s.title + ' ' + s.id + ' ' + (s.notes || '')).toLowerCase().includes(q)))
        .forEach((s) => { (groups[s.group || 'Other'] = groups[s.group || 'Other'] || []).push(s); });
      const art = (g) => g.startsWith('Concept art');  // what the project runs on first, the reference art after
      list.replaceChildren(...Object.keys(groups).sort((a, b) => art(a) - art(b) || a.localeCompare(b)).map((g) => h('section', {}, h('h2', {}, g), h('div', { class: 'rows' }, groups[g].map((s) => {
        const cur = s.current, target = 's.' + s.id;
        const kids = [
          cur && cur.thumb && !S.state.static ? h('img', { class: 'thumb', src: '/' + cur.thumb, alt: '', loading: 'lazy' }) : h('span', { class: 'thumb' }, { model: '3D', audio: 'SFX', texture: 'TEX', image: 'IMG', in_app: 'APP', video: 'CLIP', text: 'TXT' }[s.kind] || ''),
          h('div', { class: 'grow' }, h('div', { class: 'title' }, s.title), h('div', { class: 'sub mono' }, s.id)),
          h('div', { class: 'sub', style: 'flex:1 1 200px' }, cur ? 'v' + cur.version + ': ' + (cur.title || cur.candidate) + (cur.score ? ' · ' + cur.score + '/10' : '') : (s.needed_by ? 'For ' + s.needed_by : (s.files || []).length ? (s.files.length === 1 ? '1 file' : s.files.length + ' files') : '')),
          h('div', { class: 'status' }, h('span', { class: 'dot st-' + s.status }), SLOT[s.status] || s.status)];
        return link(target, { class: 'row' }, kids);
      })))));
      if (!list.childNodes.length) list.append(h('div', { class: 'empty' }, 'Nothing here yet.'));
    }
    draw();
    return h('main', {},
      h('section', {}, h('h1', {}, 'What the project needs, and where each stands'),
        h('div', { class: 'bar-status', role: 'img', 'aria-label': order.filter((s) => counts[s]).map((s) => counts[s] + ' ' + SLOT[s]).join(', ') },
          order.filter((s) => counts[s]).map((s) => h('i', { class: 'st-' + s, style: 'width:' + (100 * counts[s] / slots.length) + '%' }))),
        h('div', { class: 'legend' }, order.filter((s) => counts[s]).map((s) => h('span', {}, h('span', { class: 'dot st-' + s }), h('b', {}, String(counts[s])), ' ' + SLOT[s]))),
        h('div', { class: 'filters' }, chips, gsel, find)),
      sharesSection(),
      list);
  }

  // --------------------------------------------------------------- decisions
  function decisionsPage() {
    const all = S.state.decisions.slice().reverse();
    const tagCount = {}; all.forEach((d) => (d.tags || []).forEach((t) => { tagCount[t] = (tagCount[t] || 0) + 1; }));
    const tags = Object.keys(tagCount).filter((t) => !t.includes('.')).sort((a, b) => tagCount[b] - tagCount[a]).slice(0, 12);
    let q = '', tag = '', limit = 30;
    const list = h('div', { class: 'rows' }), more = h('button', { class: 'btn', type: 'button', onclick: () => { limit += 60; draw(); } }, 'Show more');
    const search = h('input', { class: 'field', type: 'search', id: 'dec-search', placeholder: 'Search rulings and your own words', 'aria-label': 'Search decisions', oninput: () => { q = search.value.toLowerCase(); limit = 30; draw(); } });
    const tagBtns = tags.map((t) => { const btn = h('button', { class: 'btn small', type: 'button', onclick: () => { tag = tag === t ? '' : t; tagBtns.forEach((x) => x.classList.toggle('on', x === btn && tag === t)); limit = 30; draw(); } }, t); return btn; });
    function draw() {
      const hits = all.filter((d) => (!tag || (d.tags || []).includes(tag)) && (!q || [d.id, d.legacy, d.title, d.his_words, d.ruling].join(' ').toLowerCase().includes(q)));
      list.replaceChildren(...hits.slice(0, limit).map((d) => {
        const body = h('div', { hidden: true, style: 'display:flex;flex-direction:column;gap:10px' });
        const el = h('div', { class: 'dec' + (d.status === 'superseded' ? ' old' : '') },
          h('div', { class: 'dh', role: 'button', tabindex: '0', 'aria-expanded': 'false' }, h('span', { class: 'id' }, d.id + (d.legacy ? ' · ' + d.legacy : '')), h('span', { class: 't' }, d.title),
            d.status === 'superseded' ? h('span', { class: 'chip' }, 'Replaced by ' + d.superseded_by) : null, h('span', { class: 'd' }, d.date || '')),
          d.his_words ? h('blockquote', {}, d.his_words) : null, body);
        const head = el.firstChild, open = () => {
          if (!body.childNodes.length) body.append(d.ruling ? h('p', { class: 'full', html: inline(d.ruling) }) : '',
            h('p', { class: 'src' }, [(d.source || {}).type, (d.source || {}).ref].filter(Boolean).join(' · ') + ((d.tags || []).length ? ' · ' + d.tags.join(', ') : '')),
            (d.source || {}).type !== 'spec' && S.state.batches.some((b) => b.id === (d.source || {}).ref) ? link('b.' + d.source.ref, { class: 'btn small', style: 'align-self:flex-start' }, 'Open the batch') : '');
          body.hidden = !body.hidden; body.style.display = body.hidden ? 'none' : 'flex'; head.setAttribute('aria-expanded', String(!body.hidden));
        };
        body.style.display = 'none';
        head.addEventListener('click', open); head.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
        return el;
      }));
      if (!hits.length) list.replaceChildren(h('div', { class: 'row muted' }, 'No ruling matches.'));
      more.hidden = hits.length <= limit; more.textContent = 'Show more (' + Math.max(0, hits.length - limit) + ' left)';
    }
    draw();
    const title = h('input', { class: 'field', id: 'new-title', placeholder: 'What it settles, in a few words', 'aria-label': 'Title' });
    const words = h('textarea', { class: 'field', id: 'new-words', rows: 3, placeholder: 'Your ruling, in your own words', 'aria-label': 'Your words' });
    const add = h('button', { class: 'btn primary', type: 'button', onclick: async () => {
      if (!title.value.trim()) { toast('Give it a title'); return; }
      try { await API.addDecision({ title: title.value, his_words: words.value }); S.state = await API.state(); toast('On the record'); render(); } catch (e) { toast(e.message); }
    } }, 'Put it on the record');
    return h('main', {},
      h('section', {}, h('h1', {}, all.length + ' rulings on the record'),
        h('p', { class: 'muted', style: 'max-width:70ch' }, 'Newest first. The quoted lines are your words as they were written down; open a ruling to read what was taken from them. Every verdict you submit lands here by itself when Claude closes it.'),
        search, h('div', { class: 'filters' }, tagBtns)),
      h('section', {}, list, more),
      h('section', {}, h('div', { class: 'sec-head' }, h('h2', {}, 'Rule on something now'), h('p', {}, 'For a decision that did not come from a batch.')), h('div', { class: 'form' }, title, words, h('div', {}, add))));
  }

  // ------------------------------------------------------------ the notes box
  const NOTE = { directive: 'Change', bug: 'Bug', discussion: 'Discussion', options: 'Options', rule: 'Rule', later: 'Later' };
  const NOTE_CAT = [['', 'Unsorted']].concat(Object.keys(NOTE).map((k) => [k, NOTE[k]])); // the categories, in the order the filter row and the Category menu show them
  const notesOf = () => (S.state || {}).notes || [];
  const clip = (text, n) => { const t = String(text || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1).trimEnd() + '…' : t; };
  const afterNote = async (said) => { S.state = await API.state(); if (said) toast(said); const r = route(); if (r === 'notes' || r === 'overview') render(r, true); else { const bar = $('.top'); if (bar) bar.replaceWith(top(r)); } };

  // files on a note: any kind, any size; pictures show, the rest is a link
  const PICTURE = /\.(png|jpe?g|gif|webp|svg|bmp)$/i;
  const noteFileUrl = (n, f) => '/notefile/' + encodeURIComponent(n.id) + '/' + encodeURIComponent(f.name);
  const bytes = (n) => (n < 1024 ? n + ' bytes' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : n < 1073741824 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1073741824).toFixed(2) + ' GB');
  const stampName = (file) => { // a pasted screenshot comes in as "image.png": give it the time instead
    if (file.name && file.name !== 'image.png') return file.name;
    const d = new Date(), p = (x) => String(x).padStart(2, '0');
    return 'screenshot ' + d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds()) + '.' + ((file.type || '').split('/')[1] || 'png');
  };
  const pastedFiles = (e) => Array.from((e.clipboardData || {}).files || []);
  async function sendFiles(nid, files) {
    if (!files.length) return;
    toast(files.length === 1 ? 'Sending ' + files[0].name + '…' : 'Sending ' + files.length + ' files…');
    for (const f of files) await API.putFile(nid, f, f.studioName || f.name);
  }
  function pickFiles(take) {
    const input = h('input', { type: 'file', multiple: true, style: 'display:none', onchange: () => { take(Array.from(input.files || [])); input.remove(); } });
    document.body.append(input); input.click();
  }
  function dropTarget(el, take) {
    el.addEventListener('dragover', (e) => { if (Array.from(e.dataTransfer.types || []).includes('Files')) { e.preventDefault(); el.classList.add('dropping'); } });
    el.addEventListener('dragleave', () => el.classList.remove('dropping'));
    el.addEventListener('drop', (e) => { el.classList.remove('dropping'); const fs = Array.from(e.dataTransfer.files || []); if (fs.length) { e.preventDefault(); take(fs); } });
  }
  function noteFiles(n, open) {
    const files = n.files || [];
    if (!files.length) return null;
    const closed = n.status === 'done' || n.status === 'parked';
    return h('div', { class: 'nfiles' }, files.map((f) => {
      const url = noteFileUrl(n, f), away = !f.here;
      const label = h('span', { class: 'nfname' }, f.name, h('span', { class: 'muted' }, ' · ' + bytes(f.size || 0) + (away ? (closed ? ' · in the archive' : ' · on its way from the other copy') : '')));
      const off = open ? h('button', { class: 'btn small', type: 'button', title: 'Take this file off the note', onclick: async () => {
        try { await API.note(n.id, 'unfile', { name: f.name }); await afterNote('Taken off'); } catch (e) { toast(e.message); } } }, '×') : null;
      if (PICTURE.test(f.name) && !(away && !closed)) return h('figure', { class: 'nfile pic' }, h('a', { href: url, target: '_blank', rel: 'noopener' }, h('img', { src: url, alt: f.name, loading: 'lazy' })), h('figcaption', {}, label, off));
      return h('div', { class: 'nfile' }, away && !closed ? label : h('a', { href: url, target: '_blank', rel: 'noopener', download: f.name }, label), off);
    }));
  }

  // the Category menu: one drop menu, the same in the box for a new note and under every note; Unsorted leaves the sorting to a session
  function categoryMenu(value, pick, what) {
    const menu = h('select', { 'aria-label': what, onchange: () => pick(menu.value) }, NOTE_CAT.map(([k, label]) => h('option', { value: k }, label)));
    menu.value = value || ''; // set once the options are in: a value given before them does not hold
    return h('label', { class: 'cat', title: 'Unsorted leaves it to a session to say what kind of note it is' }, h('span', {}, 'Category'), menu);
  }

  // where the user types: one box, the same on the Notes page and behind the Note button on every page
  function noteBox(done) {
    const D = S.jot || (S.jot = { text: '', kind: '', files: [] });
    D.files = D.files || [];
    const tray = h('div', { class: 'nfiles pending' });
    const drawTray = () => tray.replaceChildren(...D.files.map((f, i) => h('span', { class: 'chip' }, f.studioName || f.name, ' · ' + bytes(f.size),
      h('button', { class: 'x', type: 'button', title: 'Leave this file out', onclick: () => { D.files.splice(i, 1); drawTray(); } }, '×'))));
    const take = (fs) => { for (const f of fs) { f.studioName = stampName(f); D.files.push(f); } drawTray(); };
    drawTray();
    const text = h('textarea', { class: 'field', rows: 2, placeholder: 'An order, a bug, a question, a half-formed idea. Enter sends it; Shift+Enter starts a new line.', 'aria-label': 'A note for the project',
      value: D.text, oninput: (e) => { D.text = e.target.value; } });
    const category = categoryMenu(D.kind, (k) => { D.kind = k; }, 'Category of the new note');
    const send = async () => {
      if (!text.value.trim()) { toast('Write the note first'); return; }
      let made = null;
      try {
        made = (await API.addNote(text.value, D.kind)).note;
        await sendFiles(made.id, D.files);
        S.jot = null; text.value = ''; await afterNote(D.kind === 'later' ? 'Kept for later' : 'Noted'); if (done) done();
      } catch (e) { // the note is kept even when a file did not get through: say so, and keep the files to try again on the note
        if (made) { S.jot = null; text.value = ''; await afterNote(); toast('Noted, but a file did not get through: ' + e.message + '. Add it on the note.'); }
        else toast(e.message);
      }
    };
    text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
    text.addEventListener('paste', (e) => { const fs = pastedFiles(e); if (fs.length) { e.preventDefault(); take(fs); } });
    const attach = h('button', { class: 'btn small', type: 'button', title: 'Put a file on the note. You can also paste a screenshot into the box, or drop files on it.', onclick: () => pickFiles(take) }, 'Attach');
    const box = h('div', { class: 'notebox' }, text, tray, h('div', { class: 'picks' }, h('span', { class: 'grow' }), category, attach, h('button', { class: 'btn small primary', type: 'button', onclick: send }, 'Send')));
    dropTarget(box, take);
    return { el: box, text };
  }
  function closeNotePop() { const el = $('.notepop'); if (el) el.remove(); document.removeEventListener('keydown', notePopKey); }
  function notePopKey(e) { if (e.key === 'Escape') { closeNotePop(); e.stopPropagation(); } }
  function openNotePop() {
    if ($('.notepop')) { closeNotePop(); return; }
    const box = noteBox(closeNotePop);
    document.body.append(h('div', { class: 'notepop', role: 'dialog', 'aria-label': 'Leave a note' },
      h('div', { class: 'jh' }, h('h2', { class: 'grow' }, 'Leave a note'), link('notes', { class: 'btn small', onclick: () => { closeNotePop(); go('notes'); } }, 'All notes'),
        h('button', { class: 'btn small', type: 'button', onclick: closeNotePop }, 'Close (Esc)')), box.el));
    document.addEventListener('keydown', notePopKey);
    box.text.focus();
  }
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'n' || e.ctrlKey || e.metaKey || e.altKey || S.over || !S.state || route().startsWith('b.')) return;
    if (/^(TEXTAREA|INPUT|SELECT)$/.test((e.target || {}).tagName || '')) return;
    e.preventDefault(); openNotePop();
  });

  function noteWhere(n) {
    const who = (x) => clip(x, 46);
    if (n.status === 'new') return n.handed ? 'Handed to ' + who(n.handed.name) + ' ' + when(n.handed.at) + '; not read yet' : 'Waiting for a session to read it';
    if (n.status === 'confirm') return n.choice_at === 'reading' ? 'Pick what you meant' : 'Confirm what Claude took it to mean';
    if (n.status === 'go') {
      if (n.waits === 'you') return 'Pick one before it is worked in';
      if (n.handed) return 'Handed to ' + who(n.handed.name) + ' ' + when(n.handed.at);
      if (n.to === '') return 'No session is on this part of the project';
      return 'Waiting for ' + (n.to === '*' ? 'the first session to reach a break' : who(n.to_name)) + ' to reach a break';
    }
    if (n.status === 'talk') return n.waits === 'you' ? (n.choice_at === null || n.choice_at === undefined ? 'Claude answered' : 'Claude answered: pick one') : (n.handed ? 'Handed to ' + who(n.handed.name) + ' ' + when(n.handed.at) : 'Waiting for a session to answer');
    if (n.status === 'later') return 'Kept for later';
    return n.status === 'done' ? (n.closed_by === 'you' ? 'Closed by you' : 'Done') : (n.closed_by === 'you' ? 'Set aside by you' : 'Left with you');
  }
  function noteCard(n) {
    S.notes = S.notes || {};
    const key = 'n:' + n.id, open = ['new', 'confirm', 'go', 'talk'].includes(n.status);
    const act = async (action, extra, said) => { // the box is emptied only by what sends its words; a change of category or of session leaves them there
      try { await API.note(n.id, action, extra); if (extra && 'text' in extra) delete S.notes[key]; await afterNote(said); } catch (e) { toast(e.message); } };
    const takes = open || n.status === 'later';
    const addFiles = async (fs) => { for (const f of fs) f.studioName = stampName(f); try { await sendFiles(n.id, fs); await afterNote(fs.length === 1 ? 'File added' : fs.length + ' files added'); } catch (e) { toast(e.message); } };
    const words = (hint) => h('textarea', { class: 'field', rows: 1, placeholder: hint, 'aria-label': hint + ' (' + n.id + ')', value: S.notes[key] || '', oninput: (e) => { S.notes[key] = e.target.value; },
      onpaste: (e) => { const fs = pastedFiles(e); if (fs.length) { e.preventDefault(); addFiles(fs); } } });
    const btn = (label, fn, cls) => h('button', { class: 'btn small' + (cls ? ' ' + cls : ''), type: 'button', onclick: fn }, label);
    const category = takes ? categoryMenu(n.kind, (k) => { if (k !== (n.kind || '')) act('kind', { kind: k }, k === 'later' ? 'Kept for later' : k ? 'Category: ' + NOTE[k] : 'Unsorted: a session will sort it'); }, 'Category of note ' + n.id) : null;
    const attach = takes ? btn('Attach', () => pickFiles(addFiles)) : null;
    const close = btn('Close', () => act('done', {}, 'Closed'));
    const tail = [h('span', { class: 'grow' }), category, attach];
    // the choices a session gave with a reading or an answer: a card each; only the latest set nobody has answered takes a click
    const thread = n.thread || [], asks = n.choice_at !== null && n.choice_at !== undefined;
    const saidAfter = (at) => { for (let j = at; j < thread.length; j++) if (thread[j].who === 'you') return String(thread[j].text || '').trim(); return null; };
    let picking = false;
    const pick = async (o) => { // a pick is the user's reply; on a reading to confirm it says which reading they meant, so a session reads the note again
      if (picking) return;
      picking = true;
      try { await API.note(n.id, n.status === 'confirm' ? 'back' : 'reply', { text: o.name }); await afterNote('Sent: ' + o.name); } catch (e) { picking = false; toast(e.message); }
    };
    const choices = (opts, at) => {
      if (!Array.isArray(opts) || !opts.length) return null;
      const live = asks && n.choice_at === at && !S.state.static, said = live ? null : saidAfter(at === 'reading' ? n.options_after || 0 : at + 1);
      return h('div', { class: 'choices', role: 'group', 'aria-label': live ? 'Pick one' : 'The choices given' }, opts.map((o, i) => {
        const mine = said !== null && said === o.name;
        const inside = [h('span', { class: 'ck' }, String.fromCharCode(65 + i)), h('span', { class: 'cn' }, o.name), mine ? h('span', { class: 'chip accent' }, 'Your pick') : null, o.what ? h('span', { class: 'cw' }, o.what) : null];
        return live ? h('button', { class: 'choice', type: 'button', title: 'Pick this one: it goes to the session as your reply', onclick: () => pick(o) }, inside) : h('div', { class: 'choice' + (mine ? ' picked' : '') }, inside);
      }));
    };
    let controls = null;
    if (n.status === 'confirm') {
      const t = words(asks ? 'What you meant, if it is none of these' : 'Anything to add, or what you meant instead');
      controls = [t, h('div', { class: 'jf' }, asks ? null : btn(n.kind === 'rule' ? 'Confirm the rule' : 'Confirm, work it in', () => act('confirm', { text: t.value }, 'Confirmed'), 'primary'),
        btn('Not what I meant', () => (t.value.trim() ? act('back', { text: t.value }, 'Sent back') : toast('Say what you meant instead'))), close, tail)];
    } else if (open) {
      const t = words(n.status === 'talk' ? 'Your reply' : 'Add to it'), sessions = ((S.state.overview || {}).live || {}).sessions || [];
      const sendTo = n.status === 'go' ? h('select', { 'aria-label': 'Send ' + n.id + ' to a session', onchange: (e) => { if (e.target.value) act('send', { session: e.target.value === '*' ? '' : e.target.value }, 'Sent'); } },
        h('option', { value: '' }, 'Send it to…'), h('option', { value: '*' }, 'Whichever session is free first'),
        sessions.filter((s) => s.state !== 'ended').map((s) => h('option', { value: s.id }, clip(s.title || s.prompt || 'A session', 50)))) : null;
      controls = [t, h('div', { class: 'jf' }, btn('Reply', () => (t.value.trim() ? act('reply', { text: t.value }, 'Sent') : toast('Write your reply first')), n.status === 'talk' || n.waits === 'you' ? 'primary' : ''), sendTo, close, tail)];
    } else if (n.status === 'later') controls = h('div', { class: 'jf' }, close, tail);
    else controls = h('div', { class: 'jf' }, btn('Open again', () => act('reopen', {}, 'Open again')));
    const card = h('article', { class: 'jot ' + n.status + (n.waits === 'you' ? ' mine' : ''), id: 'note-' + n.id },
      h('div', { class: 'jh' }, h('span', { class: 'id' }, n.id), h('span', { class: 'chip' + (n.kind ? ' accent' : '') }, n.kind ? NOTE[n.kind] || n.kind : 'Unsorted'),
        h('span', { class: 'where' }, noteWhere(n)), h('span', { class: 'd' }, when(n.created))),
      h('blockquote', {}, n.text),
      noteFiles(n, takes),
      n.from ? h('span', { class: 'sub' }, 'Part of ' + n.from + ', split off so each part gets its own answer.') : null,
      n.reading ? h('div', { class: 'answer' }, h('span', { class: 'label' }, n.status === 'confirm' ? 'Claude takes this to mean' : 'Taken to mean'), h('span', { html: inline(n.reading) }), choices(n.reading_options, 'reading')) : null,
      thread.map((m, i) => h('div', { class: 'msg ' + m.who }, h('span', {}, m.who === 'you' ? 'You' : 'Claude', h('br'), when(m.at)), m.who === 'you' ? h('div', { class: 'said' }, m.text) : [md(m.text), choices(m.options, i)])),
      n.result ? h('div', { class: 'answer' }, h('span', { class: 'label' }, n.status === 'parked' ? 'Why it was left' : 'What was done'), h('span', { html: inline(n.result) }),
        n.ref || n.decision ? h('span', { class: 'mono muted' }, [n.ref, n.decision ? 'on the record as ' + n.decision : ''].filter(Boolean).join(' · ')) : null) : null,
      controls);
    if (takes) dropTarget(card, addFiles);
    return card;
  }
  function notesPage() {
    const all = notesOf().slice().reverse(), ov = S.state.overview || {};
    const open = (n) => ['new', 'confirm', 'go', 'talk'].includes(n.status);
    const views = [['open', 'Open', open], ['you', 'Needs you', (n) => n.waits === 'you'], ['closed', 'Closed', (n) => n.status === 'done' || n.status === 'parked'], ['new', 'Unsorted', (n) => n.status === 'new' && !n.kind]]
      .concat(Object.keys(NOTE).map((k) => [k, NOTE[k], (n) => n.kind === k && (k === 'later' ? n.status === 'later' : open(n))]));
    S.noteView = views.some((v) => v[0] === S.noteView) ? S.noteView : 'open';
    const list = h('div', { class: 'jots' });
    const tabs = views.map(([id, label, test]) => { const count = all.filter(test).length;
      const b = h('button', { class: 'btn small' + (S.noteView === id ? ' on' : ''), type: 'button', onclick: () => { S.noteView = id; tabs.forEach((x) => x.classList.toggle('on', x === b)); draw(); } },
        label, count ? h('span', { class: 'count' + (id === 'you' ? ' hot' : '') }, String(count)) : null); return b; });
    function draw() {
      const test = views.find((v) => v[0] === S.noteView)[2];
      const rows = all.filter(test).sort((a, b) => (b.waits === 'you') - (a.waits === 'you'));
      list.replaceChildren(...(rows.length ? rows.map(noteCard) : [h('div', { class: 'empty' }, all.length ? 'Nothing here.' : (S.state.static ? 'No notes in this sample.' : 'No notes yet. Type one above.'))]));
    }
    draw();
    return h('main', {},
      h('section', {}, h('h1', {}, 'Notes'),
        h('p', { class: 'muted', style: 'max-width:76ch' }, 'Type whatever comes to mind and carry on. A session is handed your notes when it finishes a turn, or between steps once a note has waited a while, so nothing is spent checking for them. ',
          'A change or a rule comes back to you to confirm before anything is done; a question becomes a thread you answer here.'),
        S.state.static ? null : noteBox().el,
        ov.hooks_notes === false && !S.state.static ? h('div', { class: 'say' }, h('span', {}, 'Sessions are not being handed your notes yet. In the project, say to Claude Code:'), h('code', {}, 'turn on the Studio\'s live reporting'), copyButton('turn on the Studio\'s live reporting')) : null),
      h('section', {}, h('div', { class: 'filters' }, tabs.slice(0, 3), h('span', { class: 'split' }), tabs.slice(3)), list)); // three statuses, then the seven categories as the Category menu names them
  }

  // ------------------------------------------------------------ talking to the project's sessions
  const TALK_STATE = { starting: 'Starting', working: 'Working', asking: 'Asks you', idle: 'Your turn', ended: 'Stopped' };
  function talkPage() {
    const T = S.talk || (S.talk = { key: '', after: 0, draft: '', files: [], resume: '', fork: false, title: '' });
    T.files = T.files || [];
    const side = h('div', { class: 'tside' });
    const log = h('div', { class: 'tlog', 'aria-live': 'polite' });
    const asks = h('div', { class: 'tasks' });
    const btns = h('div', { class: 'tbtns' });
    let btnKey = '';
    const head = h('div', { class: 'thead' });
    const tray = h('div', { class: 'nfiles pending' });
    const text = h('textarea', { class: 'field', rows: 3, 'aria-label': 'Your message to the session',
      placeholder: 'Talk to the session. Enter sends; Shift+Enter starts a new line. Paste a screenshot or drop files to attach them.',
      value: T.draft, oninput: (e) => { T.draft = e.target.value; } });
    let busy = false, ended = false, cur = '';
    const working = () => cur === 'working' || cur === 'asking';
    const acts = h('span', { class: 'tacts' });
    async function stopIt() {
      try { await call('POST', '/api/talk/' + encodeURIComponent(T.key), { action: 'interrupt' }); poll(); } catch (e) { toast(e.message); }
    }
    function drawActs() {
      text.placeholder = working() ? 'It is working. Enter sends: it reads your message at its next step, as in the terminal. Esc stops it.'
        : 'Talk to the session. Enter sends; Shift+Enter starts a new line. Paste a screenshot or drop files to attach them.';
      acts.replaceChildren(...[h('button', { class: 'btn small', type: 'button', onclick: () => pickFiles(take) }, 'Attach'),
        working() ? h('button', { class: 'btn small', type: 'button', title: 'Stop what it is doing now (Esc); the session stays', onclick: stopIt }, 'Stop') : null,
        working() ? h('button', { class: 'btn small', type: 'button', title: 'Stop what it is doing, then send this as your next message', onclick: () => send(undefined, true) }, 'Stop and send') : null,
        h('button', { class: 'btn small primary', type: 'button', title: working() ? 'It reads this at its next step, without stopping' : 'Send (Enter)', onclick: () => send() }, 'Send')].filter(Boolean));
    }

    const drawTray = () => tray.replaceChildren(...T.files.map((f, i) => h('span', { class: 'chip' }, f.studioName || f.name, ' · ' + bytes(f.size),
      h('button', { class: 'x', type: 'button', title: 'Leave this file out', onclick: () => { T.files.splice(i, 1); drawTray(); } }, '×'))));
    const take = (fs) => { for (const f of fs) { f.studioName = stampName(f); T.files.push(f); } drawTray(); };
    drawTray();

    function line(e) {
      const old = e.old ? ' old' : '';
      if (e.kind === 'you') return h('div', { class: 'msg you' + old }, h('span', {}, 'You', h('br'), when(e.at)), h('div', { class: 'said' }, e.text));
      if (e.kind === 'claude') return h('div', { class: 'msg claude' + old }, h('span', {}, 'Claude', h('br'), when(e.at)), md(e.text));
      if (e.kind === 'tool') return h('div', { class: 'tline' + old }, '› ' + e.text);
      if (e.kind === 'tool-error') return h('div', { class: 'tline bad' }, '› ' + clip(e.text, 300));
      if (e.kind === 'ask') return h('div', { class: 'tline' }, 'Asked to: ' + e.text);
      if (e.kind === 'answer') return h('div', { class: 'tline' }, e.text);
      if (e.kind === 'turn') return h('div', { class: 'tturn' });
      if (e.kind === 'blocked') {
        const row = h('div', { class: 'tblock' }, h('span', { class: 'label' }, 'Auto mode blocked this'), h('div', {}, e.text));
        if (!e.old && !ended) row.append(h('div', { class: 'jf' },
          h('button', { class: 'btn small primary', type: 'button', onclick: () => send('I allow what auto mode just blocked (' + clip(e.text, 300) + '). Go ahead and do it.') }, 'Allow it'),
          h('button', { class: 'btn small', type: 'button', onclick: () => row.remove() }, 'Leave it')));
        return row;
      }
      return h('div', { class: 'tline' + (e.kind === 'ended' ? ' bad' : '') }, e.text);
    }
    function add(events) {
      const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
      for (const e of events) log.append(line(e));
      if (atEnd || events.some((e) => e.kind === 'you')) log.scrollTop = log.scrollHeight;
    }
    function drawAsks(list) {
      asks.replaceChildren(...list.map((a) => {
        const why = h('input', { class: 'field', type: 'text', placeholder: 'Why not (optional, the session reads it)', 'aria-label': 'Why not' });
        const act = async (action) => { try { await call('POST', '/api/talk/' + encodeURIComponent(T.key), { action, ask: a.id, text: why.value }); poll(); } catch (e) { toast(e.message); } };
        return h('div', { class: 'task' }, h('span', { class: 'label' }, 'The session asks to'), h('code', { class: 'cmd' }, a.line), a.why ? h('div', { class: 'muted' }, a.why) : null,
          h('div', { class: 'jf' }, h('button', { class: 'btn small primary', type: 'button', onclick: () => act('allow') }, 'Allow'), h('button', { class: 'btn small', type: 'button', onclick: () => act('deny') }, 'Deny'), why));
      }));
    }
    function drawButtons(list) { // drawn again only when the session files or changes one, so a run being read keeps going
      const key = JSON.stringify(list.map((b) => [b.id, b.button, b.run, b.open, b.cwd]));
      if (key === btnKey) return;
      btnKey = key;
      btns.replaceChildren(...list.map((b) => h('div', { class: 'task' }, h('span', { class: 'label' }, 'A button for you: ' + b.title), buttonBox(b).el)));
    }
    function drawHead(state) {
      if (state !== cur) { cur = state; drawActs(); }
      const label = state ? TALK_STATE[state] || state : (T.resume ? 'Not started here yet' : 'New session');
      head.replaceChildren(...[h('h2', { class: 'grow' }, T.title || (T.key || T.resume ? 'A session' : 'A new session')),
        h('span', { class: 'chip' + (state === 'asking' ? ' accent' : state === 'ended' ? ' bad' : '') }, label),
        state === 'working' || state === 'asking' ? h('button', { class: 'btn small', type: 'button', title: 'Stop what it is doing now (Esc); the session stays', onclick: stopIt }, 'Stop') : null,
        sid() && state !== 'working' && state !== 'asking' ? h('button', { class: 'btn small primary', type: 'button', title: 'Carry this session on in the Claude desktop app: the same session, with all of it',
          onclick: toDesktop }, 'Open in Claude app') : null].filter(Boolean));
    }
    function sid() { return T.key && !T.key.startsWith('new-') ? T.key : T.resume; }
    async function toDesktop() {
      const id = sid();
      try {
        toast('Opening it in the Claude app…');
        await call('POST', '/api/talk/desktop', { id });
        toast('It is in the Claude app now. Carry on there.');
        Object.assign(T, { key: '', resume: '', title: '' }); log.replaceChildren(); asks.replaceChildren(); btns.replaceChildren(); btnKey = ''; drawHead(''); list();
      } catch (e) { toast(e.message); }
    }
    async function poll() {
      if (!T.key || busy) return;
      busy = true;
      try {
        const v = await call('GET', '/api/talk/' + encodeURIComponent(T.key) + '?after=' + T.after + (document.visibilityState === 'visible' ? '&seen=1' : ''));
        if (v.key && v.key !== T.key) T.key = v.key;
        add(v.events); T.after = v.seq; ended = v.state === 'ended';
        drawAsks(v.asks || []); drawButtons(v.buttons || []); drawHead(v.state);
      } catch (e) { drawHead('ended'); ended = true; }
      finally { busy = false; }
    }
    function pick(row, fork) { // an older session: show what was said; it starts again here when you send
      Object.assign(T, { key: '', after: 0, resume: row ? row.id : '', fork: !!fork, title: row ? (row.title || clip(row.prompt, 60)) : '' });
      log.replaceChildren(); asks.replaceChildren(); btns.replaceChildren(); btnKey = ''; ended = false; drawHead('');
      if (row) call('GET', '/api/talk/' + encodeURIComponent(row.id) + '/history').then((d) => { if (T.resume === row.id && !T.key) add(d.events || []); }).catch(() => {});
      text.focus(); list();
    }
    function show(row) { // a conversation this page has going
      Object.assign(T, { key: row.key, after: 0, resume: '', fork: false, title: clip(row.last, 60) || 'A session' });
      log.replaceChildren(); asks.replaceChildren(); btns.replaceChildren(); btnKey = ''; poll(); list();
    }
    async function send(words, stop) {
      const said = (words === undefined ? text.value : words).trim();
      if (!said && !T.files.length) { toast('Write your message first'); return; }
      let full = said;
      try {
        if (T.files.length) {
          const paths = [];
          for (const f of T.files) {
            const res = await fetch(rel('/api/talkfile?name=' + encodeURIComponent(f.studioName || f.name)), { method: 'PUT', headers: { 'X-Studio-File': '1' }, body: f });
            const d = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(d.error || 'a file did not get through');
            paths.push(d.path);
          }
          full += (full ? '\n\n' : '') + 'Files I attached:\n' + paths.map((p) => '- ' + p).join('\n');
        }
        if (T.key && !ended) await call('POST', '/api/talk/' + encodeURIComponent(T.key), { action: 'say', text: full, stop: !!stop });
        else {
          const d = await call('POST', '/api/talk', { text: full, resume: T.key || T.resume, fork: T.fork });
          T.key = d.key; T.after = T.resume ? 0 : T.after; if (T.resume) log.replaceChildren(); T.resume = '';
        }
        if (words === undefined) { text.value = ''; T.draft = ''; }
        T.files = []; drawTray(); poll(); list();
      } catch (e) { toast(e.message); }
    }
    async function list() {
      let d;
      try { d = await call('GET', '/api/talk'); } catch (e) { side.replaceChildren(h('div', { class: 'empty' }, e.message)); return; }
      const rows = [];
      rows.push(h('div', { class: 'jf' }, h('button', { class: 'btn small primary', type: 'button', onclick: () => pick(null) }, 'New session'),
        d.past.length ? h('button', { class: 'btn small', type: 'button', title: 'Like claude -c: the last session in this project', onclick: () => pick(d.past[0], !!d.past[0].live && d.past[0].live !== 'ended') }, 'Carry on with the last') : null,
        !I.stage ? h('button', { class: 'btn small', type: 'button', title: 'Work a loose idea over with Claude, a few questions at a time, until it is a spec', onclick: () => { I.shaping = true; drawIdea(); } }, 'Shape an idea') : null));
      if (d.talks.length) {
        rows.push(h('h3', {}, 'Going here'));
        for (const t of d.talks) rows.push(h('button', { class: 'trow' + (t.key === T.key ? ' on' : ''), type: 'button', onclick: () => show(t) },
          h('span', { class: 'chip' + (t.waits ? ' accent' : '') }, t.waits === 'ask' ? 'Asks you' : t.waits === 'reply' ? 'Replied' : TALK_STATE[t.state] || t.state), h('span', { class: 'tt' }, clip(t.last, 90) || 'Starting')));
      }
      const mine = new Set(d.talks.map((t) => t.id));
      const past = d.past.filter((p) => !mine.has(p.id));
      if (past.length) {
        rows.push(h('h3', {}, 'Earlier sessions'));
        for (const p of past) {
          const elsewhere = p.live && p.live !== 'ended';
          rows.push(h('button', { class: 'trow' + (p.id === T.resume ? ' on' : ''), type: 'button', title: elsewhere ? 'Open in a terminal now: carrying on here makes a copy, so the two do not trip over each other' : 'Show it; send a message to carry on with it',
            onclick: () => pick(p, elsewhere) }, h('span', { class: 'tt' }, p.title || clip(p.prompt, 80) || p.id), h('span', { class: 'd' }, (elsewhere ? 'open elsewhere · ' : '') + when(p.at))));
        }
      }
      side.replaceChildren(...rows);
    }

    text.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
      else if (e.key === 'Escape' && working()) { e.preventDefault(); stopIt(); }
    });
    text.addEventListener('paste', (e) => { const fs = pastedFiles(e); if (fs.length) { e.preventDefault(); take(fs); } });
    drawActs();
    const box = h('div', { class: 'tbox' }, tray, text, h('div', { class: 'jf' }, h('span', { class: 'grow muted' }, 'Auto mode decides what it may do. What it asks about comes here.'), acts));
    dropTarget(box, take);

    // the idea loop: docs/idea.md beside the talk, kept by the session; start it, then say when it is done
    const I = S.idea || (S.idea = { stage: '', text: '', first: '', key: '', shaping: false, shown: '' });
    const ideaBox = h('div', { class: 'tidea' });
    function drawIdea() {
      if (!I.stage && !I.shaping) { ideaBox.replaceChildren(); ideaBox.hidden = true; return; }
      ideaBox.hidden = false;
      const parts = [h('div', { class: 'jf' }, h('span', { class: 'label grow' }, I.stage === 'loop' ? 'The idea so far (Claude keeps this as you talk)' : I.stage === 'done' ? 'The idea, done: the spec is written from it' : 'The idea loop'),
        I.stage === 'loop' ? h('button', { class: 'btn small primary', type: 'button', title: 'Claude writes docs/spec.md from this and finishes setting the project up', onclick: ideaDone }, 'Done: write the spec') : null)];
      if (I.stage === 'idea' || (!I.stage && I.shaping)) {
        const first = h('textarea', { class: 'field', rows: 3, 'aria-label': 'The idea', placeholder: 'The idea, however loose', value: I.first || '' });
        parts.push(h('p', { class: 'muted' }, 'Claude asks 3 to 5 questions at a time, each with what it recommends, and names the holes it sees. What gets settled goes into docs/idea.md, shown here. Say "done" with the button when it is clear.'),
          first, h('div', { class: 'jf' }, h('span', { class: 'grow' }), !I.stage ? h('button', { class: 'btn small', type: 'button', onclick: () => { I.shaping = false; drawIdea(); } }, 'Not now') : null,
            h('button', { class: 'btn small primary', type: 'button', onclick: () => ideaStart(first.value) }, 'Start the loop')));
      }
      if (I.text && I.stage) parts.push(h('div', { class: 'ideadoc' }, md(I.text.replace(/^# .*\n/, ''))));
      ideaBox.replaceChildren(...parts);
    }
    async function ideaLoad() {
      try {
        const v = await call('GET', '/api/idea');
        const key = v.stage + '|' + v.text;
        Object.assign(I, { stage: v.stage, first: I.first || v.first, key: v.key, text: v.text });
        if (v.stage === 'loop' && !T.key && !T.resume && v.key) show({ key: v.key, last: 'The idea loop' });
        if (key !== I.shown) { I.shown = key; drawIdea(); }
      } catch (e) { /* the page is a sample, or the server is restarting */ }
    }
    async function ideaStart(words) {
      if (!String(words || '').trim()) { toast('Write the idea first'); return; }
      try {
        const d = await call('POST', '/api/idea', { action: 'start', text: words });
        I.shaping = false; I.shown = ''; T.key = ''; show({ key: d.key, last: 'The idea loop' }); ideaLoad();
      } catch (e) { toast(e.message); }
    }
    async function ideaDone() {
      try { const d = await call('POST', '/api/idea', { action: 'done', key: I.key || T.key }); show({ key: d.key, last: 'The idea loop' }); I.shown = ''; ideaLoad(); toast('Claude is writing the spec'); }
      catch (e) { toast(e.message); }
    }

    drawHead(''); list(); drawIdea(); ideaLoad();
    if (T.key) poll(); else if (T.resume) pick({ id: T.resume, title: T.title }, T.fork);
    const timer = setInterval(poll, 1000), lister = setInterval(list, 8000), ideaTimer = setInterval(ideaLoad, 3000);
    S.cleanup.push(() => { clearInterval(timer); clearInterval(lister); clearInterval(ideaTimer); });
    return h('main', { class: 'talk' }, h('section', { class: 'tgrid' }, side, h('div', { class: 'tmain' }, head, ideaBox, log, btns, asks, box)));
  }

  // --------------------------------------------------------------- test_runs
  function testRunsPage() {
    const sessions = S.state.test_runs;
    const main = h('main', {});
    main.append(h('section', {}, h('h1', {}, 'What you said in test runs, and what became of it'),
      h('p', { class: 'muted', style: 'max-width:70ch' }, 'Each F8 report is listed with what was done about it. When a note is marked fixed, try the build and say whether it is.')));
    if (!sessions.length) main.append(h('div', { class: 'empty' }, 'No test-run folder is set yet (studio.toml, [test_runs] dirs), or it holds no session.'));
    for (const p of sessions) {
      const tot = { pass: 0, fail: 0, untested: 0 }; p.checklist.forEach((c) => { tot[c.result] = (tot[c.result] || 0) + 1; });
      const ptUrl = (rep, name) => S.state.static ? API.src('/pt/' + p.root + '/' + p.name + '/' + rep + '/' + name) : '/pt/' + p.root + '/' + encodeURIComponent(p.name) + '/' + rep + '/' + name;
      main.append(h('section', {},
        h('div', { class: 'pt-head' }, h('h3', {}, 'Build ' + p.build), h('span', { class: 'mono muted' }, [p.date, p.machine].filter(Boolean).join(' · ')),
          h('span', { class: 'chip ok' }, tot.pass + ' pass'), tot.fail ? h('span', { class: 'chip bad' }, tot.fail + ' fail') : null, tot.untested ? h('span', { class: 'chip' }, tot.untested + ' untested') : null,
          Object.entries(p.sliders || {}).map(([k, val]) => h('span', { class: 'chip' }, k + ' ' + val + '/5'))),
        p.end_note ? h('div', { class: 'endnote' }, h('h2', {}, 'What you wrote on the end screen'), h('blockquote', {}, p.end_note)) : null,
        p.checklist.length ? h('details', { class: 'brief' }, h('summary', {}, 'The checklist, item by item'),
          h('div', { class: 'marks', style: 'padding-top:8px' }, p.checklist.map((c) => h('div', { class: 'mark' }, h('b', { class: c.result }, c.result), h('span', {}, c.feature))))) : null,
        h('div', { class: 'notes' }, p.reports.map((rep) => {
          const t = rep.triage || { status: 'open' };
          const label = { open: ['Not answered yet', 'reject'], planned: ['Planned', 'keep'], fixed: ['Fixed' + (t.build ? ' in ' + t.build : ''), 'ok'], wontfix: ['Not doing', ''], question: ['Claude has a question', 'redo'] }[t.status] || [t.status, ''];
          const said = h('textarea', { class: 'field', rows: 1, placeholder: 'What is still wrong (optional)', 'aria-label': 'What is still wrong' }); said.value = t.confirm_note || '';
          const confirm = async (ok) => { try { await API.confirm(rep.key, ok, said.value); S.state = await API.state(); toast(ok ? 'Marked fixed for you' : 'Sent back'); render(); } catch (e) { toast(e.message); } };
          return h('article', { class: 'note' },
            rep.screenshot ? h('img', { class: 'shot', src: ptUrl(rep.id, rep.screenshot), alt: 'Screenshot for this note', loading: 'lazy', onclick: (e) => shot(e.target.src) }) : null,
            h('div', { class: 'nb' }, h('blockquote', {}, rep.note || '(no note)'),
              h('div', { class: 'meta', style: 'display:flex;gap:6px;flex-wrap:wrap' }, h('span', { class: 'chip ' + label[1] }, label[0]),
                (rep.stats || {}).checklist_item ? h('span', { class: 'chip' }, 'Item: ' + (rep.stats.checklist_item.feature || rep.stats.checklist_item.id || rep.stats.checklist_item)) : null, h('span', { class: 'mono muted' }, rep.id)),
              t.note || t.ref ? h('div', { class: 'answer' }, t.note ? h('span', {}, t.note) : null, t.ref ? h('span', { class: 'mono muted' }, t.ref) : null) : null,
              t.status === 'fixed' ? (t.confirmed == null
                ? h('div', { style: 'display:flex;flex-direction:column;gap:8px' }, said, h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
                  h('button', { class: 'btn small', type: 'button', onclick: () => confirm(true) }, 'Fixed for me'), h('button', { class: 'btn small', type: 'button', onclick: () => confirm(false) }, 'Still wrong')))
                : h('span', { class: 'chip ' + (t.confirmed ? 'ok' : 'bad') }, t.confirmed ? 'You confirmed it' : 'You said: still wrong' + (t.confirm_note ? ' · ' + t.confirm_note : ''))) : null));
        }))));
    }
    return main;
  }
  function shot(src) {
    const group = { t: { z: 1, cx: 0.5, cy: 0.5 }, panes: [] };
    const pane = zoomPane(src, group);
    const el = h('div', { class: 'over', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Screenshot' },
      h('div', { class: 'bar' }, h('h3', {}, 'Screenshot'), h('span', { class: 'hint' }, 'Scroll or pinch to zoom'), h('button', { class: 'btn small', type: 'button', onclick: () => closeOver() }, 'Close (Esc)')),
      h('div', { class: 'panes' }, h('div', { class: 'pane' }, pane.el)));
    const esc2 = (e) => { if (e.key === 'Escape') closeOver(); };
    document.addEventListener('keydown', esc2);
    S.over = { el, ids: [], destroy: () => { document.removeEventListener('keydown', esc2); if (pane.destroy) pane.destroy(); } };
    document.body.append(el); document.body.style.overflow = 'hidden';
  }

  // ------------------------------------------------------------------ notify
  // desktop notifications: the server keeps what was already seen and hands each new thing in Needs you out once,
  // to the first page that asks and can show it; in the app that covers every project opened in the window
  const NT = { busy: false };
  const canNotify = () => 'Notification' in window && !STATIC && !!(S.state && S.state.notify);
  const notifyOn = () => !!((S.state || {}).ui || {}).notify;
  // the switch at the top of Needs you: off until the user turns it on, and Windows asks once for this page
  function notifySwitch() {
    if (!canNotify()) return null;
    const on = notifyOn(), allowed = Notification.permission;
    const label = !on ? 'Notify' : allowed === 'granted' ? 'Notify' : allowed === 'denied' ? 'Notify: blocked here' : 'Notify: allow here';
    return h('button', { class: 'btn small notify-btn' + (on && allowed === 'granted' ? ' on' : ''), type: 'button', 'aria-pressed': String(on), onclick: notifyPress }, label);
  }
  function notifyDraw() { for (const b of document.querySelectorAll('.notify-btn')) { const n = notifySwitch(); if (n) b.replaceWith(n); else b.remove(); } }
  async function notifyPress() {
    const on = notifyOn();
    if (on && Notification.permission === 'granted') return notifySet(false);
    let allowed = Notification.permission;
    if (allowed === 'default') { try { allowed = await Notification.requestPermission(); } catch (e) { allowed = Notification.permission; } }
    if (allowed !== 'granted') {
      notifyDraw();
      toast(allowed === 'denied' ? 'Blocked: allow notifications in site settings' : 'Not allowed: press Notify, then Allow');
      return;
    }
    if (!on) await notifySet(true); else { notifyDraw(); toast('Notifications on'); }
    notifyLook();
  }
  async function notifySet(on) {
    try {
      const d = await API.ui({ notify: on }); S.state.ui = d.ui || Object.assign({}, S.state.ui, { notify: on }); notifyDraw();
      toast(on ? 'Notifications on' : 'Notifications off');
    } catch (e) { toast(e.message); }
  }
  // asks the server what is new; with no leave to show it here, the server keeps it for a page that has
  async function notifyLook() {
    if (!canNotify() || !notifyOn() || NT.busy) return;
    NT.busy = true;
    try {
      const d = await call('GET', '/api/notices' + (Notification.permission === 'granted' ? '?can=1' : ''));
      if (!d.on) { S.state.ui = Object.assign({}, S.state.ui, { notify: false }); notifyDraw(); }
      for (const x of d.notices || []) notifyShow(x);
    } catch (e) { /* the server is restarting; the next beat asks again */ }
    NT.busy = false;
  }
  function notifyShow(x) {
    try {
      const n = new Notification(x.title, { body: x.project + ' · ' + x.what, tag: x.project + '|' + x.key, icon: new URL(rel('/web/icon-256.png'), location.href).href });
      n.onclick = () => { try { window.focus(); } catch (e) { /* the window comes forward by itself */ } n.close(); notifyGo(x.url); };
    } catch (e) { toast('New in Needs you: ' + x.title); }
  }
  // a click on one: that project's page, at the thing itself
  function notifyGo(url) {
    const to = new URL(url, location.href);
    if (to.origin + to.pathname !== location.origin + location.pathname) { location.href = to.href; return; }
    if (location.hash === to.hash) render(route()); else location.hash = to.hash;
  }
  // #ask.<id> and #note.<id>: that ask opened in Needs you, or that note on the Notes page, scrolled into view
  function focusOn(r) {
    const at = r.indexOf('.'), kind = r.slice(0, at), id = r.slice(at + 1), to = kind === 'ask' ? 'overview' : 'notes';
    if (kind === 'ask') { OPEN.set('ask:' + id, true); S.focus = '[data-fold="' + CSS.escape('ask:' + id) + '"]'; }
    else { S.noteView = 'you'; S.focus = '#' + CSS.escape('note-' + id); }
    try { history.replaceState(null, '', '#' + to); } catch (e) { /* sandboxed */ }
    return to;
  }
  function reveal() {
    const el = $(S.focus); S.focus = '';
    if (!el) { toast('No longer waiting'); return; }
    el.scrollIntoView({ block: 'center' }); el.classList.add('found'); setTimeout(() => el.classList.remove('found'), 2500);
  }
  if (!STATIC) setInterval(notifyLook, 5000);

  // -------------------------------------------------------------------- live
  async function pulse() {
    try {
      const p = await API.pulse();
      if (S.state && p.stamp !== S.state.stamp) {
        const before = new Set(S.state.batches.filter((b) => b.status === 'open').map((b) => b.id));
        S.state = await API.state();
        const fresh = S.state.batches.filter((b) => b.status === 'open' && !before.has(b.id));
        if (fresh.length) toast('New in your inbox: ' + fresh[0].title);
        const r = route();
        if (!r.startsWith('b.') && !r.startsWith('s.') && r !== 'talk' && !S.over && !/^(TEXTAREA|INPUT)$/.test((document.activeElement || {}).tagName || '')) render(r, true);
        else { const bar = $('.top'); if (bar) bar.replaceWith(top(r)); }
      }
    } catch (e) { /* the server is restarting; try again on the next beat */ }
  }
  if (!STATIC) setInterval(pulse, 4000);
  render(route());
})();
