(() => {
  if (window.__d) return;
  const ORANGE = '#f59e0b', YELLOW = 'rgba(255,221,0,.5)';
  const style = document.createElement('style');
  style.textContent = `
   .__box{position:fixed;border:3px solid ${ORANGE};border-radius:14px;pointer-events:none;z-index:2147483646;opacity:0;transition:opacity .35s;
          box-shadow:0 0 0 2px rgba(255,255,255,.55)}
   .__mark{position:fixed;background:rgba(255,221,0,.16);border-bottom:4px solid rgba(245,158,11,.9);border-radius:6px 6px 3px 3px;
           pointer-events:none;z-index:2147483645;opacity:0;transition:opacity .35s}
   .__cur{position:fixed;left:0;top:0;width:26px;height:26px;pointer-events:none;z-index:2147483647;opacity:0;
          transition:transform .8s cubic-bezier(.4,.1,.2,1),opacity .45s}
   .__rip{position:fixed;width:12px;height:12px;border-radius:50%;border:3px solid ${ORANGE};pointer-events:none;z-index:2147483646;transform:translate(-50%,-50%) scale(1);opacity:.7;transition:transform .6s ease-out,opacity .6s ease-out}`;
  const ensure = () => { if (!style.isConnected && document.documentElement) document.documentElement.appendChild(style); };
  const pick = (s, i = 0) => (typeof s === 'string' ? document.querySelectorAll(s)[i] : s);
  const rect = (el, pad) => { const r = el.getBoundingClientRect(); return { x: r.left - pad, y: r.top - pad, w: r.width + pad * 2, h: r.height + pad * 2 }; };
  let cur = null, boxes = [], curTimer = null;
  const ensureCur = () => { if (!cur) { cur = document.createElement('div'); cur.className = '__cur'; cur.style.transform = 'translate(900px,500px)';
    cur.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7 18 2.6-7.4L20 10z" fill="rgba(255,255,255,.55)" stroke="rgba(20,30,45,.7)" stroke-width="1.4" stroke-linejoin="round"/></svg>'; document.documentElement.appendChild(cur); } return cur; };
  const wake = () => { const c = ensureCur(); c.style.opacity = .6; clearTimeout(curTimer); curTimer = setTimeout(() => { c.style.opacity = 0; }, 1900); };
  const keep = b => { setTimeout(() => { b.style.opacity = 0; }, 4200); };
  window.__d = {
    reveal(sel, i = 0) { ensure(); const el = pick(sel, i); if (!el) return false; el.scrollIntoView({ block: 'center', inline: 'nearest' }); return true; },
    box(sel, o = {}) { ensure(); const el = pick(sel, o.i || 0); if (!el) return false; const r = rect(el, o.pad ?? 10);
      const b = document.createElement('div'); b.className = '__box'; Object.assign(b.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' });
      document.documentElement.appendChild(b); requestAnimationFrame(() => b.style.opacity = 1); boxes.push(b); keep(b); return true; },
    mark(sel, o = {}) { ensure(); const el = pick(sel, o.i || 0); if (!el) return false; const r = rect(el, o.pad ?? 4);
      const b = document.createElement('div'); b.className = '__mark'; Object.assign(b.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' });
      document.documentElement.appendChild(b); requestAnimationFrame(() => b.style.opacity = 1); boxes.push(b); keep(b); return true; },
    clear() { boxes.forEach(b => { b.style.opacity = 0; setTimeout(() => b.remove(), 300); }); boxes = []; },
    moveTo(sel, o = {}) { ensure(); const el = pick(sel, o.i || 0); if (!el) return false; const r = el.getBoundingClientRect(); const c = ensureCur();
      c.style.transform = `translate(${r.left + r.width * (o.fx ?? .5) - 5}px,${r.top + r.height * (o.fy ?? .5) - 3}px)`; wake(); return true; },
    ripple(sel, o = {}) { ensure(); const el = pick(sel, o.i || 0); if (!el) return false; const r = el.getBoundingClientRect(); const d = document.createElement('div'); d.className = '__rip';
      d.style.left = (r.left + r.width * (o.fx ?? .5)) + 'px'; d.style.top = (r.top + r.height * (o.fy ?? .5)) + 'px'; document.documentElement.appendChild(d);
      requestAnimationFrame(() => { d.style.transform = 'translate(-50%,-50%) scale(5)'; d.style.opacity = 0; }); setTimeout(() => d.remove(), 700); return true; },
    count(sel) { return document.querySelectorAll(sel).length; },
    exists(sel) { return !!document.querySelector(sel); },
    text(sel, i = 0) { const e = pick(sel, i); return e ? e.textContent : ''; },
    setSlider(sel, v) { const e = pick(sel); e.value = v; e.dispatchEvent(new Event('input', { bubbles: true })); },
    fireChange(sel) { pick(sel).dispatchEvent(new Event('change', { bubbles: true })); },
    click(sel, i = 0) { const e = pick(sel, i); if (!e) return false; e.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); return true; },
  };
})();
