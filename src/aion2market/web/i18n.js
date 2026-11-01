"use strict";
/* ---------- language ---------- */
// English texts keyed by the Turkish original; t() falls back to the Turkish text. {0}, {1}… are arguments.
const EN = {
  // tabs, header, toolbar
  "Fiyat değişimleri": "Price changes", "Fırsatlar": "Deals", "Üretim": "Crafting", "Envanterim": "My inventory",
  "Favoriler": "Favorites", "Market sunucusu": "Market server", "Sunucuya ad ver": "Name this server",
  "Oyundaki sunucu adı": "Server name in game", "Kaydet": "Save", "Yükleniyor…": "Loading…", "Yenile": "Refresh",
  "↻ Yenile": "↻ Refresh", "Dil": "Language",
  "Güncel listede": "In current listing", "Fiyatı düşen": "Price dropped", "En çok düşen": "Biggest drop",
  "Son market listesi": "Last market listing", "Son listeleme": "Last listing", "7 gün": "7 days", "30 gün": "30 days",
  "Item adı ya da kodu ara…": "Search item name or code…", "Tüm kategoriler": "All categories",
  "Kategori filtresini sıfırla": "Clear category filter", "Tümü": "All", "Sadece düşenler": "Falling only",
  "Sadece yükselenler": "Rising only", "En az bu kadar ilanı olan itemler": "Items with at least this many listings",
  "Min. ilan": "Min. listings",
  "Son market listesinde olmayan (0 ilanlı) itemler normalde listenin en altında gösterilir":
    "Items missing from the last market listing (0 listings) are normally shown at the bottom",
  "İlanı olmayanları gizle": "Hide items without listings", "Sadece adı olanlar": "Named only",
  "★ Sadece favoriler": "★ Favorites only",
  "Bir haftadır sürekli düşen itemlerin dibi daha aşağıda olabilir": "Items falling all week may not have bottomed yet",
  "Düşüşü sürenleri gizle": "Hide ongoing slides", "Görmek istemediğin itemleri gizle": "Hide items you don't want to see",
  "⊘ Gizle": "⊘ Hide", ", gösteriliyor": ", shown",
  // table headers
  "Item": "Item", "Birim fiyat": "Unit price", "İlan": "Listings", "Trend": "Trend", "Güncelleme": "Updated",
  "Adet": "Qty", "7 gün ort.": "7-day avg.", "7 gün ort. göre": "vs 7-day avg.",
  "Son 7 günün fiyat ortalaması (uydurma uç ilanlar hariç)": "Average price over the last 7 days (bogus outlier listings excluded)",
  "Adet × fiyat, market kesintisi düşülmüş": "Qty × price, after the market fee", "Toplam (net)": "Total (net)",
  "Öneri": "Advice", "Hedef": "Target", "Şu anki fiyatın hedefe uzaklığı": "How far the current price is from the target",
  "Hedefe kalan": "To target", "Sende": "You own", "Durum": "Status", "İndirim": "Discount",
  "Şimdi alıp 7 gün ortalamasından satarsan, market kesintisinden sonra adet başına kalan":
    "Per-unit profit if you buy now and sell at the 7-day average, after the market fee",
  "Al-sat kârı": "Flip profit", "30 gün aralığı": "30-day range", "Malzeme": "Material", "Malzeme fiyatı": "Material price",
  "Kaynak Odyle": "Source Odyle", "Odyle fiyatı": "Odyle price", "Üretimde tasarruf": "Crafting saving",
  "Dönüştürüp satma kârı": "Morph-and-sell profit", "Adım": "Step", "Üretim maliyeti": "Crafting cost",
  "Market fiyatı": "Market price", "Vergi sonrası kâr": "Profit after tax", "Toplam": "Total", "Birim": "Unit",
  "Sonuç ve bir denemenin malzemesi": "Result and one attempt's materials", "Bir deneme": "One attempt",
  "Önceki kademenin en ucuz yolu + bu adımın beklenen malzemesi": "Previous tier's cheapest route + this step's expected materials",
  "En ucuz yol": "Cheapest route", "Üretip satarsan, kesinti sonrası": "If you craft and sell, after the fee",
  "Üret-sat kârı": "Craft-and-sell profit",
  "Tek adımlı tarifler": "Single-step recipes", "Ekipman zincirleri": "Equipment chains",
  "Ürün ve malzemeler": "Product and materials", "Tür": "Type", "Malzeme maliyeti": "Material cost",
  "Satış (kesinti sonrası)": "Sale (after fee)", "Kâr": "Profit", "Hepsi": "All",
  "Mastery {0}": "Mastery {0}", "adet {0}": "{0} each", " (üret)": " (craft)",
  "Kendin üretmek marketten ucuz": "Cheaper to craft yourself than to buy",
  "NPC'den alınır, fiyatı bilinmiyor": "Bought from an NPC; price unknown",
  "NPC'den alınan malzemeler (Bound) fiyatı bilinmediği için maliyete katılmadı": "NPC materials (Bound) are left out of the cost because their price is unknown",
  "Bu meslekte tek adımlı tarif yok.": "No single-step recipes in this profession.",
  "son adım üret-sat: {0}": "last step craft-and-sell: {0}",
  // page sections
  "Envanter değeri": "Inventory value", "Satılmaya değer": "Worth selling", "Envanter zamanı": "Inventory time",
  "oyuna her girişte güncellenir": "updated every time you log in", "Satış günü": "Best day to sell",
  "7 günde yükselen": "Rose in 7 days", "Son listelemede yükselen": "Rose since last listing",
  "7 gün ort. üstünde": "Over 7-day avg.", "Değer": "Value", "Sat": "Sell", "Normal": "Normal", "Bekle": "Wait",
  "Kontrol et": "Check", "Hedefe yakınlık": "Closest to target", "7 günde düşen": "Fell in 7 days", "Ada göre": "By name",
  "Hedefi olanlar": "With target", "Hedefsiz": "No target",
  "Hedef fiyatı değiştirmek için satıra tıkla.": "Click a row to change its target price.",
  "Hedefi olan item hedefin altına inince bildirim gelir; hedefsiz favoriler 7 gün ortalamasının %20 altına inince bildirilir.":
    "Items with a target alert you when they drop below it; favorites without a target alert you when they fall 20% under their 7-day average.",
  "Puana göre": "By score", "Al-sat kârına göre": "By flip profit", "Sadece vergi sonrası kârlı olanlar": "Profitable after tax only",
  "Odyle dönüştürme farkı": "Odyle morph margin",
  "Odyle, aynı seviyedeki cevher, mücevher ve kütüğe 1:1 dönüştürülebilir.": "Odyle can be morphed 1:1 into the ore, gemstone and log of the same tier.",
  "Üretim için": "For crafting",
  ": malzeme Odyle'dan pahalıysa Odyle alıp dönüştürmek daha ucuz.": ": if the material costs more than its Odyle, buying Odyle and morphing is cheaper.",
  "Satış için": "For selling",
  ": Odyle alıp dönüştürüp malzemeyi satınca market kesintisinden sonra kalan. Dönüştürmenin kendi maliyeti (varsa) hesaba katılmadı.":
    ": what's left after the market fee when you buy Odyle, morph it and sell the material. The morph's own cost (if any) is not included.",
  "Öneriler sadece geçmiş market fiyatlarına dayanır; fiyatın daha da düşmeyeceğinin garantisi yoktur. Almadan önce oyundaki ilanı kontrol et.":
    "Suggestions are based only on past market prices; there's no guarantee the price won't fall further. Check the in-game listing before buying.",
  "Üretip satınca en kârlı olanlar": "Most profitable to craft and sell",
  // time and generic
  "az önce": "just now", "{0} dk önce": "{0} min ago", "{0} sa önce": "{0} h ago", "{0} gün önce": "{0} days ago",
  "son listelemeye göre": "vs last listing", "7 güne göre": "vs 7 days", "30 güne göre": "vs 30 days",
  "Karşılaştıracak eski kayıt yok": "No older record to compare with",
  "Veri {0} tarihinden beri; bu süreden kısa": "Data since {0}; shorter than this period",
  "Adsız": "Unnamed", "Adsız item": "Unnamed item", "{0} ilan": "{0} listings", "{0} item": "{0} items", "yok": "none",
  "Kaydedilemedi": "Couldn't save", "Filtrelere uyan item yok.": "No items match the filters.",
  "En ucuz ilan 30 günlük fiyatlara göre uç değerde": "The cheapest listing is an outlier against 30-day prices",
  // hide settings
  "Zırh": "Armor", "Silah": "Weapon", "Aksesuar": "Accessory", "Diğer": "Other",
  "Ayar kaydedilemedi": "Couldn't save the setting", "Her nadirlik": "Any grade", "her kategori": "any category",
  "tüm {0}": "all {0}", "Listede gösterme": "Hide from list",
  "Burada seçtiklerin listeden gizlenir. Ayar veritabanına kaydedilir; tarayıcı değişse de kalır.":
    "What you pick here is hidden from the list. The setting is saved in the database, so it stays even if you switch browsers.",
  "Yeni kural": "New rule",
  "Nadirlik <b>ve</b> kategori birlikte eşleşirse gizlenir. Birini boş bırakırsan “hepsi” sayılır.":
    "Hidden when grade <b>and</b> category both match. Leave one empty to mean “all”.",
  "Nadirlik": "Grade", "seçimi kaldır": "clear selection", "tümünü seç": "select all", "Kuralı ekle": "Add rule",
  "Bu kural {0} item'ı gizler": "This rule hides {0} items", "Nadirlik ya da kategori seç": "Pick a grade or category",
  "Kurallar": "Rules", "Kuralı sil": "Delete rule", "Henüz kural yok.": "No rules yet.",
  "Tek tek gizlenen itemler": "Individually hidden items", "Tekrar göster": "Show again",
  "Yok. Bir item'ı tek başına gizlemek için satırına tıkla, detay panelinde “Listede gösterme”yi seç.":
    "None. To hide a single item, click its row and choose “Hide from list” in the detail panel.",
  "Gizlenenleri geçici olarak göster": "Temporarily show hidden items", "Kural eklendi": "Rule added",
  "Kural silindi": "Rule deleted", "Item tekrar gösteriliyor": "Item shown again",
  // favorites
  "Favorilerden çıkar": "Remove from favorites", " (hedef {0})": " (target {0})", "Favorilere ekle": "Add to favorites",
  "Bu item'ın hedef fiyatı var; favorilerden çıkarılırsa bildirimler de durur. Devam edilsin mi?":
    "This item has a target price; removing it from favorites also stops its alerts. Continue?",
  "Favorilere eklendi": "Added to favorites", "Favorilerden çıkarıldı": "Removed from favorites",
  "{0} altında": "{0} under", "{0} üstünde": "{0} over", "{0} fark": "{0} to go", "Markette yok": "Not on market",
  "Hedefin altında": "Under target", "7 gün ort. {0} altında": "{0} under 7-day avg.", "Bekleniyor": "Waiting",
  "İzleniyor": "Watching", "Filtrelere uyan favori yok.": "No favorites match the filters.",
  "Henüz favorin yok. Diğer sayfalarda bir item'ın ☆ işaretine tıkla ya da item'ı açıp hedef fiyat gir.":
    "No favorites yet. Click an item's ☆ on the other pages, or open an item and enter a target price.",
  // deals
  "Şu an <b>kendi 7 günlük ortalama fiyatının en az {0} altında</b> olan ve <b>son listelemede ya da 7 günde en az {1} düşen</b> itemler. En az {2} ilanı ve {3} günlük geçmişi olmalı; uydurma uç fiyatlar sayılmaz. Sıralama: indirim × 30 günün dibine yakınlık × ilan sayısı; bir haftadır düşüşte olanlar ani düşüşlerin arkasına alınır.":
    "Items currently <b>at least {0} under their own 7-day average</b> that <b>fell at least {1} since the last listing or over 7 days</b>. They need at least {2} listings and {3} days of history; bogus outlier prices don't count. Ranking: discount × closeness to the 30-day bottom × listings; items sliding for a week rank behind sudden dips.",
  "Şu an normal fiyatının altında olan itemler: <b>{0}</b> öneri": "Items below their usual price right now: <b>{0}</b> suggestions",
  " (filtrelerle {0} tanesi gizli)": " ({0} hidden by filters)", "adet başı {0} ucuz": "{0} cheaper each",
  "Fiyatın 30 günlük aralıktaki yeri; en dipteki önce": "Where the price sits in its 30-day range; lowest first",
  "{0} getiri": "{0} return","30 günlük aralık (uç değerler hariç) {0} – {1}": "30-day range (outliers excluded) {0} – {1}",
  "Filtrelere uyan öneri yok.": "No suggestions match the filters.", "Şu an bu kurallara uyan fırsat yok.": "No deals match these rules right now.",
  "Son 30 gün: en ucuz gün <b>{0}</b>, en pahalı gün <b>{1}</b>.": "Last 30 days: cheapest day <b>{0}</b>, dearest day <b>{1}</b>.",
  "Odyle al, {0} ucuz": "buy Odyle, {0} cheaper", "malzemeyi al": "buy the material",
  "Odyle ve malzemelerin güncel fiyatı yok.": "No current prices for Odyle and the materials.",
  // inventory
  "{0} satılabilir item çeşidi · kesinti sonrası": "{0} sellable item types · after fee",
  '{0} item "Sat" önerisinde': '{0} items marked "Sell"', "henüz yok": "none yet",
  "fiyatlar en yüksek; en düşük {0} (fark {1})": "highest prices; lowest on {0} (spread {1})",
  "{0}'den listele": "list at {0}",
  "Envanter henüz yok. Oyuna giriş yaptığında kendiliğinden gelir.": "No inventory yet. It arrives by itself when you log in to the game.",
  '"Sat": fiyat 7 gün ortalamasının en az %10 üstünde ya da 7 günde en az %15 yükselmiş. "Bekle": 7 gün ortalamasının en az %10 altında. ':
    '"Sell": the price is at least 10% over its 7-day average or rose at least 15% in 7 days. "Wait": at least 10% under its 7-day average. ',
  "Önerilen fiyat, en ucuz ilanın 1 altı (en ucuz ilan uydurmaysa 7 gün ortalaması). Market kesintisi {0}. ":
    "The suggested price is 1 under the cheapest listing (the 7-day average if that listing is bogus). Market fee {0}. ",
  "Markette şu an ilanı olmayan {0} item listede yok: {1}.": "{0} items with no listings on the market right now aren't shown: {1}.",
  // crafting
  "Her kademe için en ucuz yol: marketten <b>al</b> ya da bir önceki kademenin en ucuz yolundan <b>üret</b>.":
    "The cheapest way to each tier: <b>buy</b> it on the market or <b>craft</b> it from the previous tier's cheapest route.",
  "Üretim maliyeti = bir denemenin malzemesi × beklenen deneme sayısı (her adımda %25 kombo ihtimali; 4. adımın normal sonucu ~1,06 denemede). Malzeme en ucuz yoldan hesaplanır: marketten, Odyle'dan dönüştürerek (mor) ya da kendi tarifinden üreterek (yeşil). NPC'den alınan (Bound) malzemelerin fiyatı bilinmediğinden maliyete katılmaz (+NPC). Kâr, market kesintisi ({0}) düşüldükten sonra. Tarifler aion2.app'in crafting veritabanından (NCSOFT verisi), kombo oranları topluluğun tablosundan; şansa bağlı olduğundan gerçek maliyet sapabilir. Fiyatlar şu anki market listesi.":
    "Crafting cost = one attempt's materials × expected attempts (25% combo chance per step; step 4's normal result takes ~1.06 attempts). Each material takes its cheapest route: the market, morphing from Odyle (purple) or crafting it from its own recipe (green). NPC (Bound) materials are left out of the cost because their price is unknown (+NPC). Profit is after the market fee ({0}). Recipes come from aion2.app's crafting database (NCSOFT data), combo rates from the community sheet; since it's luck-based the real cost can differ. Prices are the current market listing.",
  "markette yok": "not on market", "{0} · {1}. adım": "{0} · step {1}",
  "Şu an üretip satınca kâr eden kademe yok.": "No tier is profitable to craft and sell right now.",
  " (fiyat yok)": " (no price)", "Odyle'dan dönüştürmek daha ucuz": "Cheaper to morph from Odyle", "Marketten": "From the market",
  "{0} deneme": "{0} attempts", " (normal sonuç)": " (normal result)", "Al": "Buy", "Üret": "Craft",
  "En ucuz yol: {0}": "Cheapest route: {0}",
  // price changes page
  "Senin verdiğin ad": "Name you gave",
  "Son 30 günün fiyatlarının çok üstünde (7 gün ort. {0}); büyük ihtimalle tek bir uydurma ilan. Değişim gösterilmiyor.":
    "Far above the last 30 days' prices (7-day avg. {0}); most likely a single bogus listing. Change not shown.",
  "Son 30 günün fiyatlarının çok altında (7 gün ort. {0}); fırsat da olabilir, hatalı ilan da.":
    "Far below the last 30 days' prices (7-day avg. {0}); could be a bargain or a mistaken listing.",
  "Önceki: {0} · {1}": "Previous: {0} · {1}", "7 gün önce: {0} · {1}": "7 days ago: {0} · {1}",
  "30 gün önce: {0} · {1}": "30 days ago: {0} · {1}",
  "Son market listesinde yok. Son görüldüğünde {0} ilan, {1}": "Not in the last market listing. Last seen with {0} listings, {1}",
  "Henüz fiyat yok. Oyunda pazarı aç ya da bir item ara; fiyatlar burada görünür.":
    "No prices yet. Open the market or search an item in game; prices show up here.",
  "Henüz fiyat yok. Oyundaki pazar fiyatlarını kaydetmek için Npcap gerekli; sağ üstteki bağlantıdan indirebilirsin.":
    "No prices yet. Recording in-game market prices needs Npcap; you can download it from the link at the top right.",
  "Bu tablo hakkında": "About this table", "Nasıl seçiliyor?": "How are they picked?", "Nasıl hesaplanıyor?": "How is this calculated?",
  "Öneriler nasıl hesaplanıyor?": "How is the advice calculated?", "Bildirim ne zaman gelir?": "When do alerts come?",
  "Filtreler": "Filters", "Item ara…": "Search items…",
  "toplam {0} item kayıtlı": "{0} items recorded in total", "{0} · görünen {1} item içinde": "{0} · among {1} shown items",
  "düşen item yok": "no item fell", "kayıtlar {0} tarihinden beri": "records since {0}",
  "Fiyatlar birim fiyattır (Kinah). “Son listeleme” bir önceki market açılışıyla karşılaştırır. ":
    "Prices are unit prices (Kinah). “Last listing” compares with the previous market opening. ",
  "<b>*</b> Kayıtlar {0} günlük; daha kısa sürenin değişimi gösteriliyor. ":
    "<b>*</b> Records span {0} days; the change over that shorter period is shown. ",
  "Soluk satırlar en son market listesinde yer almayan (0 ilanlı) itemler; her zaman en altta gösterilir, fiyatları son görüldükleri andan.":
    "Faded rows are items missing from the latest market listing (0 listings); they're always shown at the bottom, with prices from when they were last seen.",
  // servers and status
  "Sunucu {0}": "Server {0}", " (senin)": " (yours)", "Ortak veri: kapalı": "Shared data: off",
  "Ortak veri hatası: {0}": "Shared data error: {0}", "Ortak veri: eşitlendi {0}": "Shared data: synced {0}",
  "Ortak veri: bekleniyor": "Shared data: waiting", "Ortak veri ayarı": "Shared data setting",
  "Ortak veri açıldı": "Shared data on", "Ortak veri kapatıldı": "Shared data off",
  "Fiyatları diğer oyuncularla paylaş": "Share prices with other players",
  "Açıkken oyunda gördüğün market fiyatları ortak depoya gönderilir, diğer oyuncuların gördükleri de sana gelir. Böylece market, sen açmasan da güncel kalır. Karakter, hesap ya da oturum bilgisi gönderilmez.":
    "While on, the market prices you see in game go to a shared store, and what other players see comes to you, so the market stays current even when you don't open it. No character, account or session data is sent.",
"Npcap kurulumu aktif": "Npcap installation active",
  "Canlı kayıt çalışmıyor": "Live recording not working",
  "Yeni sürüm {0} · indir": "New version {0} · download",
  "Yeni sürüm çıktı, indirmek için tıkla": "A new version is out, click to download",
  "Canlı kayıt çalışmıyor: {0}": "Live recording not working: {0}",
  "Item adları NCSOFT'tan alınamıyor ({0}); ortak veriden gelmesi bekleniyor.":
    "Item names can't be fetched from NCSOFT ({0}); waiting for them from shared data.",
  "Npcap kurulu değil · indir": "Npcap not installed · download",
  "Oyunda açtığın pazar aramaları anında kaydediliyor.": "Market searches you open in game are recorded instantly.",
  "Npcap kurarsan oyunda açtığın pazar aramaları anında kaydedilir; en güncel fiyatlar böyle gelir.":
    "With Npcap installed, market searches you open in game are recorded instantly; that's how the freshest prices come in.",
"Güncellendi {0}": "Updated {0}",
  "Sunucuya ulaşılamıyor": "Can't reach the server", "Sunucu adı kaydedildi": "Server name saved",
  // detail drawer
  "Kapat": "Close", "Bu item'a bir ad ver": "Give this item a name",
  "Resmi item verisinde ve aion2.exchange'de bu item'ın adı yok; adını sen verebilirsin.":
    "Neither the official item data nor aion2.exchange has a name for this item; you can name it yourself.",
  "Ad aion2.exchange'den: <b>{0}</b> (NCSoft'un resmi verisinde yok). İstersen kendi adını ver; boş bırakıp kaydedersen bu ada döner.":
    "Name from aion2.exchange: <b>{0}</b> (not in NCSoft's official data). You can give it your own name; saving it empty goes back to this one.",
  "Resmi ad: <b>{0}</b>. İstersen kendi adını ver; boş bırakıp kaydedersen resmi ada döner.":
    "Official name: <b>{0}</b>. You can give it your own name; saving it empty goes back to the official one.",
  "Kinah / adet": "Kinah / unit",
  "Son 30 günün fiyatlarının çok üstünde (7 gün ort. {0}); büyük ihtimalle tek bir uydurma ilan, değişim hesaplanmadı.":
    "Far above the last 30 days' prices (7-day avg. {0}); most likely a single bogus listing, change not calculated.",
  "30 gün en düşük {0} · en yüksek {1} · {2} kayıt": "30-day low {0} · high {1} · {2} records",
  " · camgöbeği bant: 6 saatlik en düşük–en yüksek (aion2.exchange)": " · cyan band: 6-hour low–high (aion2.exchange)",
  " · {0} uç değer (30 günlük medyan {1}'in ×{2} üstü ya da ¼ altı) gösterilmedi":
    " · {0} outliers (over ×{2} or under ¼ of the 30-day median {1}) not shown",
  "Haftalık düzen (bu item)": "Weekly pattern (this item)",
  "En ucuz <b>{0}</b>, en pahalı <b>{1}</b> (fark {2}). Son 30 güne dayanır; her gün için birkaç örnek var, kesin değildir.":
    "Cheapest on <b>{0}</b>, dearest on <b>{1}</b> (spread {2}). Based on the last 30 days with only a few samples per day, so not definitive.",
  "Listede tekrar göster": "Show in list again", "⊘ Listede gösterme": "⊘ Hide from list",
  "Bu item bir gizleme kuralına uyuyor.": "This item matches a hide rule.", "Favori ve hedef fiyat": "Favorite and target price",
  "Hedef birim fiyat (ör. 2.5m)": "Target unit price (e.g. 2.5m)", "Geçersiz fiyat": "Invalid price", "Hedefi kaydet": "Save target", "★ Favorilere ekle": "★ Add to favorites",
  "Hedef fiyat girersen fiyat hedefin altına inince, girmezsen 7 gün ortalamasının %20 altına inince bildirim gelir.":
    "With a target price you're alerted when the price drops below it; without one, when it falls 20% under its 7-day average.",
  "Son aramadaki ilanlar": "Listings from the last search",
  "Bu item oyunda henüz aranmadı. Aradığında ilanlar burada görünür.": "This item hasn't been searched in game yet. Its listings show up here once you do.",
  "Ad kaydedildi": "Name saved", "Resmi ada dönüldü": "Back to the official name", "Ad silindi": "Name removed",
  "Hedef kaydedildi": "Target saved", "Listeden gizlendi": "Hidden from list", "Listede tekrar gösteriliyor": "Shown in list again",
  "Grafik için en az iki kayıt gerekli.": "At least two records are needed for a chart.", " · aralık {0}–{1}": " · range {0}–{1}",
};
const LANGS = ["tr", "en"];
let LANG = "tr", LOC = "tr-TR", NF, PF1, PF2;
const t = (s, ...a) => ((LANG === "en" && EN[s]) || s).replace(/\{(\d)\}/g, (_, i) => a[i]);
const pct = v => LANG === "en" ? PF.format(v) + "%" : "%" + PF.format(v);       // Turkish puts % first
const pctRaw = v => LANG === "en" ? v + "%" : "%" + v;
function setLocale(lang) {
  LANG = lang; LOC = lang === "en" ? "en-US" : "tr-TR";
  NF = new Intl.NumberFormat(LOC, { maximumFractionDigits: 0 });
  PF1 = new Intl.NumberFormat(LOC, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  PF2 = new Intl.NumberFormat(LOC, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  document.documentElement.lang = lang;
}
// The page's own static texts and titles, remembered in Turkish so they can be switched back and forth.
const STATIC = [];
{
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walk.nextNode());) if (n.nodeValue.trim() && n.parentElement.tagName !== "SCRIPT") STATIC.push([n, n.nodeValue]);
  document.querySelectorAll("[title], [placeholder]").forEach(el =>
    ["title", "placeholder"].forEach(a => { if (el.hasAttribute(a)) STATIC.push([el, el.getAttribute(a), a]); }));
}
function translateStatic() {
  STATIC.forEach(([n, orig, attr]) => {
    if (attr) n.setAttribute(attr, t(orig));
    else n.nodeValue = orig.replace(orig.trim(), t(orig.trim()));
  });
}
