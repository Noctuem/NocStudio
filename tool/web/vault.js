// Your own notes under the menu: a few pages to read, and a box that adds to the end of one.
// Only where the app's hub.toml names a notes folder; anywhere else the section stays hidden.
(() => {
  'use strict';
  const box = document.getElementById('vault');
  if (!box) return;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  // a small reader for the markdown these pages use: headings, lists, checkboxes, tables, bold, [[links]]
  function inline(text) {
    const out = document.createDocumentFragment();
    const re = /\*\*([^*]+)\*\*|\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|`([^`]+)`|\[([^\]]+)\]\((https?:[^)\s]+)\)/g;
    let at = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > at) out.append(text.slice(at, m.index));
      if (m[1]) out.append(el('b', '', m[1]));
      else if (m[2]) out.append(el('span', 'wl', m[3] || m[2]));
      else if (m[4]) out.append(el('code', 'i', m[4]));
      else { const a = el('a', '', m[5]); a.href = m[6]; a.target = '_blank'; a.rel = 'noopener'; out.append(a); }
      at = re.lastIndex;
    }
    if (at < text.length) out.append(text.slice(at));
    return out;
  }
  function render(md) {
    const root = el('div', 'md'), lines = md.replace(/\r/g, '').split('\n');
    let list = null, i = 0;
    const close = () => { list = null; };
    while (i < lines.length) {
      const line = lines[i];
      if (/^\s*\|/.test(line)) { // a table: header, the dashes, then rows
        close();
        const rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
        const cells = (r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
        const table = el('table'), body = el('tbody');
        rows.forEach((r, n) => {
          if (/^\s*\|?\s*:?-{2,}/.test(r)) return;
          const tr = el('tr');
          for (const c of cells(r)) { const td = el(n === 0 ? 'th' : 'td'); td.append(inline(c)); tr.append(td); }
          (n === 0 ? (table.createTHead()) : body).append(tr);
        });
        table.append(body); root.append(el('div', 'tw')); root.lastChild.append(table);
        continue;
      }
      let m;
      if ((m = line.match(/^(#{1,4})\s+(.*)/))) { close(); const hd = el(m[1].length === 1 ? 'h2' : 'h' + Math.min(6, m[1].length + 1)); hd.append(inline(m[2])); root.append(hd); }
      else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { close(); root.append(el('hr')); }
      else if ((m = line.match(/^\s*(?:[-*]|(\d+)\.)\s+(\[( |x|X)\]\s+)?(.*)/))) {
        const tag = m[1] ? 'ol' : 'ul';
        if (!list || list.tagName.toLowerCase() !== tag) { list = el(tag); root.append(list); }
        const li = el('li', m[2] ? 'task' + (m[3].trim() ? ' done' : '') : '');
        if (m[2]) li.append(el('span', 'tick', m[3].trim() ? '✓' : ''));
        li.append(inline(m[4])); list.append(li);
      } else if (!line.trim()) close();
      else { close(); const p = el('p'); p.append(inline(line)); root.append(p); }
      i += 1;
    }
    return root;
  }

  let shown = '';
  async function load() {
    let data;
    try { data = await (await fetch('api/vault')).json(); } catch (e) { return; }
    if (!data || !data.vault) { box.hidden = true; return; }
    const key = JSON.stringify(data.pages.map((p) => [p.path, p.updated]));
    if (key === shown) return; // nothing changed: leave what is typed and where it is scrolled
    shown = key;
    box.hidden = false;
    const pages = document.getElementById('vault-pages');
    pages.replaceChildren(...data.pages.map((p) => {
      const card = el('article', 'vpage');
      const titled = /^\s*#\s/.test(p.text); // the page names itself in its first line: no second name over it
      const head = el('div', 'vh'); head.append(el('h2', '', p.name), el('span', 'muted', p.missing ? 'not found' : ''));
      card.append(titled ? '' : head, p.missing ? el('p', 'muted', p.path + ' is not in the notes folder.') : render(p.text));
      return card;
    }));
    const form = document.getElementById('vault-dump');
    form.hidden = !data.dump;
    if (data.dump) document.getElementById('vault-dump-to').textContent = 'Adds to the end of ' + data.dump + '.';
  }
  const text = document.getElementById('vault-text'), said = document.getElementById('vault-said');
  async function add() {
    if (!text.value.trim()) { said.textContent = 'Write something first.'; return; }
    try {
      const res = await fetch('api/dump', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: text.value }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'It was not added');
      text.value = ''; said.textContent = 'Added to ' + data.page + '.';
      shown = ''; load();
    } catch (e) { said.textContent = String(e.message || e); }
  }
  document.getElementById('vault-add').addEventListener('click', add);
  text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); add(); } });
  text.addEventListener('input', () => { said.textContent = ''; });
  load(); setInterval(load, 15000);
})();
