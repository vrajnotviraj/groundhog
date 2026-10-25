// One atomic DOM read per document: the indexed table of interactive elements
// Jev chooses from, plus the visible text. Node identity lives in window.__gh so
// Python can verify that a derived selector resolves to the very node that was
// offered. Called as page.evaluate(JS, maxElements).
(maxElements) => {
  if (!document.body) return {url: location.href, title: document.title, text: '',
    elements: [], omitted: 0};

  const cache = window.__gh ||= {ids: new WeakMap(), nodes: new Map(), next: 1};
  for (const [id, e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e, cache.next++);
    const id = cache.ids.get(e); cache.nodes.set(id, e); return id;
  };

  const safe = e => !['password', 'file', 'hidden'].includes(e.type);
  const visible = e => !!e && !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
  const hasBox = e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const name = (e, seen = new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced = (e.getAttribute('aria-labelledby') || '').split(/\s+/)
      .map(id => name(document.getElementById(id), seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels || [])].map(l => name(l, seen)).filter(Boolean).join(' ') ||
      (['button', 'submit', 'reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName === 'INPUT' ? '' : [...e.childNodes].map(n => n.nodeType === 3 ? n.textContent :
        n.nodeType === 1 && n.getAttribute('aria-hidden') !== 'true' ? name(n, seen) : '').join(' ')) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();

  const roles = ['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem', 'menuitemradio',
    'option', 'gridcell', 'combobox', 'textbox', 'searchbox', 'spinbutton'];
  const selector = 'a[href],button,input,textarea,select,summary,[contenteditable="true"],' +
    roles.map(r => '[role="' + r + '"]').join(',');
  const role = e => {
    const explicit = e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName === 'BUTTON' || e.tagName === 'SUMMARY') return 'button';
    if (e.tagName === 'A') return 'link';
    if (e.tagName === 'SELECT') return 'combobox';
    if (e.tagName === 'TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName === 'INPUT') {
      if (['checkbox', 'radio'].includes(e.type)) return e.type;
      if (['button', 'submit', 'reset', 'image'].includes(e.type)) return 'button';
      if (e.type === 'search') return 'searchbox';
      if (e.type === 'number') return 'spinbutton';
      if (['text', 'email', 'url', 'tel', ''].includes(e.type)) return 'textbox';
    }
    return null;
  };

  // The nearest ancestor a selector can be scoped by; null when there is none.
  const scopeOf = node => {
    for (let p = node.parentElement; p; p = p.parentElement) {
      if (p.matches('dialog,[role="dialog"]')) return {kind: 'dialog'};
      if (p.matches('a[href]')) return {kind: 'link', href: p.getAttribute('href')};
      if (p.matches('[role="region"]')) {
        const n = clean(name(p));
        if (n) return {kind: 'region', name: n};
      }
      if (p.matches('tr,li,[role="row"]')) {
        const t = clean(p.innerText).slice(0, 40);
        if (t) return {kind: 'row', tag: p.matches('[role="row"]') && p.tagName !== 'TR' && p.tagName !== 'LI'
          ? '[role=row]' : p.tagName.toLowerCase(), text: t};
      }
    }
    return null;
  };

  const attrsOf = node => {
    const a = {tag: node.tagName.toLowerCase()};
    const pairs = {type: 'type', testid: 'data-testid', id: 'id', aria_label: 'aria-label',
      placeholder: 'placeholder', name: 'name', href: 'href'};
    for (const [key, attr] of Object.entries(pairs)) {
      const v = node.getAttribute(attr);
      if (v) a[key] = v;
    }
    return a;
  };

  const elements = [];
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e)) continue;
    const r = role(e);
    if (!r) continue;
    // Disabled controls stay in the table as state (a disabled Delete is the cue to
    // fill its confirmation), but the Python side never offers them as targets.
    const disabled = e.matches(':disabled') || !!e.closest('[aria-disabled="true"]');
    let node = e, label = clean(name(e)), hiddenBox = false;
    if (!visible(e)) {
      // Ant Design hides the real checkbox (opacity 0) behind a clickable label.
      if (!['checkbox', 'radio'].includes(r)) continue;
      const lab = e.closest('label');
      if (!visible(lab)) continue;
      node = lab; label = clean(name(lab)); hiddenBox = true;
    }
    if (!hasBox(node)) continue;
    if (label === 'Accept All') continue;           // consent banner: the session clears it
    if (r === 'gridcell' && e.querySelector('button,[role="button"]')) continue;

    const editable = !hiddenBox && !e.readOnly && e.getAttribute('aria-readonly') !== 'true' &&
      (['textbox', 'searchbox', 'spinbutton'].includes(r) ||
        (r === 'combobox' && ['INPUT', 'TEXTAREA'].includes(e.tagName)));
    const value = ['checkbox', 'radio'].includes(r) ? ''
      : typeof e.value === 'string' ? e.value
      : e.isContentEditable || r === 'combobox' ? clean(e.innerText) : '';

    const state = {};
    for (const key of ['checked', 'expanded', 'selected']) {
      const v = e.getAttribute('aria-' + key);
      if (v !== null) state[key] = v;
    }
    if (['checkbox', 'radio'].includes(r)) state.checked = String(e.checked);
    if (disabled) state.disabled = 'true';

    elements.push({node: identity(node), role: r, label: label || r, value: value.slice(0, 120),
      kind: editable ? 'fill' : 'click', attrs: attrsOf(node), state, scope: scopeOf(node)});
  }
  const omitted = Math.max(0, elements.length - maxElements);
  elements.splice(maxElements);
  for (const el of elements) el.label = el.label.slice(0, 80);

  // Toasts are transient; letting them into the text would make them post-conditions.
  const words = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  let n, length = 0;
  while ((n = walker.nextNode()) && length < 6000) {
    const value = n.textContent.trim(), parent = n.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') ||
        parent.closest('[role="alert"],[role="status"],.ant-message,.ant-notification') ||
        !visible(parent)) continue;
    range.selectNodeContents(n);
    const r = range.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) continue;
    words.push(value); length += value.length;
  }

  return {
    url: location.href, title: document.title, text: words.join('\n').slice(0, 6000), elements, omitted,
  };
}
