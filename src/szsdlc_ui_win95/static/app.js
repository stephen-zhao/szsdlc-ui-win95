/* szsdlc-ui-win95: trait-driven frontend. No build step, no framework. Design: SPK-0005 in szsdlc-szsdlc.
 *
 * Rule of the house: nothing below names an entity type. Every window is
 * assembled from the schema descriptor (/api/schema): a type's capability
 * flags, declared fields, workflow, layouts and relations.
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------ utils
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const svg = (markup) => { const t = document.createElement('template'); t.innerHTML = markup.trim(); return t.content.firstChild; };
  const normId = (ref) => { const m = /^\s*([A-Za-z][A-Za-z0-9]*)-0*(\d+)\s*$/.exec(String(ref || '')); return m ? `${m[1].toUpperCase()}-${+m[2]}` : null; };
  const humanize = (s) => { const t = String(s).replace(/[_-]+/g, ' ').trim(); return t.charAt(0).toUpperCase() + t.slice(1); };
  const basename = (p) => String(p).split('/').pop();
  const dirname = (p) => { const i = String(p).lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i); };
  function joinPath(base, rel) {
    const out = [];
    for (const part of (rel.startsWith('/') ? rel.slice(1) : (base ? base + '/' : '') + rel).split('/')) {
      if (!part || part === '.') continue;
      if (part === '..') { if (!out.length) return null; out.pop(); } else out.push(part);
    }
    return out.join('/');
  }
  const store = {
    get(k) { try { return localStorage.getItem('szv:' + k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem('szv:' + k, v); } catch { /* storage unavailable */ } },
  };
  const fmtSize = (n) => n == null ? '' : n < 1024 ? `${n} bytes` : `${(n / 1024).toFixed(1)} KB`;

  // -------------------------------------------------------------------- api
  // The viewer is a multiplexer: one instance, many projects. Everything below
  // the project list is scoped to one project id (`/api/p/<id>/…`).
  const SNAP = window.SZ_SNAPSHOT || null;
  const TOKEN = document.querySelector('meta[name="viewer-token"]')?.content || '';
  async function get(path, params) {
    const qs = params ? '?' + new URLSearchParams(params) : '';
    const r = await fetch('/api/' + path + qs, { headers: { Accept: 'application/json' } });
    if (!r.ok && r.status !== 404) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }
  const hub = SNAP ? {
    meta: async () => SNAP.meta || {},
    projects: async () => SNAP.projects,
    open: async () => { throw new Error('A snapshot cannot open more projects.'); },
    refresh: async () => { throw new Error('A snapshot cannot be refreshed.'); },
  } : {
    meta: () => get('meta'),
    projects: () => get('projects'),
    async open(location, codeRoot) {
      const r = await fetch('/api/projects', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Viewer-Token': TOKEN },
        body: JSON.stringify({ location, code_root: codeRoot || null }) });
      const body = await r.json();
      if (!r.ok) { const e = new Error(body.detail || body.title || `HTTP ${r.status}`); e.fix = body.fix; throw e; }
      return body;
    },
    // Take the latest from where the project is kept. Nothing is sent. A 409
    // means unsent changes would be replaced; the caller asks, then sets replace.
    async refresh(pid, replace = false) {
      const r = await fetch('/api/p/' + encodeURIComponent(pid) + '/refresh', { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Viewer-Token': TOKEN }, body: JSON.stringify({ replace }) });
      const body = await r.json();
      if (!r.ok) { const e = new Error(body.detail || body.title || `HTTP ${r.status}`); e.status = r.status; e.fix = body.fix; throw e; }
      return body;
    },
  };
  function apiFor(pid) {
    if (SNAP) {
      const D = SNAP.data[pid];
      return {
        project: async () => D.project, schema: async () => D.schema, entities: async () => D.entities,
        roadmaps: async () => D.roadmaps, docs: async () => D.docs_list,
        entity: async (id) => D.details[id] || null,
        doc: async (root, path) => D.docs[`${root}:${path}`] || { root, path, exists: false, code_root: false },
        raw: () => null,
      };
    }
    const base = 'p/' + encodeURIComponent(pid) + '/';
    return {
      project: () => get(base + 'project'), schema: () => get(base + 'schema'), entities: () => get(base + 'entities'),
      roadmaps: () => get(base + 'roadmaps'), docs: () => get(base + 'docs'),
      entity: (id) => get(base + 'entities/' + encodeURIComponent(id)),
      doc: (root, path, fallback) => get(base + 'doc', { root, path, fallback: fallback ? '1' : '0' }),
      raw: (root, path) => '/api/' + base + 'raw?' + new URLSearchParams({ root, path }),
    };
  }

  // ------------------------------------------------------------------ state
  // S is the *current* project's context; CTX holds every project loaded so far.
  let S = null;
  const CTX = new Map();
  let PROJECTS = [];
  let META = {};
  const typeOf = (row) => S.types.get(row.type);
  const rowsOfType = (prefix) => S.rows.filter((r) => r.type === prefix);
  const schemaFromConfig = () => S.schema.source !== 'inferred';

  // ------------------------------------------------------------------ icons
  // Original 16px pixel art. A type's glyph comes from its traits; its colour from its prefix.
  const PAL = ['#000080', '#008000', '#800000', '#808000', '#800080', '#008080', '#a05000', '#404090'];
  const hashColor = (s) => { let x = 7; for (const c of String(s)) x = (x * 31 + c.charCodeAt(0)) >>> 0; return PAL[x % PAL.length]; };
  const PAGE = '<path d="M3.5 1.5h6l3 3v10h-9z" fill="#fff" stroke="#000"/><path d="M9.5 1.5v3h3" fill="#c0c0c0" stroke="#000"/>';
  const LINES = '<rect x="5" y="7" width="6" height="1" fill="#808080"/><rect x="5" y="9" width="6" height="1" fill="#808080"/><rect x="5" y="11" width="4" height="1" fill="#808080"/>';
  const ICONS = {
    computer: (c) => `<rect x="1" y="1" width="14" height="10" fill="#c0c0c0"/><rect x="1" y="1" width="14" height="1" fill="#fff"/><rect x="1" y="1" width="1" height="10" fill="#fff"/><rect x="14" y="1" width="1" height="10" fill="#000"/><rect x="1" y="10" width="14" height="1" fill="#000"/><rect x="3" y="3" width="10" height="6" fill="${c || '#008080'}"/><rect x="3" y="3" width="10" height="1" fill="#000"/><rect x="5" y="11" width="6" height="1" fill="#808080"/><rect x="2" y="12" width="12" height="3" fill="#c0c0c0"/><rect x="2" y="12" width="12" height="1" fill="#fff"/><rect x="2" y="14" width="12" height="1" fill="#000"/><rect x="10" y="13" width="2" height="1" fill="#00a000"/>`,
    folder: (c) => `<rect x="1" y="3" width="6" height="2" fill="#c8a030"/><rect x="1" y="4" width="14" height="10" fill="#f2d65c"/><rect x="1" y="5" width="13" height="1" fill="#fff6b0"/><rect x="14" y="4" width="1" height="10" fill="#7a5c00"/><rect x="1" y="13" width="14" height="1" fill="#7a5c00"/>${c ? `<rect x="9" y="8" width="5" height="5" fill="${c}"/><rect x="9" y="8" width="5" height="1" fill="#fff" opacity=".45"/>` : ''}`,
    doc: (c) => `${PAGE}${LINES}${c ? `<rect x="5" y="4" width="3" height="2" fill="${c}"/>` : ''}`,
    stack: (c) => `<path d="M5.5 .5h6l2 2v9h-8z" fill="#e0e0e0" stroke="#000"/><path d="M2.5 3.5h6l3 3v9h-9z" fill="#fff" stroke="#000"/><rect x="4" y="9" width="6" height="1" fill="#808080"/><rect x="4" y="11" width="6" height="1" fill="#808080"/><rect x="4" y="13" width="4" height="1" fill="#808080"/><rect x="4" y="6" width="3" height="2" fill="${c || '#000080'}"/>`,
    checklist: (c) => `${PAGE}<rect x="5" y="5" width="2" height="2" fill="${c || '#008000'}"/><rect x="8" y="5" width="3" height="1" fill="#808080"/><rect x="5" y="8" width="2" height="2" fill="${c || '#008000'}"/><rect x="8" y="8" width="3" height="1" fill="#808080"/><rect x="5" y="11" width="2" height="2" fill="none" stroke="#808080" stroke-width=".8"/><rect x="8" y="11" width="3" height="1" fill="#808080"/>`,
    note: (c) => `<path d="M2.5 2.5h11v8l-3 3h-8z" fill="#ffff88" stroke="#806000"/><path d="M10.5 13.5v-3h3" fill="#e0e060" stroke="#806000"/><rect x="4" y="6" width="7" height="1" fill="#a09040"/><rect x="4" y="8" width="5" height="1" fill="#a09040"/><rect x="7" y="1" width="2" height="3" fill="${c || '#800000'}"/>`,
    scroll: (c) => `${PAGE}${LINES}<circle cx="10.5" cy="12" r="2.5" fill="${c || '#800000'}" stroke="#000" stroke-width=".6"/>`,
    calendar: () => '<rect x="1.5" y="2.5" width="13" height="12" fill="#fff" stroke="#000"/><rect x="2" y="3" width="12" height="3" fill="#800000"/><rect x="4" y="1" width="1" height="3" fill="#000"/><rect x="11" y="1" width="1" height="3" fill="#000"/><g fill="#808080"><rect x="3" y="8" width="2" height="2"/><rect x="7" y="8" width="2" height="2"/><rect x="11" y="8" width="2" height="2"/><rect x="3" y="11" width="2" height="2"/><rect x="7" y="11" width="2" height="2"/></g><rect x="11" y="11" width="2" height="2" fill="#000080"/>',
    inbox: () => '<path d="M1.5 9.5l2-6h9l2 6v5h-13z" fill="#c0c0c0" stroke="#000"/><rect x="5" y="4" width="6" height="4" fill="#fff"/><rect x="6" y="5" width="4" height="1" fill="#808080"/><path d="M1.5 9.5h4l1 2h3l1-2h4" fill="none" stroke="#000"/>',
    views: () => `${PAGE}<rect x="5" y="7" width="6" height="1" fill="#000080"/><rect x="5" y="9" width="4" height="1" fill="#000080"/><path d="M11 8.5l-2.5 3.5h2l-1 3.5 3.5-4.5h-2l1.2-2.5z" fill="#ffc000" stroke="#604000" stroke-width=".6"/>`,
    globe: () => '<circle cx="8" cy="8" r="6.5" fill="#3a78d0" stroke="#000"/><path d="M4 5h3v2h2v3H6v3H4zM10 4h2v2h-2zM10 9h3v2h-3z" fill="#3aa03a"/>',
    missing: () => `<path d="M3.5 1.5h6l3 3v10h-9z" fill="#fff" stroke="#808080" stroke-dasharray="1 1"/><path d="M6 6l4 4M10 6l-4 4" stroke="#c00000" stroke-width="1.5"/>`,
    warn: () => '<path d="M8 1L15.5 14.5H.5z" fill="#ffd800" stroke="#000"/><rect x="7" y="5" width="2" height="5" fill="#000"/><rect x="7" y="11" width="2" height="2" fill="#000"/>',
    info: () => '<circle cx="8" cy="8" r="7" fill="#fff" stroke="#000080"/><rect x="7" y="7" width="2" height="5" fill="#000080"/><rect x="7" y="4" width="2" height="2" fill="#000080"/>',
    error: () => '<circle cx="8" cy="8" r="7" fill="#d00000" stroke="#600000"/><path d="M5 5l6 6M11 5l-6 6" stroke="#fff" stroke-width="2"/>',
    gear: () => '<g fill="#606060"><rect x="7" y="1" width="2" height="3"/><rect x="7" y="12" width="2" height="3"/><rect x="1" y="7" width="3" height="2"/><rect x="12" y="7" width="3" height="2"/><rect x="3" y="3" width="2" height="2"/><rect x="11" y="11" width="2" height="2"/><rect x="11" y="3" width="2" height="2"/><rect x="3" y="11" width="2" height="2"/></g><circle cx="8" cy="8" r="4.5" fill="#909090" stroke="#000"/><circle cx="8" cy="8" r="1.8" fill="#e0e0e0" stroke="#000" stroke-width=".6"/>',
    help: () => '<rect x="2.5" y="1.5" width="11" height="13" fill="#000080" stroke="#000"/><rect x="3" y="2" width="2" height="12" fill="#4040c0"/><path d="M7 6a2 2 0 1 1 3 1.7c-.8.5-1 .8-1 1.8" fill="none" stroke="#ffff00" stroke-width="1.6"/><rect x="8.2" y="11" width="1.6" height="1.6" fill="#ffff00"/>',
    details: () => '<g fill="#000080"><rect x="1" y="2" width="3" height="2"/><rect x="1" y="7" width="3" height="2"/><rect x="1" y="12" width="3" height="2"/></g><g fill="#404040"><rect x="6" y="2" width="9" height="2"/><rect x="6" y="7" width="9" height="2"/><rect x="6" y="12" width="9" height="2"/></g>',
    board: () => '<rect x=".5" y="1.5" width="4" height="13" fill="#fff" stroke="#404040"/><rect x="6" y="1.5" width="4" height="13" fill="#fff" stroke="#404040"/><rect x="11.5" y="1.5" width="4" height="13" fill="#fff" stroke="#404040"/><rect x="1.5" y="3" width="2" height="2" fill="#000080"/><rect x="1.5" y="6" width="2" height="2" fill="#000080"/><rect x="7" y="3" width="2" height="2" fill="#008080"/><rect x="12.5" y="3" width="2" height="2" fill="#800000"/>',
    graphv: () => '<path d="M4 4L12 8M4 12L12 8" stroke="#404040"/><rect x="1" y="2" width="5" height="4" fill="#c0c0c0" stroke="#000" stroke-width=".8"/><rect x="1" y="10" width="5" height="4" fill="#c0c0c0" stroke="#000" stroke-width=".8"/><rect x="10" y="6" width="5" height="4" fill="#000080" stroke="#000" stroke-width=".8"/>',
    back: () => '<path d="M2 8l6-6v4h6v4H8v4z" fill="#008000" stroke="#003000" stroke-width=".8"/>',
    // Two arrows chasing each other round a circle: the top one heads right, the bottom one left.
    refresh: () => '<path d="M3 7a5 5 0 0 1 8.6-3.4" fill="none" stroke="#003000" stroke-width="3"/><path d="M3 7a5 5 0 0 1 8.6-3.4" fill="none" stroke="#008000" stroke-width="1.6"/><path d="M14.5 1.5v5h-5z" fill="#008000" stroke="#003000" stroke-width=".8"/><path d="M13 9a5 5 0 0 1-8.6 3.4" fill="none" stroke="#003000" stroke-width="3"/><path d="M13 9a5 5 0 0 1-8.6 3.4" fill="none" stroke="#008000" stroke-width="1.6"/><path d="M1.5 14.5v-5h5z" fill="#008000" stroke="#003000" stroke-width=".8"/>',
    fwd: () => '<path d="M14 8L8 2v4H2v4h6v4z" fill="#008000" stroke="#003000" stroke-width=".8"/>',
    up: () => '<rect x="1" y="5" width="6" height="2" fill="#c8a030"/><rect x="1" y="6" width="14" height="8" fill="#f2d65c"/><rect x="1" y="13" width="14" height="1" fill="#7a5c00"/><path d="M8 3l-3 4h2v4h2V7h2z" fill="#000" />',
    newwin: () => '<rect x="1.5" y="3.5" width="10" height="9" fill="#fff" stroke="#000"/><rect x="2" y="4" width="9" height="2" fill="#000080"/><rect x="5.5" y=".5" width="10" height="9" fill="#fff" stroke="#000"/><rect x="6" y="1" width="9" height="2" fill="#000080"/>',
    copy: () => '<path d="M2.5 1.5h6v9h-6z" fill="#fff" stroke="#000"/><path d="M6.5 5.5h7v9h-7z" fill="#fff" stroke="#000"/><rect x="8" y="8" width="4" height="1" fill="#808080"/><rect x="8" y="10" width="4" height="1" fill="#808080"/><rect x="8" y="12" width="3" height="1" fill="#808080"/>',
    tag: () => '<path d="M1.5 2.5h6l7 7-5 5-7-7z" fill="#f2d65c" stroke="#7a5c00"/><circle cx="5" cy="6" r="1.3" fill="#7a5c00"/>',
    network: () => '<rect x="1" y="2" width="7" height="5" fill="#c0c0c0" stroke="#000" stroke-width=".8"/><rect x="2" y="3" width="5" height="3" fill="#008080"/><rect x="8" y="8" width="7" height="5" fill="#c0c0c0" stroke="#000" stroke-width=".8"/><rect x="9" y="9" width="5" height="3" fill="#000080"/><path d="M4.5 7v4.5H8M11.5 8V5.5H8" fill="none" stroke="#000"/><rect x="1" y="13" width="6" height="2" fill="#808080"/>',
    power: () => '<path d="M5 4.5a5 5 0 1 0 6 0" fill="none" stroke="#800000" stroke-width="2"/><rect x="7" y="1" width="2" height="7" fill="#800000"/>',
    logo: () => '<rect x="1.5" y="2.5" width="9" height="3" fill="#00a0a0" stroke="#000"/><rect x="3.5" y="6.5" width="10" height="3" fill="#2040c0" stroke="#000"/><rect x="5.5" y="10.5" width="9" height="3" fill="#c03020" stroke="#000"/>',
  };
  function icon(spec, size = 16) {
    const [name, color] = Array.isArray(spec) ? spec : [spec];
    const draw = ICONS[name] || ICONS.doc;
    return svg(`<svg class="ico" xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 16 16" shape-rendering="crispEdges" aria-hidden="true">${draw(color)}</svg>`);
  }
  function typeIcon(t) {
    const f = t.flags, c = hashColor(t.prefix);
    const name = f.can_parent ? 'folder' : f.intake ? 'note' : f.tracks_progress ? 'checklist'
      : f.persistent ? 'scroll' : t.layouts.includes('directory') ? 'stack' : 'doc';
    return [name, c];
  }
  const GLYPH = {
    min: '<svg width="8" height="7" aria-hidden="true"><rect x="1" y="5" width="6" height="2" fill="currentColor"/></svg>',
    max: '<svg width="9" height="8" aria-hidden="true"><rect x=".5" y=".5" width="8" height="7" fill="none" stroke="currentColor"/><rect width="9" height="2" fill="currentColor"/></svg>',
    restore: '<svg width="9" height="9" aria-hidden="true"><rect x="2.5" y=".5" width="6" height="5" fill="none" stroke="currentColor"/><rect x="2" width="7" height="2" fill="currentColor"/><rect x=".5" y="3.5" width="6" height="5" fill="var(--face)" stroke="currentColor"/><rect y="3" width="7" height="2" fill="currentColor"/></svg>',
    close: '<svg width="8" height="7" aria-hidden="true"><path d="M0 0h2l2 2 2-2h2L5 3.5 8 7H6L4 5 2 7H0l3-3.5z" fill="currentColor"/></svg>',
  };

  // --------------------------------------------------------- window manager
  const WM = { z: 10, list: [], cascade: 0, active: null };
  const tasks = () => document.getElementById('tasks');

  // A window belongs to the project that was current when it opened, unless it
  // is global (dialogs, the Projects window). Keys are scoped the same way.
  const scopedKey = (key, global) => key && (global ? key : `${S ? S.pid : '-'}|${key}`);
  const findWin = (key, global) => WM.list.find((w) => w.key === scopedKey(key, global));
  function openWindow(o) {
    const pid = o.global || o.dialog ? null : (S ? S.pid : null);
    o = { ...o, key: scopedKey(o.key, o.global || o.dialog) };
    if (o.key) {
      const ex = WM.list.find((w) => w.key === o.key);
      if (ex) { ex.restore(); ex.focus(); ex.reused = true; return ex; }
    }
    const vw = innerWidth, vh = innerHeight - 30;
    const width = Math.min(o.width || 560, vw - 8), height = Math.min(o.height || 420, vh - 8);
    let x = o.x, y = o.y;
    if (o.dialog) { x = (vw - width) / 2; y = Math.max(8, vh / 2 - 140); }
    if (x == null) { x = 60 + (WM.cascade % 7) * 26; y = 20 + (WM.cascade % 7) * 26; WM.cascade++; }
    x = Math.max(0, Math.min(x, vw - width)); y = Math.max(0, Math.min(y, vh - height));

    const titleText = h('span', { class: 't' }, o.title);
    const ctrls = [];
    if (!o.dialog) {
      ctrls.push(h('button', { class: 'tb-btn min', type: 'button', 'aria-label': 'Minimize', title: 'Minimize', onclick: () => w.minimize() }));
      ctrls.push(h('button', { class: 'tb-btn max', type: 'button', 'aria-label': 'Maximize', title: 'Maximize', onclick: () => w.toggleMax() }));
    }
    ctrls.push(h('button', { class: 'tb-btn close', type: 'button', 'aria-label': 'Close', title: 'Close', onclick: () => w.close() }));
    ctrls.forEach((b) => { b.innerHTML = GLYPH[b.classList[1]]; });
    const bar = h('div', { class: 'titlebar' }, o.icon ? icon(o.icon) : null, titleText, ctrls);
    const body = h('div', { class: 'wbody' });
    const status = o.status ? h('div', { class: 'statusbar' }) : null;
    const el = h('section', {
      class: 'window' + (o.dialog ? ' dialog' : ''), role: o.dialog ? 'dialog' : 'region', 'aria-label': o.title,
      style: { left: x + 'px', top: y + 'px', width: width + 'px', height: o.dialog ? 'auto' : height + 'px' },
    }, bar, o.menu ? menubar(o.menu) : null, body, status, o.dialog ? null : h('div', { class: 'grip', 'aria-hidden': 'true' }));
    document.body.append(el);

    const taskBtn = o.dialog ? null : h('button', { class: 'btn', type: 'button', title: o.title, onclick: () => {
      if (WM.active === w && !el.classList.contains('minimized')) w.minimize(); else { w.restore(); w.focus(); }
    } }, o.icon ? icon(o.icon) : null, h('span', null, o.title));
    if (taskBtn) tasks().append(taskBtn);

    const w = {
      key: o.key, pid, el, body, reused: false,
      setTitle(t) { titleText.textContent = t; el.setAttribute('aria-label', t); if (taskBtn) { taskBtn.title = t; taskBtn.lastChild.textContent = t; } },
      setStatus(parts) { if (status) status.replaceChildren(...parts.map((p) => h('div', null, p))); },
      focus() {
        if (WM.active && WM.active !== w) { WM.active.el.classList.remove('active'); WM.active.taskBtn?.classList.remove('on'); }
        WM.active = w; el.classList.add('active'); taskBtn?.classList.add('on'); el.style.zIndex = ++WM.z;
      },
      minimize() { el.classList.add('minimized'); el.classList.remove('active'); taskBtn?.classList.remove('on'); if (WM.active === w) WM.active = null; focusTop(); },
      restore() { el.classList.remove('minimized'); },
      toggleMax() {
        el.classList.toggle('maximized');
        const b = bar.querySelector('.tb-btn.max');
        if (b) b.innerHTML = GLYPH[el.classList.contains('maximized') ? 'restore' : 'max'];
      },
      close() {
        el.remove(); taskBtn?.remove(); WM.list.splice(WM.list.indexOf(w), 1);
        if (WM.active === w) { WM.active = null; focusTop(); }
        o.onclose?.();
      },
      taskBtn,
    };
    el.addEventListener('pointerdown', () => w.focus(), true);
    bar.addEventListener('dblclick', (e) => { if (!o.dialog && !e.target.closest('button')) w.toggleMax(); });
    drag(bar, el, (dx, dy, start) => {
      if (el.classList.contains('maximized')) return;
      el.style.left = Math.max(-start.w + 60, Math.min(innerWidth - 60, start.l + dx)) + 'px';
      el.style.top = Math.max(0, Math.min(innerHeight - 50, start.t + dy)) + 'px';
    });
    const grip = el.querySelector('.grip');
    if (grip) drag(grip, el, (dx, dy, start) => {
      el.style.width = Math.max(260, start.w + dx) + 'px';
      el.style.height = Math.max(160, start.h + dy) + 'px';
    });
    WM.list.push(w); w.focus();
    return w;
  }
  function focusTop() {
    const vis = WM.list.filter((w) => !w.el.classList.contains('minimized') && !w.el.classList.contains('elsewhere'));
    vis.sort((a, b) => +a.el.style.zIndex - +b.el.style.zIndex);
    vis.at(-1)?.focus();
  }
  function drag(handle, el, move) {
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button')) return;
      const start = { x: e.clientX, y: e.clientY, l: el.offsetLeft, t: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
      handle.setPointerCapture(e.pointerId);
      dragging = true;  // a background redraw waits until the drag ends
      const mv = (ev) => move(ev.clientX - start.x, ev.clientY - start.y, start);
      const up = () => { dragging = false; handle.removeEventListener('pointermove', mv); handle.removeEventListener('pointerup', up); };
      handle.addEventListener('pointermove', mv); handle.addEventListener('pointerup', up);
      e.preventDefault();
    });
  }

  // ------------------------------------------------------------------ menus
  let openMenuEl = null;
  function closeMenus() {
    if (!openMenuEl) return;
    openMenuEl.el.remove(); openMenuEl.anchor?.setAttribute('aria-expanded', 'false'); openMenuEl = null;
    setTimeout(() => flushPending(), 0);  // a redraw that waited for the menu
  }
  function popMenu(anchor, items, opts = {}) {
    closeMenus();
    const list = h('ul', { role: 'menu' }, items.map((it) => {
      if (it === '-') return h('li', { class: 'sep', role: 'separator' });
      if (it.head) return h('li', { class: 'head' }, it.head);
      return h('li', { role: 'none' }, h('button', {
        type: 'button', role: 'menuitem', disabled: it.disabled || null, title: it.title || null,
        onclick: () => { closeMenus(); it.action?.(); },
      }, it.icon ? icon(it.icon, opts.big ? 24 : 16) : null, h('span', null, it.label)));
    }));
    const el = h('div', { class: 'menu' + (opts.big ? ' big' : '') + (opts.scroll ? ' scroll' : '') }, opts.banner || null, list);
    document.body.append(el);
    const r = anchor.getBoundingClientRect();
    if (opts.above) { el.style.left = r.left + 'px'; el.style.bottom = (innerHeight - r.top) + 'px'; }
    else { el.style.left = Math.min(r.left, innerWidth - el.offsetWidth - 4) + 'px'; el.style.top = r.bottom + 'px'; }
    anchor.setAttribute('aria-expanded', 'true');
    openMenuEl = { el, anchor };
    el.querySelector('button:not(:disabled)')?.focus();
  }
  function menubar(spec) {
    return h('div', { class: 'menubar', role: 'menubar' }, spec.map((m) => h('button', {
      type: 'button', 'aria-haspopup': 'menu', 'aria-expanded': 'false',
      onclick: (e) => { e.stopPropagation(); if (openMenuEl?.anchor === e.currentTarget) closeMenus(); else popMenu(e.currentTarget, typeof m.items === 'function' ? m.items() : m.items); },
    }, h('u', null, m.label[0]), m.label.slice(1))));
  }
  document.addEventListener('pointerdown', (e) => { if (openMenuEl && !openMenuEl.el.contains(e.target) && e.target !== openMenuEl.anchor && !openMenuEl.anchor.contains(e.target)) closeMenus(); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (openMenuEl) return closeMenus();
    const dlg = WM.list.filter((w) => w.el.classList.contains('dialog')).at(-1);
    dlg?.close();
  });

  // --------------------------------------------------------------- dialogs
  function messageBox({ title, kind = 'info', text, buttons }) {
    const w = openWindow({ title: title || 'szsdlc Viewer', dialog: true, width: 400 });
    const paras = (Array.isArray(text) ? text : [text]).map((t) => t instanceof Node ? t : h('p', null, t));
    w.body.append(
      h('div', { class: 'dialog-body' }, icon(kind, 32), h('div', { class: 'grow' }, paras)),
      h('div', { class: 'row', style: { justifyContent: 'center' } }, (buttons || [{ label: 'OK', default: true }]).map((b) =>
        h('button', { class: 'btn' + (b.default ? ' default' : ''), type: 'button', onclick: () => { w.close(); b.action?.(); } }, b.label))),
    );
    w.body.querySelector('.btn.default')?.focus();
    return w;
  }

  // -------------------------------------------------------------- markdown
  function slugger() {
    const seen = new Map();
    return (text) => {
      let s = text.toLowerCase().trim().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s/g, '-');
      const n = seen.get(s) || 0; seen.set(s, n + 1);
      return n ? `${s}-${n}` : s;
    };
  }
  function entLink(ref, label) {
    const row = S.byKey.get(normId(ref));
    const b = h('button', { class: 'link', type: 'button', title: row ? `${row.title} (${row.status || 'no status'})` : 'Not found in this project',
      onclick: (e) => { e.preventDefault(); openItem(ref, e.currentTarget); } }, label || ref);
    if (!row) b.classList.add('bad');
    return b;
  }
  function linkifyIds(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => n.parentElement.closest('a, pre, button, .fm') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    const hits = [];
    while (walker.nextNode()) if (/\b[A-Z][A-Z0-9]*-\d+\b/.test(walker.currentNode.nodeValue)) hits.push(walker.currentNode);
    for (const node of hits) {
      const frag = document.createDocumentFragment();
      let last = 0;
      const text = node.nodeValue;
      for (const m of text.matchAll(/\b([A-Z][A-Z0-9]*-\d+)\b/g)) {
        if (!S.byKey.has(normId(m[1]))) continue;
        frag.append(text.slice(last, m.index));
        const a = h('a', { href: '#' + m[1], class: 'ent', title: S.byKey.get(normId(m[1])).title });
        a.textContent = m[1];
        a.addEventListener('click', (e) => { e.preventDefault(); openItem(m[1], e.currentTarget); });
        frag.append(a);
        last = m.index + m[1].length;
      }
      if (last) { frag.append(text.slice(last)); node.replaceWith(frag); }
    }
  }
  function renderMarkdown(md, ctx, { inline = false } = {}) {
    const html = inline ? marked.parseInline(md || '', { gfm: true }) : marked.parse(md || '', { gfm: true });
    const el = h(inline ? 'span' : 'div', { class: inline ? 'md-inline' : 'md' });
    el.innerHTML = DOMPurify.sanitize(html);
    const slug = slugger();
    el.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((x) => { x.id = 'h-' + slug(x.textContent); });
    el.querySelectorAll('table').forEach((t) => t.replaceWith(h('div', { class: 'tablewrap' }, t.cloneNode(true))));
    el.querySelectorAll('a[href]').forEach((a) => wireLink(a, ctx, el));
    el.querySelectorAll('img[src]').forEach((img) => {
      const src = img.getAttribute('src');
      if (/^(https?:|data:)/i.test(src)) return;
      const p = joinPath(dirname(ctx.path || ''), src);
      const url = p && S.api.raw(ctx.root, p);
      if (url) img.src = url;
    });
    linkifyIds(el);
    return el;
  }
  function wireLink(a, ctx, container) {
    const href = a.getAttribute('href');
    if (/^[a-z][a-z0-9+.-]*:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; a.title = href; return; }
    if (href.startsWith('#')) {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        container.querySelector('#h-' + CSS.escape(decodeURIComponent(href.slice(1))))?.scrollIntoView({ block: 'start' });
      });
      return;
    }
    const [p] = href.split('#');
    let root = ctx.root, path = joinPath(dirname(ctx.path || ''), decodeURIComponent(p));
    if (path == null) { root = 'code'; path = decodeURIComponent(p).replace(/^(\.\.\/)+/, ''); }
    a.title = `${root === 'store' ? 'In tree' : 'Out of tree'}: ${path}`;
    a.addEventListener('click', (e) => { e.preventDefault(); openPath(root, path, e.currentTarget); });
  }
  function openPath(root, path, src) {
    const ent = root === 'store' && S.byPath.get(path);
    if (ent && ent.layout !== 'section') return openItem(ent.id, src);
    openDoc(root, path, { fallback: true });
  }

  // ------------------------------------------------------------- listview
  function listView({ columns, rows, onOpen, empty = 'This folder is empty.', sortKey = 'listview' }) {
    const box = h('div', { class: 'lv' });
    let sort = null;
    try { sort = JSON.parse(store.get('sort:' + sortKey) || 'null'); } catch { sort = null; }
    function draw() {
      let data = rows.slice();
      if (sort) {
        const col = columns.find((c) => c.key === sort.key);
        if (col) {
          const val = (r) => { const v = col.sort ? col.sort(r) : col.get ? col.get(r) : r[col.key]; return v == null ? '' : v; };
          data.sort((a, b) => { const x = val(a), y = val(b); return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * sort.dir; });
        }
      }
      const thead = h('thead', null, h('tr', null, columns.map((c) => h('th', {
        scope: 'col', 'data-sort': sort && sort.key === c.key ? (sort.dir > 0 ? '▲' : '▼') : null, style: c.width ? { width: c.width } : null,
        onclick: () => { sort = sort && sort.key === c.key ? { key: c.key, dir: -sort.dir } : { key: c.key, dir: 1 }; store.set('sort:' + sortKey, JSON.stringify(sort)); draw(); },
      }, c.label))));
      const tbody = h('tbody', null, data.length ? data.map((r) => {
        const tr = h('tr', { tabindex: '0' }, columns.map((c) => {
          const v = c.render ? c.render(r) : c.get ? c.get(r) : r[c.key];
          return h('td', { class: c.wrap ? 'wrap' : null, title: typeof v === 'string' ? v : null }, v);
        }));
        tr.addEventListener('click', () => { box.querySelectorAll('tr.sel').forEach((x) => x.classList.remove('sel')); tr.classList.add('sel'); if (matchMedia('(pointer: coarse)').matches) onOpen?.(r); });
        tr.addEventListener('dblclick', () => onOpen?.(r));
        tr.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') onOpen?.(r);
          if (e.key === 'ArrowDown') { tr.nextElementSibling?.focus(); e.preventDefault(); }
          if (e.key === 'ArrowUp') { tr.previousElementSibling?.focus(); e.preventDefault(); }
        });
        return tr;
      }) : h('tr', null, h('td', { class: 'empty', colspan: columns.length }, empty)));
      box.replaceChildren(h('table', null, thead, tbody));
    }
    draw();
    return box;
  }
  const cell = (ic, ...txt) => h('span', { class: 'cell' }, ic ? icon(ic) : null, txt);
  function miniProgress(p) {
    if (!p || !p.total) return h('span', { class: 'muted' }, p ? '0/0' : '');
    return h('span', { class: 'cell', title: `${p.done} of ${p.total} checked in ${basename(p.source)}` },
      h('span', { class: 'progress mini' }, h('b', { style: { width: Math.round(100 * p.done / p.total) + '%' } })), `${p.done}/${p.total}`);
  }
  const COL = {
    id: () => ({ key: 'id', label: 'ID', render: (r) => cell(typeIcon(typeOf(r)), r.id), sort: (r) => `${r.type}-${String(r.id.split('-')[1]).padStart(8, '0')}` }),
    title: () => ({ key: 'title', label: 'Title', get: (r) => String(r.title || '').replace(/`/g, '') }),
    type: () => ({ key: 'type', label: 'Type', get: (r) => typeOf(r).label }),
    status: () => ({ key: 'status', label: 'Status' }),
    progress: () => ({ key: 'progress', label: 'Progress', render: (r) => miniProgress(r.progress), sort: (r) => r.progress && r.progress.total ? r.progress.done / r.progress.total : -1 }),
    children: () => ({ key: 'children', label: 'Children' }),
    parent: () => ({ key: 'parent', label: 'Parent', render: (r) => r.parent ? entLink(r.parent) : '', sort: (r) => r.parent || '' }),
    horizon: () => ({ key: 'horizon', label: 'Horizon', get: (r) => r.placement ? `${r.placement.horizon} #${r.placement.position}` : '', sort: (r) => r.placement ? `${r.placement.roadmap}:${r.placement.horizon}:${String(r.placement.position).padStart(4, '0')}` : '~' }),
    tags: () => ({ key: 'tags', label: 'Tags', get: (r) => (r.tags || []).join(', ') }),
    field: (f) => ({ key: 'f:' + f.name, label: humanize(f.name), render: (r) => fieldCell(f, r.fields[f.name]), sort: (r) => r.fields[f.name] == null ? '' : String(r.fields[f.name]) }),
  };
  function fieldCell(f, v) {
    if (v == null) return '';
    if (f.kind === 'ref') return entLink(v);
    if (Array.isArray(v)) return v.join(', ');
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
  }
  function typeColumns(t) {
    const cols = [COL.id(), COL.title(), COL.status()];
    if (t.flags.tracks_progress) cols.push(COL.progress());
    if (t.flags.can_parent) cols.push(COL.children());
    if (t.relations_out.includes(S.schema.parent_relation)) cols.push(COL.parent());
    if (t.flags.schedulable) cols.push(COL.horizon());
    for (const f of t.fields) if (!['text', 'map'].includes(f.kind)) cols.push(COL.field(f));
    cols.push(COL.tags());
    return cols;
  }
  const mixedColumns = () => [COL.id(), COL.title(), COL.type(), COL.status(), COL.progress()];

  // -------------------------------------------------------------- explorer
  // The Explorer is the viewer's main window, and there may be many of them.
  // Each keeps its own location, history, tree state and remembered tabs.
  // A location is a node id:
  //   project · type:<PREFIX> · item:<ID> · tags · tag:<name> · roadmap · inbox · docs
  const plain = (t) => String(t || '').replace(/`/g, '').replace(/\*\*/g, '');
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const splitNode = (node) => { const i = node.indexOf(':'); return i < 0 ? [node, ''] : [node.slice(0, i), node.slice(i + 1)]; };
  const childrenOf = (id) => S.children.get(normId(id)) || [];
  let uidN = 0;
  const uid = () => 'u' + (++uidN);

  function explorersHere() { return WM.list.filter((w) => w.explorer && w.pid === S.pid); }
  // Which Explorer a click should drive: the one it happened in, else the frontmost.
  function explorerFor(src) {
    const el = src instanceof Element ? src.closest('.window') : null;
    const w = el && WM.list.find((x) => x.el === el);
    if (w && w.explorer) return w;
    const xs = explorersHere().sort((a, b) => +b.el.style.zIndex - +a.el.style.zIndex);
    return xs.find((x) => !x.el.classList.contains('minimized')) || xs[0] || null;
  }
  function go(node, src, { newWindow = false } = {}) {
    const x = newWindow ? null : explorerFor(src);
    if (x) { x.restore(); x.focus(); x.navigate(node); return x; }
    return openExplorer(node);
  }
  function openItem(ref, src, opts) {
    const row = S.byKey.get(normId(ref));
    if (!row) {
      return messageBox({ kind: 'warn', title: 'Item not found', text: [`${ref} does not name an item in this project.`, 'A relation that points at a missing id is a dangling reference; szsdlc validate reports it with a fix.'] });
    }
    return go('item:' + row.id, src, opts);
  }
  const openRoadmap = (src) => go('roadmap', src);

  function nodeLabel(node) {
    const [k, v] = splitNode(node);
    if (k === 'project') return S.project.name;
    if (k === 'type') return S.types.get(v)?.plural || v;
    if (k === 'item') return v;
    if (k === 'tag') return '#' + v;
    return { tags: 'Tags', roadmap: 'Roadmap', inbox: 'Inbox', docs: 'Views & documents' }[k] || node;
  }
  function nodeIcon(node) {
    const [k, v] = splitNode(node);
    if (k === 'type') return typeIcon(S.types.get(v));
    if (k === 'item') { const r = S.byKey.get(normId(v)); return r ? typeIcon(typeOf(r)) : 'doc'; }
    return { project: 'computer', tags: 'tag', tag: ['folder'], roadmap: 'calendar', inbox: 'inbox', docs: 'views' }[k] || 'doc';
  }
  function upOf(node) {
    const [k, v] = splitNode(node);
    if (k === 'item') { const r = S.byKey.get(normId(v)); return r && r.parent && S.byKey.has(normId(r.parent)) ? 'item:' + S.byKey.get(normId(r.parent)).id : 'type:' + (r ? r.type : ''); }
    if (k === 'tag') return 'tags';
    return k === 'project' ? null : 'project';
  }
  function defaultPath(node) {
    const [k, v] = splitNode(node);
    if (k === 'project') return '/project';
    if (k === 'item') { const r = S.byKey.get(normId(v)); return `/project/type:${r ? r.type : ''}/item:${v}`; }
    if (k === 'tag') return `/project/tags/tag:${v}`;
    return '/project/' + node;
  }

  function treeRoots({ hideClosed = false } = {}) {
    const keep = (rows) => (hideClosed ? rows.filter((r) => !isClosed(r)) : rows);
    const itemNodes = (rows, seen) => keep(rows).map((r) => {
      const key = normId(r.id);
      const kids = keep(childrenOf(r.id)).filter((c) => !seen.has(normId(c.id)));
      const next = new Set(seen).add(key);
      return { id: 'item:' + r.id, label: `${r.id}  ${plain(r.title)}`, icon: typeIcon(typeOf(r)), title: `${r.title} (${r.status || 'no status'})`,
        kids: kids.length ? () => itemNodes(kids, next) : null };
    });
    const tags = [...S.tags.keys()].sort();
    return [{ id: 'project', label: S.project.name, icon: 'computer', kids: () => [
      ...S.schema.types.map((t) => ({ id: 'type:' + t.prefix, label: t.plural, icon: typeIcon(t), kids: () => itemNodes(rowsOfType(t.prefix), new Set()) })),
      { id: 'roadmap', label: 'Roadmap', icon: 'calendar' },
      S.schema.types.some((t) => t.flags.intake) ? { id: 'inbox', label: 'Inbox', icon: 'inbox' } : null,
      tags.length ? { id: 'tags', label: 'Tags', icon: 'tag', kids: () => tags.map((tg) => ({ id: 'tag:' + tg, label: tg, icon: ['folder'], kids: () => itemNodes(S.tags.get(tg), new Set()) })) } : null,
      { id: 'docs', label: 'Views & documents', icon: 'views' },
    ].filter(Boolean) }];
  }

  function openExplorer(node = 'project') {
    const vw = innerWidth, vh = innerHeight - 30;
    const w = openWindow({
      title: 'Exploring', icon: 'computer', width: Math.min(1180, vw - 104), height: Math.min(760, vh - 10), status: true,
      menu: [
        { label: 'File', items: () => [
          { label: 'New window', icon: 'newwin', action: () => openExplorer(cur) },
          '-', { head: 'Switch project' }, ...projectMenuItems(),
          '-', { label: 'Close', action: () => w.close() }] },
        { label: 'View', items: () => [
          { label: 'Back', disabled: !back.length, action: goBack }, { label: 'Forward', disabled: !fwd.length, action: goFwd },
          { label: 'Up one level', disabled: !canUp(), action: goUp }, '-',
          ...(SNAP ? [] : [{ label: 'Refresh (F5)', action: () => refreshProject() }]),
          { label: (w.hideClosed ? '● ' : ' ') + 'Hide closed', action: () => setHideClosed(!w.hideClosed) }, '-',
          { label: 'Roadmap', icon: 'calendar', action: () => navigate('roadmap') },
          ...S.schema.types.map((t) => ({ label: t.plural, icon: typeIcon(t), action: () => navigate('type:' + t.prefix) })),
          '-', { label: 'Display settings…', icon: 'gear', action: openDisplay }] },
        { label: 'Help', items: () => [{ label: 'About szsdlc Viewer', icon: 'help', action: openAbout }] },
      ],
    });
    w.explorer = true;
    w.tabFor = new Map();
    // The key keeps its original name so a saved setting survives the rename.
    w.hideClosed = store.get('hideDone') === '1';
    let cur = null, selPath = null;
    const back = [], fwd = [];
    const expanded = new Set(['/project']);

    const tb = (ic, label, fn) => h('button', { class: 'tbtn icon', type: 'button', title: label, 'aria-label': label, onclick: fn }, icon(ic));
    const bBack = tb('back', 'Back', () => goBack()), bFwd = tb('fwd', 'Forward', () => goFwd()), bUp = tb('up', 'Up one level', () => goUp());
    // A snapshot has nothing to refresh from, so it gets no button (as it gets no menu entry).
    const bRefresh = SNAP ? null : tb('refresh', 'Refresh (F5)', () => refreshProject());
    if (bRefresh) { bRefresh.disabled = scheduler ? scheduler.buttonDisabled() : false; w.refreshBtn = bRefresh; }
    // The other half of a split button, as in Grafana: how often to refresh by itself.
    const bInterval = SNAP ? null : h('button', { class: 'tbtn interval', type: 'button', 'aria-haspopup': 'menu', 'aria-expanded': 'false',
      onclick: (e) => { e.stopPropagation(); if (openMenuEl?.anchor === bInterval) closeMenus(); else popMenu(bInterval, intervalMenu()); } });
    if (bInterval) { w.intervalBtn = bInterval; paintInterval(bInterval); }
    const crumbs = h('div', { class: 'field crumbbar', role: 'navigation', 'aria-label': 'Address' });
    const search = h('input', { class: 'field', id: uid(), type: 'search', placeholder: 'Find in folder', 'aria-label': 'Find in this folder', style: { width: '140px', flex: 'none' } });
    const hideId = uid();
    const hideBox = h('input', { type: 'checkbox', id: hideId, checked: w.hideClosed || null, onchange: () => setHideClosed(hideBox.checked) });
    const tree = h('div', { class: 'tree', role: 'tree', 'aria-label': 'Folders' });
    const splitter = h('div', { class: 'splitter', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Resize folders pane', tabindex: '0' });
    const pane = h('div', { class: 'pane' });
    const split = h('div', { class: 'split' }, tree, splitter, pane);
    const foldersBtn = h('button', { class: 'tbtn only-phone', type: 'button', onclick: () => split.classList.toggle('show-tree') }, 'Folders');
    w.body.append(h('div', { class: 'toolbar' }, bBack, bFwd, bUp, h('span', { class: 'split' }, bRefresh, bInterval), h('span', { class: 'tsep' }), crumbs, search,
      h('label', { class: 'tbtn check-tb', for: hideId, title: 'Hide closed items (any terminal status: done, dropped, …) everywhere in this window' }, hideBox, 'Hide closed'), foldersBtn), split);

    // The folders pane is resizable; its width is remembered per browser.
    const savedW = +store.get('treeWidth');
    if (savedW) tree.style.width = savedW + 'px';
    drag(splitter, tree, (dx, dy, start) => {
      const max = Math.max(160, split.clientWidth * 0.6);
      tree.style.width = Math.max(120, Math.min(max, start.w + dx)) + 'px';
      store.set('treeWidth', String(tree.offsetWidth));
    });
    splitter.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      tree.style.width = Math.max(120, tree.offsetWidth + (e.key === 'ArrowLeft' ? -16 : 16)) + 'px';
      store.set('treeWidth', String(tree.offsetWidth)); e.preventDefault();
    });

    function setHideClosed(on) {
      w.hideClosed = on; hideBox.checked = on; store.set('hideDone', on ? '1' : '0'); // original key; see above
      drawTree(); drawPane();
    }
    const roots = () => treeRoots({ hideClosed: w.hideClosed });
    // The tree nodes under a path ("/project/type:EPIC/item:EPIC-0007"), or null.
    function nodeAt(path) {
      let nodes = roots(), found = null;
      for (const seg of path.split('/').filter(Boolean)) {
        found = nodes.find((n) => n.id === seg);
        if (!found) return null;
        nodes = found.kids ? found.kids() : [];
      }
      return found ? { node: found, kids: nodes } : null;
    }

    function toggle(path, force) {
      if (force === true || (force == null && !expanded.has(path))) expanded.add(path); else expanded.delete(path);
      drawTree();
    }
    function drawTree() {
      const build = (nodes, parent) => h('ul', { role: 'group' }, nodes.map((n) => {
        const path = parent + '/' + n.id;
        const open = expanded.has(path);
        const tw = h('span', { class: 'tw' + (n.kids ? '' : ' none'), 'aria-hidden': 'true' }, n.kids ? (open ? '−' : '+') : '');
        const btn = h('button', {
          class: 'node' + (path === selPath ? ' sel' : ''), type: 'button', role: 'treeitem', title: n.title || null,
          'aria-expanded': n.kids ? String(open) : null, 'aria-selected': String(path === selPath),
          onclick: (e) => { if (e.target === tw) toggle(path); else navigate(n.id, { path }); },
          ondblclick: (e) => { if (n.kids && e.target !== tw) toggle(path); },
        }, tw, icon(n.icon), h('span', { class: 'lbl' }, n.label));
        return h('li', null, btn, n.kids && open ? build(n.kids(), path) : null);
      }));
      tree.replaceChildren(build(roots(), ''));
      tree.querySelector('.node.sel')?.scrollIntoView({ block: 'nearest' });
    }

    // Where in the tree a navigation lands. An item opened from inside a
    // folder or a parent stays under it; an ancestor on the current path is
    // found on that path; anything else goes to its own type folder.
    function contextualPath(node) {
      const segs = (selPath || '').split('/').filter(Boolean);
      const at = segs.indexOf(node);
      if (at >= 0) return '/' + segs.slice(0, at + 1).join('/');
      const [k, v] = splitNode(node);
      if (k === 'item' && cur) {
        const r = S.byKey.get(normId(v));
        const [ck, cv] = splitNode(cur);
        const inside = r && ((ck === 'item' && normId(r.parent) === normId(cv)) || (ck === 'type' && r.type === cv)
          || (ck === 'tag' && (r.tags || []).includes(cv)) || ck === 'inbox' || ck === 'roadmap');
        if (inside) return selPath + '/' + node;
      }
      return defaultPath(node);
    }
    function navigate(node, { path, push = true } = {}) {
      if (push && cur && (cur !== node || (path && path !== selPath))) { back.push({ node: cur, path: selPath }); fwd.length = 0; }
      const nextPath = path || contextualPath(node);
      cur = node;
      selPath = nextPath;
      const parts = selPath.split('/').filter(Boolean);
      for (let i = 1; i < parts.length; i++) expanded.add('/' + parts.slice(0, i).join('/'));
      split.classList.remove('show-tree');
      search.value = '';
      drawTree(); drawPane();
    }
    const canUp = () => selPath && selPath.split('/').filter(Boolean).length > 1;
    function goBack() { if (!back.length) return; fwd.push({ node: cur, path: selPath }); const b = back.pop(); navigate(b.node, { path: b.path, push: false }); }
    function goFwd() { if (!fwd.length) return; back.push({ node: cur, path: selPath }); const f = fwd.pop(); navigate(f.node, { path: f.path, push: false }); }
    // Up follows the address bar: one segment back along the path you came by.
    function goUp() {
      const segs = selPath.split('/').filter(Boolean);
      if (segs.length > 1) navigate(segs.at(-2), { path: '/' + segs.slice(0, -1).join('/') });
    }

    // ---- the address bar: a breadcrumb, or a typed path ----
    const crumbLabel = (seg) => { const [k, v] = splitNode(seg); return k === 'item' ? v : nodeLabel(seg); };
    const pathText = () => S.project.name + ':\\' + selPath.split('/').filter(Boolean).slice(1).map(crumbLabel).join('\\');
    function drawCrumbs() {
      const segs = selPath.split('/').filter(Boolean);
      const parts = [icon(nodeIcon(cur))];
      const chev = (items, label) => h('button', { class: 'chev', type: 'button', 'aria-label': label, title: label,
        onclick: (e) => { e.stopPropagation(); if (openMenuEl?.anchor === e.currentTarget) closeMenus(); else popMenu(e.currentTarget, items(), { scroll: true }); } }, '›');
      segs.forEach((seg, i) => {
        const path = '/' + segs.slice(0, i + 1).join('/');
        parts.push(h('button', { class: 'crumb' + (i === segs.length - 1 ? ' last' : ''), type: 'button', title: nodeLabel(seg),
          onclick: (e) => { e.stopPropagation(); navigate(seg, { path }); } }, i === 0 ? S.project.name : crumbLabel(seg)));
        const here = nodeAt(path);
        if (here && here.node.kids) parts.push(chev(() => (nodeAt(path)?.kids || []).map((k) => ({
          label: (segs[i + 1] === k.id ? '● ' : ' ') + k.label, icon: k.icon, action: () => navigate(k.id, { path: path + '/' + k.id }),
        })), `Go to an item inside ${nodeLabel(seg)}`));
      });
      parts.push(h('span', { class: 'crumb-fill', title: 'Click to type a path' }));
      crumbs.replaceChildren(...parts);
      crumbs.scrollLeft = crumbs.scrollWidth;
    }
    function editCrumbs() {
      const input = h('input', { class: 'crumb-edit', type: 'text', id: uid(), 'aria-label': 'Path', spellcheck: 'false', value: pathText() });
      crumbs.replaceChildren(icon(nodeIcon(cur)), input);
      input.focus(); input.select();
      let done = false;
      const finish = (go) => { if (done) return; done = true; if (go) goToText(input.value); else drawCrumbs(); };
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); finish(true); } if (e.key === 'Escape') { e.preventDefault(); finish(false); } });
      input.addEventListener('blur', () => finish(false));
    }
    crumbs.addEventListener('click', (e) => { if (e.target === crumbs || e.target.classList.contains('crumb-fill')) editCrumbs(); });
    // Accepts "szsdlc:\Epics\EPIC-0007\WI-0029", "Epics/EPIC-7", or just "wi-29".
    function goToText(text) {
      const t = text.trim();
      const direct = normId(t);
      if (direct && S.byKey.has(direct)) return navigate('item:' + S.byKey.get(direct).id);
      let parts = t.split(/[\\/]+/).filter(Boolean);
      if (parts.length && (parts[0].replace(/:$/, '').toLowerCase() === S.project.name.toLowerCase() || /:$/.test(parts[0]))) parts = parts.slice(1);
      let path = '/project', nodes = roots()[0].kids(), node = 'project';
      for (const part of parts) {
        const p = part.toLowerCase(), pid = normId(part);
        const hit = nodes.find((n) => {
          const [k, v] = splitNode(n.id);
          return n.id.toLowerCase() === p || crumbLabel(n.id).toLowerCase() === p || n.label.toLowerCase() === p
            || (k === 'type' && v.toLowerCase() === p) || (k === 'tag' && '#' + v.toLowerCase() === p) || (k === 'item' && pid && normId(v) === pid);
        });
        if (!hit) { drawCrumbs(); return messageBox({ kind: 'warn', title: 'Address', text: [`Cannot find “${part}” in ${nodeLabel(node)}.`, 'Type a folder or item name from the path, or just an item ID such as WI-0029.'] }); }
        node = hit.id; path += '/' + hit.id; nodes = hit.kids ? hit.kids() : [];
      }
      navigate(node, { path });
    }

    function drawPane() {
      const [k, v] = splitNode(cur);
      w.setTitle(`Exploring - ${nodeLabel(cur)}`);
      drawCrumbs();
      bBack.disabled = !back.length; bFwd.disabled = !fwd.length; bUp.disabled = !canUp();
      search.hidden = k === 'item';
      let status = '';
      if (k === 'item') {
        const row = S.byKey.get(normId(v));
        if (!row) { pane.replaceChildren(h('p', { class: 'muted pad' }, `${v} is not in this project.`)); return; }
        setHash(row.id);
        pane.replaceChildren(itemPage(row, w));
        status = `${row.id} · ${typeOf(row).label} · ${row.path}`;
      } else {
        const c = folderContent(k, v);
        pane.replaceChildren(c.el);
        status = c.status;
      }
      w.setStatus([status, S.schema.source !== 'inferred' ? `Read by szsdlc ${S.schema.szsdlc_version || ''}` : 'Schema: inferred from files', `Backend: ${S.project.backend.kind}`]);
    }
    function folderContent(k, v) {
      const q = search.value.trim().toLowerCase();
      const match = (r) => !q || `${r.id} ${r.title} ${r.status} ${(r.tags || []).join(' ')}`.toLowerCase().includes(q);
      const visible = (rows) => rows.filter(match).filter((r) => !(w.hideClosed && isClosed(r)));
      const hiddenNote = (all, shown) => (w.hideClosed && all > shown ? ` (${all - shown} closed hidden)` : '');
      const coll = (rows, opts) => collectionView(visible(rows), { host: w, ...opts });
      if (k === 'project') {
        const flags = (t) => Object.entries(t.flags).filter(([, x]) => x).map(([f]) => humanize(f)).join(', ');
        return {
          el: listView({ rows: S.schema.types.filter((t) => !q || `${t.plural} ${t.prefix}`.toLowerCase().includes(q)), sortKey: 'project', onOpen: (t) => navigate('type:' + t.prefix),
            columns: [
              { key: 'plural', label: 'Name', render: (t) => cell(typeIcon(t), t.plural) },
              { key: 'prefix', label: 'Prefix' }, { key: 'count', label: 'Items' },
              { key: 'layouts', label: 'Layout', get: (t) => t.layouts.join(', ') },
              { key: 'traits', label: 'Traits', get: flags },
              { key: 'statuses', label: 'Statuses in use', get: (t) => t.workflow.statuses.map((s) => s.name).join(', ') },
            ] }),
          status: `${S.schema.types.length} type(s), ${S.rows.length} item(s)`,
        };
      }
      if (k === 'type') {
        const t = S.types.get(v), all = rowsOfType(v), rows = visible(all);
        return { el: coll(all, { key: 'type:' + v, columns: typeColumns(t), defaultView: t.flags.actionable ? 'board' : 'details' }), status: `${rows.length} object(s)${hiddenNote(all.length, rows.length)}` };
      }
      if (k === 'tags') {
        const rows = [...S.tags.entries()].map(([tag, rs]) => ({ tag, count: rs.length, types: [...new Set(rs.map((r) => typeOf(r).plural))].join(', ') })).filter((r) => !q || r.tag.includes(q));
        return { el: listView({ rows, sortKey: 'tags', onOpen: (r) => navigate('tag:' + r.tag),
          columns: [{ key: 'tag', label: 'Tag', render: (r) => cell(['folder'], r.tag) }, { key: 'count', label: 'Items' }, { key: 'types', label: 'Types' }] }), status: `${rows.length} tag(s)` };
      }
      if (k === 'tag') {
        const all = S.tags.get(v) || [], rows = visible(all);
        return { el: coll(all, { key: 'tag' }), status: `${rows.length} item(s) tagged ${v}${hiddenNote(all.length, rows.length)}` };
      }
      if (k === 'inbox') {
        const types = S.schema.types.filter((t) => t.flags.intake);
        const all = S.rows.filter((r) => types.some((t) => t.prefix === r.type)), rows = visible(all);
        return { el: coll(all, { key: 'inbox', columns: types.length === 1 ? typeColumns(types[0]) : null }), status: `${rows.length} captured thought(s)${hiddenNote(all.length, rows.length)}` };
      }
      if (k === 'roadmap') {
        // The roadmap is the schedulable items, viewed by default as a board grouped by horizon.
        const all = S.rows.filter((r) => typeOf(r).flags.schedulable || r.placement);
        const el = h('div', { class: 'pane' },
          S.roadmaps.length ? null : h('p', { class: 'muted' }, 'This project has no roadmap yet. szsdlc schedule places the first item.'),
          coll(all, { key: 'roadmap', defaultView: 'board', defaultGroup: 'horizon' }));
        return { el, status: S.roadmaps.length ? `Placement lives in ${S.roadmaps.map((r) => r.path).join(', ')} and nowhere else; szsdlc schedule writes it.` : 'No roadmap' };
      }
      if (k === 'docs') {
        const rows = S.docs.filter((d) => !q || `${d.title} ${d.path}`.toLowerCase().includes(q));
        return { el: listView({ rows, sortKey: 'docs', onOpen: (d) => openDoc(d.root, d.path),
          columns: [{ key: 'title', label: 'Name', render: (d) => cell(d.generated ? 'views' : 'doc', d.title) }, { key: 'path', label: 'File' }, { key: 'generated', label: 'Kind', get: (d) => d.generated ? 'Generated view' : 'Document' }] }),
          status: `${rows.length} document(s); generated views are rendered by szsdlc, never edited by hand` };
      }
      return { el: h('div'), status: '' };
    }
    search.addEventListener('input', drawPane);
    w.navigate = (n) => navigate(n);
    // After a refresh: the project's data was reloaded, so draw again in place.
    w.redraw = () => { drawTree(); drawPane(); };  // keeps each item's chosen tab
    navigate(node, { push: false });
    return w;
  }

  // -------------------------------------------------------------- item page
  // An item is shown as a page, not a property sheet. Its tabs follow traits:
  // children for a parent, a checklist for the progress artifact, one tab per
  // Markdown artifact, a relations graph, and the documents list.
  const FLAG_LABELS = {
    intake: 'Accepts typeless capture (intake)', actionable: 'Shows in the next-up queue (actionable)',
    tracks_progress: 'Tracks progress from checkboxes', can_parent: 'Can be a parent',
    persistent: 'Never archived (persistent)', schedulable: 'Can be placed on a roadmap',
  };
  function check(state, label, title) {
    const cls = state === true ? 'on' : state == null ? 'unknown' : '';
    return h('span', { class: `check ${cls}${state === false ? ' dim' : ''}`, title: title || null, role: 'img', 'aria-label': `${label}: ${state == null ? 'unknown' : state ? 'yes' : 'no'}` }, h('i'), label);
  }
  function fieldValue(f, v, ctx) {
    if (v == null || v === '' || (Array.isArray(v) && !v.length)) return h('span', { class: 'muted' }, '(not set)');
    if (f.kind === 'ref' || (typeof v === 'string' && S.byKey.has(normId(v)))) return entLink(v);
    if (Array.isArray(v)) return h('span', { class: 'chips' }, v.map((x) => typeof x === 'string' && S.byKey.has(normId(x)) ? entLink(x) : h('span', { class: 'chip' }, typeof x === 'object' ? JSON.stringify(x) : String(x))));
    if (typeof v === 'string' && /^https?:\/\//.test(v)) return h('a', { href: v, target: '_blank', rel: 'noopener noreferrer' }, v);
    if (typeof v === 'boolean') return check(v, v ? 'Yes' : 'No');
    if (typeof v === 'object') return h('code', null, JSON.stringify(v));
    if (f.kind === 'text') return renderMarkdown(String(v), ctx, { inline: true });
    return String(v);
  }
  function tabbed(tabs, initial, onSelect) {
    const sheet = h('div', { class: 'sheet', role: 'tabpanel' });
    const bar = h('div', { class: 'tabs', role: 'tablist' });
    const cache = new Map();
    const select = (id) => {
      const tab = tabs.find((x) => x.id === id) || tabs[0];
      bar.querySelectorAll('.tab').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.id === tab.id)));
      if (!cache.has(tab.id)) cache.set(tab.id, tab.render());
      sheet.replaceChildren(cache.get(tab.id));
      onSelect?.(tab.id);
    };
    tabs.forEach((t) => bar.append(h('button', { class: 'tab', type: 'button', role: 'tab', 'data-id': t.id, onclick: () => select(t.id) }, t.label)));
    const wrap = h('div', { class: 'tabbed' }, bar, sheet);
    wrap.select = select;
    select(initial);
    return wrap;
  }
  function workflowStrip(t, status) {
    const sts = t.workflow.statuses;
    if (!sts.length) return null;
    const ordered = t.workflow.ordered;
    const guessed = sts.some((s) => s.source === 'guessed');
    return h('div', { class: 'wf', title: guessed ? 'Each state declares `terminal` in szsdlc config. This prototype cannot read szsdlc’s built-in defaults, so states it could not see are guessed from their names.' : 'Workflow, as config declares it' },
      sts.map((s, i) => [i && ordered ? h('span', { class: 'wf-arrow', 'aria-hidden': 'true' }, '›') : null,
        h('span', { class: 'wf-step' + (s.name === status ? ' on' : '') + (s.terminal ? ' terminal' : ''), title: [
          s.name === t.workflow.initial ? 'Initial state' : null, s.terminal ? (s.abandoned ? 'Terminal (abandoned)' : 'Terminal') : null,
          s.requires_artifact && s.requires_artifact.length ? `Entering needs ${s.requires_artifact.join(', ')}` : null,
          s.requires_tasks_complete ? 'Entering needs every task checked' : null,
          s.to && s.to.length ? `Next: ${s.to.join(', ')}` : null, s.description || null].filter(Boolean).join('\n') || null }, s.name)]),
      guessed ? h('span', { class: 'muted wf-note' }, '(guessed: defaults not readable)') : null);
  }

  function itemPage(row, host) {
    const t = typeOf(row);
    const key = normId(row.id);
    const root = h('div', { class: 'item-page' }, h('p', { class: 'muted pad' }, `Reading ${row.id}…`));
    const pid = S.pid;
    S.api.entity(row.id).then((d) => {
      if (!root.isConnected || S.pid !== pid) return;
      if (!d) { root.replaceChildren(h('p', { class: 'bad pad' }, `Could not read ${row.id}.`)); return; }
      const ctx = { root: 'store', path: d.path };
      const kids = childrenOf(row.id);
      const tabs = [];
      const overview = { id: 'overview', label: 'Overview', render: () => overviewTab(d, t, ctx) };
      const children = t.flags.can_parent || kids.length ? { id: 'children', label: `Children (${kids.length})`, render: () => childrenTab(kids, host) } : null;
      // A parent opens on its children; its own content is one tab away.
      if (children && kids.length) tabs.push(children, overview); else tabs.push(overview, ...(children ? [children] : []));
      const arts = d.documents.filter((x) => x.kind === 'artifact' && /\.(md|markdown)$/i.test(x.path))
        .sort((a, b) => (d.progress && b.path === d.progress.source) - (d.progress && a.path === d.progress.source) || a.path.localeCompare(b.path));
      for (const a of arts) {
        const name = humanize(basename(a.path).replace(/\.(md|markdown)$/i, ''));
        const isChecklist = d.progress && d.progress.source === a.path;
        tabs.push({ id: 'art:' + basename(a.path), label: isChecklist ? `${name} ${d.progress.done}/${d.progress.total}` : name,
          render: () => isChecklist ? checklistTab(a.path, host) : artifactTab(a.path) });
      }
      tabs.push({ id: 'relations', label: `Relations (${d.relations.length})`, render: () => relationsTab(row, host) });
      tabs.push({ id: 'documents', label: `Documents (${d.documents.length})`, render: () => documentsTab(d) });
      root.replaceChildren(itemHeader(row, d, t), tabbed(tabs, host?.tabFor?.get(key), (id) => host?.tabFor?.set(key, id)));
    });
    return root;
  }
  function itemHeader(row, d, t) {
    const chain = [];
    for (let p = row.parent, n = 0; p && n < 12; n++) { const pr = S.byKey.get(normId(p)); if (!pr || chain.includes(pr)) break; chain.unshift(pr); p = pr.parent; }
    const crumbs = h('nav', { class: 'crumbs', 'aria-label': 'Parents' },
      h('button', { class: 'link', type: 'button', onclick: (e) => go('type:' + t.prefix, e.currentTarget) }, t.plural),
      chain.map((c) => [h('span', { class: 'muted' }, ' › '), entLink(c.id), h('span', { class: 'muted crumb-t' }, ' ' + plain(c.title))]),
      h('span', { class: 'muted' }, ' › '), h('b', null, row.id));
    const meta = h('div', { class: 'meta' },
      d.status ? h('span', { class: 'pill' }, d.status) : null,
      d.progress ? miniProgress(d.progress) : null,
      d.placement ? h('button', { class: 'chip', type: 'button', title: `Position ${d.placement.position} on ${d.placement.roadmap}`, onclick: (e) => openRoadmap(e.currentTarget) }, icon('calendar'), ` ${humanize(d.placement.horizon)} #${d.placement.position}`) : null,
      (d.tags || []).map((tg) => h('button', { class: 'chip', type: 'button', onclick: (e) => go('tag:' + tg, e.currentTarget) }, '#' + tg)));
    return h('header', { class: 'item-head' },
      icon(typeIcon(t), 32),
      h('div', { class: 'grow', style: { minWidth: 0 } }, crumbs,
        h('h2', null, renderMarkdown(d.title, { root: 'store', path: d.path }, { inline: true })),
        meta, workflowStrip(t, d.status)),
      h('button', { class: 'btn', type: 'button', title: 'Open this item in a new Explorer window', onclick: () => openItem(row.id, null, { newWindow: true }) }, icon('newwin'), ' New window'));
  }
  function overviewTab(d, t, ctx) {
    const parentRel = S.schema.parent_relation;
    const details = h('fieldset', null, h('legend', null, 'Details'), h('dl', { class: 'kv' },
      h('dt', null, 'Type'), h('dd', null, `${t.label} (${t.prefix})`),
      h('dt', null, 'Status'), h('dd', null, d.status || h('span', { class: 'muted' }, '(none)')),
      h('dt', null, 'Layout'), h('dd', null, humanize(d.layout)),
      h('dt', null, 'File'), h('dd', null, h('button', { class: 'link', type: 'button', title: d.path, onclick: () => openDoc('store', d.path) }, basename(d.path))),
      t.relations_out.includes(parentRel) || d.parent ? [h('dt', null, humanize(parentRel)), h('dd', null, d.parent ? entLink(d.parent) : h('span', { class: 'muted' }, '(none)'))] : null,
      t.flags.schedulable ? [h('dt', null, 'Roadmap'), h('dd', null, d.placement ? `${humanize(d.placement.horizon)} #${d.placement.position}` : h('span', { class: 'muted' }, 'Not scheduled'))] : null));
    const fields = t.fields.length ? h('fieldset', null, h('legend', null, 'Fields'),
      h('dl', { class: 'kv' }, t.fields.map((f) => [h('dt', null, humanize(f.name)), h('dd', null, fieldValue(f, d.fields[f.name], ctx))]))) : null;
    const byKind = new Map();
    for (const r of d.relations) { const k = r.direction === 'out' ? `→ ${humanize(r.kind)}` : `← ${humanize(r.inverse || r.kind + ' (from)')}`; if (!byKind.has(k)) byKind.set(k, []); byKind.get(k).push(r.id); }
    const links = h('fieldset', null, h('legend', null, 'Connections'), byKind.size
      ? h('dl', { class: 'kv' }, [...byKind].map(([k, ids]) => [h('dt', null, k), h('dd', null, h('span', { class: 'chips' }, ids.map((x) => entLink(x))))]))
      : h('span', { class: 'muted' }, 'No relations.'));
    const decl = t.derived || [];
    const derivedVal = (dd, v) => {
      if (v == null) return h('span', { class: 'muted' }, '—');
      if (typeof v === 'boolean') return check(v, v ? 'Yes' : 'No');
      if (Array.isArray(v)) return v.length ? h('span', { class: 'chips' }, v.map((x) => entLink(x))) : h('span', { class: 'muted' }, 'none');
      if (typeof v === 'object' && 'children' in v) {
        const pct = v.children ? Math.round(100 * v.terminal / v.children) : 0;
        return h('span', { class: 'cell', title: v.tasks ? `${v.tasks.done}/${v.tasks.total} tasks across children` : null },
          h('span', { class: 'progress mini' }, h('b', { style: { width: pct + '%' } })), `${v.terminal}/${v.children} children done`);
      }
      return typeof v === 'object' ? h('code', null, JSON.stringify(v)) : String(v);
    };
    const derived = decl.length ? h('fieldset', null, h('legend', null, 'Derived'),
      h('dl', { class: 'kv' }, decl.map((dd) => [h('dt', { title: dd.description || `${dd.kind} over ${dd.relation}` }, humanize(dd.name)), h('dd', null, derivedVal(dd, (d.derived || {})[dd.name]))])),
      h('p', { class: 'muted', style: { margin: '6px 0 0' } }, 'Computed from the relation graph by szsdlc; never stored.')) : null;
    const traits = h('details', { class: 'traits' }, h('summary', null, `What a ${t.label.toLowerCase()} can do`),
      h('div', { class: 'trait-list' }, Object.keys(FLAG_LABELS).map((k) => check(t.flags[k], FLAG_LABELS[k], t.flag_source?.[k]))));
    const aside = h('aside', { class: 'facts' }, details, derived, fields, links, traits);
    const savedW = +store.get('factsWidth');
    if (savedW) aside.style.width = savedW + 'px';
    const handle = h('div', { class: 'splitter', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Resize the details panel', tabindex: '0' });
    const wrap = h('div', { class: 'overview' }, docBlock({ text: d.body, ctx, empty: '(This item has no description.)', open: () => openDoc('store', d.path) }), handle, aside);
    const setW = (px) => { aside.style.width = Math.max(180, Math.min(px, Math.max(220, wrap.clientWidth - 260))) + 'px'; store.set('factsWidth', String(aside.offsetWidth)); };
    drag(handle, aside, (dx, dy, start) => setW(start.w - dx));
    handle.addEventListener('keydown', (e) => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { setW(aside.offsetWidth + (e.key === 'ArrowLeft' ? 16 : -16)); e.preventDefault(); } });
    return wrap;
  }
  function childrenTab(kids, host) {
    const shown = host?.hideClosed ? kids.filter((r) => !isClosed(r)) : kids;
    return h('div', { class: 'panel-fill' }, statusBar(kids),
      host?.hideClosed && shown.length < kids.length ? h('p', { class: 'muted', style: { margin: 0 } }, `${kids.length - shown.length} closed hidden.`) : null,
      collectionView(shown, { key: 'children', host }));
  }
  const STATUS_PAL = ['#000080', '#008080', '#808000', '#800080', '#008000', '#800000', '#404040'];
  function statusBar(rows, { compact = false } = {}) {
    const counts = new Map();
    rows.forEach((r) => counts.set(r.status || '(none)', (counts.get(r.status || '(none)') || 0) + 1));
    const total = rows.length || 1;
    const order = [...counts.keys()];
    const bar = h('div', { class: 'stackbar' + (compact ? ' mini' : ''), role: 'img', 'aria-label': order.map((s) => `${s}: ${counts.get(s)}`).join(', ') },
      order.map((s, i) => h('b', { style: { width: (100 * counts.get(s) / total) + '%', background: STATUS_PAL[i % STATUS_PAL.length] }, title: `${s}: ${counts.get(s)}` })));
    if (compact) return bar;
    return h('div', { class: 'stackwrap' }, bar, h('div', { class: 'chips' }, order.map((s, i) =>
      h('span', { class: 'chip' }, h('i', { class: 'swatch', style: { background: STATUS_PAL[i % STATUS_PAL.length] } }), ` ${s}: ${counts.get(s)}`))));
  }
  function artifactTab(path) {
    const root = h('div', { class: 'panel-fill' }, h('p', { class: 'muted pad' }, 'Reading…'));
    S.api.doc('store', path).then((doc) => root.replaceChildren(docBlock({ text: doc.text, raw: doc.raw, ctx: { root: 'store', path }, front: doc.frontmatter, title: path, open: () => openDoc('store', path) })));
    return root;
  }

  // A checklist artifact is shown as steps, not as a rendered list: what is
  // done, what is next, and the notes around them.
  function parseChecklist(md) {
    const segs = []; let buf = []; let cur = null;
    const flush = () => { if (buf.join('').trim()) segs.push({ kind: 'md', text: buf.join('\n') }); buf = []; };
    for (const line of md.split('\n')) {
      const m = /^(\s*)[-*+]\s+\[( |x|X)\]\s+(.*)$/.exec(line);
      if (m) { flush(); cur = { kind: 'task', indent: m[1].replace(/\t/g, '    ').length, done: m[2] !== ' ', text: m[3] }; segs.push(cur); continue; }
      if (cur && /^\s+\S/.test(line)) { cur.text += '\n' + line.replace(/^\s{1,8}/, ''); continue; }
      cur = null; buf.push(line);
    }
    flush();
    return segs;
  }
  function checklistTab(path, host) {
    const root = h('div', { class: 'panel-fill' }, h('p', { class: 'muted pad' }, 'Reading…'));
    S.api.doc('store', path).then((doc) => {
      const ctx = { root: 'store', path };
      const segs = parseChecklist(doc.text || '');
      const tasks = segs.filter((s) => s.kind === 'task');
      const done = tasks.filter((s) => s.done).length;
      const next = tasks.find((s) => !s.done);
      const pct = tasks.length ? Math.round(100 * done / tasks.length) : 0;
      const hideId = uid();
      const hide = h('input', { type: 'checkbox', id: hideId, checked: host?.hideClosed || null });
      const list = h('ol', { class: 'steps' });
      let nextEl = null;
      function draw() {
        nextEl = null;
        list.replaceChildren(...segs.map((s) => {
          if (s.kind === 'md') return h('li', { class: 'step-note' }, renderMarkdown(s.text, ctx));
          if (hide.checked && s.done) return null;
          const li = h('li', { class: 'step' + (s.done ? ' done' : '') + (s === next ? ' next' : ''), style: s.indent ? { marginLeft: Math.min(s.indent, 16) * 3 + 'px' } : null },
            h('span', { class: 'check' + (s.done ? ' on' : ''), role: 'img', 'aria-label': s.done ? 'done' : 'not done' }, h('i')),
            h('span', { class: 'step-n' }, String(tasks.indexOf(s) + 1)),
            h('div', { class: 'step-body' }, s === next ? h('span', { class: 'pill next-pill' }, 'Next') : null, renderMarkdown(s.text, ctx)));
          if (s === next) nextEl = li;
          return li;
        }).filter(Boolean));
      }
      hide.addEventListener('change', draw);
      draw();
      const summary = h('div', { class: 'cl-summary' },
        h('div', { class: 'row' }, h('b', { class: 'big' }, `${done} of ${tasks.length} done`), h('span', { class: 'muted' }, `${pct}%`), h('span', { class: 'grow' }),
          next ? h('button', { class: 'btn', type: 'button', onclick: () => nextEl?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, 'Go to next step') : h('span', { class: 'pill' }, 'All done'),
          h('label', { class: 'row', for: hideId }, hide, 'Hide done'),
          h('button', { class: 'btn', type: 'button', onclick: () => openDoc('store', path) }, icon('doc'), ' As document')),
        h('div', { class: 'progress big', role: 'progressbar', 'aria-valuenow': String(pct), 'aria-valuemin': '0', 'aria-valuemax': '100' }, h('b', { style: { width: pct + '%' } })),
        h('p', { class: 'muted', style: { margin: 0 } }, `Parsed from ${basename(path)}. Progress is counted from its checkboxes, never typed in.`));
      root.replaceChildren(summary, h('div', { class: 'page' }, h('div', { class: 'page-inner' }, list)));
    });
    return root;
  }

  // ---------------------------------------------------------- relations graph
  // An ego graph: the item in the middle, what it names to the right, what
  // names it to the left, and (at depth 2) their neighbours beyond.
  function relationsTab(row, host) {
    const root = h('div', { class: 'panel-fill' });
    const center = normId(row.id);
    let depth = 1, asList = false;
    const hidden = new Set();
    const kinds = [...new Set(S.schema.relations.map((r) => r.name))];
    function edgesOf(k) {
      const out = [];
      const r = S.byKey.get(k);
      if (r) for (const [kind, tgt] of r.relations || []) out.push({ a: k, b: S.byKey.has(normId(tgt)) ? normId(tgt) : String(tgt), kind });
      for (const [kind, src] of S.incoming.get(k) || []) out.push({ a: normId(src), b: k, kind });
      return out.filter((e) => !hidden.has(e.kind)).filter((e) => {
        if (!host?.hideClosed) return true;
        const other = S.byKey.get(e.a === k ? e.b : e.a);
        return !(other && normId(other.id) !== center && isClosed(other));
      });
    }
    function build() {
      const col = new Map([[center, 0]]);
      const edges = new Map();
      let frontier = [center];
      for (let dd = 1; dd <= depth; dd++) {
        const next = [];
        for (const k of frontier) for (const e of edgesOf(k)) {
          edges.set(`${e.a}|${e.kind}|${e.b}`, e);
          const other = e.a === k ? e.b : e.a;
          if (!col.has(other)) { col.set(other, col.get(k) + (e.a === k ? 1 : -1)); next.push(other); }
        }
        frontier = next;
      }
      return { col, edges: [...edges.values()].filter((e) => col.has(e.a) && col.has(e.b)) };
    }
    const box = h('div', { class: 'graph' });
    const seg = (label, on, fn) => h('button', { class: 'tbtn', type: 'button', 'aria-pressed': String(on), onclick: fn }, label);
    const controls = h('div', { class: 'toolbar wrap' });
    function drawControls() {
      controls.replaceChildren(
        h('span', null, 'Depth'), h('span', { class: 'seg' }, seg('1', depth === 1, () => { depth = 1; redraw(); }), seg('2', depth === 2, () => { depth = 2; redraw(); })),
        h('span', { class: 'tsep' }),
        h('span', { class: 'seg' }, seg('Graph', !asList, () => { asList = false; redraw(); }), seg('List', asList, () => { asList = true; redraw(); })),
        h('span', { class: 'tsep' }),
        ...kinds.map((k) => h('button', { class: 'tbtn', type: 'button', 'aria-pressed': String(!hidden.has(k)), title: `Show or hide “${k}” edges`, onclick: () => { hidden.has(k) ? hidden.delete(k) : hidden.add(k); redraw(); } }, humanize(k))),
        h('span', { class: 'grow' }),
        h('span', { class: 'muted' }, 'Arrows run from where a relation is written to what it names.'));
    }
    function redraw() {
      drawControls();
      const g = build();
      if (asList) {
        const rows = g.edges.map((e) => ({ ...e, ar: S.byKey.get(e.a), br: S.byKey.get(e.b) }));
        box.replaceChildren(listView({ sortKey: 'edges', rows, empty: 'No relations.',
          columns: [{ key: 'a', label: 'From', render: (r) => r.ar ? cell(typeIcon(typeOf(r.ar)), r.ar.id) : r.a }, { key: 'kind', label: 'Relation', get: (r) => humanize(r.kind) },
            { key: 'b', label: 'To', render: (r) => r.br ? cell(typeIcon(typeOf(r.br)), r.br.id) : h('span', { class: 'bad' }, `${r.b} (not found)`) },
            { key: 'bt', label: 'Title', get: (r) => plain((normId(r.a) === center ? r.br : r.ar)?.title || '') }],
          onOpen: (r) => openItem(normId(r.a) === center ? r.b : r.a, root) }));
        return;
      }
      box.replaceChildren(graphSvg(g, center, (k) => openItem(k, root)));
      requestAnimationFrame(() => {
        const c = box.querySelector('.gnode.center');
        if (c) { const r = c.getBBox(); box.scrollLeft = Math.max(0, r.x + r.width / 2 - box.clientWidth / 2); box.scrollTop = Math.max(0, r.y + r.height / 2 - box.clientHeight / 2); }
      });
    }
    root.append(controls, box);
    redraw();
    return root;
  }
  function graphSvg({ col, edges }, center, onOpen, { order = null, outside = new Set() } = {}) {
    const NW = 196, NH = 46, GX = 120, GY = 16, PAD = 28;
    const cols = new Map();
    for (const [k, c] of col) { if (!cols.has(c)) cols.set(c, []); cols.get(c).push(k); }
    const keys = [...cols.keys()].sort((a, b) => a - b);
    const minC = keys[0], maxC = keys.at(-1);
    const kindOf = (k) => (edges.find((e) => e.a === k || e.b === k) || {}).kind || '';
    for (const [c, ks] of cols) {
      if (order) ks.sort((x, y) => order.get(x) - order.get(y));
      else ks.sort((x, y) => kindOf(x).localeCompare(kindOf(y)) || String(x).localeCompare(String(y), undefined, { numeric: true }));
      if (center != null && c === 0) { ks.splice(ks.indexOf(center), 1); ks.splice(Math.floor(ks.length / 2), 0, center); }
    }
    const maxN = Math.max(...[...cols.values()].map((v) => v.length));
    const H = PAD * 2 + maxN * NH + (maxN - 1) * GY + 20;
    const W = PAD * 2 + (maxC - minC + 1) * NW + (maxC - minC) * GX;
    const pos = new Map();
    for (const [c, ks] of cols) {
      const y0 = (H - (ks.length * NH + (ks.length - 1) * GY)) / 2;
      ks.forEach((k, i) => pos.set(k, { x: PAD + (c - minC) * (NW + GX), y: y0 + i * (NH + GY) }));
    }
    const mid = uid();
    const parts = [`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Relations graph">`,
      `<defs><marker id="${mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>`];
    const labels = [];
    const labelled = new Set();
    edges.forEach((e, i) => {
      const A = pos.get(e.a), B = pos.get(e.b), ca = col.get(e.a), cb = col.get(e.b);
      let p0, p3, c1, c2;
      if (ca < cb) { p0 = [A.x + NW, A.y + NH / 2]; p3 = [B.x - 2, B.y + NH / 2]; const dx = (p3[0] - p0[0]) / 2; c1 = [p0[0] + dx, p0[1]]; c2 = [p3[0] - dx, p3[1]]; }
      else if (ca > cb) { p0 = [A.x, A.y + NH / 2]; p3 = [B.x + NW + 2, B.y + NH / 2]; const dx = (p0[0] - p3[0]) / 2; c1 = [p0[0] - dx, p0[1]]; c2 = [p3[0] + dx, p3[1]]; }
      else { p0 = [A.x + NW, A.y + NH / 2]; p3 = [B.x + NW + 2, B.y + NH / 2]; const bulge = 40 + Math.abs(p3[1] - p0[1]) / 4; c1 = [p0[0] + bulge, p0[1]]; c2 = [p3[0] + bulge, p3[1]]; }
      // Edges converging on one item share a label, placed near that item.
      const tt = 0.78, u = 1 - tt;
      const lx = u * u * u * p0[0] + 3 * u * u * tt * c1[0] + 3 * u * tt * tt * c2[0] + tt * tt * tt * p3[0];
      const ly = u * u * u * p0[1] + 3 * u * u * tt * c1[1] + 3 * u * tt * tt * c2[1] + tt * tt * tt * p3[1];
      parts.push(`<g class="edge" data-a="${esc(e.a)}" data-b="${esc(e.b)}"><path d="M${p0} C${c1} ${c2} ${p3}" marker-end="url(#${mid})"/></g>`);
      const group = `${e.b}|${e.kind}|${Math.sign(cb - ca)}`;
      if (labelled.has(group)) return;
      labelled.add(group);
      const text = humanize(e.kind);
      const tw = text.length * 6 + 8;
      labels.push(`<g class="elabel" data-a="${esc(e.a)}" data-b="${esc(e.b)}"><rect x="${lx - tw / 2}" y="${ly - 8}" width="${tw}" height="15"/><text x="${lx}" y="${ly + 3}" text-anchor="middle">${esc(text)}</text></g>`);
    });
    parts.push(...labels);
    for (const [k, p] of pos) {
      const r = S.byKey.get(k);
      const isC = k === center;
      const t = r && typeOf(r);
      const [iname, icol] = t ? typeIcon(t) : ['missing'];
      const title = r ? plain(r.title) : 'not found in this project';
      const short = title.length > 30 ? title.slice(0, 29) + '…' : title;
      parts.push(`<g class="gnode${isC ? ' center' : ''}${r ? '' : ' dangling'}${outside.has(k) ? ' outside' : ''}${r && isClosed(r) ? ' done' : ''}" data-k="${esc(k)}" tabindex="0" role="link" aria-label="${esc((r ? r.id : k) + ': ' + title)}">`,
        `<title>${esc((r ? r.id : k) + ' — ' + title + (r && r.status ? ` (${r.status})` : ''))}</title>`,
        `<rect class="gbox" x="${p.x}" y="${p.y}" width="${NW}" height="${NH}"/>`,
        `<path class="hi" d="M${p.x + .5},${p.y + NH - .5} V${p.y + .5} H${p.x + NW - .5}"/><path class="lo" d="M${p.x + NW - .5},${p.y + .5} V${p.y + NH - .5} H${p.x + .5}"/>`,
        `<svg x="${p.x + 6}" y="${p.y + 6}" width="16" height="16" viewBox="0 0 16 16" shape-rendering="crispEdges">${(ICONS[iname] || ICONS.doc)(icol)}</svg>`,
        `<text class="gid" x="${p.x + 27}" y="${p.y + 18}">${esc(r ? r.id : k)}</text>`,
        r && r.status ? `<text class="gstatus" x="${p.x + NW - 7}" y="${p.y + 18}" text-anchor="end">${esc(r.status)}</text>` : '',
        `<text class="gtitle" x="${p.x + 8}" y="${p.y + 36}">${esc(short)}</text></g>`);
    }
    parts.push('</svg>');
    const el = svg(parts.join(''));
    const hl = (k, on) => el.querySelectorAll('.edge, .elabel').forEach((g) => { if (g.dataset.a === k || g.dataset.b === k) g.classList.toggle('hl', on); });
    el.querySelectorAll('.gnode').forEach((n) => {
      const k = n.dataset.k;
      n.addEventListener('mouseenter', () => hl(k, true)); n.addEventListener('mouseleave', () => hl(k, false));
      n.addEventListener('focus', () => hl(k, true)); n.addEventListener('blur', () => hl(k, false));
      if (k === center || !S.byKey.has(k)) return;
      n.addEventListener('click', () => onOpen(k));
      n.addEventListener('keydown', (e) => { if (e.key === 'Enter') onOpen(k); });
    });
    return el;
  }

  const WHERE = { store: 'In tree', code: 'Out of tree', 'code?': 'Out of tree', web: 'Web' };
  function documentsTab(d) {
    const docs = d.documents;
    const root = h('div', { class: 'panel-fill' });
    const n = (k) => docs.filter((x) => (WHERE[x.root] || '') === k).length;
    const iconFor = (x) => x.kind === 'link' ? 'globe' : x.exists === false ? 'missing' : x.kind === 'entity' ? typeIcon(typeOf(S.byKey.get(normId(x.entity)))) : x.kind === 'record' ? typeIcon(typeOf(d)) : 'doc';
    root.append(
      h('div', { class: 'row', style: { flexWrap: 'wrap' } },
        h('span', { class: 'badge' }, `In tree: ${n('In tree')}`), h('span', { class: 'badge out' }, `Out of tree: ${n('Out of tree')}`), h('span', { class: 'badge' }, `Web: ${n('Web')}`),
        S.project.code_root ? null : h('span', { class: 'muted' }, 'No code root: out-of-tree paths cannot be opened.')),
      listView({
        sortKey: 'documents', rows: docs, empty: 'No documents.',
        columns: [
          { key: 'name', label: 'Name', render: (x) => cell(iconFor(x), x.name) },
          { key: 'where', label: 'Where', get: (x) => WHERE[x.root] || x.root },
          { key: 'kind', label: 'Kind', get: (x) => ({ record: 'The record', artifact: 'Artifact', reference: 'Referenced', entity: 'Item record', link: 'Link' })[x.kind] || x.kind },
          { key: 'exists', label: 'Status', render: (x) => x.exists === false ? h('span', { class: 'bad' }, 'Not found') : x.exists ? 'Present' : '', sort: (x) => String(x.exists) },
          { key: 'size', label: 'Size', get: (x) => fmtSize(x.size), sort: (x) => x.size || 0 },
          { key: 'mentioned_in', label: 'Mentioned in', get: (x) => x.mentioned_in ? basename(x.mentioned_in) : '' },
        ],
        onOpen: (x) => {
          if (x.kind === 'link') { const a = h('a', { href: x.url, target: '_blank', rel: 'noopener noreferrer' }); document.body.append(a); a.click(); a.remove(); return; }
          if (x.kind === 'entity') return openItem(x.entity, root);
          if (x.exists === false) return missingDoc(x.root, x.path);
          openDoc(x.root, x.path);
        },
      }));
    return root;
  }
  function missingDoc(root, path) {
    const out = root !== 'store';
    messageBox({ kind: 'warn', title: 'Document not found', text: [
      `Cannot find “${path}”.`,
      out && !S.project.code_root ? (SNAP ? 'It lives outside the project store. This snapshot carries only the store; the local viewer resolves it against the code root you start it with.' : 'It lives outside the project store. Restart the viewer with STORE::CODE_ROOT pointing at the repository it describes.')
        : 'It is mentioned by the item but no file exists at that path.',
    ] });
  }

  // ---------------------------------------------------------- document block
  // Every Markdown shown anywhere can flip between rendered and source, and its
  // raw text can be copied.
  async function copyText(text, btn) {
    const label = btn.lastChild.textContent;
    const flash = (msg) => { btn.lastChild.textContent = ' ' + msg; setTimeout(() => { btn.lastChild.textContent = label; }, 1600); };
    try { await navigator.clipboard.writeText(text); flash('Copied'); return; } catch { /* fall back below */ }
    const ta = h('textarea', { style: { position: 'fixed', left: '-9999px', top: '0' } });
    ta.value = text; document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    ta.remove();
    flash(ok ? 'Copied' : 'Blocked: use Source and select');
  }
  function docBlock({ text, raw, ctx, empty, open, front, title, lead }) {
    const source = raw ?? text ?? '';
    let mode = 'rendered';
    const page = h('div', { class: 'page', tabindex: '0' });
    const bR = h('button', { class: 'tbtn', type: 'button', 'aria-pressed': 'true', onclick: () => set('rendered') }, 'Rendered');
    const bS = h('button', { class: 'tbtn', type: 'button', 'aria-pressed': 'false', onclick: () => set('source') }, 'Source');
    const copy = h('button', { class: 'tbtn', type: 'button', title: 'Copy the raw Markdown', onclick: (e) => copyText(source, e.currentTarget) }, icon('copy'), ' Copy raw');
    function set(m) { mode = m; bR.setAttribute('aria-pressed', String(m === 'rendered')); bS.setAttribute('aria-pressed', String(m === 'source')); draw(); }
    function draw() {
      const inner = h('div', { class: 'page-inner' }, lead || null);
      if (!source.trim()) inner.append(h('p', { class: 'muted' }, empty || '(empty)'));
      else if (mode === 'source') inner.append(h('pre', { class: 'src' }, source));
      else {
        if (front && Object.keys(front).length) inner.append(h('details', { class: 'fm' }, h('summary', null, 'Front matter'),
          h('dl', { class: 'kv' }, Object.entries(front).map(([k, v]) => [h('dt', null, k), h('dd', null, typeof v === 'object' ? h('code', null, JSON.stringify(v)) : String(v))]))));
        inner.append(renderMarkdown(text || '', ctx));
      }
      page.replaceChildren(inner);
    }
    draw();
    return h('div', { class: 'docblock' },
      h('div', { class: 'toolbar' }, h('span', { class: 'seg' }, bR, bS), copy,
        open ? h('button', { class: 'tbtn', type: 'button', onclick: open }, icon('doc'), ' Open in Document Viewer') : null,
        h('span', { class: 'grow' }), title ? h('span', { class: 'muted ellip' }, title) : null),
      page);
  }

  // ------------------------------------------------------------- doc viewer
  async function openDoc(root, path, { fallback = false } = {}) {
    const d = await S.api.doc(root, path, fallback);
    if (!d || !d.exists) return missingDoc(root, path);
    const out = d.root !== 'store';
    const w = openWindow({
      key: `doc:${d.root}:${d.path}`, title: `${basename(d.path)} - Document Viewer`, icon: out ? ['doc', '#a05000'] : 'doc', width: 720, height: 560, status: true,
      menu: [{ label: 'File', items: () => [d.entity ? { label: `Open ${d.entity}`, action: () => openItem(d.entity) } : null, { label: 'Close', action: () => w.close() }].filter(Boolean) }],
    });
    if (w.reused) return w;
    const lead = d.entity ? h('p', null, h('button', { class: 'btn', type: 'button', onclick: () => openItem(d.entity) }, icon(typeIcon(typeOf(S.byKey.get(normId(d.entity))))), ` Open ${d.entity}`)) : null;
    w.body.append(
      h('div', { class: 'addr' }, h('span', null, 'Address'), h('div', { class: 'field' }, h('span', { class: 'badge' + (out ? ' out' : '') }, out ? 'Out of tree' : 'In tree'), `${d.root}:/${d.path}`)),
      d.kind === 'markdown'
        ? docBlock({ text: d.text, raw: d.raw, ctx: { root: d.root, path: d.path }, front: d.frontmatter, lead })
        : docBlock({ text: '```\n' + (d.text || '') + '\n```', raw: d.raw ?? d.text, ctx: { root: d.root, path: d.path } }));
    w.setStatus([d.kind === 'markdown' ? 'GitHub-flavoured Markdown' : 'Plain text', out ? 'Out of tree' : 'In tree', fmtSize(d.size)]);
    return w;
  }

  // ------------------------------------------------------------ collections
  // Any set of items can be looked at three ways, as Explorer's View menu
  // offers: Details (a table), Board (a column per group) and Graph (nodes and
  // edges). The choice and the grouping are remembered per folder.
  function isClosed(r) {
    const st = typeOf(r).workflow.statuses.find((s) => s.name === r.status);
    return !!(st && st.terminal);
  }
  const VIEWS = [['details', 'Details', 'details'], ['board', 'Board', 'board'], ['graph', 'Graph', 'graphv']];
  function groupOptions(rows) {
    const types = [...new Set(rows.map((r) => r.type))].map((p) => S.types.get(p));
    const opts = [['status', 'Status']];
    if (types.length > 1) opts.push(['type', 'Type']);
    if (rows.some((r) => r.parent)) opts.push(['parent', humanize(S.schema.parent_relation)]);
    if (S.roadmaps.length && rows.some((r) => typeOf(r).flags.schedulable || r.placement)) opts.push(['horizon', 'Roadmap horizon']);
    if (rows.some((r) => (r.tags || []).length)) opts.push(['tag', 'Tag']);
    const seen = new Set();
    for (const t of types) for (const f of t.fields) if (!seen.has(f.name) && ['string', 'date', 'number', 'ref', 'bool', 'list'].includes(f.kind)) { seen.add(f.name); opts.push(['f:' + f.name, humanize(f.name)]); }
    return opts;
  }
  // Columns for a grouping, in a meaningful order, and which column(s) a row falls in.
  function groupSpec(rows, group) {
    const NONE = '\u0000none';
    if (group === 'status') {
      const order = [];
      for (const p of [...new Set(rows.map((r) => r.type))]) for (const s of S.types.get(p).workflow.statuses) if (!order.some((o) => o.name === s.name)) order.push(s);
      const open = order.filter((s) => !s.terminal), term = order.filter((s) => s.terminal);
      return { cols: [...open, ...term].map((s) => ({ key: s.name, label: s.name, terminal: s.terminal })).concat(rows.some((r) => !r.status) ? [{ key: NONE, label: '(no status)' }] : []), of: (r) => [r.status || NONE] };
    }
    if (group === 'type') return { cols: S.schema.types.filter((t) => rows.some((r) => r.type === t.prefix)).map((t) => ({ key: t.prefix, label: t.plural, icon: typeIcon(t) })), of: (r) => [r.type] };
    if (group === 'parent') {
      const ps = [...new Set(rows.map((r) => r.parent).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      return { cols: ps.map((p) => { const pr = S.byKey.get(normId(p)); return { key: p, label: pr ? `${pr.id} ${plain(pr.title)}` : p, icon: pr ? typeIcon(typeOf(pr)) : null }; }).concat([{ key: NONE, label: '(no parent)' }]), of: (r) => [r.parent || NONE] };
    }
    if (group === 'horizon') {
      const cols = [];
      for (const rm of S.roadmaps) for (const hz of rm.horizons) cols.push({ key: `${rm.name}:${hz.name}`, label: S.roadmaps.length > 1 ? `${rm.name}: ${humanize(hz.name)}` : humanize(hz.name), ordered: true });
      cols.push({ key: NONE, label: 'Not scheduled', collapsed: true });
      return { cols, of: (r) => [r.placement ? `${r.placement.roadmap}:${r.placement.horizon}` : NONE], position: (r) => r.placement ? r.placement.position : 1e9 };
    }
    if (group === 'tag') {
      const tags = [...new Set(rows.flatMap((r) => r.tags || []))].sort();
      return { cols: tags.map((t) => ({ key: t, label: '#' + t })).concat([{ key: NONE, label: '(untagged)' }]), of: (r) => (r.tags && r.tags.length ? r.tags : [NONE]) };
    }
    if (group.startsWith('f:')) {
      const f = group.slice(2);
      const val = (r) => { const v = r.fields ? r.fields[f] : undefined; return v == null || v === '' ? [NONE] : (Array.isArray(v) ? (v.length ? v.map(String) : [NONE]) : [String(v)]); };
      const vals = [...new Set(rows.flatMap(val))].filter((x) => x !== NONE).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      return { cols: vals.map((x) => ({ key: x, label: x })).concat([{ key: NONE, label: '(not set)' }]), of: val };
    }
    return groupSpec(rows, 'status');
  }

  function collectionView(rows, { key, host, columns = null, defaultView = 'details', defaultGroup = 'status' }) {
    const root = h('div', { class: 'collection' });
    let view = store.get('view:' + key) || defaultView;
    let group = store.get('group:' + key) || defaultGroup;
    const options = groupOptions(rows);
    if (!options.some(([g]) => g === group)) group = options.some(([g]) => g === defaultGroup) ? defaultGroup : 'status';
    let linked = store.get('linked:' + key) !== '0';
    const open = (r) => (host && host.navigate ? host.navigate('item:' + r.id) : openItem(r.id, root));
    const body = h('div', { class: 'coll-body' });
    const bar = h('div', { class: 'toolbar wrap viewbar' });
    function drawBar() {
      const selId = uid(), chkId = uid();
      bar.replaceChildren(...[
        h('span', { class: 'seg', role: 'group', 'aria-label': 'View' }, VIEWS.map(([v, label, ic]) =>
          h('button', { class: 'tbtn', type: 'button', 'aria-pressed': String(view === v), title: `${label} view`, onclick: () => { view = v; store.set('view:' + key, v); draw(); } }, icon(ic), ' ' + label))),
        view === 'board' ? [h('label', { for: selId }, 'Group by'), h('select', { class: 'field sel', id: selId, onchange: (e) => { group = e.target.value; store.set('group:' + key, group); draw(); } },
          options.map(([g, label]) => h('option', { value: g, selected: g === group || null }, label)))] : null,
        view === 'graph' ? h('label', { class: 'row', for: chkId, title: 'Also draw the items outside this folder that these items link to' },
          h('input', { type: 'checkbox', id: chkId, checked: linked || null, onchange: (e) => { linked = e.target.checked; store.set('linked:' + key, linked ? '1' : '0'); draw(); } }), 'Include linked items') : null,
        h('span', { class: 'grow' }),
        h('span', { class: 'muted' }, `${rows.length} item(s)`)].flat(2).filter((x) => x != null));
    }
    function draw() {
      drawBar();
      if (view === 'board') body.replaceChildren(boardView(rows, { group, key, open, hideClosed: host?.hideClosed }));
      else if (view === 'graph') body.replaceChildren(setGraph(rows, { linked, open, hideClosed: host?.hideClosed }));
      else body.replaceChildren(listView({ columns: columns || mixedColumns(), rows, onOpen: open, sortKey: key, empty: host?.hideClosed ? 'Nothing here that is still open.' : 'This folder is empty.' }));
    }
    root.append(bar, body);
    draw();
    return root;
  }

  function itemCard(r, { pos, open }) {
    const t = typeOf(r);
    const kids = childrenOf(r.id);
    const el = h('article', { class: 'card', tabindex: '0', 'data-k': normId(r.id), style: { '--stripe': hashColor(t.prefix) }, title: 'Double-click to open' },
      h('div', { class: 'card-top' }, icon(typeIcon(t)), h('b', null, r.id), h('span', { class: 'grow' }), r.status ? h('span', { class: 'pill' + (isClosed(r) ? ' done' : '') }, r.status) : null, pos ? h('span', { class: 'pos' }, '#' + pos) : null),
      h('div', { class: 'card-title' }, plain(r.title)),
      h('div', { class: 'card-meta' },
        r.progress ? miniProgress(r.progress) : null,
        kids.length ? h('span', { class: 'cell' }, statusBar(kids, { compact: true }), `${kids.length} children`) : null,
        r.parent ? h('span', { class: 'muted ellip' }, '↳ ', entLink(r.parent)) : null));
    el.addEventListener('dblclick', () => open(r));
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(r); });
    return el;
  }
  function boardView(rows, { group, key, open, hideClosed = false }) {
    const spec = groupSpec(rows, group);
    const canvas = h('div', { class: 'board' });
    const colsEl = h('div', { class: 'bcols' });
    const collapsedKey = (c) => `bcol:${key}:${group}:${c.key}`;
    for (const c of spec.cols) {
      let items = rows.filter((r) => spec.of(r).includes(c.key));
      if (spec.position) items.sort((a, b) => spec.position(a) - spec.position(b));
      else items.sort((a, b) => a.type.localeCompare(b.type) || (+a.id.split('-')[1] - +b.id.split('-')[1]));
      if (!items.length && (c.key.startsWith('\u0000') || (hideClosed && c.terminal))) continue;
      const saved = store.get(collapsedKey(c));
      const collapsed = saved == null ? !!c.collapsed : saved === '1';
      const colEl = h('section', { class: 'bcol' + (collapsed ? ' collapsed' : '') + (c.terminal ? ' terminal' : '') + (items.length ? '' : ' empty') },
        h('header', null,
          h('button', { class: 'bcol-toggle', type: 'button', 'aria-expanded': String(!collapsed), title: collapsed ? 'Expand this column' : 'Collapse this column',
            onclick: () => { store.set(collapsedKey(c), collapsed ? '0' : '1'); canvas.replaceWith(boardView(rows, { group, key, open, hideClosed })); } }, collapsed ? '▸' : '▾'),
          c.icon ? icon(c.icon) : null, h('b', { class: 'ellip' }, c.label), h('span', { class: 'count' }, String(items.length))),
        collapsed ? null : h('div', { class: 'bcol-body' }, items.length ? items.map((r) => itemCard(r, { pos: spec.position && r.placement ? r.placement.position : null, open })) : h('p', { class: 'muted' }, 'Nothing here.')));
      colsEl.append(colEl);
    }
    if (!colsEl.children.length) colsEl.append(h('p', { class: 'muted pad' }, 'Nothing to show.'));
    const overlay = svg('<svg class="deps" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"></svg>');
    canvas.append(colsEl, overlay);
    // Dependency arrows between visible cards, from prerequisite to dependent.
    const dep = S.schema.dependency_relation;
    const mid = uid();
    function drawDeps() {
      if (!canvas.isConnected) return;
      const base = canvas.getBoundingClientRect();
      overlay.setAttribute('width', canvas.scrollWidth); overlay.setAttribute('height', canvas.scrollHeight);
      const rect = (k) => { const c = canvas.querySelector(`.card[data-k="${CSS.escape(k)}"]`); if (!c) return null; const r = c.getBoundingClientRect(); return { x: r.left - base.left + canvas.scrollLeft, y: r.top - base.top + canvas.scrollTop, w: r.width, h: r.height }; };
      const out = [`<defs><marker id="${mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>`];
      for (const r of rows) for (const [kind, tgt] of r.relations || []) {
        if (kind !== dep) continue;
        const a = normId(tgt), b = normId(r.id);
        const A = rect(a), B = rect(b);
        if (!A || !B) continue;
        let d;
        if (A.x + A.w <= B.x) d = `M${A.x + A.w},${A.y + A.h / 2} C${A.x + A.w + 40},${A.y + A.h / 2} ${B.x - 40},${B.y + B.h / 2} ${B.x - 2},${B.y + B.h / 2}`;
        else if (B.x + B.w <= A.x) d = `M${A.x},${A.y + A.h / 2} C${A.x - 40},${A.y + A.h / 2} ${B.x + B.w + 40},${B.y + B.h / 2} ${B.x + B.w + 2},${B.y + B.h / 2}`;
        else { const x = Math.max(A.x + A.w, B.x + B.w); d = `M${x},${A.y + A.h / 2} C${x + 30},${A.y + A.h / 2} ${x + 30},${B.y + B.h / 2} ${x + 2},${B.y + B.h / 2}`; }
        out.push(`<path class="dep" data-a="${esc(a)}" data-b="${esc(b)}" d="${d}" marker-end="url(#${mid})"><title>${esc(r.id)} ${esc(humanize(dep))} ${esc(tgt)}</title></path>`);
      }
      overlay.innerHTML = out.join('');
    }
    new ResizeObserver(drawDeps).observe(canvas);
    canvas.addEventListener('scroll', drawDeps, { passive: true });
    canvas.addEventListener('click', (e) => {
      const card = e.target.closest('.card');
      const was = card && card.classList.contains('sel');
      canvas.querySelectorAll('.card.sel').forEach((c) => c.classList.remove('sel'));
      canvas.querySelectorAll('.dep.hl').forEach((p) => p.classList.remove('hl'));
      if (card && !was) { card.classList.add('sel'); const k = CSS.escape(card.dataset.k); canvas.querySelectorAll(`.dep[data-a="${k}"], .dep[data-b="${k}"]`).forEach((p) => p.classList.add('hl')); }
    });
    return canvas;
  }

  // A graph of a whole set: columns by longest path along authored edges, so
  // what writes a relation sits left of what it names; one barycentre sweep
  // each way keeps crossings down.
  function setGraph(rows, { linked, open, hideClosed }) {
    const inSet = new Set(rows.map((r) => normId(r.id)));
    const keys = new Set(inSet);
    const edges = [];
    for (const r of rows) for (const [kind, tgt] of r.relations || []) {
      const b = S.byKey.has(normId(tgt)) ? normId(tgt) : String(tgt);
      if (!inSet.has(b) && !linked) continue;
      const br = S.byKey.get(b);
      if (br && hideClosed && isClosed(br) && !inSet.has(b)) continue;
      keys.add(b); edges.push({ a: normId(r.id), b, kind });
    }
    if (linked) for (const r of rows) for (const [kind, src] of S.incoming.get(normId(r.id)) || []) {
      const a = normId(src);
      if (inSet.has(a)) continue;
      const ar = S.byKey.get(a);
      if (ar && hideClosed && isClosed(ar)) continue;
      keys.add(a); edges.push({ a, b: normId(r.id), kind });
    }
    if (!keys.size) return h('p', { class: 'muted pad' }, 'Nothing to draw.');
    const preds = new Map([...keys].map((k) => [k, []]));
    edges.forEach((e) => preds.get(e.b).push(e.a));
    const level = new Map();
    const lv = (k, stack) => {
      if (level.has(k)) return level.get(k);
      if (stack.has(k)) return 0;
      stack.add(k);
      let m = 0;
      for (const p of preds.get(k)) m = Math.max(m, lv(p, stack) + 1);
      stack.delete(k); level.set(k, m);
      return m;
    };
    keys.forEach((k) => lv(k, new Set()));
    const byCol = new Map();
    for (const [k, c] of level) { if (!byCol.has(c)) byCol.set(c, []); byCol.get(c).push(k); }
    const cols = [...byCol.keys()].sort((a, b) => a - b);
    const order = new Map();
    cols.forEach((c) => byCol.get(c).sort((x, y) => x.localeCompare(y, undefined, { numeric: true })).forEach((k, i) => order.set(k, i)));
    const nbrs = (k, dir) => edges.filter((e) => (dir < 0 ? e.b === k : e.a === k)).map((e) => (dir < 0 ? e.a : e.b));
    for (const dir of [-1, 1]) {
      const seq = dir < 0 ? cols.slice(1) : cols.slice(0, -1).reverse();
      for (const c of seq) {
        const ks = byCol.get(c);
        const bary = (k) => { const ns = nbrs(k, dir).filter((n) => order.has(n)); return ns.length ? ns.reduce((s, n) => s + order.get(n), 0) / ns.length : order.get(k); };
        ks.sort((x, y) => bary(x) - bary(y)).forEach((k, i) => order.set(k, i));
      }
    }
    const outside = new Set([...keys].filter((k) => !inSet.has(k)));
    const box = h('div', { class: 'graph' });
    box.append(graphSvg({ col: level, edges }, null, (k) => open(S.byKey.get(k)), { order, outside }));
    return h('div', { class: 'panel-fill' },
      h('p', { class: 'muted', style: { margin: 0 } }, `${inSet.size} item(s)${outside.size ? `, plus ${outside.size} linked item(s) outside this folder (dashed)` : ''}. Arrows run from where a relation is written to what it names; click a node to open it.`),
      box);
  }

  // ------------------------------------------------------- settings & about
  const THEMES = [['system', 'Follow my system'], ['light', 'Standard (light)'], ['dark', 'Storm (dark)']];
  function applyTheme(v) { if (v === 'light' || v === 'dark') document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme; }
  function openDisplay() {
    const w = openWindow({ title: 'Display Properties', dialog: true, width: 340 });
    const cur = store.get('theme') || 'system';
    w.body.append(h('fieldset', null, h('legend', null, 'Scheme'), THEMES.map(([v, label]) => h('label', { class: 'row', style: { padding: '2px 0' } },
      h('input', { type: 'radio', name: 'szv-theme', id: 'szv-theme-' + v, value: v, checked: v === cur || null, onchange: () => { store.set('theme', v); applyTheme(v); } }), label))),
    h('div', { class: 'row end' }, h('button', { class: 'btn default', type: 'button', onclick: () => w.close() }, 'OK')));
  }
  function openAbout() {
    const p = S.project;
    messageBox({ title: 'About szsdlc Viewer', kind: 'info', text: [
      h('p', null, h('b', null, 'szsdlc-ui-win95'), ` ${META.version || ''}`, h('span', { class: 'muted' }, ' — read-only')),
      h('dl', { class: 'kv', style: { margin: '8px 0' } },
        h('dt', null, 'Project:'), h('dd', null, `${p.name} (${S.pid}), one of ${PROJECTS.length} open`),
        h('dt', null, 'Store:'), h('dd', null, p.store),
        h('dt', null, 'Code root:'), h('dd', null, p.code_root || '(none)'),
        h('dt', null, 'Backend:'), h('dd', null, `${p.backend.kind} (${p.backend.source})`),
        h('dt', null, 'Schema:'), h('dd', null, schemaFromConfig() ? `read by szsdlc ${S.schema.szsdlc_version || ''}` : 'inferred from the store’s files'),
        h('dt', null, 'Items:'), h('dd', null, `${S.rows.length} across ${S.schema.types.length} types`),
        SNAP ? [h('dt', null, 'Snapshot:'), h('dd', null, SNAP.generated_at)] : null),
      h('p', { class: 'muted' }, 'Phase 2 adds editing through szsdlc’s own commands, so every gate and validation still applies.'),
    ] });
  }
  function openWelcome() {
    const w = openWindow({ title: 'Welcome', dialog: true, width: 470 });
    const again = h('input', { type: 'checkbox', id: 'szv-welcome-again', checked: true });
    w.body.append(
      h('div', { class: 'dialog-body' }, icon('logo', 32), h('div', { class: 'grow' },
        h('p', null, h('b', { style: { fontSize: '14px' } }, `Welcome to ${S.project.name}`)),
        h('p', null, `${S.rows.length} items across ${S.schema.types.length} types${SNAP ? `, as of ${SNAP.generated_at}` : ''}.`),
        h('div', { class: 'tip' }, h('b', null, 'Did you know…'), h('p', { style: { margin: '4px 0 0' } },
          'Every window here is assembled from what a type can do: its flags, fields, workflow and relations. Nothing is hard-wired to “work item” or “epic”, so a project that renames or replaces all of its types still gets a full viewer.'),
          PROJECTS.length > 1 ? h('p', { style: { margin: '6px 0 0' } }, `This viewer has ${PROJECTS.length} projects open. Switch between them from the project button on the taskbar.`) : null))),
      h('div', { class: 'row' }, h('label', { class: 'row grow' }, again, 'Show this Welcome screen next time'),
        h('button', { class: 'btn default', type: 'button', onclick: () => { w.close(); openExplorer('project'); } }, 'Explore'),
        h('button', { class: 'btn', type: 'button', onclick: () => w.close() }, 'Close')));
    again.addEventListener('change', () => store.set('welcome', again.checked ? '1' : '0'));
  }

  // --------------------------------------------------------- desktop & start
  function buildDesktop() {
    const desk = document.getElementById('desktop');
    const items = [
      { label: 'My Projects', icon: 'network', open: openProjects },
      { label: S.project.name, icon: 'computer', open: () => openExplorer('project') },
      { label: 'Roadmap', icon: 'calendar', open: () => openExplorer('roadmap') },
      S.tags.size ? { label: 'Tags', icon: 'tag', open: () => openExplorer('tags') } : null,
      S.schema.types.some((t) => t.flags.intake) ? { label: 'Inbox', icon: 'inbox', open: () => openExplorer('inbox') } : null,
      { label: 'Views', icon: 'views', open: () => openExplorer('docs') },
      ...S.schema.types.map((t) => ({ label: t.plural, icon: typeIcon(t), open: () => openExplorer('type:' + t.prefix) })),
    ].filter(Boolean);
    desk.replaceChildren(...items.map((it) => {
      const b = h('button', { class: 'desk-icon', type: 'button', ondblclick: it.open, onkeydown: (e) => { if (e.key === 'Enter') it.open(); } }, icon(it.icon, 32), h('span', null, it.label));
      b.addEventListener('click', () => { desk.querySelectorAll('.sel').forEach((x) => x.classList.remove('sel')); b.classList.add('sel'); if (matchMedia('(pointer: coarse)').matches) it.open(); });
      return b;
    }));
  }
  function buildStart() {
    const start = document.getElementById('start');
    start.prepend(icon('logo'), ' ');
    start.addEventListener('click', (e) => {
      e.stopPropagation();
      if (openMenuEl?.anchor === start) return closeMenus();
      popMenu(start, [
        { label: 'Projects…', icon: 'network', action: openProjects },
        '-',
        ...S.schema.types.map((t) => ({ label: t.plural, icon: typeIcon(t), action: () => openExplorer('type:' + t.prefix) })),
        '-',
        { label: 'Roadmap', icon: 'calendar', action: () => openExplorer('roadmap') },
        S.tags.size ? { label: 'Tags', icon: 'tag', action: () => openExplorer('tags') } : null,
        S.schema.types.some((t) => t.flags.intake) ? { label: 'Inbox', icon: 'inbox', action: () => openExplorer('inbox') } : null,
        { label: 'Views & documents', icon: 'views', action: () => openExplorer('docs') },
        '-',
        { label: 'Display settings…', icon: 'gear', action: openDisplay },
        { label: 'About szsdlc Viewer…', icon: 'help', action: openAbout },
        { label: 'Welcome…', icon: 'logo', action: openWelcome },
        '-',
        { label: 'Shut down…', icon: 'power', action: () => messageBox({ title: 'Shut Down', kind: 'info', text: ['Nothing to save: this viewer is read-only.', SNAP ? 'You can close this tab.' : 'You can close this tab. Stop the local server with Ctrl+C.'] }) },
      ].filter(Boolean), { big: true, above: true, banner: h('div', { class: 'banner' }, h('b', null, 'szsdlc ', h('em', null, 'Viewer'))) });
    });
  }
  function clock() {
    const el = document.getElementById('clock');
    const tick = () => { el.textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); };
    tick(); setInterval(tick, 30000);
  }
  function updateTray() {
    const tray = document.getElementById('tray-schema');
    tray.replaceChildren(icon(schemaFromConfig() ? 'gear' : 'warn'));
    tray.title = schemaFromConfig() ? 'Schema read from szsdlc config' : 'Schema inferred from the store’s files (szsdlc not importable)';
  }

  // -------------------------------------------------------------- projects
  function setHash(id) {
    try { history.replaceState(null, '', '#' + S.pid + (id ? '--' + id : '')); } catch { /* sandboxed */ }
  }
  function parseHash() {
    const hsh = decodeURIComponent(location.hash.slice(1));
    const m = /^([a-z0-9-]+?)(?:--(.+))?$/.exec(hsh);
    if (m && PROJECTS.some((p) => p.id === m[1])) return { pid: m[1], id: m[2] || null };
    return { pid: null, id: hsh || null };  // a bare `#WI-0029` means the current project
  }
  async function loadProject(pid) {
    if (CTX.has(pid)) return CTX.get(pid);
    const api = apiFor(pid);
    const [project, schema, rows, roadmaps, docs] = await Promise.all([api.project(), api.schema(), api.entities(), api.roadmaps(), api.docs()]);
    const ctx = { pid, api, project, schema, rows, roadmaps, docs, byKey: new Map(), byPath: new Map(), types: new Map() };
    schema.types.forEach((t) => ctx.types.set(t.prefix, t));
    rows.forEach((r) => { ctx.byKey.set(normId(r.id), r); ctx.byPath.set(r.path, r); });
    // Indexes the tree, graph and roadmap read. Children follow the configured
    // parent relation only; inverses are derived here, never stored (REQ-0005).
    ctx.children = new Map(); ctx.incoming = new Map(); ctx.tags = new Map();
    for (const r of rows) {
      if (r.parent && normId(r.parent)) { const k = normId(r.parent); if (!ctx.children.has(k)) ctx.children.set(k, []); ctx.children.get(k).push(r); }
      for (const [kind, tgt] of r.relations || []) { const k = normId(tgt); if (!k) continue; if (!ctx.incoming.has(k)) ctx.incoming.set(k, []); ctx.incoming.get(k).push([kind, r.id]); }
      for (const tg of r.tags || []) { if (!ctx.tags.has(tg)) ctx.tags.set(tg, []); ctx.tags.get(tg).push(r); }
    }
    CTX.set(pid, ctx);
    return ctx;
  }
  // Switching swaps the whole desktop: the other project's windows are hidden,
  // not closed, and come back exactly as they were when you switch back.
  async function switchProject(pid, { quiet = false } = {}) {
    if (S && S.pid === pid) return S;
    let ctx;
    try { ctx = await loadProject(pid); } catch (err) {
      messageBox({ kind: 'error', title: 'Cannot open project', text: [`The viewer could not read “${pid}”.`, String(err.message || err)] });
      return null;
    }
    closeMenus();
    S = ctx;
    for (const w of WM.list) {
      const away = w.pid !== null && w.pid !== pid;
      w.el.classList.toggle('elsewhere', away);
      if (w.taskBtn) w.taskBtn.hidden = away;
    }
    if (WM.active && WM.active.pid !== null && WM.active.pid !== pid) { WM.active.el.classList.remove('active'); WM.active = null; }
    document.title = `${S.project.name} - szsdlc Viewer`;
    const sw = document.getElementById('switcher');
    sw.replaceChildren(icon('computer'), h('span', null, S.project.name), h('span', { class: 'caret', 'aria-hidden': 'true' }, '▾'));
    sw.title = `Project: ${S.project.name} (${PROJECTS.length} open). Click to switch.`;
    buildDesktop(); updateTray();
    if (!WM.list.some((w) => w.pid === pid)) { if (innerWidth > 640 || !quiet) openExplorer('project'); } else focusTop();
    setHash(null);
    store.set('project', pid);
    refreshProjectsWindow();
    // Only the project on screen refreshes in the background, so one switched
    // to is brought up to date on arrival (the first one was, by opening it).
    if (booted) scheduler?.arrive();
    return S;
  }
  function projectMenuItems() {
    return [
      ...PROJECTS.map((p) => ({ label: `${p.id === S?.pid ? '● ' : ' '}${p.name}`, icon: 'computer', title: p.store, action: () => switchProject(p.id) })),
      SNAP ? null : { label: 'Open project…', icon: ['folder'], action: openProjectDialog },
      SNAP || !S ? null : { label: `Refresh ${S.project.name} (F5)`, action: () => refreshProject() },
    ].filter(Boolean);
  }

  // Refresh: take the latest from where the project is kept, then redraw every
  // open window of it in place. Nothing is sent. When to refresh, and how a
  // person's Refresh and the background one take turns, is refresh.js's job
  // (the scheduler); this is what one refresh does.
  //
  // Replacing unsent changes is asked first, and only ever for a refresh a
  // person asked for: a background refresh skips that project and says so in
  // the status bar.
  const AUTO_REFRESH = [[0, 'Off'], [30000, 'Every 30 seconds'], [60000, 'Every minute'], [300000, 'Every 5 minutes']];
  function autoRefreshMs() {
    const v = Number(store.get('autoRefresh'));
    return AUTO_REFRESH.some(([ms]) => ms === v) && store.get('autoRefresh') !== null ? v : 60000;
  }
  // Set from the ▾ beside Refresh, the one place to set it. Per browser, and
  // the same in every Explorer: choosing in one repaints them all.
  const SHORT = { 30000: '30s', 60000: '1m', 300000: '5m' };
  function intervalMenu() {
    const cur = autoRefreshMs();
    return [{ head: 'Refresh automatically' },
      ...AUTO_REFRESH.map(([ms, label]) => ({ label: (ms === cur ? '● ' : '\u2003') + label, action: () => setAutoRefresh(ms) }))];
  }
  function paintInterval(btn) {
    const ms = autoRefreshMs();
    const what = ms ? AUTO_REFRESH.find(([v]) => v === ms)[1].toLowerCase() : 'off';
    btn.title = `Refresh automatically: ${what}`;
    btn.setAttribute('aria-label', btn.title);
    btn.replaceChildren(...(ms ? [h('span', { class: 'ival' }, SHORT[ms])] : []), h('span', { class: 'caret', 'aria-hidden': 'true' }, '▾'));
  }
  function setAutoRefresh(ms) {
    store.set('autoRefresh', String(ms));
    scheduler?.setInterval(ms);
    for (const w of WM.list) if (w.intervalBtn) paintInterval(w.intervalBtn);
  }
  function quietStatus(text) { const front = explorerFor(null); if (front) front.setStatus([text]); }

  // A redraw waits while someone is in the middle of something: a menu open,
  // typing in the find field, or a drag. It is applied as soon as that ends.
  let dragging = false;
  let pendingApply = null;
  function busy() {
    return !!openMenuEl || dragging || !!document.activeElement?.matches?.('.toolbar input[type="search"]');
  }
  function whenIdle(fn) { if (busy()) pendingApply = fn; else { pendingApply = null; fn(); } }
  function flushPending() { if (pendingApply && !busy()) { const fn = pendingApply; pendingApply = null; fn(); } }
  for (const ev of ['pointerup', 'focusout', 'keyup']) document.addEventListener(ev, () => setTimeout(flushPending, 0));

  function applyRefresh(pid, ctx, message) {
    if (!S || S.pid !== pid) return;  // switched away meanwhile: the new data is cached for later
    S = ctx;
    buildDesktop(); updateTray();
    for (const w of WM.list) if (w.pid === pid && w.redraw) w.redraw();
    if (message) quietStatus(message);
    refreshProjectsWindow();
  }

  async function runRefresh(kind, { replace = false } = {}) {
    const pid = S?.pid;
    if (!pid) return { ok: true };
    const manual = kind === 'manual';
    let result;
    try { result = await hub.refresh(pid, replace); } catch (err) {
      if (err.status === 409) {
        if (manual) {
          messageBox({ kind: 'warn', title: 'Refresh', text: [String(err.message), 'Refresh anyway to take the latest, or cancel and send your changes first.'],
            buttons: [{ label: 'Refresh anyway', action: () => scheduler.manual({ replace: true }) }, { label: 'Cancel', default: true }] });
        } else {
          quietStatus('Not refreshed: this copy has unsent changes');
        }
        return { ok: true };  // reachable; nothing to back off from
      }
      if (manual) messageBox({ kind: 'error', title: 'Refresh', text: [String(err.message || err), err.fix ? `Fix: ${err.fix}` : null].filter(Boolean) });
      else quietStatus(`Not refreshed: ${err.message || err}`);
      return { ok: false };
    }
    PROJECTS = PROJECTS.map((p) => (p.id === pid ? result.project : p));
    // A background refresh redraws only when something arrived; a manual one always re-reads.
    if (manual || result.arrived) {
      CTX.delete(pid);
      const ctx = await loadProject(pid);
      const message = manual ? (result.arrived ? 'Refreshed: changes arrived' : 'Refreshed: nothing new') : 'Updated: changes arrived';
      if (manual) applyRefresh(pid, ctx, message); else whenIdle(() => applyRefresh(pid, ctx, message));
    }
    if (result.replaced) {
      messageBox({ kind: 'warn', title: 'Refresh', text: ['Changes in this copy that differed from the latest were replaced.', result.note ? `szsdlc ${result.note}.` : null].filter(Boolean) });
    }
    return { ok: true };
  }

  function paintRefreshButtons() {
    const off = scheduler ? scheduler.buttonDisabled() : false;
    for (const w of WM.list) if (w.refreshBtn) w.refreshBtn.disabled = off;
  }
  const scheduler = SNAP ? null : window.SzRefresh.createScheduler({
    run: runRefresh, interval: 0, onChange: paintRefreshButtons, onStatus: quietStatus,
  });
  // A person asked: the toolbar button, the menu or F5.
  function refreshProject() { scheduler?.manual(); }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'F5' && !SNAP && S) { e.preventDefault(); refreshProject(); }
  });
  if (scheduler) document.addEventListener('visibilitychange', () => scheduler.setVisible(!document.hidden));
  function buildSwitcher() {
    const sw = document.getElementById('switcher');
    sw.addEventListener('click', (e) => {
      e.stopPropagation();
      if (openMenuEl?.anchor === sw) return closeMenus();
      popMenu(sw, [{ head: 'Switch project' }, ...projectMenuItems(), '-', { label: 'Projects…', icon: 'network', action: openProjects }], { above: true });
    });
  }
  let projectsWin = null;
  function openProjects() {
    const w = openWindow({ key: 'projects', global: true, title: 'My Projects', icon: 'network', width: 720, height: 340, x: 160, y: 60, status: true,
      onclose: () => { projectsWin = null; } });
    if (w.reused) return w;
    projectsWin = w;
    refreshProjectsWindow();
    return w;
  }
  function refreshProjectsWindow() {
    const w = projectsWin;
    if (!w) return;
    const bar = h('div', { class: 'row' },
      SNAP ? h('span', { class: 'muted' }, 'This snapshot carries a fixed set of projects.') : h('button', { class: 'btn', type: 'button', onclick: openProjectDialog }, 'Open project…'),
      h('span', { class: 'grow' }),
      h('span', { class: 'muted' }, 'Double-click a project to switch to it.'));
    w.body.replaceChildren(bar, listView({
      sortKey: 'projects', rows: PROJECTS, empty: 'No projects yet. Use Open project… to add one.',
      columns: [
        { key: 'name', label: 'Project', render: (p) => cell(['computer', p.id === S?.pid ? '#00a000' : null], p.id === S?.pid ? h('b', null, p.name) : p.name) },
        { key: 'entity_count', label: 'Items' }, { key: 'type_count', label: 'Types' },
        { key: 'backend', label: 'Backend', get: (p) => p.backend.kind },
        { key: 'schema_source', label: 'Schema', get: (p) => p.schema_source === 'inferred' ? 'inferred' : 'szsdlc config' },
        { key: 'location', label: 'Location', get: (p) => p.location || p.store }, { key: 'code_root', label: 'Code root', get: (p) => p.code_root || '' },
      ],
      onOpen: (p) => switchProject(p.id),
    }));
    w.setStatus([`${PROJECTS.length} project(s) in this viewer`, S ? `Current: ${S.project.name}` : 'No project open']);
  }
  function openProjectDialog() {
    const w = openWindow({ title: 'Open Project', dialog: true, width: 440 });
    const store = h('input', { class: 'field grow', id: 'szv-open-store', type: 'text', placeholder: 'C:\\code\\project, or https://host/org/repo.git', autocomplete: 'off', spellcheck: 'false' });
    const code = h('input', { class: 'field grow', id: 'szv-open-code', type: 'text', placeholder: 'optional: the repo it describes', autocomplete: 'off' });
    const err = h('p', { class: 'bad', hidden: true });
    const busy = h('p', { class: 'muted', hidden: true }, 'Opening… a project kept elsewhere is fetched the first time, which can take a moment.');
    let working = false;
    async function go() {
      if (working) return;
      working = true;
      err.hidden = true; busy.hidden = false;
      w.body.querySelectorAll('button, input').forEach((x) => { x.disabled = true; });
      try {
        const p = await hub.open(store.value.trim(), code.value.trim());
        PROJECTS = await hub.projects();
        w.close();
        await switchProject(p.id);
      } catch (e) {
        err.textContent = e.message + (e.fix ? ` ${e.fix}` : '');
        err.hidden = false;
      } finally {
        working = false; busy.hidden = true;
        w.body.querySelectorAll('button, input').forEach((x) => { x.disabled = false; });
      }
    }
    w.body.append(
      h('div', { class: 'dialog-body' }, icon(['folder'], 32), h('div', { class: 'grow', style: { display: 'grid', gap: '6px' } },
        h('p', null, 'Type where the project is: a folder on this computer (any folder inside a project works), or where it is kept, such as a repository URL.'),
        h('label', { class: 'row', for: 'szv-open-store' }, h('span', { style: { width: '74px' } }, 'Location:'), store),
        h('label', { class: 'row', for: 'szv-open-code' }, h('span', { style: { width: '74px' } }, 'Code root:'), code),
        busy, err)),
      h('div', { class: 'row end' }, h('button', { class: 'btn default', type: 'button', onclick: go }, 'Open'), h('button', { class: 'btn', type: 'button', onclick: () => w.close() }, 'Cancel')));
    store.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    store.focus();
  }

  // -------------------------------------------------------------------- boot
  let booted = false;
  async function boot() {
    applyTheme(store.get('theme') || 'system');
    buildStart(); buildSwitcher(); clock();
    try { [META, PROJECTS] = await Promise.all([hub.meta().catch(() => ({})), hub.projects()]); } catch (err) {
      messageBox({ kind: 'error', title: 'szsdlc Viewer', text: ['The viewer could not reach its local service.', String(err.message || err)] });
      return;
    }
    if (!PROJECTS.length) { openProjects(); return; }
    const want = parseHash();
    const remembered = store.get('project');
    const pid = want.pid || (PROJECTS.some((p) => p.id === remembered) ? remembered : PROJECTS[0].id);
    if (!(await switchProject(pid, { quiet: !!want.id }))) return;
    store.set('project', pid);
    booted = true;
    if (scheduler) { scheduler.setVisible(!document.hidden); scheduler.setInterval(autoRefreshMs()); }
    const target = normId(want.id);
    if (target && S.byKey.has(target)) await openItem(target);
    else if (store.get('welcome') !== '0' && innerWidth > 640) openWelcome();
    addEventListener('hashchange', async () => {
      const t = parseHash();
      if (t.pid && t.pid !== S.pid) await switchProject(t.pid, { quiet: !!t.id });
      const k = normId(t.id);
      if (k && S.byKey.has(k)) openItem(k);
    });
  }
  boot();
})();
