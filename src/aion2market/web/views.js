"use strict";
/* ---------- crafting page ---------- */
const money = v => v == null ? `<span class="na">–</span>` : fmt(v);
const profitCell = v => v == null ? `<span class="na">–</span>`
  : `<span class="profit ${v > 0 ? "pos" : "neg"}">${v > 0 ? "+" : ""}${fmt(v)}</span>`;

function renderCraft() {
  const fee = craftData.fee_pct ?? 12;
  const craftIntro = document.getElementById("craftIntro");
  craftIntro.innerHTML = t("Her kademe için en ucuz yol: marketten <b>al</b> ya da bir önceki kademenin en ucuz yolundan <b>üret</b>.") +
    help(craftIntro, "Nasıl hesaplanıyor?", t("Üretim maliyeti = bir denemenin malzemesi × beklenen deneme sayısı (her adımda %25 kombo ihtimali; 4. adımın normal sonucu ~1,06 denemede). " +
      "Malzeme en ucuz yoldan hesaplanır: marketten, Odyle'dan dönüştürerek (mor) ya da kendi tarifinden üreterek (yeşil). " +
      "NPC'den alınan (Bound) malzemelerin fiyatı bilinmediğinden maliyete katılmaz (+NPC). Kâr, market kesintisi ({0}) düşüldükten sonra. " +
      "Tarifler aion2.app'in crafting veritabanından (NCSOFT verisi), kombo oranları topluluğun tablosundan; şansa bağlı olduğundan gerçek maliyet sapabilir. Fiyatlar şu anki market listesi.",
      pctRaw(fee)));
  const named = x => `<div class="item">${iconHtml(x.icon)}<div class="txt"><span class="nm ${gradeCls(x)}">${esc(x.name)}</span>` +
    `<span class="sub">${x.listings ? t("{0} ilan", x.listings) : t("markette yok")}</span></div></div>`;
  const profs = [...new Set([...craftData.chains, ...(craftData.recipes || [])].map(x => x.profession))];
  if (state.craftProf && !profs.includes(state.craftProf)) state.craftProf = "";
  const profBox = document.getElementById("craftProf");
  profBox.innerHTML = ["", ...profs].map(p => `<button data-prof="${p}" class="${(state.craftProf || "") === p ? "on" : ""}">${p ? esc(p) : t("Hepsi")}</button>`).join("");
  profBox.onclick = e => { const b = e.target.closest("button[data-prof]"); if (b) { state.craftProf = b.dataset.prof; renderCraft(); } };
  const inProf = x => !state.craftProf || x.profession === state.craftProf;
  const npcMark = x => x.npc ? `<span class="npcmark" title="${t("NPC'den alınan malzemeler (Bound) fiyatı bilinmediği için maliyete katılmadı")}">+NPC</span>` : "";
  const best = craftData.best_sales.filter(inProf);
  document.getElementById("craftBest").innerHTML = best.length
    ? best.slice(0, 12).map(x => `<tr data-key="${x.item_key}">
        <td class="l">${named(x)}</td><td class="muted">${x.step ? t("{0} · {1}. adım", x.slot, x.step) : esc(x.slot)}</td>
        <td>${money(x.craft_cost)}${npcMark(x)}</td><td class="price">${money(x.market_price)}</td>
        <td>${profitCell(x.sell_profit)}<span class="save">${pct(x.profit_pct)}</span></td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">${t("Şu an üretip satınca kâr eden kademe yok.")}</td></tr>`;
  const crafted = m => m.via === "craft" || m.via === "craft_npc";
  const matLine = m => m.price == null
    ? `<span class="miss">${m.qty}× ${esc(m.name)}${t(" (fiyat yok)")}</span>`
    : m.via === "npc" ? `<span class="npc" title="${t("NPC'den alınır, fiyatı bilinmiyor")}">${m.qty}× ${esc(m.name)} (NPC)</span>`
    : `<span class="${m.via === "odyle" ? "odyle" : crafted(m) ? "crafted" : ""}" title="${t(m.via === "odyle" ? "Odyle'dan dönüştürmek daha ucuz"
        : crafted(m) ? "Kendin üretmek marketten ucuz" : "Marketten")}">${m.qty}× ${esc(m.name)} ${fmt(m.price)}${m.via === "odyle" ? " (Odyle)" : crafted(m) ? t(" (üret)") : ""}</span>`;
  const singles = (craftData.recipes || []).filter(inProf);
  document.getElementById("craftSingles").innerHTML = singles.length ? singles.map(r => `<tr data-key="${r.item_key}">
      <td class="l">${named(r)}<div class="mats">${r.materials.map(matLine).join("")}</div></td>
      <td class="muted">${esc(r.category || r.profession)}<span class="save">${t("Mastery {0}", r.mastery)}${r.qty > 1 ? " · ×" + r.qty : ""}</span></td>
      <td>${money(r.cost)}${npcMark(r)}${r.qty > 1 && r.unit_cost != null ? `<span class="save">${t("adet {0}", fmt(r.unit_cost))}</span>` : ""}</td>
      <td class="price">${money(r.market_price)}</td><td>${money(r.revenue)}</td>
      <td>${profitCell(r.profit)}${r.profit_pct != null ? `<span class="save">${pct(r.profit_pct)}</span>` : ""}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">${t("Bu meslekte tek adımlı tarif yok.")}</td></tr>`;
  const tierRow = (st, x, normal) => `<tr data-key="${x.item_key}" class="${normal ? "normal" : ""}">
      <td class="rank">${normal ? "" : st.step}</td>
      <td class="l">${named(x)}${normal ? "" : `<div class="mats">${st.materials.map(matLine).join("")}</div>`}</td>
      <td>${money(x.attempt_cost)}<span class="save">× ${t("{0} deneme", PF.format(x.tries))}${normal ? t(" (normal sonuç)") : ""}</span></td>
      <td>${money(x.craft_cost)}</td><td class="price">${money(x.market_price)}</td>
      <td>${x.best ? `<span class="badge ${x.best}">${t(x.best === "buy" ? "Al" : "Üret")}</span> ${money(x.cost)}` : `<span class="na">–</span>`}</td>
      <td>${profitCell(x.sell_profit)}</td></tr>`;
  const lastProfit = c => { const st = c.steps[c.steps.length - 1]; return [st.result, st.normal_result].map(x => x && x.sell_profit).filter(v => v != null); };
  document.getElementById("craftChains").innerHTML = craftData.chains.filter(inProf).map(c => `<details class="chain"${(state.craftOpen || {})[c.slot] ? " open" : ""} data-slot="${esc(c.slot)}">
      <summary><div class="ch"><h2>${esc(c.slot)}</h2><span class="muted">${esc(c.profession)}</span><span class="route">${t("En ucuz yol: {0}", esc(c.route))}</span>
        ${lastProfit(c).length ? `<span class="muted">${t("son adım üret-sat: {0}", lastProfit(c).map(v => (v > 0 ? "+" : "") + fmt(v)).join(" / "))}</span>` : ""}${npcMark(c)}</div></summary>
      <div class="tablebox"><table class="deals">
        <thead><tr><th>${t("Adım")}</th><th class="l">${t("Sonuç ve bir denemenin malzemesi")}</th><th>${t("Bir deneme")}</th>
          <th title="${t("Önceki kademenin en ucuz yolu + bu adımın beklenen malzemesi")}">${t("Üretim maliyeti")}</th><th>${t("Market fiyatı")}</th>
          <th>${t("En ucuz yol")}</th><th title="${t("Üretip satarsan, kesinti sonrası")}">${t("Üret-sat kârı")}</th></tr></thead>
        <tbody>${c.steps.map(st => tierRow(st, st.result, false) + (st.normal_result ? tierRow(st, st.normal_result, true) : "")).join("")}</tbody>
      </table></div></details>`).join("");
  document.querySelectorAll("#craftChains details.chain").forEach(d => d.ontoggle = () => {
    state.craftOpen = { ...(state.craftOpen || {}), [d.dataset.slot]: d.open };
  });
}

function setTitle() {
  const page = { deals: "Fırsatlar", craft: "Üretim", inv: "Envanterim", fav: "Favoriler" }[state.view];
  document.title = page ? `${t(page)} · Aion 2 Market` : "Aion 2 Market";
}

/* Each page keeps its own toolbar filters; state.q, state.cat, ... hold the open page's and
   state.pageFilters the others', so clearing a filter on Deals leaves Price changes as it was. */
const PAGE_FILTERS = { q: "", cat: "", minc: 0, favOnly: false };
function swapPageFilters(from, to) {
  state.pageFilters = state.pageFilters || {};
  state.pageFilters[from] = Object.fromEntries(Object.keys(PAGE_FILTERS).map(k => [k, state[k]]));
  Object.assign(state, PAGE_FILTERS, state.pageFilters[to]);
  document.getElementById("q").value = state.q;
  document.getElementById("cat").value = state.cat;
  document.getElementById("minc").value = state.minc;
  document.getElementById("favOnly").checked = !!state.favOnly;
  syncCatReset();
}

function setView(v) {
  swapPageFilters(state.view, v);
  state.view = v; save();
  const deals = v === "deals", craft = v === "craft", inv = v === "inv", fav = v === "fav";
  const changes = !deals && !craft && !inv && !fav;
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  document.getElementById("changesView").hidden = !changes;
  document.getElementById("cards").hidden = !changes;
  document.getElementById("toolbar").hidden = craft;
  document.getElementById("craftView").hidden = !craft;
  document.getElementById("dealsView").hidden = !deals;
  document.getElementById("invView").hidden = !inv;
  document.getElementById("favView").hidden = !fav;
  document.getElementById("favOnly").parentElement.hidden = fav;
  document.getElementById("period").hidden = !changes;
  document.getElementById("dir").hidden = !changes;
  document.getElementById("hideEmpty").parentElement.hidden = !changes;
  document.getElementById("slidingBox").hidden = !deals;
  setTitle();
  closeDrawer();
  refresh();
}

function renderChanges() {
  renderHead();
  const rows = sorted(filtered());
  const tb = document.getElementById("rows");
  tb.innerHTML = rows.map(r => {
    const name = r.name
      ? `<span class="nm ${gradeCls(r)}" title="${esc(r.official_name || "")}">${esc(r.name)}${r.custom_name ? `<span class="custom" title="${t("Senin verdiğin ad")}">●</span>` : ""}</span>`
      : `<span class="nm unnamed">${t("Adsız")}</span>`;
    const sub = esc(r.category || "");
    const ap = id => id === state.period ? "active-period" : "";
    return `<tr data-key="${r.item_key}" class="${r.listed ? "" : "stale"} ${selected === r.item_key ? "sel" : ""}">
      ${starCell(r)}
      <td class="l"><div class="item">${iconHtml(r.icon)}<div class="txt">${name}<span class="sub">${sub}</span></div></div></td>
      <td class="price">${r.suspect ? `<span class="warn" title="${r.suspect === "high"
          ? t("Son 30 günün fiyatlarının çok üstünde (7 gün ort. {0}); büyük ihtimalle tek bir uydurma ilan. Değişim gösterilmiyor.", fmt(r.typical))
          : t("Son 30 günün fiyatlarının çok altında (7 gün ort. {0}); fırsat da olabilir, hatalı ilan da.", fmt(r.typical))}">⚠</span> ` : ""}${fmt(r.price)}</td>
      <td class="${ap("prev")}" title="${t("Önceki: {0} · {1}", fmt(r.prev.price), fmtTime(r.prev.ts))}">${chg(r.prev.change)}</td>
      <td class="${ap("week")}" title="${t("7 gün önce: {0} · {1}", fmt(r.week.price), fmtTime(r.week.ts))}">${chg(r.week.change, r.week.partial, r.week.ts)}</td>
      <td class="${ap("month")}" title="${t("30 gün önce: {0} · {1}", fmt(r.month.price), fmtTime(r.month.ts))}">${chg(r.month.change, r.month.partial, r.month.ts)}</td>
      <td class="muted" title="${r.count ? "" : t("Son market listesinde yok. Son görüldüğünde {0} ilan, {1}", r.last_count, fmtTime(r.ts))}">${r.count}</td>
      <td>${spark(r.spark)}</td>
      <td class="muted" title="${fmtTime(r.ts)}">${ago(r.ts)}</td>
    </tr>`;
  }).join("");
  const empty = document.getElementById("empty");
  empty.hidden = rows.length > 0;
  empty.textContent = t(data.items.length ? "Filtrelere uyan item yok."
    : (servers.npcap || {}).installed === false
      ? "Henüz fiyat yok. Oyundaki pazar fiyatlarını kaydetmek için Npcap gerekli; sağ üstteki bağlantıdan indirebilirsin."
      : "Henüz fiyat yok. Oyunda pazarı aç ya da bir item ara; fiyatlar burada görünür.");
  renderCards(rows);
}

function renderCards(rows) {
  const listed = data.items.filter(r => r.listed);
  document.getElementById("c-count").textContent = NF.format(listed.length);
  document.getElementById("c-count-s").textContent = t("toplam {0} item kayıtlı", NF.format(data.items.length));
  const p = state.period;
  const downs = rows.filter(r => r[p].change < 0);
  document.getElementById("c-down").textContent = NF.format(downs.length);
  document.getElementById("c-down-s").textContent = t("{0} · görünen {1} item içinde", t(PERIOD_LABEL[p]), NF.format(rows.length));
  const top = downs.slice().sort((a, b) => a[p].change - b[p].change)[0];
  document.getElementById("c-top").textContent = top ? pct(Math.abs(top[p].change)) : "–";
  document.getElementById("c-top-s").textContent = top ? `${top.name || t("Adsız") + " " + top.item_key} · ${fmt(top[p].price)} → ${fmt(top.price)}` : t("düşen item yok");
  document.getElementById("c-last").textContent = data.latest ? fmtTime(data.latest) : "–";
  document.getElementById("c-last-s").textContent = data.first ? t("kayıtlar {0} tarihinden beri", fmtDate(data.first)) : " ";
  const days = data.first ? (data.now - data.first) / 86400 : 0;
  const foot = document.getElementById("foot");
  foot.innerHTML = help(foot, "Bu tablo hakkında",
    t("Fiyatlar birim fiyattır (Kinah). “Son listeleme” bir önceki market açılışıyla karşılaştırır. ") +
    (days < 30 ? t("<b>*</b> Kayıtlar {0} günlük; daha kısa sürenin değişimi gösteriliyor. ", PF.format(days)) : "") +
    t("Soluk satırlar en son market listesinde yer almayan (0 ilanlı) itemler; her zaman en altta gösterilir, fiyatları son görüldükleri andan."));
}

let servers = { servers: [], home: null, sync: {} };
const serverLabel = s => `${s.name || t("Sunucu {0}", s.server_id)}${s.mine ? t(" (senin)") : ""} · ${t("{0} item", NF.format(s.items))}`;

async function loadServers() {
  servers = await (await fetch("/api/servers", { cache: "no-store" })).json();
  const ids = servers.servers.map(s => s.server_id);
  if (!ids.includes(state.server)) state.server = servers.home || ids[0] || null;
  const sel = document.getElementById("server");
  sel.innerHTML = servers.servers.map(s => `<option value="${s.server_id}">${esc(serverLabel(s))}</option>`).join("");
  sel.value = state.server ?? "";
  document.querySelector("header .server").hidden = servers.servers.length < 2;
  const sy = servers.sync || {}, el = document.getElementById("sync");
  el.parentElement.hidden = !sy.configured;           // no shared store built in: nothing to switch
  el.className = "sync" + (!sy.enabled ? "" : sy.last_error ? " err" : sy.last_ok ? " ok" : "");
  el.textContent = !sy.enabled ? t("Ortak veri: kapalı")
    : sy.last_error ? t("Ortak veri hatası: {0}", sy.last_error)
    : sy.last_ok ? t("Ortak veri: eşitlendi {0}", ago(sy.last_ok)) : t("Ortak veri: bekleniyor");
  el.title = t("Ortak veri ayarı");
  document.getElementById("syncOn").checked = !!sy.enabled;
  const np = servers.npcap || {}, nel = document.getElementById("npcap");
  const broken = np.installed && np.error;
  nel.className = "npcap " + (broken ? "err" : np.installed ? "ok" : "off");
  nel.textContent = broken ? t("Canlı kayıt çalışmıyor")
    : np.installed ? t("Npcap kurulumu aktif") : t("Npcap kurulu değil · indir");
  nel.title = (broken ? t("Canlı kayıt çalışmıyor: {0}", np.error)
    : np.installed ? t("Oyunda açtığın pazar aramaları anında kaydediliyor.")
    : t("Npcap kurarsan oyunda açtığın pazar aramaları anında kaydedilir; en güncel fiyatlar böyle gelir."))
    + (np.names_error ? "\n" + t("Item adları NCSOFT'tan alınamıyor ({0}); ortak veriden gelmesi bekleniyor.", np.names_error) : "");
  if (np.installed) nel.removeAttribute("href"); else nel.href = np.url;
  const up = servers.update || {}, uel = document.getElementById("update");
  uel.hidden = !up.available;
  if (up.available) {
    uel.textContent = t("Yeni sürüm {0} · indir", up.latest.replace(/^v/i, ""));
    uel.title = t("Yeni sürüm çıktı, indirmek için tıkla");
    uel.href = up.url;
  }
}

async function refresh() {
  try {
    await loadServers();
    exclude = (await (await fetch("/api/settings", { cache: "no-store" })).json()).exclude;
    const qs = "?lang=" + LANG + (state.server ? "&server=" + state.server : "");
    const r = await fetch(`/api/items${qs}`, { cache: "no-store" });
    data = await r.json();
    if (state.view === "deals") dealsData = await (await fetch(`/api/deals${qs}`, { cache: "no-store" })).json();
    if (state.view === "craft") craftData = await (await fetch(`/api/crafting${qs}`, { cache: "no-store" })).json();
    if (state.view === "inv" || state.view === "fav") invData =await (await fetch(`/api/inventory${qs}`, { cache: "no-store" })).json();
    fillCategories();
    document.getElementById("status").textContent = t("Güncellendi {0}", new Date().toLocaleTimeString(LOC, { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    render();
    if (selected) openItem(selected, true);
  } catch (e) {
    document.getElementById("status").textContent = t("Sunucuya ulaşılamıyor");
  }
}

function fillCategories() {
  const counts = {};
  data.items.forEach(r => { if (r.category) counts[r.category] = (counts[r.category] || 0) + 1; });
  const cats = Object.keys(counts).sort((a, b) => a.localeCompare(b, "tr"));
  const sel = document.getElementById("cat");
  sel.innerHTML = `<option value="">${t("Tüm kategoriler")}</option>` +
    cats.map(c => `<option value="${esc(c)}">${esc(c)} (${counts[c]})</option>`).join("");
  sel.value = cats.includes(state.cat) ? state.cat : "";
  syncCatReset();
}

function syncCatReset() {
  const sel = document.getElementById("cat");
  document.getElementById("catReset").hidden = !sel.value;
  sel.classList.toggle("on", !!sel.value);
}

