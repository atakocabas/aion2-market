"use strict";
const PF = { format: v => (Math.abs(v) < 1 && v !== 0 ? PF2 : PF1).format(v) };   // small moves keep 2 decimals
const fmt = v => v == null ? "–" : NF.format(v);
/* Typed prices: "2.5m" = 2 500 000, "2,5k" = 2 500, "750" and "2.500.000" as they are; "" → null, nonsense → NaN.
   A lone "." or "," before exactly three digits without a suffix groups thousands (995.000), otherwise it's the decimal. */
function parsePrice(s) {
  s = String(s).trim().toLowerCase().replace(/\s/g, "");
  if (!s) return null;
  const m = s.match(/^([\d.,]+)([kmb]?)$/);
  if (!m) return NaN;
  let [, num, unit] = m;
  const seps = num.match(/[.,]/g) || [];
  if (seps.length) {
    const last = Math.max(num.lastIndexOf("."), num.lastIndexOf(","));
    const grouping = !unit && num.length - last - 1 === 3 && (seps.length === 1 || seps.every(c => c === seps[0]));
    num = grouping ? num.replace(/[.,]/g, "") : num.slice(0, last).replace(/[.,]/g, "") + "." + num.slice(last + 1);
  }
  const v = Number(num) * { "": 1, k: 1e3, m: 1e6, b: 1e9 }[unit];
  return Number.isFinite(v) ? Math.round(v) : NaN;
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dt = ts => ts ? new Date(ts * 1000) : null;
const fmtTime = ts => ts ? dt(ts).toLocaleString(LOC, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";
const fmtDate = ts => ts ? dt(ts).toLocaleDateString(LOC, { day: "numeric", month: "long" }) : "–";
const ago = ts => {
  if (!ts) return "–";
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  if (m < 1) return t("az önce");
  if (m < 60) return t("{0} dk önce", m);
  const h = Math.round(m / 60);
  return h < 48 ? t("{0} sa önce", h) : t("{0} gün önce", Math.round(h / 24));
};
const gradeCls = r => r && r.grade_name ? "g-" + r.grade_name.toLowerCase().replace(/[^a-z]/g, "") : "";
const iconHtml = (url, big) => `<span class="icon${big ? " big" : ""}"${url ? ` style="background-image:url('${encodeURI(url)}')"` : ""}></span>`;
const PERIOD_LABEL ={ prev: "son listelemeye göre", week: "7 güne göre", month: "30 güne göre" };

const COLS = [
  { id: "star", label: "★", cls: "star", sort: r => r.watched ? 0 : 1 },
  { id: "name", label: "Item", cls: "l", sort: r => (r.name || "￿" + r.item_key).toLocaleLowerCase("tr") },
  { id: "price", label: "Birim fiyat", sort: r => r.price },
  { id: "prev", label: "Son listeleme", sort: r => r.prev.change },
  { id: "week", label: "7 gün", sort: r => r.week.change },
  { id: "month", label: "30 gün", sort: r => r.month.change },
  { id: "count", label: "İlan", sort: r => r.count },
  { id: "spark", label: "Trend", nosort: true },
  { id: "ts", label: "Güncelleme", sort: r => -r.ts },
];

const state = load({ view: "changes", period: "prev", sort: "prev", asc: true, q: "", cat: "", dir: "all", minc: 0,
                     hideEmpty: false, named: false, hideSliding: false, lang: null });
if (!LANGS.includes(state.lang)) {     // first visit: the browser's language; earlier users keep Turkish
  let saved = null;
  try { saved = localStorage.getItem("aion2-ui"); } catch {}
  state.lang = saved || /^tr\b/i.test(navigator.language || "") ? "tr" : "en";
}
setLocale(state.lang);
let dealsData = { items: [], rules: {} };
let craftData = { chains: [], best_sales: [] };
let invData = { items: [], unpriced: [] };
delete state.listed;                     // replaced by hideEmpty (0-listing items now sit at the bottom)
let data = { items: [] }, selected = null;

function load(def) {
  try { return Object.assign(def, JSON.parse(localStorage.getItem("aion2-ui") || "{}")); } catch { return def; }
}
function save() {
  try { localStorage.setItem("aion2-ui", JSON.stringify(state)); } catch {}
}

function chg(c, partial, sinceTs) {
  if (c == null) return `<span class="na" title="${t("Karşılaştıracak eski kayıt yok")}">–</span>`;
  const cls = c < -0.05 ? "down" : c > 0.05 ? "up" : "flat";
  const arrow = cls === "down" ? "▼" : cls === "up" ? "▲" : "";
  const w = Math.min(100, Math.abs(c) * 2);           // 50% change fills the bar
  const star = partial ? `<span class="partial" title="${t("Veri {0} tarihinden beri; bu süreden kısa", fmtDate(sinceTs))}">*</span>` : "";
  return `<span class="chg ${cls}"><span class="bar"><i style="width:${w}%"></i></span>` +
         `<span class="p">${arrow} ${pct(Math.abs(c))}${star}</span></span>`;
}

function spark(points) {
  if (!points || points.length < 2) return `<span class="na">–</span>`;
  const W = 92, H = 26, ys = points.map(p => p[1]);
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const xs = points.map((_, i) => i / (points.length - 1) * (W - 2) + 1);
  const pts = points.map((p, i) => `${xs[i].toFixed(1)},${(H - 3 - (p[1] - lo) / span * (H - 6)).toFixed(1)}`).join(" ");
  const color = ys[ys.length - 1] < ys[0] ? "var(--down)" : ys[ys.length - 1] > ys[0] ? "var(--up)" : "var(--muted)";
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}

/* ---------- hide settings (stored in the database via /api/settings) ---------- */
const GRADES = ["Common", "Rare", "Epic", "Unique", "Heroic", "Special"];       // lowest to highest
const ARMOR = ["Top", "Legs", "Helm", "Pauldrons", "Gloves", "Shoes", "Cloak", "Guard"];
const GROUPS = ["Zırh", "Silah", "Aksesuar", "Diğer"];
const groupOf = r => r.type === "Accessory" ? "Aksesuar" : r.type === "Equip" ? (ARMOR.includes(r.category) ? "Zırh" : "Silah") : "Diğer";
let exclude = { rules: [], items: [], show_hidden: false };
let draft = { grades: new Set(), categories: new Set() };

const ruleMatches = (rule, r) =>
  (!rule.grades.length || rule.grades.includes(r.grade_name)) &&
  (!rule.categories.length || rule.categories.includes(r.category));
const isHidden = r => exclude.items.includes(r.item_key) || exclude.rules.some(rule => ruleMatches(rule, r));

async function saveExclude(msg) {
  try {
    const r = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
                                              body: JSON.stringify({ exclude }) });
    if (!r.ok) throw new Error(r.status);
    exclude = (await r.json()).exclude;
    if (msg) toast(msg);
  } catch { toast(t("Ayar kaydedilemedi")); }
  render();
  if (document.getElementById("hideModal").classList.contains("on")) renderHide();
}

function categoriesByGroup() {
  const out = Object.fromEntries(GROUPS.map(g => [g, {}]));
  data.items.forEach(r => { if (r.category) out[groupOf(r)][r.category] = (out[groupOf(r)][r.category] || 0) + 1; });
  return out;
}

function describeRule(rule) {
  const grades = rule.grades.length
    ? rule.grades.map(g => `<b class="g-${g.toLowerCase()}">${esc(g)}</b>`).join(", ") : t("Her nadirlik");
  let cats = t("her kategori");
  if (rule.categories.length) {
    const groups = categoriesByGroup();
    const whole = GROUPS.filter(g => { const c = Object.keys(groups[g]); return c.length && c.every(x => rule.categories.includes(x)); });
    const rest = rule.categories.filter(c => !whole.some(g => c in groups[g]));
    const parts = [...whole.map(g => t("tüm {0}", t(g).toLocaleLowerCase(LOC))), ...rest.slice(0, 4).map(esc)];
    cats = parts.join(", ") + (rest.length > 4 ? ` +${rest.length - 4}` : "");
  }
  return `${grades} · ${cats}`;
}

function renderHide() {
  const groups = categoriesByGroup();
  const gradeCounts = {};
  data.items.forEach(r => { if (r.grade_name) gradeCounts[r.grade_name] = (gradeCounts[r.grade_name] || 0) + 1; });
  const draftRule = { grades: [...draft.grades], categories: [...draft.categories] };
  const draftCount = (draftRule.grades.length || draftRule.categories.length) ? data.items.filter(r => ruleMatches(draftRule, r)).length : 0;
  const hiddenItems = exclude.items.map(k => data.items.find(r => r.item_key === k) || { item_key: k });
  document.getElementById("hideSheet").innerHTML = `
    <div class="top" style="display:flex;align-items:flex-start">
      <div><h2>${t("Listede gösterme")}</h2>
        <div class="hint">${t("Burada seçtiklerin listeden gizlenir. Ayar veritabanına kaydedilir; tarayıcı değişse de kalır.")}</div></div>
      <button class="x" id="hideClose" style="margin-left:auto;background:none;border:0;color:var(--muted);font-size:20px;cursor:pointer">✕</button>
    </div>

    <h3>${t("Yeni kural")}</h3>
    <div class="hint" style="margin-bottom:8px">${t("Nadirlik <b>ve</b> kategori birlikte eşleşirse gizlenir. Birini boş bırakırsan “hepsi” sayılır.")}</div>
    <div class="group"><div class="gh">${t("Nadirlik")}</div><div class="chips">
      ${GRADES.filter(g => gradeCounts[g]).map(g => `<button class="chipbtn ${draft.grades.has(g) ? "sel" : ""}" data-grade="${g}">
        <span class="g-${g.toLowerCase()}">●</span> ${g}<span class="n">${gradeCounts[g]}</span></button>`).join("")}
    </div></div>
    ${GROUPS.filter(g => Object.keys(groups[g]).length).map(g => {
      const cats = Object.keys(groups[g]).sort((a, b) => a.localeCompare(b, "tr"));
      const all = cats.every(c => draft.categories.has(c));
      return `<div class="group"><div class="gh">${t(g)}<button data-group="${g}">${all ? t("seçimi kaldır") : t("tümünü seç")}</button></div>
        <div class="chips">${cats.map(c => `<button class="chipbtn ${draft.categories.has(c) ? "sel" : ""}" data-cat="${esc(c)}">${esc(c)}<span class="n">${groups[g][c]}</span></button>`).join("")}</div></div>`;
    }).join("")}
    <div class="actions">
      <button class="btn gold" id="ruleAdd" ${draftCount ? "" : "disabled"}>${t("Kuralı ekle")}</button>
      <span class="preview">${draftCount ? t("Bu kural {0} item'ı gizler", draftCount) : t("Nadirlik ya da kategori seç")}</span>
    </div>

    <h3>${t("Kurallar")}</h3>
    ${exclude.rules.length ? exclude.rules.map((rule, i) => `<div class="rule"><span class="what">${describeRule(rule)}</span>
        <span class="muted">${t("{0} item", data.items.filter(r => ruleMatches(rule, r)).length)}</span>
        <button class="x" data-del-rule="${i}" title="${t("Kuralı sil")}">✕</button></div>`).join("")
      : `<div class="hint">${t("Henüz kural yok.")}</div>`}

    <h3>${t("Tek tek gizlenen itemler")}</h3>
    ${hiddenItems.length ? hiddenItems.map(r => `<div class="hidden-item">${iconHtml(r.icon)}
        <span class="${gradeCls(r)}">${esc(r.name || t("Adsız"))}</span><span class="muted">${r.item_key}</span>
        <button class="x" data-show-item="${r.item_key}" title="${t("Tekrar göster")}">✕</button></div>`).join("")
      : `<div class="hint">${t("Yok. Bir item'ı tek başına gizlemek için satırına tıkla, detay panelinde “Listede gösterme”yi seç.")}</div>`}

    <div class="actions" style="margin-top:18px">
      <label class="chk"><input type="checkbox" id="showHidden" ${exclude.show_hidden ? "checked" : ""}> ${t("Gizlenenleri geçici olarak göster")}</label>
    </div>`;
  const sheet = document.getElementById("hideSheet");
  sheet.querySelector("#hideClose").onclick = closeHide;
  sheet.querySelectorAll("[data-grade]").forEach(b => b.onclick = () => { toggle(draft.grades, b.dataset.grade); renderHide(); });
  sheet.querySelectorAll("[data-cat]").forEach(b => b.onclick = () => { toggle(draft.categories, b.dataset.cat); renderHide(); });
  sheet.querySelectorAll("[data-group]").forEach(b => b.onclick = () => {
    const cats = Object.keys(groups[b.dataset.group]);
    const all = cats.every(c => draft.categories.has(c));
    cats.forEach(c => all ? draft.categories.delete(c) : draft.categories.add(c));
    renderHide();
  });
  sheet.querySelector("#ruleAdd").onclick = () => {
    exclude.rules.push({ grades: [...draft.grades], categories: [...draft.categories] });
    draft = { grades: new Set(), categories: new Set() };
    saveExclude(t("Kural eklendi"));
  };
  sheet.querySelectorAll("[data-del-rule]").forEach(b => b.onclick = () => { exclude.rules.splice(+b.dataset.delRule, 1); saveExclude(t("Kural silindi")); });
  sheet.querySelectorAll("[data-show-item]").forEach(b => b.onclick = () => {
    exclude.items = exclude.items.filter(k => k !== b.dataset.showItem); saveExclude(t("Item tekrar gösteriliyor"));
  });
  sheet.querySelector("#showHidden").onchange = e => { exclude.show_hidden = e.target.checked; saveExclude(); };
}
const toggle = (set, v) => set.has(v) ? set.delete(v) : set.add(v);
function openHide() { renderHide(); document.getElementById("hideModal").classList.add("on"); }
function closeHide() { document.getElementById("hideModal").classList.remove("on"); }

function filtered() {
  const q = state.q.trim().toLocaleLowerCase("tr");
  return data.items.filter(r => {
    if (!exclude.show_hidden && isHidden(r)) return false;
    if (state.hideEmpty && r.count === 0) return false;
    if (state.favOnly && !r.watched) return false;
    if (r.count < state.minc) return false;
    if (state.cat && r.category !== state.cat) return false;
    const c = r[state.period].change;
    if (state.dir === "down" && !(c < 0)) return false;
    if (state.dir === "up" && !(c > 0)) return false;
    if (q && !(r.item_key.includes(q) || [r.name, r.official_name, r.category].some(s => (s || "").toLocaleLowerCase("tr").includes(q)))) return false;
    return true;
  });
}

function sorted(rows) {
  const col = COLS.find(c => c.id === state.sort) || COLS[3];
  const dir = state.asc ? 1 : -1;
  return rows.slice().sort((a, b) => {
    if ((a.count === 0) !== (b.count === 0)) return a.count === 0 ? 1 : -1;   // no listings: always last
    const x = col.sort(a), y = col.sort(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;                      // missing values always last
    if (y == null) return -1;
    return x < y ? -dir : x > y ? dir : 0;
  });
}

function renderHead() {
  document.getElementById("head").innerHTML = COLS.map(c => {
    const on = state.sort === c.id;
    const cls = [c.cls || "", on ? "sorted" : "", c.id === state.period ? "active-period" : ""].join(" ");
    const arrow = on ? `<span class="arrow">${state.asc ? "▲" : "▼"}</span>` : "";
    return `<th class="${cls}" data-col="${c.id}">${t(c.label)}${arrow}</th>`;
  }).join("");
}

/* Click-to-sort tables. `desc` columns put the biggest value first on the first click;
   the column and direction live in state[key] and state[key + "Asc"]. */
function sortableTable(headId, key, cols, fallback) {
  const col = () => cols.find(c => c.id === state[key]) || cols.find(c => c.id === fallback);
  const asc = () => state[key + "Asc"] ?? !col().desc;
  document.getElementById(headId).onclick = e => {
    const c = cols.find(c => c.id === e.target.closest("th")?.dataset.col); if (!c || c.nosort) return;
    if (col() === c) state[key + "Asc"] = !asc(); else { state[key] = c.id; state[key + "Asc"] = !c.desc; }
    save(); render();
  };
  return {
    sort(rows) {
      const c = col(), dir = asc() ? 1 : -1;
      return rows.slice().sort((a, b) => {
        const x = c.sort(a), y = c.sort(b);
        if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;   // missing values always last
        return x < y ? -dir : x > y ? dir : 0;
      });
    },
    renderHead() {
      const cur = col(), up = asc();
      document.getElementById(headId).innerHTML = cols.map(c => {
        const on = c === cur, arrow = on ? `<span class="arrow">${up ? "▲" : "▼"}</span>` : "";
        return `<th class="${c.cls || ""} ${on ? "sorted" : ""}" data-col="${c.id}"${c.title ? ` title="${t(c.title)}"` : ""}>${t(c.label)}${arrow}</th>`;
      }).join("");
    },
  };
}
const byName = r => (r.name || "￿" + r.item_key).toLocaleLowerCase("tr");
const AVG_TITLE = "Son 7 günün fiyat ortalaması (uydurma uç ilanlar hariç)";

/* Favorites = the watchlist. A star adds an item without a target price (no alerts until one is set). */
