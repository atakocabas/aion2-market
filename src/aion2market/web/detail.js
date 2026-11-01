"use strict";
/* ---------- detail drawer ---------- */
const drawer = document.getElementById("drawer"), scrim = document.getElementById("scrim");

function closeDrawer() {
  selected = null;
  drawer.classList.remove("on"); scrim.classList.remove("on");
  drawer.setAttribute("aria-hidden", "true");
  render();
}

async function openItem(key, quiet) {
  selected = key;
  const row = data.items.find(r => r.item_key === key);
  const d = await (await fetch(`/api/item/${key}?lang=${LANG}${state.server ? "&server=" + state.server : ""}`, { cache: "no-store" })).json();
  if (quiet && document.activeElement && drawer.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  const statBox = (k, x) => x ? `<div class="stat"><div class="k">${k}</div><div class="v">${chg(x.change, x.partial, x.ts)}</div><div class="s">${fmt(x.price)} · ${fmtTime(x.ts)}</div></div>` : "";
  const since30 = Date.now() / 1000 - 30 * 86400;
  // Outliers (bogus listings far from the 30-day median) stay out of the chart and the low/high.
  const tp = d.typical, normal = v => !tp || (v >= tp.low && v <= tp.high);
  const clip = v => tp ? Math.min(tp.high, Math.max(tp.low, v)) : v;
  const shownHistory = d.history.filter(h => normal(h[1]));
  const shownRanges = (d.ranges || []).map(r => [r[0], r[1], clip(r[2]), clip(r[3]), ...r.slice(4)]);
  const hiddenPoints = d.history.length - shownHistory.length;
  const ranges30 = shownRanges.filter(r => r[0] >= since30);
  const prices30 = [...shownHistory.filter(h => h[0] >= since30).map(h => h[1]),
                    ...ranges30.map(r => r[2]), ...ranges30.map(r => r[3])];       // band extremes count too
  const lst = d.listings;
  drawer.innerHTML = `
    <div class="top">
      ${iconHtml(d.info && d.info.icon, true)}
      <div>
        <div class="brand">Item ${esc(key)}</div>
        <h2 class="${gradeCls(d.info)}">${d.name ? esc(d.name) : `<span class="muted">${t("Adsız item")}</span>`}</h2>
        ${d.info ? `<div style="margin-top:4px"><span class="chip ${gradeCls(d.info)}">${esc(d.info.grade_name || "")}</span><span class="muted">${esc(d.info.category || "")}</span></div>` : ""}
      </div>
      <button class="x" id="dx" title="${t("Kapat")}">✕</button>
    </div>
    <div class="namebox">
      <input id="nm" placeholder="${d.info && d.info.name ? esc(d.info.name) : t("Bu item'a bir ad ver")}" value="${d.custom_name ? esc(d.name) : ""}" maxlength="80">
      <button class="btn" id="nmsave">${t("Kaydet")}</button>
    </div>
    <div class="hint">${!d.info || !d.info.name
      ? t("Resmi item verisinde ve aion2.exchange'de bu item'ın adı yok; adını sen verebilirsin.")
      : d.info.source === "aion2.exchange"
        ? t("Ad aion2.exchange'den: <b>{0}</b> (NCSoft'un resmi verisinde yok). İstersen kendi adını ver; boş bırakıp kaydedersen bu ada döner.", esc(d.info.name))
        : t("Resmi ad: <b>{0}</b>. İstersen kendi adını ver; boş bırakıp kaydedersen resmi ada döner.", esc(d.info.name))}</div>
    <div class="bigprice">${row ? fmt(row.price) : "–"} <small>${t("Kinah / adet")} · ${row ? t("{0} ilan", row.count) : ""} · ${row ? ago(row.ts) : ""}</small></div>
    ${row && row.suspect ? `<div class="hint"><span class="warn">⚠</span> ${row.suspect === "high"
      ? t("Son 30 günün fiyatlarının çok üstünde (7 gün ort. {0}); büyük ihtimalle tek bir uydurma ilan, değişim hesaplanmadı.", fmt(row.typical))
      : t("Son 30 günün fiyatlarının çok altında (7 gün ort. {0}); fırsat da olabilir, hatalı ilan da.", fmt(row.typical))}</div>` : ""}
    ${row ? `<div class="stats">${statBox(t("Son listeleme"), row.prev)}${statBox(t("7 gün"), row.week)}${statBox(t("30 gün"), row.month)}</div>` : ""}
    <div class="chart" id="chart"></div>
    ${prices30.length ? `<div class="hint" style="margin-top:6px">${t("30 gün en düşük {0} · en yüksek {1} · {2} kayıt", fmt(Math.min(...prices30)), fmt(Math.max(...prices30)), d.history.length)}${ranges30.length ? t(" · camgöbeği bant: 6 saatlik en düşük–en yüksek (aion2.exchange)") : ""}${
      hiddenPoints ? t(" · {0} uç değer (30 günlük medyan {1}'in ×{2} üstü ya da ¼ altı) gösterilmedi", hiddenPoints, fmt(tp.median), (tp.high / tp.median).toFixed(0)) : ""}</div>` : ""}
    ${d.weekdays ? `<h3>${t("Haftalık düzen (bu item)")}</h3><div class="week" style="margin-bottom:4px">${d.weekdays.by_day.map((v, i) =>
        `<div class="d ${v != null && d.weekdays.cheapest_day === i ? "cheap"
          : v != null && d.weekdays.dearest_day === i ? "dear" : ""}">
          <div class="n">${DAYS[LANG][i]}</div><div class="v">${v == null ? "–" : (v > 0 ? "+" : "") + PF.format(v) + "%"}</div></div>`).join("")}</div>
      <div class="hint">${t("En ucuz <b>{0}</b>, en pahalı <b>{1}</b> (fark {2}). Son 30 güne dayanır; her gün için birkaç örnek var, kesin değildir.", d.weekdays.cheapest, d.weekdays.dearest, pct(d.weekdays.spread))}</div>` : ""}
    <div class="actions" style="display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap">
      <button class="btn" id="hideOne">${t(exclude.items.includes(key) ? "Listede tekrar göster" : "⊘ Listede gösterme")}</button>
      ${row && !exclude.items.includes(key) && exclude.rules.some(rule => ruleMatches(rule, row))
        ? `<span class="hint">${t("Bu item bir gizleme kuralına uyuyor.")}</span>` : ""}
    </div>
    <h3>${t("Favori ve hedef fiyat")}</h3>
    <div class="watch">
      <input id="tg" type="text" inputmode="decimal" autocomplete="off" placeholder="${t("Hedef birim fiyat (ör. 2.5m)")}" value="${d.watch && d.watch.target != null ? d.watch.target : ""}">
      <span class="hint" id="tgv"></span>
      <button class="btn gold" id="wsave">${t(d.watch ? "Hedefi kaydet" : "★ Favorilere ekle")}</button>
      ${d.watch ? `<button class="btn" id="wdel">${t("Favorilerden çıkar")}</button>` : ""}
    </div>
    <div class="hint" style="margin-top:6px">${t("Hedef fiyat girersen fiyat hedefin altına inince, girmezsen 7 gün ortalamasının %20 altına inince bildirim gelir.")}</div>
    <h3>${t("Son aramadaki ilanlar")}</h3>
    ${lst.rows.length ? `<div class="hint">${fmtTime(lst.ts)} · ${t("{0} ilan", lst.total)}</div>
      <table class="mini"><tr><th class="l">${t("Adet")}</th><th>${t("Toplam")}</th><th>${t("Birim")}</th></tr>
      ${lst.rows.map(r => `<tr><td class="l">${r[0]}</td><td>${fmt(r[1])}</td><td class="price">${fmt(r[2])}</td></tr>`).join("")}</table>`
      : `<div class="hint">${t("Bu item oyunda henüz aranmadı. Aradığında ilanlar burada görünür.")}</div>`}
  `;
  drawChart(document.getElementById("chart"), shownHistory, shownRanges);
  document.getElementById("dx").onclick = closeDrawer;
  document.getElementById("nmsave").onclick = () => {
    const v = document.getElementById("nm").value.trim();
    post("/api/name", { item_key: key, name: v }, t(v ? "Ad kaydedildi" : (d.info ? "Resmi ada dönüldü" : "Ad silindi")));
  };
  document.getElementById("nm").onkeydown = e => { if (e.key === "Enter") document.getElementById("nmsave").click(); };
  const tg = document.getElementById("tg"), tgv = document.getElementById("tgv");
  tg.oninput = () => {
    const v = parsePrice(tg.value);
    tgv.textContent = v == null ? "" : Number.isNaN(v) ? t("Geçersiz fiyat") : "= " + fmt(v);
  };
  tg.onkeydown = e => { if (e.key === "Enter") document.getElementById("wsave").click(); };
  document.getElementById("wsave").onclick = () => {
    const v = parsePrice(tg.value);
    if (Number.isNaN(v)) return toast(t("Geçersiz fiyat"));
    post("/api/watch", { item_key: key, target: v ?? "" }, t(d.watch ? "Hedef kaydedildi" : "Favorilere eklendi"));
  };
  document.getElementById("hideOne").onclick = () => {
    const hiding = !exclude.items.includes(key);
    exclude.items = hiding ? [...exclude.items, key] : exclude.items.filter(k => k !== key);
    saveExclude(t(hiding ? "Listeden gizlendi" : "Listede tekrar gösteriliyor")).then(() => openItem(key, true));
  };
  const del = document.getElementById("wdel");
  if (del) del.onclick = () => post("/api/watch", { item_key: key, watch: false }, t("Favorilerden çıkarıldı"));
  if (!quiet) {
    drawer.classList.add("on"); scrim.classList.add("on");
    drawer.setAttribute("aria-hidden", "false");
    drawer.scrollTop = 0;
    render();
  }
}

function drawChart(box, history, ranges = []) {
  if (history.length < 2) {
    box.innerHTML = `<div class="hint" style="padding:30px 0;text-align:center">${t("Grafik için en az iki kayıt gerekli.")}</div>`;
    return;
  }
  const W = 480, H = 190, L = 58, R = 10, T = 12, B = 24;
  // ranges: [ts, span, low, high, avg, close, listings] — drawn as a low–high band behind the price line
  const xs = [...history.map(h => h[0]), ...ranges.map(r => r[0]), ...ranges.map(r => r[0] + r[1])];
  const ys = [...history.map(h => h[1]), ...ranges.map(r => r[2]), ...ranges.map(r => r[3])];
  const x0 = Math.min(...xs), x1 = Math.max(...xs), lo = Math.min(...ys), hi = Math.max(...ys);
  const pad = (hi - lo) * 0.12 || hi * 0.02 || 1;
  const yl = lo - pad, yh = hi + pad;
  const X = t => L + (t - x0) / ((x1 - x0) || 1) * (W - L - R);
  const Y = v => T + (1 - (v - yl) / (yh - yl)) * (H - T - B);
  const pts = history.map(h => [X(h[0]), Y(h[1])]);
  const line = pts.map(p => p.map(n => n.toFixed(1)).join(",")).join(" ");
  const area = `${L},${H - B} ${line} ${(W - R)},${H - B}`;
  const ticks = [hi, (hi + lo) / 2, lo].map(v => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#323a5c" stroke-dasharray="3 4"/>` +
    `<text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end" fill="#9ba3c2" font-size="11">${fmt(v)}</text>`).join("");
  const mid = r => X(r[0] + r[1] / 2);
  const band = ranges.length > 1
    ? `<polygon points="${[...ranges.map(r => `${mid(r).toFixed(1)},${Y(r[3]).toFixed(1)}`),
                          ...ranges.slice().reverse().map(r => `${mid(r).toFixed(1)},${Y(r[2]).toFixed(1)}`)].join(" ")}"
         fill="rgba(134,211,227,.12)" stroke="rgba(134,211,227,.35)" stroke-width="1" vector-effect="non-scaling-stroke"/>`
    : "";
  const rangeAt = t => ranges.find(r => t >= r[0] && t <= r[0] + r[1]);
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#e7c47c" stop-opacity=".25"/><stop offset="1" stop-color="#e7c47c" stop-opacity="0"/></linearGradient></defs>
      ${ticks}
      ${band}
      <polygon points="${area}" fill="url(#g)"/>
      <polyline points="${line}" fill="none" stroke="#e7c47c" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
      <text x="${L}" y="${H - 6}" fill="#9ba3c2" font-size="11">${fmtTime(x0)}</text>
      <text x="${W - R}" y="${H - 6}" fill="#9ba3c2" font-size="11" text-anchor="end">${fmtTime(x1)}</text>
      <circle id="dot" r="4" fill="#e7c47c" stroke="#121626" stroke-width="2" style="display:none"/>
    </svg><div class="tip" id="tip"></div>`;
  const svg = box.querySelector("svg"), dot = box.querySelector("#dot"), tip = box.querySelector("#tip");
  svg.addEventListener("mousemove", e => {
    const r = svg.getBoundingClientRect(), mx = (e.clientX - r.left) / r.width * W;
    let i = 0;
    pts.forEach((p, j) => { if (Math.abs(p[0] - mx) < Math.abs(pts[i][0] - mx)) i = j; });
    dot.setAttribute("cx", pts[i][0]); dot.setAttribute("cy", pts[i][1]); dot.style.display = "";
    tip.style.display = "block";
    tip.style.left = (pts[i][0] / W * r.width + 10) + "px";
    tip.style.top = (pts[i][1] / H * r.height + 10) + "px";
    const rg = rangeAt(history[i][0]) || rangeAt(history[i][0] - 1);
    tip.textContent = `${fmt(history[i][1])} · ${t("{0} ilan", history[i][2])} · ${fmtTime(history[i][0])}` +
      (rg ? t(" · aralık {0}–{1}", fmt(rg[2]), fmt(rg[3])) : "");
  });
  svg.addEventListener("mouseleave", () => { dot.style.display = "none"; tip.style.display = "none"; });
}

async function post(url, body, okMsg) {
  try {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(r.status);
    toast(okMsg);
    await refresh();
  } catch (e) {
    toast(t("Kaydedilemedi"));
  }
}

let toastTimer;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("on");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), 1800);
}

