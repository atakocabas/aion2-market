"use strict";
/* ---------- wiring ---------- */
function setPeriod(p) {
  state.period = p; state.sort = p; state.asc = true; save();
  document.querySelectorAll("#period button").forEach(b => b.classList.toggle("on", b.dataset.p === p));
  render();
}
document.querySelectorAll("#period button").forEach(b => b.onclick = () => setPeriod(b.dataset.p));
document.getElementById("head").onclick = e => {
  const th = e.target.closest("th"); if (!th) return;
  const col = COLS.find(c => c.id === th.dataset.col); if (!col || col.nosort) return;
  if (state.sort === col.id) state.asc = !state.asc; else { state.sort = col.id; state.asc = true; }
  save(); render();
};
// A click on the star toggles the favorite; anywhere else on the row opens the detail panel.
const rowClick = e => {
  const star = e.target.closest("[data-star]");
  if (star) return toggleFavorite(star.dataset.star);
  const tr = e.target.closest("tr");
  if (tr) openItem(tr.dataset.key);
};
document.getElementById("rows").onclick = rowClick;
document.getElementById("dealRows").onclick = rowClick;
document.getElementById("invRows").onclick = rowClick;
document.getElementById("favRows").onclick = rowClick;
document.querySelectorAll("#favKind button").forEach(b => b.onclick = () => { state.favKind = b.dataset.g; save(); render(); });
document.querySelectorAll("#invSignal button").forEach(b => b.onclick = () => { state.invSignal = b.dataset.g; save(); render(); });
document.getElementById("craftView").onclick = e => { const tr = e.target.closest("tr[data-key]"); if (tr) openItem(tr.dataset.key); };
document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { if (state.view !== b.dataset.view) setView(b.dataset.view); });
const bind = (id, key, get) => { const el = document.getElementById(id); el.addEventListener("input", () => { state[key] = get(el); save(); render(); }); };
bind("q", "q", el => el.value);
bind("dir", "dir", el => el.value);
bind("cat", "cat", el => el.value);
document.getElementById("cat").addEventListener("input", syncCatReset);
document.getElementById("catReset").onclick = () => {
  document.getElementById("cat").value = "";
  state.cat = ""; save(); syncCatReset(); render();
};
bind("minc", "minc", el => Math.max(0, +el.value || 0));
bind("hideEmpty", "hideEmpty", el => el.checked);
bind("hideSliding", "hideSliding", el => el.checked);
document.getElementById("hideSliding").checked = state.hideSliding;
bind("favOnly", "favOnly", el => el.checked);
document.getElementById("favOnly").checked = !!state.favOnly;
bind("profitOnly", "profitOnly", el => el.checked);
document.getElementById("profitOnly").checked = !!state.profitOnly;
const dealTable = sortableTable("dealHead", "dealSort", [
  { id: "score", label: "#", desc: true, sort: r => r.deal.score },
  { id: "star", label: "★", cls: "star", title: "Favoriler", sort: r => r.watched ? 0 : 1 },
  { id: "name", label: "Item", cls: "l", sort: byName },
  { id: "price", label: "Birim fiyat", sort: r => r.price },
  { id: "typical", label: "7 gün ort.", title: AVG_TITLE, sort: r => r.typical },
  { id: "discount", label: "İndirim", desc: true, sort: r => r.deal.discount },
  { id: "profit", label: "Al-sat kârı", desc: true, sort: r => r.deal.profit_pct,
    title: "Şimdi alıp 7 gün ortalamasından satarsan, market kesintisinden sonra adet başına kalan" },
  { id: "range", label: "30 gün aralığı", title: "Fiyatın 30 günlük aralıktaki yeri; en dipteki önce", sort: r => r.deal.position },
  { id: "week", label: "7 gün", sort: r => r.week.change },
  { id: "count", label: "İlan", desc: true, sort: r => r.count },
], "score");
const SIGNAL_RANK = { sell: 0, check: 1, normal: 2, hold: 3 };
const invTable = sortableTable("invHead", "invSort", [
  { id: "star", label: "★", cls: "star", title: "Favoriler", sort: r => r.watched ? 0 : 1 },
  { id: "name", label: "Item", cls: "l", sort: byName },
  { id: "owned", label: "Adet", desc: true, sort: r => r.owned },
  { id: "price", label: "Birim fiyat", desc: true, sort: r => r.price },
  { id: "typical", label: "7 gün ort.", title: AVG_TITLE, desc: true, sort: r => r.typical },
  { id: "premium", label: "7 gün ort. göre", desc: true, sort: r => r.premium },
  { id: "prev", label: "Son listeleme", desc: true, sort: r => r.prev.change },
  { id: "week", label: "7 gün", desc: true, sort: r => r.week.change },
  { id: "value", label: "Toplam (net)", title: "Adet × fiyat, market kesintisi düşülmüş", desc: true, sort: r => r.value_net },
  { id: "signal", label: "Öneri", cls: "l", sort: r => SIGNAL_RANK[r.signal] },
], "week");
const favTable = sortableTable("favHead", "favSort", [
  { id: "star", label: "★", cls: "star", title: "Favoriler", nosort: true },
  { id: "name", label: "Item", cls: "l", sort: byName },
  { id: "price", label: "Birim fiyat", sort: r => r.price },
  { id: "tgt", label: "Hedef", sort: r => r.target },
  { id: "target", label: "Hedefe kalan", title: "Şu anki fiyatın hedefe uzaklığı", sort: toTarget },
  { id: "typical", label: "7 gün ort.", title: AVG_TITLE, sort: r => r.typical },
  { id: "prev", label: "Son listeleme", sort: r => r.prev.change },
  { id: "week", label: "7 gün", sort: r => r.week.change },
  { id: "month", label: "30 gün", sort: r => r.month.change },
  { id: "count", label: "İlan", desc: true, sort: r => r.count },
  { id: "owned", label: "Sende", desc: true, sort: r => favOwned[r.item_key] },
  { id: "status", label: "Durum", cls: "l", sort: r => favStatus(r)[0] },
], "target");
document.getElementById("q").value = state.q;
document.getElementById("dir").value = state.dir;
document.getElementById("minc").value = state.minc;
document.getElementById("hideEmpty").checked = state.hideEmpty;
document.querySelectorAll("#period button").forEach(b => b.classList.toggle("on", b.dataset.p === state.period));
document.getElementById("refresh").onclick = refresh;
document.getElementById("server").onchange = e => { state.server = +e.target.value; save(); closeDrawer(); refresh(); };
// Inline editor (embedded browsers may not support prompt()).
const srvEditing = on => {
  document.getElementById("srvedit").hidden = !on;
  document.getElementById("server").hidden = on;
  document.getElementById("srvname").hidden = on;
};
document.getElementById("srvname").onclick = () => {
  const s = servers.servers.find(x => x.server_id === state.server); if (!s) return;
  const input = document.getElementById("srvinput");
  input.value = s.name || "";
  srvEditing(true);
  input.focus();
};
document.getElementById("srvcancel").onclick = () => srvEditing(false);
document.getElementById("srvsave").onclick = () => {
  const name = document.getElementById("srvinput").value.trim();
  srvEditing(false);
  if (name && state.server) post("/api/server-name", { server_id: state.server, name }, t("Sunucu adı kaydedildi"));
};
document.getElementById("srvinput").onkeydown = e => {
  if (e.key === "Enter") document.getElementById("srvsave").click();
  if (e.key === "Escape") { e.stopPropagation(); srvEditing(false); }
};
scrim.onclick = closeDrawer;
document.getElementById("hideBtn").onclick = openHide;
const filterPanel = document.getElementById("filterPanel"), filterBtn = document.getElementById("filterBtn");
const showFilters = on => { filterPanel.hidden = !on; filterBtn.setAttribute("aria-expanded", on); };
filterBtn.onclick = e => { e.stopPropagation(); showFilters(filterPanel.hidden); };
document.addEventListener("click", e => { if (!filterPanel.hidden && !e.target.closest(".filterbox")) showFilters(false); });
const syncPanel = document.getElementById("syncPanel"), syncBtn = document.getElementById("sync");
const showSync = on => { syncPanel.hidden = !on; syncBtn.setAttribute("aria-expanded", on); };
syncBtn.onclick = e => { e.stopPropagation(); showSync(syncPanel.hidden); };
document.addEventListener("click", e => { if (!syncPanel.hidden && !e.target.closest(".syncbox")) showSync(false); });
document.getElementById("syncOn").onchange = async e => {
  await post("/api/sync", { enabled: e.target.checked }, t(e.target.checked ? "Ortak veri açıldı" : "Ortak veri kapatıldı"));
};
document.getElementById("hideModal").onclick = e => { if (e.target.id === "hideModal") closeHide(); };
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  if (!filterPanel.hidden) return showFilters(false);
  if (!syncPanel.hidden) return showSync(false);
  if (document.getElementById("hideModal").classList.contains("on")) closeHide();
  else if (selected) closeDrawer();
});

function applyLang() {
  setLocale(state.lang);
  translateStatic();
  setTitle();
  document.querySelectorAll("#lang button").forEach(b => b.classList.toggle("on", b.dataset.l === state.lang));
}
document.querySelectorAll("#lang button").forEach(b => b.onclick = () => {
  if (state.lang === b.dataset.l) return;
  state.lang = b.dataset.l; save(); applyLang();
  render();
  if (document.getElementById("hideModal").classList.contains("on")) renderHide();
  refresh();                                     // server-made texts (reasons, advice, weekdays) come in the new language
});

applyLang();
setView(["deals", "craft", "inv", "fav"].includes(state.view) ? state.view : "changes");       // also does the first refresh
setInterval(refresh, 30000);
