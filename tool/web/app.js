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
  function md(text) {
    const out = h('div', { class: 'md' });
    let list = null;
    for (const raw of String(text || '').split('\n')) {
      const line = raw.trimEnd();
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
  function copyButton(text, label) {
    const btn = h('button', { class: 'btn small', type: 'button' }, label || 'Copy');
    btn.addEventListener('click', () => {
      const done = () => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = label || 'Copy'; }, 1400); };
      try { navigator.clipboard.writeText(text).then(done, () => toast('Select the text and copy it by hand')); }
      catch (e) { toast('Select the text and copy it by hand'); }
    });
    return btn;
  }
  const KIND = { image: 'Pictures', texture: 'Textures', model: 'Models', audio: 'Sounds', video: 'Clips', text: 'Writing', ingame: 'In the game', question: 'Question', mixed: 'Mixed' };
  const GLYPH = { model: '3D', audio: 'Sound', video: 'Clip', text: 'Text', ingame: 'In game', question: '?', mixed: 'Mixed' };
  const CALLS = { pick: [['winner', 'Winner', 'W'], ['keep', 'Keep', 'K'], ['redo', 'Redo', 'R'], ['reject', 'Reject', 'X']],
    rate: [['approve', 'Approve', 'A'], ['redo', 'Redo', 'R'], ['reject', 'Reject', 'X']], question: [['winner', 'Choose this', 'W']] };
  const ACTIONS = { pick: [['ship', 'Ship the winner'], ['ship_and_iterate', 'Ship it, and try for better'], ['another_round', 'Another round'], ['park', 'Park it']],
    rate: [['ship', 'Ship the approved'], ['ship_and_iterate', 'Ship the approved, redo the rest'], ['another_round', 'Redo them all'], ['park', 'Park it']],
    question: [['answer', 'That is my answer'], ['park', 'Park it']] };
  const ACTION_SAID = { ship: 'ship the winner', ship_and_iterate: 'ship, and another round', another_round: 'another round', park: 'parked', answer: 'answered' };
  const SLOT = { needed: 'Needed', placeholder: 'Placeholder', in_review: 'In review', approved: 'Approved', in_game: 'In the game', parked: 'Parked' };
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
    addDecision: async (d) => {
      const n = STATIC.state.decisions.length + 1;
      const rec = { id: 'D-' + String(n).padStart(4, '0'), date: new Date().toISOString().slice(0, 10), title: d.title, his_words: d.his_words, ruling: '', source: { type: 'studio', ref: 'written by hand' }, tags: d.tags || [], status: 'active' };
      STATIC.state.decisions.push(rec); return { decision: rec };
    },
    confirm: async (key, confirmed, note) => {
      for (const p of STATIC.state.playtests) for (const r of p.reports) if (r.key === key) Object.assign(r.triage, { confirmed, confirm_note: note });
    },
    hand: async (id, action, note) => {
      for (const x of ((STATIC.state.overview || {}).hands || [])) if (x.id === id) Object.assign(x, { status: { done: 'done', park: 'parked', reopen: 'open' }[action], his_note: note });
    },
    addNote: async () => { throw new Error('This is a sample page: notes are not kept here'); },
    note: async () => { throw new Error('This is a sample page: notes are not kept here'); },
    src: (url) => STATIC.files[url] || '',
    bytes: async (url) => { if (!STATIC.files[url]) throw new Error('missing'); return b64bytes(STATIC.files[url]); },
  } : {
    state: () => call('GET', '/api/state'),
    pulse: () => call('GET', '/api/pulse'),
    live: () => call('GET', '/api/live'),
    batch: (id) => call('GET', '/api/batch/' + encodeURIComponent(id)),
    saveDraft: (id, v) => call('PUT', '/api/batch/' + encodeURIComponent(id) + '/draft', v),
    submit: (id, v) => call('POST', '/api/batch/' + encodeURIComponent(id) + '/submit', v),
    reopen: (id) => call('POST', '/api/batch/' + encodeURIComponent(id) + '/reopen', {}),
    reset: (id) => call('POST', '/api/batch/' + encodeURIComponent(id) + '/reset', {}),
    ui: (v) => call('POST', '/api/ui', v),
    addDecision: (d) => call('POST', '/api/decisions', d),
    confirm: (key, confirmed, note) => call('PUT', '/api/triage', { key, confirmed, confirm_note: note }),
    hand: (id, action, note) => call('POST', '/api/hand', { id, action, note }),
    addNote: (text, kind, urgent) => call('POST', '/api/note', { text, kind, urgent }),
    note: (id, action, extra) => call('POST', '/api/note/' + encodeURIComponent(id), Object.assign({ action }, extra || {})),
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
  function rateButtons(apply) {
    const btns = [[1, 'Full speed'], [0.5, 'Half'], [0.25, 'Quarter']].map(([r, label]) => {
      const btn = h('button', { class: 'btn small' + (S.opts.rate === r ? ' on' : ''), type: 'button', onclick: () => { S.opts.rate = r; btns.forEach((x) => x.classList.toggle('on', x === btn)); apply(); } }, label); return btn; });
    return btns;
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
      if (!pos) return;
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
      box: new THREE.Box3(new THREE.Vector3(-0.4, 0, -0.2), new THREE.Vector3(0.4, 1.8, 0.2)), fit: { c: new THREE.Vector3(0, 0.9, 0), d: 1 } };
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
      if (o.wire !== undefined && v.model) v.model.traverse((n) => { if (n.material) n.material.wireframe = o.wire; });
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
    box.append(img);
    const t = group.t;
    const pane = { el: box, apply };
    group.panes.push(pane);
    function dims() { return { bw: box.clientWidth, bh: box.clientHeight, iw: img.naturalWidth, ih: img.naturalHeight }; }
    function apply() {
      const d = dims(); if (!d.bw || !d.iw) return;
      const s = Math.min(d.bw / d.iw, d.bh / d.ih) * t.z;
      img.style.transform = 'translate(' + (d.bw / 2 - t.cx * d.iw * s) + 'px,' + (d.bh / 2 - t.cy * d.ih * s) + 'px) scale(' + s + ')';
    }
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
    const pts = new Map(); let pinch = 0;
    box.addEventListener('pointerdown', (e) => { box.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); pinch = 0; });
    box.addEventListener('pointermove', (e) => {
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
    const up = (e) => { pts.delete(e.pointerId); pinch = 0; };
    box.addEventListener('pointerup', up); box.addEventListener('pointercancel', up);
    if (window.ResizeObserver) { const ro = new ResizeObserver(apply); ro.observe(box); pane.destroy = () => ro.disconnect(); }
    return pane;
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
  const seq = { token: 0 };

  // ------------------------------------------------------------------- shell
  function top(r) {
    const st = S.state, mine = st.batches.filter((b) => b.status === 'open' || b.status === 'draft').length;
    const confirmQ = st.playtests.reduce((n, p) => n + p.reports.filter((x) => x.triage.status === 'fixed' && x.triage.confirmed == null).length, 0);
    const noteQ = notesOf().filter((n) => n.waits === 'you').length;
    const tab = (id, label, count, hot) => link(id, { class: (r === id || (id === 'inbox' && (r.startsWith('b.') || r === 'samples')) || (id === 'library' && r.startsWith('s.'))) ? 'on' : '' }, label,
      count ? h('span', { class: 'count' + (hot ? ' hot' : '') }, String(count)) : null);
    return h('header', { class: 'top' },
      h('div', { class: 'brand' }, link('overview', { class: 'name' }, h('b', {}, 'Noc'), 'Studio'),
        st.hub ? h('a', { class: 'proj', href: st.hub, title: 'Your other projects' }, st.project || '', h('span', { 'aria-hidden': 'true' }, ' ▾'))
          : h('small', {}, st.project || '')),
      h('nav', { class: 'nav', 'aria-label': 'Sections' }, tab('overview', 'Overview'), tab('inbox', 'Inbox', mine, true), tab('notes', 'Notes', noteQ, true), tab('library', 'Library'), tab('decisions', 'Decisions', st.decisions.length), tab('build', 'Build'), st.has_playtests === false ? null : tab('playtests', 'Playtests', confirmQ, true)),
      h('span', { class: 'spacer' }),
      syncChip(st.sync),
      st.static ? null : h('button', { class: 'btn small', type: 'button', title: 'Leave a note for the project (N)', onclick: openNotePop }, 'Note'),
      st.hub ? h('a', { class: 'btn small allp', href: st.hub, title: 'Back to the list of your projects' }, 'All projects') : null, scaleControl(), themeControl(),
      st.static ? h('span', { class: 'sample' }, 'Sample data. Candidates are placeholders drawn by script.') : null);
  }
  // a Studio kept in step with another copy (sync.py): quiet while it goes through, plain when it does not
  function syncChip(sy) {
    if (!sy) return null;
    const stale = !sy.ok || Date.now() - new Date(sy.ok) > 10 * 60000;
    const tip = [sy.error || sy.waiting, sy.ok ? 'Last in step with the other copy ' + when(sy.ok) : ''].filter(Boolean).join('. ');
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
      if (!UI.synced) { UI.synced = true; const ui = S.state.ui || {}; if (ui.scale) setScale(ui.scale); if (ui.theme && !SHELL) setTheme(ui.theme); }
      let page;
      if (r.startsWith('b.')) page = await batchPage(r.slice(2));
      else if (r.startsWith('s.')) page = slotPage(r.slice(2));
      else if (r === 'inbox') page = inboxPage();
      else if (r === 'samples') page = samplesPage();
      else if (r === 'library') page = libraryPage();
      else if (r === 'decisions') page = decisionsPage();
      else if (r === 'playtests') page = playtestsPage();
      else if (r === 'notes') page = notesPage();
      else if (r === 'build') page = buildPage();
      else page = overviewPage();
      app.replaceChildren(top(r), page);
      if (!keep) window.scrollTo(0, 0);
      else if (railAt && $('.rail')) $('.rail').scrollTop = railAt;
    } catch (err) {
      app.replaceChildren(S.state ? top(r) : '', h('main', {}, h('div', { class: 'empty' }, String(err.message || err), ' ', link('inbox', {}, 'Back to the inbox'))));
    }
  }

  // ---------------------------------------------------------------- overview
  const MSTONE = { done: 'Done', current: 'In hand', next: 'Next', later: 'Later', parked: 'Parked' };
  const ORDER = ['needed', 'placeholder', 'in_review', 'approved', 'in_game', 'parked'];
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

  function askRow(x) {
    S.notes = S.notes || {};
    const open = x.status === 'open' || x.status === 'later', decide = x.kind === 'decision';
    const note = h('textarea', { class: 'field', rows: 1, placeholder: decide ? 'Your answer, in your words' : 'Anything to add (optional)', 'aria-label': 'Note on ' + x.title,
      value: S.notes[x.id] || '', oninput: (e) => { S.notes[x.id] = e.target.value; } });
    const send = async (action, text) => {
      try { await API.hand(x.id, action, text === undefined ? note.value : text); delete S.notes[x.id]; S.state = await API.state(); toast({ done: decide ? 'Answered' : 'Marked done', park: 'Set aside', reopen: 'Open again' }[action]); render(null, true); }
      catch (e) { toast(e.message); }
    };
    const fact = (label, text) => (text ? h('div', { class: 'fact' }, h('span', {}, label), h('span', { html: inline(text) })) : null);
    const body = h('div', { class: 'askbody' },
      x.detail ? h('p', { html: inline(x.detail) }) : null,
      fact('Blocks', x.gates), fact('If you say nothing', x.default), fact('Takes you', x.time), fact('Waiting since', when(x.created)),
      x.run ? h('div', { class: 'runline' }, h('code', { class: 'i' }, x.run), copyButton(x.run)) : null,
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
          h('b', { class: 'grow' }, s.title || s.prompt || 'A Claude Code session'), s.where ? h('span', { class: 'chip' }, s.where) : null),
        h('div', { class: 'sub' }, sessionLine(s)), sessionBits(s)));
    }
    if (!out.length) return [h('div', { class: 'empty' }, 'Nothing is running. ', hooks ? 'A Claude Code session in the project shows here as soon as it starts.'
      : 'Sessions will show here on their own once live reporting is on: say to Claude Code, “turn on the Studio\'s live reporting”.')];
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
    const st = S.state, ov = st.overview || {}, now = ov.now || {}, game = ov.game || {}, hands = ov.hands || [];
    const board = ov.board || { pct: 0, share: {}, counts: {}, milestones: ov.milestones || [], days: [], pace: {}, events: [], lanes: [] };
    const ms = board.milestones || [], cur = ms.find((m) => m.status === 'current');
    const mine = st.batches.filter((b) => b.status === 'open' || b.status === 'draft');
    const sent = st.batches.filter((b) => b.status === 'submitted');
    const confirms = st.playtests.reduce((n, p) => n + p.reports.filter((x) => x.triage.status === 'fixed' && x.triage.confirmed == null).length, 0);
    const openHands = hands.filter((x) => x.status === 'open').sort((a, b) => (b.urgent ? 1 : 0) - (a.urgent ? 1 : 0));
    const laterHands = hands.filter((x) => x.status === 'later'), oldHands = hands.filter((x) => x.status === 'done' || x.status === 'parked');
    const myNotes = notesOf().filter((n) => n.waits === 'you');
    const owed = mine.length + (confirms ? 1 : 0) + openHands.length + myNotes.length;
    const col = h('div', { class: 'hudmain' });

    // a project that has not been planned yet says so, and says how
    const todo = (ov.setup || []).filter((x) => !x.optional), left = todo.filter((x) => !x.done);
    if (left.length) col.append(fold('setup', true, 'setup',
      [h('span', { class: 'grow' }, 'Getting organised'), h('span', { class: 'chip accent' }, (todo.length - left.length) + ' of ' + todo.length)],
      h('ul', { class: 'ticks' }, (ov.setup || []).map((x) => h('li', { class: x.done ? 'done' : '' }, h('span', { class: 'tick' }, x.done ? '✓' : ''), x.title, x.optional && !x.done ? h('span', { class: 'muted' }, ' (if it has any)') : null))),
      h('div', { class: 'say' }, h('span', {}, 'In the project, say to Claude Code:'), h('code', {}, PLAN_SAY), copyButton(PLAN_SAY)),
      h('p', { class: 'muted' }, 'It reads what the project already has, asks you what only you can answer, and fills in the rest.')));

    // how far along, in one number
    const done = board.milestones_done || 0;
    col.append(h('section', { class: 'gauge' },
      h('div', { class: 'gaugetop' },
        h('div', { class: 'big num' }, pctText(board.pct || 0)),
        h('div', { class: 'grow' }, h('h1', { class: (now.headline || '').length > 110 ? 'long' : '' }, now.headline || st.project || 'Overview'), now.goal ? h('p', { class: 'muted', html: inline(now.goal) }) : null)),
      h('div', { class: 'bar-status tall', role: 'img', 'aria-label': BAR.map((k) => STEP[k] + ' ' + Math.round((board.share || {})[k] || 0) + '%').join(', ') },
        BAR.filter((k) => (board.share || {})[k]).map((k) => h('i', { class: 'sp-' + k, style: 'width:' + board.share[k] + '%', title: STEP[k] + ': ' + ((board.counts || {})[k] || 0) }))),
      h('div', { class: 'legend' }, BAR.concat(['planned']).map((k) => h('span', {}, h('span', { class: 'dot sp-' + k }), STEP[k] + ' ', h('b', {}, String((board.counts || {})[k] || 0)))),
        h('span', { class: 'muted' }, board.steps ? board.steps + ' steps in all' : 'No steps yet')),
      ms.length ? h('div', { class: 'track', role: 'img', 'aria-label': ms.map((m) => m.id + ' ' + MSTONE[m.status]).join(', ') },
        ms.map((m) => h('div', { class: 'seg ' + m.status, title: m.name + ': ' + MSTONE[m.status] + (m.steps ? ', ' + pctText(m.pct) : '') }, h('b', {}, m.id), h('span', {}, m.name)))) : null,
      ms.length ? h('p', { class: 'muted' }, done + ' of ' + ms.length + ' milestones complete') : null));

    // the few facts worth a glance
    const tile = (label, value, sub, href) => h(href ? 'a' : 'div', { class: 'stat', href: href || null }, h('span', { class: 'label' }, label), h('span', { class: 'value' }, value), sub ? h('span', { class: 'sub' }, sub) : null);
    const pace = board.pace || {};
    const tiles = [
      cur ? tile('In hand', cur.id + ' · ' + cur.name, [cur.unplanned ? 'no steps yet' : pctText(cur.pct), cur.eta ? 'ETA ' + cur.eta : ''].filter(Boolean).join(' · ')) : null,
      pace.finish ? tile('Done at this pace', dayName(pace.finish), '+' + pace.per_day + ' points a day over ' + pace.over_days + (pace.over_days === 1 ? ' day' : ' days'))
        : (board.days || []).length > 1 ? tile('Done at this pace', 'No telling', 'nothing moved in the last ' + (pace.over_days || 7) + ' days') : null,
      now.finish ? tile('Claude\'s estimate', now.finish, 'for the whole project') : null,
      (now.counters || []).map((c) => tile(c.name, c.have + ' / ' + c.of)),
      now.build || game.version ? tile('Build', now.build || game.version, game.since_now ? game.since_now + (game.since_now === 1 ? ' commit' : ' commits') + ' since it was written up' : (now.gate || ''), '#build') : null];
    if (tiles.flat().filter(Boolean).length) col.append(h('div', { class: 'tiles' }, tiles));

    // running now: redrawn by itself every few seconds
    const running = h('div', { class: 'runbody' }, runningBody(ov.live || {}, ov.hooks));
    col.append(h('section', {}, h('div', { class: 'sec-head' }, h('h2', {}, 'Running now'), h('p', {}, ov.hooks ? 'Live from the project\'s sessions.' : '')), running));
    if (!STATIC && API.live) {
      const timer = setInterval(async () => { try { const live = await API.live(); (S.state.overview || {}).live = live; running.replaceChildren(...runningBody(live, ov.hooks)); } catch (e) { /* next beat */ } }, 3000);
      S.cleanup.push(() => clearInterval(timer));
    }

    // day by day
    const days = board.days || [];
    if (days.length > 1) col.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Day by day'), h('p', {}, 'The line is how far along; bars are steps landed; a red mark is a setback.')), dayChart(days)));

    // the road, and the steps of each stretch
    if (ms.length) col.append(h('section', {},
      h('div', { class: 'sec-head' }, h('h2', {}, 'Milestones')),
      h('div', { class: 'rows' }, ms.map((m) => fold('ms:' + m.id, false, 'ms ' + m.status,
        [h('span', { class: 'mid' }, m.id), h('span', { class: 'grow' }, h('span', { class: 'title' }, m.name), m.note ? h('span', { class: 'sub' }, ' · ' + m.note) : null),
          m.eta && m.status !== 'done' ? h('span', { class: 'chip' }, 'ETA ' + m.eta) : null,
          h('span', { class: 'mbar' }, h('span', { class: 'bar-status' }, h('i', { class: 'sp-done', style: 'width:' + m.pct + '%' })), h('span', { class: 'num' }, m.unplanned ? '–' : pctText(m.pct))),
          h('span', { class: 'status' }, h('span', { class: 'dot ms-' + m.status }), MSTONE[m.status] || m.status)],
        h('div', { class: 'msbody' }, m.goal ? h('p', { html: inline(m.goal) }) : null,
          m.question ? h('p', { class: 'muted' }, 'Your verdict answers: ', h('i', {}, m.question)) : null,
          (m.steps || []).length ? h('ul', { class: 'steps' }, m.steps.map((s) => h('li', { class: 'st ' + s.status }, h('span', { class: 'dot sp-' + s.status }), h('span', { class: 'grow' }, s.name, s.note ? h('span', { class: 'muted' }, ' · ' + s.note) : null),
            h('span', { class: 'sub' }, STEP[s.status] + (s.date ? ' · ' + dayName(s.date) : '')))))
            : (m.status === 'done' ? null : h('p', { class: 'muted' }, 'No steps yet, so its progress cannot be counted.'))))))));

    // the log
    const log = board.events || [];
    if (log.length) {
      const row = (e) => h('div', { class: 'row ev ' + e.kind }, h('span', { class: 'chip ' + ({ setback: 'bad', merge: 'ok', publish: 'ok', done: 'keep' }[e.kind] || '') }, EVENT[e.kind] || e.kind),
        h('div', { class: 'grow' }, h('span', { html: inline(e.text) }), e.milestone ? h('span', { class: 'muted' }, ' · ' + e.milestone) : null), h('span', { class: 'sub' }, when(e.ts)));
      col.append(h('section', {}, h('div', { class: 'sec-head' }, h('h2', {}, 'Log'), h('p', {}, 'Newest first.')),
        h('div', { class: 'rows' }, log.slice(0, 10).map(row)),
        log.length > 10 ? fold('log', false, 'brief', 'Earlier (' + (log.length - 10) + ')', h('div', { class: 'rows', style: 'margin-top:8px' }, log.slice(10).map(row))) : null));
    }

    if (!ms.length && !hands.length && !st.batches.length && !left.length) col.append(h('div', { class: 'empty' }, 'Nothing here yet.'));

    // the rail: everything that waits on the user, and what comes next
    const asks = h('div', { class: 'asks' });
    for (const b of mine) asks.append(link('b.' + b.id, { class: 'need go' },
      h('span', { class: 'chip accent' }, b.status === 'draft' ? 'Started' : (b.mode === 'question' ? 'Answer' : 'Judge ' + b.count)), h('span', { class: 'grow' }, b.title), h('span', { class: 'chip' }, KIND[b.kind] || b.kind)));
    if (confirms) asks.append(link('playtests', { class: 'need go' }, h('span', { class: 'chip accent' }, 'Confirm'), h('span', { class: 'grow' }, confirms === 1 ? 'One fix to confirm in the build' : confirms + ' fixes to confirm in the build')));
    for (const n of myNotes) asks.append(link('notes', { class: 'need go' },
      h('span', { class: 'chip accent' }, n.status === 'confirm' ? 'Confirm' : 'Reply'), h('span', { class: 'grow', html: inline(clip(n.status === 'confirm' ? n.reading || n.text : n.text, 110)) }), h('span', { class: 'chip' }, 'Note')));
    for (const x of openHands) asks.append(askRow(x));
    const setAll = (open) => { asks.querySelectorAll('details').forEach((d) => { d.open = open; OPEN.set(d.dataset.fold, open); }); };
    const next = (now.next || []).map(split);
    const rail = h('aside', { class: 'rail', 'aria-label': 'Needs you' },
      h('div', { class: 'railhead' }, h('h2', {}, 'Needs you'), owed ? h('span', { class: 'count hot' }, String(owed)) : null, h('span', { class: 'grow' }),
        openHands.length > 1 ? [h('button', { class: 'btn small', type: 'button', onclick: () => setAll(true) }, 'Open all'), h('button', { class: 'btn small', type: 'button', onclick: () => setAll(false) }, 'Close all')] : null),
      owed ? asks : h('div', { class: 'empty' }, 'Nothing waits on you.'),
      sent.length ? h('div', { class: 'say' }, h('span', {}, sent.length + (sent.length === 1 ? ' verdict waits' : ' verdicts wait') + ' on Claude. Say to Claude Code:'), h('code', {}, SAY), copyButton(SAY)) : null,
      laterHands.length ? fold('later', false, 'brief', 'Yours later, nothing waits on these yet (' + laterHands.length + ')', h('div', { class: 'asks' }, laterHands.map(askRow))) : null,
      oldHands.length ? fold('answered', false, 'brief', 'Answered (' + oldHands.length + ')', h('div', { class: 'asks' }, oldHands.map(askRow))) : null,
      next.length ? [h('h2', { class: 'railsub' }, 'Next up'), h('ul', { class: 'nextup' }, next.map(([text, eta]) => h('li', {}, h('span', { html: inline(text) }), eta ? h('span', { class: 'sub' }, eta) : null)))] : null);
    return h('main', { class: 'hud' }, col, rail);
  }

  // ------------------------------------------------------------ the build in hand
  function buildPage() {
    const st = S.state, ov = st.overview || {}, now = ov.now || {}, game = ov.game || {}, main = h('main', {});
    const list = (title, items, cls) => ((items || []).length ? h('div', { class: 'ovcol' }, h('h3', {}, title), h('ul', { class: cls || 'look' }, items.map((x) => h('li', { html: inline(split(x)[0]) })))) : null);
    const commits = game.commits || [];
    main.append(h('section', {},
      h('h1', {}, now.build ? 'Build ' + now.build : 'The build in hand'),
      h('div', { class: 'meta', style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
        now.gate ? h('span', { class: 'chip ok' }, 'Gate ' + now.gate) : null,
        game.branch ? h('span', { class: 'chip' }, game.branch + ' @ ' + game.head) : null,
        now.spec ? h('span', { class: 'chip' }, now.spec) : null,
        now.updated ? h('span', { class: 'sub muted' }, 'written ' + when(now.updated)) : null,
        game.since_now ? h('span', { class: 'chip redo', title: 'The project repo has moved since this was written' }, game.since_now + ' commit' + (game.since_now === 1 ? '' : 's') + ' since') : null)));
    if (!(now.built || []).length && !(now.start || []).length && !commits.length) main.append(h('div', { class: 'empty' }, 'No build has been written up yet.'));
    main.append(h('section', {}, h('div', { class: 'ovgrid' }, list('In the build', now.built), list('Next', now.next)),
      (now.start || []).length ? h('div', { class: 'ovcol' }, h('h3', {}, 'Start it'), now.start.map((line) => h('div', { class: 'runline' }, h('code', { class: 'i' }, line), copyButton(line)))) : null,
      (now.known || []).length ? fold('known', false, 'brief', 'Known and left as it is (' + now.known.length + ')', h('ul', { class: 'plain' }, now.known.map((x) => h('li', { html: inline(x) })))) : null,
      commits.length ? fold('commits', false, 'brief', 'Latest work in the project repo',
        h('div', { class: 'rows', style: 'margin-top:8px' }, commits.map((c) => h('div', { class: 'row' }, h('span', { class: 'mono muted' }, c.sha), h('div', { class: 'grow' }, c.subject), h('span', { class: 'sub' }, when(c.date)))))) : null));

    // what the project still lacks
    const slots = st.slots || [];
    if (slots.length) {
      const groups = {}; slots.forEach((s) => { const g = groups[s.group || 'Other'] = groups[s.group || 'Other'] || { n: 0 }; g.n++; g[s.status] = (g[s.status] || 0) + 1; });
      const lack = (g) => (g.needed || 0) + (g.placeholder || 0);
      const names = Object.keys(groups).sort((a, b) => lack(groups[b]) - lack(groups[a]) || a.localeCompare(b));
      const missing = slots.filter((s) => s.status === 'needed' || s.status === 'placeholder').length;
      main.append(h('section', {},
        h('div', { class: 'sec-head' }, h('h2', {}, 'What the project still lacks'), h('p', {}, missing + ' missing or stand-ins · ' + slots.filter((x) => x.status === 'in_review').length + ' waiting on your verdict · ' + slots.length + ' in all'), link('library', {}, 'Open the Library')),
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
      cur ? h('div', { class: 'closed' }, h('h3', {}, 'Approved: v' + cur.version + (cur.title ? ' · ' + cur.title : '') + (cur.score ? ' · ' + cur.score + '/10' : '')),
        cur.note ? h('blockquote', {}, cur.note) : null,
        h('p', { class: 'sub muted' }, [cur.date ? String(cur.date).slice(0, 10) : '', cur.source || ''].filter(Boolean).join(' · '))) : null,
      s.game_path ? h('p', { class: 'mono muted' }, 'In the game at ' + s.game_path) : null));

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
          tog('Turntable', 'rotate'), f.clip ? null : tog('Wireframe', 'wire'), tog('1.8 m figure', 'ref')), stage);
      }
      if (f.kind === 'audio') {
        const p = audioPlayer(f.url, f.label); S.cleanup.push(() => p.destroy());
        stage.append(p.el);
        return h('article', { class: 'tile' }, h('div', { class: 'thead' }, h('span', { class: 'mono muted', style: 'overflow-wrap:anywhere' }, f.label)), stage);
      }
      if (f.kind === 'video') stage.append(h('video', { src: f.url, controls: true, loop: true, muted: true, playsinline: true, preload: 'auto', style: 'width:100%;display:block' }));
      else if (f.kind === 'text') { const holder = h('div', { class: 'option' }, 'Loading'); API.bytes(f.url).then((buf) => holder.replaceChildren(md(new TextDecoder().decode(buf)))).catch(() => holder.replaceChildren('Could not read the file.')); stage.className = ''; stage.append(holder); }
      else stage.append(h('img', { class: 'fit', src: f.url, alt: f.label, loading: 'lazy', onclick: (e) => shot(e.target.src) }));
      return h('article', { class: 'tile' }, stage, h('div', { class: 'thead' }, h('span', { class: 'mono muted', style: 'overflow-wrap:anywhere' }, f.label)));
    };
    const mo = motionOf(s.motion);
    if (mo) main.append(h('section', {}, h('h2', {}, 'The motion, looping in place'),
      h('p', { class: 'muted', style: 'max-width:80ch' }, 'Baked from the game\'s own drawing of it' + (mo.seconds ? ', ' + mo.seconds.toFixed(2) + ' s a loop' : '') + '. The light here is the page\'s, not the hall\'s.'),
      h('div', { class: 'grid', style: '--tile:760px' }, show({ kind: 'model', url: mo.url, label: mo.clip.replace(/_/g, ' '), clip: mo.clip }))));
    for (const [from, title] of [['game', 'In the project today'], ['library', 'The approved master']]) {
      const rows = files.filter((f) => f.from === from).sort((a, b) => (b.kind === s.kind) - (a.kind === s.kind));
      if (!rows.length) continue;
      const wide = rows.some((f) => f.kind === 'model') || rows.length === 1;
      main.append(h('section', {}, h('h2', {}, title + (rows.length > 1 ? ' · ' + rows.length + ' files' : '')),
        h('div', { class: 'grid', style: '--tile:' + (wide ? 760 : rows[0].kind === 'audio' ? 380 : 420) + 'px' }, rows.map(show))));
    }
    if (!files.length && !mo) main.append(h('div', { class: 'empty' }, s.status === 'needed' ? 'Nothing exists for this yet.' : 'This has no file you can open here: it lives in the game as numbers or motion data' + (s.kind === 'ingame' ? ', and is judged in the game.' : '.')));
    const past = (s.history || []).slice(0, -1).reverse();
    if (past.length) main.append(h('section', {}, h('h2', {}, 'Earlier versions'), h('div', { class: 'rows' }, past.map((v) => h('div', { class: 'row' },
      h('span', { class: 'mono muted' }, 'v' + v.version), h('div', { class: 'grow' }, v.title || v.candidate || ''), h('span', { class: 'sub' }, v.date ? String(v.date).slice(0, 10) : ''))))));
    return main;
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
    if ((v.action === 'another_round' || v.action === 'ship_and_iterate') && !v.note && !calls.some((c) => c.note || c.call === 'keep' || c.call === 'redo'))
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
    return parts.join(' · ');
  }
  const primary = (cand) => (cand.files || []).find((f) => f.role === 'primary') || (cand.files || [])[0] || null;

  // what a candidate looks like, small (in the grid) or large (in the overlay)
  function media(cand, big, group) {
    const b = S.batch, file = primary(cand), views = [];
    const stage = h('div', { class: 'stage' + (S.opts.stage === 'checker' ? ' checker' : '') });
    const paint = () => { stage.classList.toggle('checker', S.opts.stage === 'checker'); stage.style.background = { dark: '', grey: '#777', white: '#f4f4f4', checker: '' }[S.opts.stage]; };
    paint();
    const api = { el: stage, set() { paint(); views.forEach((v) => v.set && v.set(S.opts)); }, destroy() { views.forEach((v) => v.destroy && v.destroy()); }, play: null, view: null };
    const mo = b.kind === 'ingame' ? motionOf(cand.motion) : null;
    if (mo) {
      const v = modelView(mo.url, { zoom: big, group: group && group.cam, clip: mo.clip });
      if (group && group.cam && v.copyCam) group.cam.views.push(v);
      views.push(v); api.view = v; stage.append(v.el);
      if (!big) stage.append(h('div', { class: 'word under' }, h('b', {}, cand.label || cand.title), h('span', {}, b.sample ? 'Made-up motion, to show the viewer' : 'Baked from the game. Confirm it in the game, under these words')));
    } else if (b.kind === 'ingame') {
      stage.append(h('div', { class: 'word' }, h('b', {}, cand.label || cand.title), h('span', {}, 'Look for these words over it in the game')));
    } else if (b.kind === 'question' || (!file && cand.body)) {
      stage.classList.remove('stage'); stage.className = 'option'; stage.append(md(cand.body || cand.summary || ''));
    } else if (!file) {
      stage.append(h('div', { class: 'fallback' }, 'No file.'));
    } else if (file.kind === 'model') {
      const v = modelView(fileUrl(b.id, file.path), { zoom: big, group: group && group.cam, ready: group && group.ready });
      if (group && group.cam && v.copyCam) group.cam.views.push(v);
      views.push(v); api.view = v; stage.append(v.el);
    } else if (file.kind === 'audio') {
      for (const f of cand.files.filter((x) => x.kind === 'audio')) {
        const p = audioPlayer(fileUrl(b.id, f.path), f.label);
        if (!api.play) api.play = p;
        views.push(p); stage.append(p.el);
      }
    } else if (file.kind === 'video') {
      stage.append(h('video', { src: API.src(fileUrl(b.id, file.path)), controls: true, loop: true, muted: true, playsinline: true, preload: 'auto', style: 'width:100%;display:block' }));
    } else if (file.kind === 'text') {
      const holder = h('div', { class: 'option' }, 'Loading');
      API.bytes(fileUrl(b.id, file.path)).then((buf) => holder.replaceChildren(md(new TextDecoder().decode(buf)))).catch(() => holder.replaceChildren('Could not read the file.'));
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
        } else if (big) { stage.style.flex = '1'; stage.style.minHeight = '0'; stage.append(zoomPane(src, group.zoom).el); }
        else stage.append(h('img', { class: 'fit', src, alt: cand.title, loading: 'lazy' }));
      };
      build(); api.set = () => { paint(); build(); };
      if (big) { stage.style.flex = '1'; stage.style.minHeight = '0'; }
    }
    return api;
  }

  // -------------------------------------------------------------- batch page
  async function batchPage(id) {
    const b = S.batch = await API.batch(id);
    S.ui = {}; S.cmp = new Set(); S.current = b.candidates.length ? b.candidates[0].id : null; S.touched = false;
    const from = b.verdict || b.draft || {};
    S.verdict = { action: from.action || null, note: from.note || '', answer: from.answer || '', candidates: JSON.parse(JSON.stringify(from.candidates || {})) };
    if (from.action) S.touched = true;
    Object.assign(S.opts, { clip: (b.candidates.map((c) => (c.facts || {}).clips).find((c) => c && c.length) || [{ name: '' }])[0].name, tile: false, rotate: false, wire: false, playing: true, rate: 1 });
    const moving = b.kind === 'ingame' && b.candidates.some((c) => motionOf(c.motion));
    const visual = S.visual = ['image', 'texture', 'model'].includes(b.kind) || moving;
    const main = h('main', {});
    const medias = {};
    S.cleanup.push(() => { Object.values(medias).forEach((m) => m.destroy()); seq.token++; clearTimeout(saveTimer); document.removeEventListener('keydown', onKey); });

    // head
    const parent = b.parent ? S.state.batches.find((x) => x.id === b.parent) : null;
    main.append(h('section', { class: 'bhead' },
      h('div', { class: 'crumb' }, link('inbox', {}, 'Inbox'), h('span', {}, '/'), b.sample ? [link('samples', {}, 'Samples'), h('span', {}, '/')] : null, h('span', { class: 'chip' }, KIND[b.kind] || b.kind),
        b.round > 1 ? h('span', { class: 'chip' }, 'Round ' + b.round) : null,
        parent ? link('b.' + parent.id, {}, 'See round ' + parent.round) : null,
        b.slot ? h('span', { class: 'mono muted' }, b.slot) : null),
      h('h1', {}, b.title), b.ask ? h('p', { class: 'ask' }, b.ask) : null,
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
        (res.imported || []).some((r) => (r.dest || []).length) ? h('p', { class: 'muted mono' }, 'game: ' + res.imported.flatMap((r) => r.dest || []).join(', ')) : null,
        h('div', { class: 'line', style: 'display:flex;gap:10px;flex-wrap:wrap' },
          res.decision ? link('decisions', { class: 'btn small' }, 'Decision ' + res.decision) : null,
          res.next_batch ? link('b.' + res.next_batch, { class: 'btn small' }, 'Go to the next round') : null))));
    }

    // tools
    const tools = h('div', { class: 'tools' });
    const apply = () => Object.values(medias).forEach((m) => m.set()), overApply = () => { if (S.over && S.over.apply) S.over.apply(); };
    const toggle = (label, key) => { const btn = h('button', { class: 'btn small' + (S.opts[key] ? ' on' : ''), type: 'button', 'aria-pressed': String(!!S.opts[key]), onclick: () => { S.opts[key] = !S.opts[key]; btn.classList.toggle('on', S.opts[key]); btn.setAttribute('aria-pressed', S.opts[key]); apply(); overApply(); } }, label); return btn; };
    const hasMedia = ['image', 'texture', 'model', 'video', 'mixed'].includes(b.kind) || moving;
    if (hasMedia) {
      const sw = [['dark', '#0b0b0c'], ['grey', '#777'], ['white', '#f4f4f4'], ['checker', 'conic-gradient(#555 25%, #222 0 50%, #555 0 75%, #222 0)']].map(([name, css]) => {
        const btn = h('button', { class: 'swatch' + (S.opts.stage === name ? ' on' : ''), type: 'button', title: 'Background: ' + name, 'aria-label': 'Background ' + name, style: 'background:' + css,
          onclick: () => { S.opts.stage = name; sw.forEach((x) => x.classList.toggle('on', x === btn)); apply(); overApply(); } });
        return btn;
      });
      tools.append(h('div', { class: 'grp' }, h('label', {}, 'Behind it'), sw));
    }
    if (b.kind === 'texture') {
      const size = h('input', { type: 'range', min: 48, max: 320, step: 8, value: S.opts.texScale, id: 'tex-scale', 'aria-label': 'Tile size', oninput: () => { S.opts.texScale = +size.value; if (S.opts.tile) { apply(); overApply(); } } });
      tools.append(h('div', { class: 'grp' }, toggle('Tile', 'tile'), h('label', { for: 'tex-scale' }, 'Tile size'), size));
    }
    if (b.kind === 'model') {
      const names = [...new Set(b.candidates.flatMap((c) => ((c.facts || {}).clips || []).map((x) => x.name)))];
      const sel = h('select', { id: 'clip', 'aria-label': 'Motion', onchange: () => { S.opts.clip = sel.value; apply(); overApply(); } },
        h('option', { value: '' }, 'Still'), names.map((n) => h('option', { value: n, selected: n === S.opts.clip }, n)));
      tools.append(h('div', { class: 'grp' }, h('label', { for: 'clip' }, 'Motion'), sel, toggle('Play', 'playing')),
        h('div', { class: 'grp' }, toggle('Turntable', 'rotate'), toggle('Wireframe', 'wire'), toggle('1.8 m figure', 'ref')));
    }
    if (moving) tools.append(h('div', { class: 'grp' }, toggle('Play', 'playing'), rateButtons(() => { apply(); overApply(); })),
      h('div', { class: 'grp' }, toggle('Turntable', 'rotate'), toggle('1.8 m figure', 'ref')));
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
    if (b.kind === 'ingame' && b.launch) tools.append(h('div', { class: 'grp' }, h('label', {}, 'Start the game with'), h('code', { class: 'i' }, b.launch), copyButton(b.launch)));
    const cmpBtn = h('button', { class: 'btn small', type: 'button', hidden: true, onclick: () => openOver([...S.cmp]) }, 'Compare');
    const canCompare = visual && b.candidates.length > 1;
    if (canCompare) tools.append(h('span', { style: 'flex:1' }), h('div', { class: 'grp' }, cmpBtn,
      h('button', { class: 'btn small', type: 'button', onclick: () => openOver(b.candidates.slice(0, 4).map((c) => c.id)) }, b.candidates.length > 4 ? 'Compare the first four' : 'Compare all')));
    const refreshCmp = () => { cmpBtn.hidden = S.cmp.size < 2; cmpBtn.textContent = 'Compare the ' + S.cmp.size + ' ticked'; };

    // grid
    const tileW = moving ? 340 : ({ image: 440, texture: 300, model: 340, audio: 380, ingame: 300, question: 380 }[b.kind] || 380);
    const grid = h('div', { class: 'grid', style: '--tile:' + tileW + 'px' });
    const tiles = {};
    for (const cand of b.candidates) {
      const m = medias[cand.id] = media(cand, false, null);
      const checks = (cand.checks || []).filter((c) => c.level !== 'ok');
      const box = canCompare ? h('input', { type: 'checkbox', 'aria-label': 'Tick to compare ' + cand.title, onchange: () => { if (box.checked) { if (S.cmp.size >= 4) { box.checked = false; toast('Compare takes four at most'); return; } S.cmp.add(cand.id); } else S.cmp.delete(cand.id); refreshCmp(); } }) : null;
      const ctl = controls(cand, false);
      const tile = tiles[cand.id] = h('article', { class: 'tile', 'data-cid': cand.id, 'aria-label': 'Candidate ' + cand.id.toUpperCase() + ': ' + cand.title },
        h('div', { class: 'thead' }, h('span', { class: 'letter' }, cand.id.length <= 2 ? cand.id : cand.id[0]), h('h3', {}, cand.title),
          cand.recommended ? h('span', { class: 'chip accent' }, 'Suggested') : null,
          cand.carried_from ? h('span', { class: 'chip keep', title: 'You kept this in an earlier round' }, 'From last round') : null,
          box ? h('label', { class: 'cmp' }, box, 'Compare') : null),
        m.el,
        h('div', { class: 'tinfo' }, cand.summary && b.kind !== 'question' ? h('p', { class: 'sum' }, cand.summary) : null,
          factsLine(cand) ? h('div', { class: 'facts' }, factsLine(cand)) : null,
          checks.length ? h('div', { class: 'checks' }, checks.map((c) => h('span', { class: c.level }, (c.level === 'error' ? 'Broken rule: ' : 'Note: ') + c.msg))) : null),
        ctl);
      tile.noteField = ctl.noteField; tile.box = box;
      tile.addEventListener('pointerenter', () => setCurrent(cand.id, false));
      tile.addEventListener('focusin', () => setCurrent(cand.id, false));
      if (visual) {
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
        try { clearTimeout(saveTimer); await API.submit(b.id, S.verdict); S.state = await API.state(); toast('Verdict sent'); render(); }
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
    const bar = h('div', { class: 'bar' },
      h('h3', {}, one ? cands[0].title : 'Comparing ' + cands.map((c) => c.id.toUpperCase()).join(', ')),
      h('span', { class: 'hint' }, one ? [h('kbd', {}, '←'), ' ', h('kbd', {}, '→'), ' next · scroll or pinch to zoom · double-click for full size']
        : ['Zoom and turn one, the others follow · point at one, then score or mark it with the keys']),
      h('button', { class: 'btn small', type: 'button', onclick: closeOver }, 'Close (Esc)'));
    const el = h('div', { class: 'over', role: 'dialog', 'aria-modal': 'true', 'aria-label': one ? cands[0].title : 'Compare' }, bar, panes);
    let noteField = null;
    if (one) {
      const ctl = controls(cands[0], true);
      S.ui[cands[0].id][S.ui[cands[0].id].length - 1].over = true;
      noteField = ctl.noteField;
      const info = h('div', {}, cands[0].summary ? h('p', { class: 'muted' }, cands[0].summary) : null, h('div', { class: 'facts' }, factsLine(cands[0])));
      const kids = [...ctl.children];
      el.append(h('div', { class: 'side' }, h('div', {}, kids[0], kids.length > 2 ? kids[1] : null), info, kids[kids.length - 1]));
    }
    S.current = cands.some((c) => c.id === S.current) ? S.current : cands[0].id;
    S.over = { el, ids: cands.map((c) => c.id), note: noteField, mark, apply: () => medias.forEach((m) => m.set()), destroy: () => medias.forEach((m) => m.destroy()) };
    document.body.append(el); document.body.style.overflow = 'hidden';
    mark();
  }

  // ----------------------------------------------------------------- library
  function libraryPage() {
    const slots = S.state.slots, order = ['needed', 'placeholder', 'in_review', 'approved', 'in_game', 'parked'];
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
      const art = (g) => g.startsWith('Concept art');  // what the game runs on first, the reference art after
      list.replaceChildren(...Object.keys(groups).sort((a, b) => art(a) - art(b) || a.localeCompare(b)).map((g) => h('section', {}, h('h2', {}, g), h('div', { class: 'rows' }, groups[g].map((s) => {
        const cur = s.current, target = 's.' + s.id;
        const kids = [
          cur && cur.thumb && !S.state.static ? h('img', { class: 'thumb', src: '/' + cur.thumb, alt: '', loading: 'lazy' }) : h('span', { class: 'thumb' }, { model: '3D', audio: 'SFX', texture: 'TEX', image: 'IMG', ingame: 'GAME', video: 'CLIP', text: 'TXT' }[s.kind] || ''),
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
  const NOTE_PICK = [['', 'Claude sorts it'], ['directive', 'Change this'], ['discussion', 'Discuss'], ['bug', 'Bug'], ['options', 'Show me options'], ['rule', 'Standing rule'], ['later', 'For later']];
  const notesOf = () => (S.state || {}).notes || [];
  const clip = (text, n) => { const t = String(text || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1).trimEnd() + '…' : t; };
  const afterNote = async (said) => { S.state = await API.state(); if (said) toast(said); const r = route(); if (r === 'notes' || r === 'overview') render(r, true); else { const bar = $('.top'); if (bar) bar.replaceWith(top(r)); } };

  // where the user types: one box, the same on the Notes page and behind the Note button on every page
  function noteBox(done) {
    const D = S.jot || (S.jot = { text: '', kind: '', urgent: false });
    const text = h('textarea', { class: 'field', rows: 2, placeholder: 'An order, a bug, a question, a half-formed idea. Enter sends it; Shift+Enter starts a new line.', 'aria-label': 'A note for the project',
      value: D.text, oninput: (e) => { D.text = e.target.value; } });
    const picks = NOTE_PICK.map(([k, label]) => { const b = h('button', { class: 'btn small' + (D.kind === k ? ' on' : ''), type: 'button', 'aria-pressed': String(D.kind === k),
      onclick: () => { D.kind = k; picks.forEach((x) => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); }); text.focus(); } }, label); return b; });
    const urgent = h('button', { class: 'btn small' + (D.urgent ? ' on' : ''), type: 'button', 'aria-pressed': String(D.urgent), title: 'Handed to a session at its next step, not its next break',
      onclick: () => { D.urgent = !D.urgent; urgent.classList.toggle('on', D.urgent); urgent.setAttribute('aria-pressed', String(D.urgent)); } }, 'Urgent');
    const send = async () => {
      if (!text.value.trim()) { toast('Write the note first'); return; }
      try { await API.addNote(text.value, D.kind, D.urgent); S.jot = null; text.value = ''; await afterNote(D.kind === 'later' ? 'Kept for later' : 'Noted'); if (done) done(); }
      catch (e) { toast(e.message); }
    };
    text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });
    return { el: h('div', { class: 'notebox' }, text, h('div', { class: 'picks' }, picks, h('span', { class: 'grow' }), urgent, h('button', { class: 'btn small primary', type: 'button', onclick: send }, 'Send'))), text };
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
    if (n.status === 'confirm') return 'Confirm what Claude took it to mean';
    if (n.status === 'go') {
      if (n.handed) return 'Handed to ' + who(n.handed.name) + ' ' + when(n.handed.at);
      if (n.to === '') return 'No session is on this part of the project';
      return 'Waiting for ' + (n.to === '*' ? 'the first session to reach a break' : who(n.to_name)) + ' to reach a break';
    }
    if (n.status === 'talk') return n.waits === 'you' ? 'Claude answered' : (n.handed ? 'Handed to ' + who(n.handed.name) + ' ' + when(n.handed.at) : 'Waiting for a session to answer');
    if (n.status === 'later') return 'Kept for later';
    return n.status === 'done' ? (n.closed_by === 'you' ? 'Closed by you' : 'Done') : (n.closed_by === 'you' ? 'Set aside by you' : 'Left with you');
  }
  function noteCard(n) {
    S.notes = S.notes || {};
    const key = 'n:' + n.id, open = ['new', 'confirm', 'go', 'talk'].includes(n.status);
    const act = async (action, extra, said) => { try { await API.note(n.id, action, extra); delete S.notes[key]; await afterNote(said); } catch (e) { toast(e.message); } };
    const words = (hint) => h('textarea', { class: 'field', rows: 1, placeholder: hint, 'aria-label': hint + ' (' + n.id + ')', value: S.notes[key] || '', oninput: (e) => { S.notes[key] = e.target.value; } });
    const btn = (label, fn, cls) => h('button', { class: 'btn small' + (cls ? ' ' + cls : ''), type: 'button', onclick: fn }, label);
    const kind = open || n.status === 'later' ? h('select', { 'aria-label': 'What kind of note ' + n.id + ' is', title: 'Say what kind of note this is yourself',
      onchange: (e) => { if (e.target.value) act('kind', { kind: e.target.value }, 'Sorted as ' + NOTE[e.target.value].toLowerCase()); } },
      h('option', { value: '' }, n.kind ? 'Change the kind' : 'Sort it yourself'), Object.keys(NOTE).filter((k) => k !== n.kind).map((k) => h('option', { value: k }, NOTE[k]))) : null;
    const urgent = open ? btn(n.urgent ? 'Not urgent' : 'Urgent', () => act('urgent', {}, n.urgent ? 'No longer urgent' : 'Marked urgent')) : null;
    let controls = null;
    if (n.status === 'confirm') {
      const t = words('Anything to add, or what you meant instead');
      controls = [t, h('div', { class: 'jf' }, btn(n.kind === 'rule' ? 'Confirm the rule' : 'Confirm, work it in', () => act('confirm', { text: t.value }, 'Confirmed'), 'primary'),
        btn('Not what I meant', () => (t.value.trim() ? act('back', { text: t.value }, 'Sent back') : toast('Say what you meant instead'))), btn('Drop it', () => act('park', {}, 'Set aside')), h('span', { class: 'grow' }), kind, urgent)];
    } else if (n.status === 'talk') {
      const t = words('Your reply');
      controls = [t, h('div', { class: 'jf' }, btn('Reply', () => (t.value.trim() ? act('reply', { text: t.value }, 'Sent') : toast('Write your reply first')), 'primary'),
        btn('Make it a change', () => act('kind', { kind: 'directive' }, 'Now a change: Claude will say what it takes it to mean')), btn('Settled', () => act('done', {}, 'Closed')), btn('Park it', () => act('park', {}, 'Set aside')),
        h('span', { class: 'grow' }), kind, urgent)];
    } else if (n.status === 'go' || n.status === 'new') {
      const t = words('Add to it'), sessions = ((S.state.overview || {}).live || {}).sessions || [];
      const sendTo = n.status === 'go' ? h('select', { 'aria-label': 'Send ' + n.id + ' to a session', onchange: (e) => { if (e.target.value) act('send', { session: e.target.value === '*' ? '' : e.target.value }, 'Sent'); } },
        h('option', { value: '' }, 'Send it to…'), h('option', { value: '*' }, 'Whichever session is free first'),
        sessions.filter((s) => s.state !== 'ended').map((s) => h('option', { value: s.id }, clip(s.title || s.prompt || 'A session', 50)))) : null;
      controls = [t, h('div', { class: 'jf' }, btn('Add', () => (t.value.trim() ? act('reply', { text: t.value }, 'Added') : toast('Write what to add first'))), sendTo, btn('Drop it', () => act('park', {}, 'Set aside')), h('span', { class: 'grow' }), kind, urgent)];
    } else if (n.status === 'later') {
      controls = h('div', { class: 'jf' }, btn('Bring it back', () => act('reopen', {}, 'Back in the box')), btn('Drop it', () => act('park', {}, 'Set aside')), h('span', { class: 'grow' }), kind);
    } else controls = h('div', { class: 'jf' }, btn('Open again', () => act('reopen', {}, 'Open again')));
    return h('article', { class: 'jot ' + n.status + (n.waits === 'you' ? ' mine' : ''), id: 'note-' + n.id },
      h('div', { class: 'jh' }, h('span', { class: 'id' }, n.id), h('span', { class: 'chip' + (n.kind ? ' accent' : '') }, n.kind ? NOTE[n.kind] || n.kind : 'Unsorted'),
        n.urgent && open ? h('span', { class: 'chip bad' }, 'Urgent') : null, h('span', { class: 'where' }, noteWhere(n)), h('span', { class: 'd' }, when(n.created))),
      h('blockquote', {}, n.text),
      n.from ? h('span', { class: 'sub' }, 'Part of ' + n.from + ', split off so each part gets its own answer.') : null,
      n.reading ? h('div', { class: 'answer' }, h('span', { class: 'label' }, n.status === 'confirm' ? 'Claude takes this to mean' : 'Taken to mean'), h('span', { html: inline(n.reading) })) : null,
      (n.thread || []).map((m) => h('div', { class: 'msg ' + m.who }, h('span', {}, m.who === 'you' ? 'You' : 'Claude', h('br'), when(m.at)), m.who === 'you' ? h('div', { class: 'said' }, m.text) : md(m.text))),
      n.result ? h('div', { class: 'answer' }, h('span', { class: 'label' }, n.status === 'parked' ? 'Why it was left' : 'What was done'), h('span', { html: inline(n.result) }),
        n.ref || n.decision ? h('span', { class: 'mono muted' }, [n.ref, n.decision ? 'on the record as ' + n.decision : ''].filter(Boolean).join(' · ')) : null) : null,
      controls);
  }
  function notesPage() {
    const all = notesOf().slice().reverse(), ov = S.state.overview || {};
    const open = (n) => ['new', 'confirm', 'go', 'talk'].includes(n.status);
    const views = [['open', 'Open', open], ['you', 'Needs you', (n) => n.waits === 'you'], ['new', 'Unsorted', (n) => n.status === 'new' && !n.kind]]
      .concat(Object.keys(NOTE).map((k) => [k, NOTE[k], (n) => n.kind === k && (k === 'later' ? n.status === 'later' : open(n))]), [['closed', 'Closed', (n) => n.status === 'done' || n.status === 'parked']]);
    S.noteView = views.some((v) => v[0] === S.noteView) ? S.noteView : 'open';
    const list = h('div', { class: 'jots' });
    const tabs = views.map(([id, label, test]) => { const count = all.filter(test).length;
      const b = h('button', { class: 'btn small' + (S.noteView === id ? ' on' : ''), type: 'button', onclick: () => { S.noteView = id; tabs.forEach((x) => x.classList.toggle('on', x === b)); draw(); } },
        label, count ? h('span', { class: 'count' + (id === 'you' ? ' hot' : '') }, String(count)) : null); return b; });
    function draw() {
      const test = views.find((v) => v[0] === S.noteView)[2];
      const rows = all.filter(test).sort((a, b) => (b.waits === 'you') - (a.waits === 'you') || (!!b.urgent) - (!!a.urgent));
      list.replaceChildren(...(rows.length ? rows.map(noteCard) : [h('div', { class: 'empty' }, all.length ? 'Nothing here.' : (S.state.static ? 'No notes in this sample.' : 'No notes yet. Type one above.'))]));
    }
    draw();
    return h('main', {},
      h('section', {}, h('h1', {}, 'Notes'),
        h('p', { class: 'muted', style: 'max-width:76ch' }, 'Type whatever comes to mind and carry on. A session is handed your notes when it finishes a turn, or between steps once a note has waited a while, so nothing is spent checking for them. ',
          'A change or a rule comes back to you to confirm before anything is done; a question becomes a thread you answer here.'),
        S.state.static ? null : noteBox().el,
        ov.hooks_notes === false && !S.state.static ? h('div', { class: 'say' }, h('span', {}, 'Sessions are not being handed your notes yet. In the project, say to Claude Code:'), h('code', {}, 'turn on the Studio\'s live reporting'), copyButton('turn on the Studio\'s live reporting')) : null),
      h('section', {}, h('div', { class: 'filters' }, tabs), list));
  }

  // --------------------------------------------------------------- playtests
  function playtestsPage() {
    const sessions = S.state.playtests;
    const main = h('main', {});
    main.append(h('section', {}, h('h1', {}, 'What you said in playtests, and what became of it'),
      h('p', { class: 'muted', style: 'max-width:70ch' }, 'Each F8 report is listed with what was done about it. When a note is marked fixed, play the build and say whether it is.')));
    if (!sessions.length) main.append(h('div', { class: 'empty' }, 'No playtest folder is set yet (studio.toml, [playtests] dirs), or it holds no session.'));
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
        if (!r.startsWith('b.') && !r.startsWith('s.') && !S.over && !/^(TEXTAREA|INPUT)$/.test((document.activeElement || {}).tagName || '')) render(r, true);
        else { const bar = $('.top'); if (bar) bar.replaceWith(top(r)); }
      }
    } catch (e) { /* the server is restarting; try again on the next beat */ }
  }
  if (!STATIC) setInterval(pulse, 4000);
  render(route());
})();
