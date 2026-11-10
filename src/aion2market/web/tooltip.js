"use strict";
/* ---------- in-game style item hover card ----------
   Any element with data-tip="<item_key>" gets the card. One set of listeners on document does all of it,
   so tables can keep rewriting their innerHTML. The card never takes pointer events: it can't trap the mouse. */
const tipCard = Object.assign(document.createElement("div"), { className: "itemtip" });
tipCard.setAttribute("aria-hidden", "true");            // decorative for mouse users; the drawer holds the same facts
document.body.appendChild(tipCard);
const TIP_DELAY = 120, TIP_RETRY = 60000;
const tipCache = new Map();                              // item_key → { d, at }; failed requests are never stored
// A response without detail may only be missing because NC's data hasn't arrived yet: ask again after a minute.
const tipFresh = c => !!c && (c.d.detail || Date.now() - c.at < TIP_RETRY);
let tipEl = null, tipKey = null, tipMuted = null, tipTimer = 0, tipX = 0, tipY = 0;

// What the page already knows about the item, so the card has a head before the request returns.
function tipKnown(key, el) {
  const lists = [data.items, dealsData.items, invData.items, salesData.listings, salesData.settled, craftData.best_sales, craftData.recipes];
  for (const l of lists) { const r = (l || []).find(r => r.item_key === key); if (r) return r; }
  return { item_key: key, name: el.dataset.tipName || null };
}

const tipStat = s => `<div><span>${esc(s.name)}</span><b>${esc(s.min != null && s.min !== s.value ? `${s.min}–${s.value}` : s.value)}</b></div>`;

function tipHtml(key, k, d, loading, note) {
  const x = d || {}, has = v => v != null && v !== "";
  const name = x.name || k.name, official = x.official_name || k.official_name;
  const kind = [x.grade_name || k.grade_name, x.category || k.category].filter(Boolean).map(esc).join(" · ");
  const who = [x.race, ...(x.classes || [])].filter(Boolean).map(esc).join(" · ");
  const row = data.items.find(r => r.item_key === key);
  const sockets = n => `<b class="sock">${"<i></i>".repeat(Math.min(n, 8))}<em>${esc(n)}</em></b>`;
  const ench = x.enchantable === false ? t("Güçlendirilemez")
    : x.max_enchant ? `+${esc(x.max_enchant)}${x.max_exceed ? ` (${t("aşma +{0}", esc(x.max_exceed))})` : ""}` : "";
  const main = x.main_stats || [], sub = x.sub_stats || [], src = x.sources || [];
  const sec = [];                                        // sections in the game's order; empty ones are skipped
  if (has(x.item_level) || has(x.equip_level) || who) sec.push(`<div class="it-lvl">
      ${has(x.item_level) ? `<div class="ilvl"><span>${t("Item Seviyesi")}</span><b>${esc(x.item_level)}</b></div>` : ""}
      <div class="req">${has(x.equip_level) ? `<span>${t("Gereken seviye {0}", esc(x.equip_level))}</span>` : ""}${who ? `<span>${who}</span>` : ""}</div></div>`);
  if (main.length) sec.push(`<div class="it-stats">${main.map(tipStat).join("")}</div>`);
  if (sub.length) sec.push(`<div class="it-cap">${x.sub_stat_count ? t("Rastgele özellikler ({0} tanesi gelir)", esc(x.sub_stat_count)) : t("Rastgele özellikler")}</div>
      <div class="it-stats two">${sub.map(tipStat).join("")}</div>`);
  if (x.manastone_slots || x.godstone_slots || ench) sec.push(`<div class="it-stats">
      ${x.manastone_slots ? `<div><span>${t("Manastone yuvası")}</span>${sockets(x.manastone_slots)}</div>` : ""}
      ${x.godstone_slots ? `<div><span>${t("Godstone yuvası")}</span>${sockets(x.godstone_slots)}</div>` : ""}
      ${ench ? `<div><span>${t("Azami güçlendirme")}</span><b>${ench}</b></div>` : ""}</div>`);
  if (has(x.desc)) sec.push(`<div class="it-desc">${esc(x.desc)}</div>`);
  if (src.length || x.tradable != null) sec.push(`<div class="it-meta">
      ${src.length ? `<div><span>${t("Elde edilişi")}</span> ${src.map(esc).join(", ")}</div>` : ""}
      ${x.tradable == null ? "" : `<div class="${x.tradable ? "" : "no"}">${t(x.tradable ? "Takas edilebilir" : "Takas edilemez")}</div>`}</div>`);
  if (loading) sec.push(`<div class="it-skel"><i></i><i></i><i></i></div>`);
  if (note) sec.push(`<div class="it-meta"><div>${esc(note)}</div></div>`);
  if (row) sec.push(`<div class="it-price"><b>${fmt(row.price)}</b> Kinah<span>${row.count ? t("{0} ilan", row.count) : t("markette yok")}</span></div>`);
  return `<div class="it-head ${gradeCls(x.grade_name ? x : k)}">${iconHtml(x.icon || k.icon)}<div>
      <div class="nm">${name ? esc(name) : `<span class="unnamed">${t("Adsız item")}</span>`}</div>
      <div class="kind">${kind || "Item " + esc(key)}</div>
      ${official && name && official !== name ? `<div class="kind">${t("Resmi ad: {0}", esc(official))}</div>` : ""}
    </div></div>${sec.map(s => `<div class="it-sec">${s}</div>`).join("")}`;
}

// Beside the cursor; flipped to its left and slid up when the card would leave the viewport.
function tipPlace() {
  const w = tipCard.offsetWidth, h = tipCard.offsetHeight, gap = 16, pad = 8;
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  let x = tipX + gap, y = tipY + gap;
  if (x + w > vw - pad) x = tipX - gap - w;
  if (y + h > vh - pad) y = vh - pad - h;
  tipCard.style.transform = `translate(${Math.round(Math.max(pad, x))}px, ${Math.round(Math.max(pad, y))}px)`;
}

function tipPaint(d, loading) {
  tipCard.innerHTML = tipHtml(tipKey, tipKnown(tipKey, tipEl), d, loading, tipEl.dataset.tipNote);
  tipPlace();
}

async function tipLoad(key) {
  let d = null;
  try {
    const r = await fetch(`/api/tooltip/${encodeURIComponent(key)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    d = await r.json();
    tipCache.set(key, { d, at: Date.now() });
  } catch {}                                             // quietly keep the basic card
  if (tipKey === key) tipPaint(d || (tipCache.get(key) || {}).d, false);       // the pointer may be on another item by now
}

function tipShow(el) {
  clearTimeout(tipTimer);
  tipEl = el; tipKey = el.dataset.tip;
  const key = tipKey, c = tipCache.get(key), fresh = tipFresh(c);
  tipPaint(c && c.d, !c);                                // instantly, from what the row knows (or a stale answer)
  tipCard.classList.add("on");
  tipWatch.observe(document.body, { childList: true, subtree: true });
  if (!fresh) tipTimer = setTimeout(() => tipLoad(key), TIP_DELAY);   // passing over a row shouldn't cost a request
}

function tipHide() {
  clearTimeout(tipTimer);
  if (!tipEl) return;
  tipEl = tipKey = null;
  tipCard.classList.remove("on");
  tipWatch.disconnect();
}
// Scroll, click and Escape also keep the card away until the pointer reaches another item.
const tipDismiss = () => { tipMuted = tipKey || tipMuted; tipHide(); };

/* The page refreshes itself and rewrites its tables: when the hovered element is gone, carry on with the one
   now under the pointer if it's the same item, otherwise close. A card must never be left hanging. */
const tipWatch = new MutationObserver(() => {
  if (!tipEl || tipEl.isConnected) return;
  const at = document.elementFromPoint(tipX, tipY), el = at && at.closest("[data-tip]");
  if (!el || el.dataset.tip !== tipKey) return tipHide();
  tipEl = el;
  tipPaint((tipCache.get(tipKey) || {}).d, !tipCache.has(tipKey));
});

document.addEventListener("pointerover", e => {
  if (e.pointerType !== "mouse") return;                 // touch: a tap stays a plain row click
  tipX = e.clientX; tipY = e.clientY;
  const el = e.target.closest ? e.target.closest("[data-tip]") : null;
  if (!el || el.dataset.tip !== tipMuted) tipMuted = null;
  if (el === tipEl) return;
  if (el && !tipMuted) tipShow(el); else tipHide();
});
document.addEventListener("pointermove", e => {
  if (!tipEl || e.pointerType !== "mouse") return;
  tipX = e.clientX; tipY = e.clientY;
  tipPlace();
});
document.addEventListener("pointerout", e => { if (!e.relatedTarget) tipHide(); });      // left the window
document.addEventListener("scroll", tipDismiss, true);   // capture: tables and the drawer scroll on their own
document.addEventListener("pointerdown", tipDismiss, true);
document.addEventListener("keydown", e => { if (e.key === "Escape") tipDismiss(); }, true);
window.addEventListener("blur", tipHide);
