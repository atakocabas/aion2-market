"use strict";
function starCell(r) {
  const tip = r.watched ? t("Favorilerden çıkar") + (r.target ? t(" (hedef {0})", fmt(r.target)) : "") : t("Favorilere ekle");
  return `<td class="star ${r.watched ? "on" : ""}" data-star="${r.item_key}" title="${tip}">${r.watched ? "★" : "☆"}</td>`;
}

async function toggleFavorite(key) {
  const rows = [data.items.find(r => r.item_key === key), dealsData.items.find(r => r.item_key === key),
                ...[...(salesData.listings || []), ...(salesData.settled || [])].filter(r => r.item_key === key)].filter(Boolean);
  const adding = !rows.some(r => r.watched);
  if (!adding && rows.some(r => r.target) &&
      !confirmSafe(t("Bu item'ın hedef fiyatı var; favorilerden çıkarılırsa bildirimler de durur. Devam edilsin mi?"))) return;
  rows.forEach(r => { r.watched = adding; if (!adding) r.target = null; });       // instant feedback
  render();
  try {
    const res = await fetch("/api/watch", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(adding ? { item_key: key, target: "" } : { item_key: key, watch: false }) });
    if (!res.ok) throw new Error(res.status);
    toast(t(adding ? "Favorilere eklendi" : "Favorilerden çıkarıldı"));
  } catch {
    toast(t("Kaydedilemedi"));
  }
  refresh();
}

// confirm() is unavailable in some embedded browsers; there, removal just proceeds.
function confirmSafe(msg) {
  try { return window.confirm(msg); } catch { return true; }
}

function render() {
  if (state.view === "deals") renderDeals();
  else if (state.view === "craft") renderCraft();
  else if (state.view === "inv") renderInventory();
  else if (state.view === "sales") renderSales();
  else if (state.view === "fav") renderFavorites();
  else renderChanges();
  const hidden = data.items.filter(isHidden).length, hb = document.getElementById("hideBtn");
  hb.textContent = hidden ? `${t("⊘ Gizle")} (${hidden}${exclude.show_hidden ? t(", gösteriliyor") : ""})` : t("⊘ Gizle");
  hb.classList.toggle("on", hidden > 0);
  const v = state.view, changes = !["deals", "craft", "inv", "sales", "fav"].includes(v);
  const active = [changes && state.dir !== "all", state.minc > 0, changes && state.hideEmpty,
                  v !== "fav" && state.favOnly, v === "deals" && state.hideSliding].filter(Boolean).length;
  const fb = document.getElementById("filterBtn");
  fb.textContent = active ? `${t("Filtreler")} · ${active}` : t("Filtreler");
  fb.classList.toggle("on", active > 0);
}

/* A "?" section for long explanations; stays open across re-renders. */
function help(el, label, body) {
  const open = el.querySelector("details.help")?.open ? " open" : "";
  return `<details class="help"${open}><summary>${t(label)}</summary>${body}</details>`;
}

/* Filters every list page applies: hide rules, plus the open page's search, category, minimum listings, favorites only.
   `own` rows (the player's own sales) ignore hide rules so a listing never drops out of view. */
function passesCommon(r, own) {
  if (own !== true && !exclude.show_hidden && isHidden(r)) return false;
  if (state.favOnly && !r.watched) return false;
  if (r.count < state.minc) return false;
  if (state.cat && r.category !== state.cat) return false;
  const q = state.q.trim().toLocaleLowerCase("tr");
  return !q || r.item_key.includes(q) || [r.name, r.official_name, r.category].some(s => (s || "").toLocaleLowerCase("tr").includes(q));
}

function renderDeals() {
  const rules = dealsData.rules || {};
  const rows = dealTable.sort(dealsData.items.filter(r => passesCommon(r) && !(state.hideSliding && r.deal.sliding)
                                                         && !(state.profitOnly && !(r.deal.net_profit > 0))));
  dealTable.renderHead();
  renderWeek(dealsData.weekdays);
  renderMorphs(dealsData.morphs || []);
  const intro = document.getElementById("dealsIntro");
  intro.innerHTML = t("Şu an normal fiyatının altında olan itemler: <b>{0}</b> öneri", rows.length) +
    (rows.length !== dealsData.items.length ? t(" (filtrelerle {0} tanesi gizli)", dealsData.items.length - rows.length) : "") + "." +
    help(intro, "Nasıl seçiliyor?",
      t("Şu an <b>kendi 7 günlük ortalama fiyatının en az {0} altında</b> olan ve <b>son listelemede ya da 7 günde en az {1} düşen</b> itemler. " +
        "En az {2} ilanı ve {3} günlük geçmişi olmalı; uydurma uç fiyatlar sayılmaz. " +
        "Sıralama: indirim × 30 günün dibine yakınlık × ilan sayısı; bir haftadır düşüşte olanlar ani düşüşlerin arkasına alınır.",
        pctRaw(rules.min_discount ?? 10), pctRaw(rules.min_drop ?? 5), rules.min_listings ?? 2, rules.min_days ?? 3));
  document.getElementById("dealRows").innerHTML = rows.map((r, i) => {
    const d = r.deal;
    const name = r.name ? `<span class="nm ${gradeCls(r)}">${esc(r.name)}</span>` : `<span class="nm unnamed">${t("Adsız")}</span>`;
    const sub = esc(r.category || "");
    // One short line with what the columns don't show; the full reasons stay on hover.
    const full = [...d.reasons, ...(d.warning ? d.warning.split(" · ").map(w => "⚠ " + w) : [])].join("\n");
    const note = (d.note || []).map(n => n.warn ? `<span class="warn">⚠ ${esc(n.text)}</span>` : esc(n.text)).join(" · ");
    return `<tr data-key="${r.item_key}">
      <td class="rank">${i + 1}</td>
      ${starCell(r)}
      <td class="l"><div class="item">${iconHtml(r.icon)}<div class="txt" title="${esc(full)}">${name}<span class="sub">${sub}</span>
        ${note ? `<span class="note">${note}</span>` : ""}</div></div></td>
      <td class="price">${fmt(r.price)}</td>
      <td class="muted">${fmt(r.typical)}</td>
      <td><span class="disc">${pct(d.discount)}</span><span class="save">${t("adet başı {0} ucuz", fmt(d.saving))}</span></td>
      <td title="${fmt(r.typical)} × ${pctRaw(100 - (dealsData.fee_pct ?? 12))} − ${fmt(r.price)}"><span class="profit ${d.net_profit > 0 ? "pos" : "neg"}">${d.net_profit > 0 ? "+" : ""}${fmt(d.net_profit)}</span>
        <span class="save">${t("{0} getiri", pct(d.profit_pct))}</span></td>
      <td title="${t("30 günlük aralık (uç değerler hariç) {0} – {1}", fmt(r.low30), fmt(r.high30))}">
        <span class="range"><i style="left:${(d.position * 100).toFixed(0)}%"></i></span>
        <div class="range-l"><span>${fmt(r.low30)}</span><span>${fmt(r.high30)}</span></div></td>
      <td>${chg(r.week.change, r.week.partial, r.week.ts)}</td>
      <td class="muted">${r.count}</td>
    </tr>`;
  }).join("");
  const empty = document.getElementById("dealsEmpty");
  empty.hidden = rows.length > 0;
  empty.textContent = t(dealsData.items.length ? "Filtrelere uyan öneri yok." : "Şu an bu kurallara uyan fırsat yok.");
}

const DAYS = { tr: ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"], en: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] };

function renderWeek(w) {
  const el = document.getElementById("weekStrip");
  el.hidden = !w;
  if (!w) return;
  el.innerHTML = w.by_day.map((v, i) => {
    const cls = v == null ? "" : v === Math.min(...w.by_day.filter(x => x != null)) ? "cheap"
              : v === Math.max(...w.by_day.filter(x => x != null)) ? "dear" : "";
    return `<div class="d ${cls}"><div class="n">${DAYS[LANG][i]}</div><div class="v">${v == null ? "–" : (v > 0 ? "+" : "") + PF.format(v) + "%"}</div></div>`;
  }).join("") + `<div class="cap">${t("Son 30 gün: en ucuz gün <b>{0}</b>, en pahalı gün <b>{1}</b>.", w.cheapest, w.dearest)}</div>`;
}

function renderMorphs(list) {
  const fee = dealsData.fee_pct ?? 12;
  const intro = document.getElementById("morphIntro");
  intro.innerHTML = t("Odyle, aynı seviyedeki cevher, mücevher ve kütüğe 1:1 dönüştürülebilir.") +
    help(intro, "Nasıl hesaplanıyor?",
      `<b>${t("Üretim için")}</b>${t(": malzeme Odyle'dan pahalıysa Odyle alıp dönüştürmek daha ucuz.")} ` +
      `<b>${t("Satış için")}</b>${t(": Odyle alıp dönüştürüp malzemeyi satınca market kesintisinden sonra kalan. Dönüştürmenin kendi maliyeti (varsa) hesaba katılmadı.")}`);
  const cell = it => `<div class="item">${iconHtml(it.icon)}<div class="txt"><span class="nm ${gradeCls(it)}">${esc(it.name || it.item_key)}</span><span class="sub">${t("{0} ilan", it.count)}</span></div></div>`;
  document.getElementById("morphRows").innerHTML = list.length ? list.map(m => `<tr>
      <td class="l">${cell(m.material)}</td><td class="price">${fmt(m.material.price)}</td>
      <td class="l">${cell(m.odyle)}</td><td class="price">${fmt(m.odyle.price)}</td>
      <td><span class="profit ${m.craft_saving > 0 ? "pos" : "neg"}">${m.craft_saving > 0 ? t("Odyle al, {0} ucuz", fmt(m.craft_saving)) : t("malzemeyi al")}</span></td>
      <td title="${fmt(m.material.price)} × ${pctRaw(100 - fee)} − ${fmt(m.odyle.price)}"><span class="profit ${m.sell_profit > 0 ? "pos" : "neg"}">${m.sell_profit > 0 ? "+" : ""}${fmt(m.sell_profit)}</span>
        <span class="save">${pct(m.sell_profit_pct)}</span></td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">${t("Odyle ve malzemelerin güncel fiyatı yok.")}</td></tr>`;
}

/* ---------- inventory page ---------- */
const SIGNAL_LABEL = { sell: "Sat", hold: "Bekle", normal: "Normal", check: "Kontrol et" };

function renderInventory() {
  const sig = state.invSignal || "", place = invPlace();
  document.querySelectorAll("#invPlace button").forEach(b => b.classList.toggle("on", b.dataset.g === place));
  document.querySelectorAll("#invSignal button").forEach(b => b.classList.toggle("on", b.dataset.g === sig));
  const rows = invTable.sort(invData.items.filter(r => passesCommon(r) && (!sig || r.signal === sig)));
  invTable.renderHead();
  const sells = invData.items.filter(r => r.signal === "sell");
  document.getElementById("i-total").textContent = invData.ts ? fmt(invData.total_value) : "–";
  document.getElementById("i-total-s").textContent = t("{0} satılabilir item çeşidi · kesinti sonrası", invData.items.length);
  document.getElementById("i-sell").textContent = sells.length ? fmt(invData.sell_value) : "–";
  document.getElementById("i-sell-s").textContent = t('{0} item "Sat" önerisinde', sells.length);
  document.getElementById("i-ts").textContent = invData.ts ? fmtTime(invData.ts) : t("henüz yok");
  const w = invData.weekdays;
  document.getElementById("i-day").textContent = w ? w.dearest : "–";
  document.getElementById("i-day-s").textContent = w ? t("fiyatlar en yüksek; en düşük {0} (fark {1})", w.cheapest, pct(w.spread)) : " ";
  document.getElementById("invRows").innerHTML = rows.map(r => {
    const name = r.name ? `<span class="nm ${gradeCls(r)}">${esc(r.name)}</span>` : `<span class="nm unnamed">${t("Adsız")}</span>`;
    const prem = r.premium == null ? `<span class="na">–</span>`
      : `<span class="chg ${r.premium > 0.05 ? "up" : r.premium < -0.05 ? "down" : "flat"}"><span class="p">${r.premium > 0 ? "+" : ""}${pct(r.premium)}</span></span>`;
    return `<tr data-key="${r.item_key}">
      ${starCell(r)}
      <td class="l"><div class="item">${iconHtml(r.icon)}<div class="txt">${name}<span class="sub">${esc(r.category || "")}</span></div></div></td>
      <td class="price">${fmt(r.owned)}</td>
      <td class="price">${r.suspect ? `<span class="warn" title="${t("En ucuz ilan 30 günlük fiyatlara göre uç değerde")}">⚠</span> ` : ""}${fmt(r.price)}</td>
      <td class="muted">${fmt(r.typical)}</td>
      <td>${prem}</td>
      <td>${chg(r.prev.change)}</td>
      <td>${chg(r.week.change, r.week.partial, r.week.ts)}</td>
      <td class="price">${fmt(r.value_net)}</td>
      <td class="l"><span class="badge ${r.signal}">${t(SIGNAL_LABEL[r.signal])}</span>
        ${r.signal === "sell" || r.signal === "check" ? `<span class="muted" style="font-size:12px"> ${t("{0}'den listele", fmt(r.suggest_price))}</span>` : ""}
        <span class="why">${esc(r.why)}</span></td>
    </tr>`;
  }).join("");
  const empty = document.getElementById("invEmpty");
  empty.hidden = rows.length > 0;
  empty.textContent = t(place === "warehouse" && !invData.warehouse_ts ? "Depo henüz yok. Bir sonraki oyuna girişte dolar."
    : !invData.ts ? "Envanter henüz yok. Oyuna giriş yaptığında kendiliğinden gelir." : "Filtrelere uyan item yok.");
  const up = invData.unpriced || [];
  const invFoot = document.getElementById("invFoot");
  invFoot.innerHTML = help(invFoot, "Öneriler nasıl hesaplanıyor?",
    t('"Sat": fiyat 7 gün ortalamasının en az %10 üstünde ya da 7 günde en az %15 yükselmiş. "Bekle": 7 gün ortalamasının en az %10 altında. ') +
    t("Önerilen fiyat, en ucuz ilanın 1 altı (en ucuz ilan uydurmaysa 7 gün ortalaması). Market kesintisi {0}. ", pctRaw(invData.fee_pct ?? 12)) +
    (up.length ? t("Markette şu an ilanı olmayan {0} item listede yok: {1}.", up.length,
                   up.slice(0, 6).map(u => esc(u.name || u.item_key) + " ×" + u.count).join(", ") + (up.length > 6 ? "…" : "")) : ""));
}

/* ---------- my sales page ---------- */
// Rows carry market_count instead of count; passesCommon's minimum-listings filter reads count.
const withCount = r => (r.count = r.market_count ?? 0, r);
const itemCell = r => {
  const name = r.name ? `<span class="nm ${gradeCls(r)}">${esc(r.name)}</span>` : `<span class="nm unnamed">${t("Adsız")}</span>`;
  return `<td class="l"><div class="item">${iconHtml(r.icon)}<div class="txt">${name}<span class="sub">${esc(r.category || "")}</span></div></div></td>`;
};
// Signed % against the market; positive (you're above / the market is above) is red, like a rise.
const signedPct = v => v == null ? `<span class="na">–</span>`
  : `<span class="chg ${v > 0.05 ? "up" : v < -0.05 ? "down" : "flat"}"><span class="p">${v > 0 ? "+" : v < 0 ? "−" : ""}${pct(Math.abs(v))}</span></span>`;
const lowestCell = r => r.lowest == null ? `<td class="price"><span class="na">–</span></td>`
  : `<td class="price" title="${t("{0} ilan · {1}", r.market_count ?? 0, fmtTime(r.lowest_ts))}">${fmt(r.lowest)}<span class="save">${ago(r.lowest_ts)}</span></td>`;

function saleStatus(r) {
  if (r.status === "lowest") return `<span class="badge sell">${t("En ucuz sensin")}</span>`;
  if (r.status === "undercut") return `<span class="badge hold">${t("Geçildin")}</span>` +
    (r.suggest_price != null ? `<span class="why">${t("{0}'den yeniden listele", fmt(r.suggest_price))}</span>` : "");
  return `<span class="badge normal">${t("Fiyat yok")}</span>`;
}

function renderSales() {
  const sd = salesData, now = Date.now() / 1000;
  const listings = (sd.listings || []).map(withCount), settled = (sd.settled || []).map(withCount);
  const lrows = salesTable.sort(listings.filter(r => passesCommon(r, true))), srows = settledTable.sort(settled.filter(r => passesCommon(r, true)));
  salesTable.renderHead();
  settledTable.renderHead();
  const under = listings.filter(r => r.status === "undercut").length, cheapest = listings.filter(r => r.status === "lowest").length;
  document.getElementById("s-total").textContent = sd.listings_ts ? fmt(sd.listings_total) : "–";
  document.getElementById("s-total-s").textContent = sd.listings_ts ? t("{0} ilan · kesinti sonrası {1}", listings.length, fmt(sd.listings_net)) : t("henüz yok");
  const ue = document.getElementById("s-under");
  ue.textContent = sd.listings_ts ? NF.format(under) : "–";
  ue.className = "v" + (under ? " up" : "");
  document.getElementById("s-under-s").textContent = sd.listings_ts ? t("{0} ilanda en ucuz sensin", cheapest) : " ";
  document.getElementById("s-settled").textContent = sd.settled_ts ? fmt(sd.settled_total) : "–";
  document.getElementById("s-settled-s").textContent = !sd.settled_ts ? t("henüz yok")
    : sd.pending_total ? t("tahsil edilmeyen {0}", fmt(sd.pending_total)) : t("hepsi tahsil edildi");
  const last = Math.max(sd.listings_ts || 0, sd.settled_ts || 0);
  document.getElementById("s-ts").textContent = last ? fmtTime(last) : t("henüz yok");
  document.getElementById("s-ts-s").textContent = last ? t("ilanlar {0} · hesap {1}", ago(sd.listings_ts), ago(sd.settled_ts)) : " ";

  document.getElementById("salesRows").innerHTML = lrows.map(r => `<tr data-key="${r.item_key}" class="${selected === r.item_key ? "sel" : ""}">
      ${starCell(r)}
      ${itemCell(r)}
      <td class="price">${fmt(r.quantity)}${r.quantity > 1 && r.sale_price != null ? `<span class="save">${t("toplam {0}", fmt(r.sale_price))}</span>` : ""}</td>
      <td class="price">${fmt(r.unit_price)}</td>
      ${lowestCell(r)}
      <td>${signedPct(r.gap_pct)}</td>
      <td class="l">${saleStatus(r)}</td>
      <td class="muted">${r.expires == null ? "–" : r.expires < now ? t("süresi doldu") : fmtTime(r.expires)}</td>
    </tr>`).join("");
  const le = document.getElementById("salesEmpty");
  le.hidden = lrows.length > 0;
  le.textContent = t(sd.error ? "Satış verisi alınamadı." : !sd.listings_ts ? "Henüz ilan yok. Oyunda markette 'Satışlarım' sayfasını açınca gelir."
    : listings.length ? "Filtrelere uyan ilan yok." : "Şu an satışta ilanın yok.");

  document.getElementById("settledRows").innerHTML = srows.map(r => `<tr data-key="${r.item_key}" class="${selected === r.item_key ? "sel" : ""}">
      ${starCell(r)}
      ${itemCell(r)}
      <td class="price">${fmt(r.quantity)}${r.quantity > 1 && r.sale_price != null ? `<span class="save">${t("toplam {0}", fmt(r.sale_price))}</span>` : ""}</td>
      <td class="price">${fmt(r.unit_price)}</td>
      <td class="price">${fmt(r.earnings)}${r.pending ? `<span class="why"><span class="badge check">${t("Tahsil edilmedi")}</span></span>` : ""}</td>
      <td class="muted" title="${ago(r.sold)}">${fmtTime(r.sold)}</td>
      ${lowestCell(r)}
      <td>${signedPct(r.diff_pct)}</td>
    </tr>`).join("");
  const se = document.getElementById("settledEmpty");
  se.hidden = srows.length > 0;
  se.textContent = t(sd.error ? "Satış verisi alınamadı." : !sd.settled_ts ? "Henüz satış kaydı yok. Oyunda markette 'Hesap' sayfasını açınca gelir."
    : settled.length ? "Filtrelere uyan satış yok." : "Hesapta satılmış item yok.");

  const foot = document.getElementById("salesFoot");
  foot.innerHTML = help(foot, "Bu sayfa hakkında",
    t("İlanların ve satılanlar, oyunda markette 'Satışlarım' ve 'Hesap' sayfalarını açtığında güncellenir; aradaki değişiklikler o sayfaları tekrar açana kadar görünmez. ") +
    t("En düşük fiyat, item'ın son market aramasındaki en ucuz ilanıdır ve senin kendi ilanın da olabilir; yanındaki süre o fiyatın ne kadar eski olduğunu gösterir. ") +
    t("Kazanç ve net toplam, market kesintisi ({0}) düşülmüş hâlidir.", pctRaw(sd.fee_pct ?? 12)));
}

/* ---------- favorites page ---------- */
const toTarget = r => r.target && r.price ? (r.price - r.target) / r.target * 100 : null;   // ≤ 0: at or under target
let favOwned = {};
// Status badge and its rank (most urgent first) for the favorites table.
function favStatus(r) {
  const gap = toTarget(r);
  if (!r.listed) return [4, `<span class="badge hold">${t("Markette yok")}</span>`];
  if (gap != null && gap <= 0) return [0, `<span class="badge sell">${t("Hedefin altında")}</span>`];
  if (r.typical && r.price <= r.typical * 0.8) return [1, `<span class="badge sell">${t("7 gün ort. {0} altında", pctRaw(20))}</span>`];
  return r.target ? [2, `<span class="badge normal">${t("Bekleniyor")}</span>`] : [3, `<span class="badge normal">${t("İzleniyor")}</span>`];
}

function renderFavorites() {
  const kind = state.favKind || "";
  document.querySelectorAll("#favKind button").forEach(b => b.classList.toggle("on", b.dataset.g === kind));
  const owned = favOwned = Object.fromEntries((invData.items || []).map(r => [r.item_key, r.owned]));
  const favs = data.items.filter(r => r.watched);
  const rows = favTable.sort(favs.filter(r => passesCommon(r) && (kind !== "target" || r.target) && (kind !== "none" || !r.target)));
  favTable.renderHead();
  document.getElementById("favRows").innerHTML = rows.map(r => {
    const name = r.name ? `<span class="nm ${gradeCls(r)}">${esc(r.name)}</span>` : `<span class="nm unnamed">${t("Adsız")}</span>`;
    const gap = toTarget(r);
    const gapCell = gap == null ? `<span class="na">–</span>`
      : gap <= 0 ? `<span class="profit pos">${t("{0} altında", pct(-gap))}</span>`
      : `<span class="muted">${t("{0} üstünde", pct(gap))}</span><span class="save">${t("{0} fark", fmt(r.price - r.target))}</span>`;
    const status = favStatus(r)[1];
    return `<tr data-key="${r.item_key}">
      ${starCell(r)}
      <td class="l"><div class="item">${iconHtml(r.icon)}<div class="txt">${name}<span class="sub">${esc(r.category || "")}</span></div></div></td>
      <td class="price">${r.suspect ? `<span class="warn" title="${t("En ucuz ilan 30 günlük fiyatlara göre uç değerde")}">⚠</span> ` : ""}${fmt(r.price)}</td>
      <td class="price">${r.target ? fmt(r.target) : `<span class="na">${t("yok")}</span>`}</td>
      <td>${gapCell}</td>
      <td class="muted">${fmt(r.typical)}</td>
      <td>${chg(r.prev.change)}</td>
      <td>${chg(r.week.change, r.week.partial, r.week.ts)}</td>
      <td>${chg(r.month.change, r.month.partial, r.month.ts)}</td>
      <td class="muted">${r.count}</td>
      <td class="muted">${owned[r.item_key] ? fmt(owned[r.item_key]) : "–"}</td>
      <td class="l">${status}</td>
    </tr>`;
  }).join("");
  const favFoot = document.getElementById("favFoot");
  favFoot.innerHTML = t("Hedef fiyatı değiştirmek için satıra tıkla.") + help(favFoot, "Bildirim ne zaman gelir?",
    t("Hedefi olan item hedefin altına inince bildirim gelir; hedefsiz favoriler 7 gün ortalamasının %20 altına inince bildirilir."));
  const empty = document.getElementById("favEmpty");
  empty.hidden = rows.length > 0;
  empty.textContent = t(favs.length ? "Filtrelere uyan favori yok."
    : "Henüz favorin yok. Diğer sayfalarda bir item'ın ☆ işaretine tıkla ya da item'ı açıp hedef fiyat gir.");
}

