# aion2market

Aion 2 market fiyat takipçisi. Faz 0: oyunun TCP trafiğini Npcap ile **pasif** olarak kaydeder (oyuna paket gönderilmez, bellek okunmaz).

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Npcap kurulu olmalı (WinPcap uyumlu mod açık). Npcap "yalnızca yönetici" modunda kurulduysa terminali Yönetici olarak aç.

## Kullanım

```bash
# Oyunun süreçlerini ve bağlantılarını göster
.venv\Scripts\python -m aion2market.capture --list

# Kaydet (Ctrl+C ile dur); 443 = TLS telemetri, oyun protokolü değil
.venv\Scripts\python -m aion2market.capture --exclude-port 443
```

Varsayılan ağ arayüzü ve loopback birlikte dinlenir. ExitLag gibi araçlar oyunu `127.0.0.1` üzerindeki yerel bir proxy'ye bağladığı için oyun trafiği loopback'ten geçer.

Çıktı `captures/<tarih>/` klasörüne yazılır:

- `raw.pcap`: sadece oyun paketleri (Wireshark'ta açılabilir)
- `index.jsonl`: her veri parçasının zamanı, yönü ve akıştaki konumu
- `connNN_*/c2s.bin`, `s2c.bin`: sıraya dizilmiş ham akış (istemciden sunucuya / sunucudan istemciye). Kayıp paketlerin yeri sıfırla doldurulur ve `index.jsonl` dosyasına `gap` olarak yazılır.

## Protokol ve rapor

Sunucudan gelen akışın çerçeve yapısı ve LZ4 açma işlemi [protocol.py](src/aion2market/protocol.py) içinde. İstemciden giden akış anahtar değişiminden sonra şifreli olduğu için çözülmüyor.

```bash
# Hangi opcode ne zaman, kaç kez, ne boyutta geldi
.venv\Scripts\python -m aion2market.report captures\<kayıt>

# Belirli opcode'ların örnek içeriği (bir saatten sonrası için)
.venv\Scripts\python -m aion2market.report captures\<kayıt> --after 04:44:20 --opcode 0x8a05
```

## Bulgular (29 Ekim 2026)

- Market araması (Pure Odyle, 82.000, 04:52–04:53) oyun akışında görünmüyor. Fiyat şu biçimlerde arandı: u32, u64, varint, float, double, zigzag, ×10, ×100 ve 256 tek baytlık XOR anahtarı. Hiçbirinde eşleşme yok.
- **Market verisi HTTPS ile `qos-api.g.nc.com` (34.117.142.223) adresinden geliyor.** Zamanlamalı testte iki arama (04:57:58 ve 04:59:15) bu sunucuda iki ayrı patlamaya denk geldi: her seferinde 3 yeni bağlantı açıldı, ~80-105 KB veri indi ve ~32-35 KB veri gitti. Oyun akışı bu anlarda değişmedi. Sunucu adındaki "qos" yanıltıcı.
- TLS parmak izi OpenSSL'e ait: GREASE yok, ALPN `http/1.1`, uzantı 49 (post_handshake_auth) var. Yani istekler CEF'ten değil, oyunun `libcurl.dll` + OpenSSL ile yaptığı çağrılardan geliyor. İçerik pasif dinlemeyle okunamaz; denenecek yol curl'ün `SSLKEYLOGFILE` desteği.
- Oyunun UDP portlarında trafik görülmedi.

## Market trafiğini çözme (SSLKEYLOGFILE)

Oyunun libcurl/OpenSSL'i `SSLKEYLOGFILE` kullanıcı ortam değişkenine uyuyor ve TLS 1.3 oturum anahtarlarını dosyaya yazıyor. Değişken ayarlandıktan sonra Steam'in tamamen kapatılıp yeniden açılması gerekir.

```powershell
[Environment]::SetEnvironmentVariable('SSLKEYLOGFILE', "$PWD\captures\sslkeys.log", 'User')
# geri almak için:
[Environment]::SetEnvironmentVariable('SSLKEYLOGFILE', $null, 'User')
```

```bash
.venv\Scripts\python -m aion2market.capture
.venv\Scripts\python -m aion2market.tls13 captures\<kayıt> captures\sslkeys.log
```

Her bağlantı klasörüne `c2s.plain`, `s2c.plain` ve `http.txt` yazılır. **Bu dosyalarda ve `sslkeys.log`'da oturum token'ları var; paylaşma.** `captures/` git'e girmez.

### Market API'si (`qos-api.g.nc.com`, JSON)

| İstek | Ne döner |
|---|---|
| `POST /trade/v1.0/sales/valid/summary/min_unit_price` `{"game_server_id":12306}` | Sunucudaki **tüm** itemlerin en düşük birim fiyatı ve ilan sayısı (~560 item) |
| aynı uç + `"game_item_keys":"610610015"` | Tek item için aynı özet |
| `POST /trade/v1.0/sales/valid/pages` `{"game_server_id":"12306","page_no":1,"page_size":100,"game_item_keys":"…","sort":{"key":"SalePrice","order_by":"ASC"}}` | İlanlar: `game_item_quantity`, `sale_price`, `unit_price`, `effective_from/to`, `grade_id`, `category_id`; `has_next_page` |
| `GET /trade/v1.0/policies` | Komisyon oranları, sıralama/arama seçenekleri |
| `GET /trade/v1.0/me/earnings`, `/me/sales`, `/me/favorites` | Kendi satışların |

- Doğrulama (29 Ekim 2026, 23:37 sunucu saati): `610610015` için 80 ilan vardı. 1 adetlik en ucuz ilan 81.999 idi; bu, oyunda not edilen Pure Odyle 82.000 ile uyuşuyor. Özetteki `min_unit_price` 56.500 ise yığın ilanlarının birim fiyatı.
- `game_server_id` iki biçimde geçiyor: `2306` (karakter sunucusu) ve `12306` (market). Para birimi item'ı `930100031`.
- Yanıtlarda item adı yok, sadece `game_item_key` var. Ad eşlemesi ayrıca tutulmalı.

## Fiyat servisi (Faz 2)

443 trafiğini pasif dinler, TLS sunucu adı `qos-api.g.nc.com` olan bağlantıları anahtar dosyasıyla çözer ve `/trade/v1.0/sales/` yanıtlarını `data/market.db` dosyasına yazar. Oyunda market ekranını açtığında ya da bir item aradığında kayıt düşer. Servis kendisi hiçbir istek göndermez.

```bash
# Canlı (Ctrl+C ile dur). Anahtar dosyası SSLKEYLOGFILE değişkeninden bulunur.
.venv\Scripts\python -m aion2market.service run

# Eski kayıtları veritabanına aktar (aynı veri iki kez yazılmaz)
.venv\Scripts\python -m aion2market.service replay captures\<kayıt>

# Item koduna ad ver, son fiyatları gör
.venv\Scripts\python -m aion2market.service name 610610015 "Pure Odyle"
.venv\Scripts\python -m aion2market.service show odyle
```

Tablolar:
- `price_snapshots`: item başına en düşük birim fiyat ve ilan sayısı. Market açıldığında tüm itemler için (~560) bir kez gelir.
- `listings`: arama sonucu sayfasındaki her ilan (adet, toplam, birim fiyat).
- `items`: senin verdiğin adlar.
- `responses`: ham JSON gövdeleri (başlıklar ve token'lar saklanmaz), ileride yeniden işlemek için.

Zaman damgası, yanıttaki sunucu saatinden (`loaded`) alınır.

## MCP sunucusu (Faz 3)

`data/market.db`'yi okuyan stdio MCP sunucusu. Proje kökündeki `.mcp.json` sayesinde bu klasörde açılan Claude Code oturumları onu görür (ilk seferde onay ister).

```bash
.venv\Scripts\python -m aion2market.mcp_server
```

| Araç | Ne yapar |
|---|---|
| `get_price(item)` | Son bilinen fiyat: piyasa geneli en düşük birim fiyat + son aramadaki 1 adetlik en ucuz ilan |
| `price_history(item, days=7)` | Kaydedilen fiyat noktaları (değişmeyen ardışık noktalar atlanır) |
| `cheapest_listings(item, limit=10, quantity=None)` | Son aramadaki en ucuz ilanlar; `quantity=1` sadece tekli ilanlar |
| `watch_item(item, target_price=None)` / `unwatch_item(item)` / `list_watchlist()` | İzleme listesi; hedef fiyatın altına inen item işaretlenir |
| `name_item(item_key, name)` / `recent_searches()` | Koda ad verme; son aranan itemlerin kodları |
| `recent_alerts(limit=10)` | Gönderilen fiyat bildirimleri |

`item` bir ad (kısmi, büyük/küçük harf duyarsız) ya da sayısal `game_item_key` olabilir. Her yanıt fiyatın ne kadar eski olduğunu (`as_of`, `age_minutes`) içerir; fiyatlar yalnızca servis çalışırken oyunda market açıldığında güncellenir. Veritabanı yolu `AION2_DB` ile değiştirilebilir.

## Fiyat arayüzü

Tüm itemleri ve fiyat değişimlerini gösteren yerel web sayfası. Sadece bu bilgisayardan erişilir (`127.0.0.1`), internet gerekmez.

```bash
.venv\Scripts\python -m aion2market.dashboard      # tarayıcıda http://127.0.0.1:8765 açılır
```

- Her item için üç değişim: **son listeleme** (bir önceki market açılışına göre), **7 gün** ve **30 gün**. Dönem seçilince liste o döneme göre en çok düşenden sıralanır; her sütun başlığına tıklayarak sıralama değiştirilir.
- Arama (ad ya da kod), sadece düşenler/yükselenler, en az ilan sayısı, sadece adı olanlar filtreleri.
- **⊘ Gizle:** görmek istemediğin itemleri listeden çıkarır. Kurallar nadirlik ve kategori birleşimiyle çalışır (ör. "Epic · tüm zırh"; oyundaki renkler: Common beyaz, Rare yeşil, Epic mavi, Unique sarı, Heroic turuncu); tek bir item da detay panelinden gizlenebilir. Ayar veritabanında (`meta` tablosu, `ui.exclude`) saklanır, tarayıcı değişse de kalır.
- **Favoriler:** satırdaki ☆ yıldızına tıklamak item'ı favorilere (izleme listesine) ekler ya da çıkarır; "★ Sadece favoriler" kutusu listeyi süzer. Favoriye hedef fiyat detay panelinden verilir; hedef yoksa fiyat 7 gün ortalamasının %20 altına inince bildirim gelir.
- Satıra tıklayınca detay paneli: fiyat grafiği, ad verme, izleme listesine alma ve hedef fiyat, son aramadaki ilanlar.
- Kayıtlar 7/30 günden kısaysa değişim eldeki en eski kayda göre hesaplanır ve `*` ile işaretlenir.
- Aynı market açılışında saniyeler arayla gelen kayıtlar tek listeleme sayılır (5 dakika kuralı).
- **7 gün ortalaması ("7 gün ort."):** fiyatların karşılaştırıldığı referans; son 7 günün fiyat kayıtlarının ortalaması, uç değerler hariç. En az 3 kayıt gerekir.
- **Uç değerler:** her item için son 30 günün medyan fiyatına bakılır. Bunun 3 katından yüksek ya da 4'te 1'inden düşük kayıtlar (ör. markette tek kalan 10.000.000'lik uydurma ilan) değişim tabanı, trend grafiği ve 30 günlük en düşük/en yüksek hesabına katılmaz. Şu anki fiyat uç değerdeyse ⚠ ile işaretlenir; çok yüksekse değişim gösterilmez, çok altındaysa gösterilir (fırsat olabilir). 5'ten az kaydı olan itemlere dokunulmaz.
- Sayfa 30 saniyede bir kendini yeniler; servis çalışırken market açtıkça yeni fiyatlar gelir.

### Masaüstü uygulaması (release)

Geliştirirken `service run` + `dashboard` tarayıcıda kullanılır. Dağıtılan sürüm ise ikisini tek süreçte çalıştıran, kendi penceresi olan bir exe'dir ([app.py](src/aion2market/app.py); pencere Windows'un Edge WebView2'si ile açılır).

```bash
.venv\Scripts\python -m aion2market            # uygulama penceresi
.venv\Scripts\python -m aion2market --browser  # aynısı tarayıcıda
```

- Veriler `%LOCALAPPDATA%\aion2market` klasöründe durur (`market.db`, `app.log`). `--db` ya da `AION2_DB` ile değiştirilebilir.
- Npcap yoksa uygulama yine açılır, ama canlı kayıt yapmaz; sadece arka plan kaynakları (item adları, ortak veri, aion2.exchange) çalışır. Sağ üstte "Npcap kurulumu aktif" ya da indirme bağlantısı görünür. Npcap varsa ve `SSLKEYLOGFILE` ayarlı değilse, ayarlamak için onay istenir; onaydan sonra Steam'in yeniden başlatılması gerekir.
- Ortak veri: uygulama ilk açılışta ortak depodan kendi anahtarını alır ve fiyatları diğer kullanıcılarla dakikada bir eşitler; sağ üstteki "Ortak veri" yazısından kapatılabilir. Deponun kurulumu ve korumaları: [cloud/README.md](cloud/README.md).
- Pencere kapanınca servis de durur.

Exe'yi derlemek için:

```bash
.venv\Scripts\pip install -e ".[app]"
.venv\Scripts\pyinstaller aion2market.spec     # dist\Aion2Market.exe
```

Kurulum dosyası ([installer/aion2market.iss](installer/aion2market.iss), Inno Setup 6) exe'den sonra derlenir:

```bash
iscc /DAppVersion=0.1.0 installer\aion2market.iss   # dist\Aion2Market-Setup-0.1.0.exe
```

Kurulum yönetici izni istemez (`%LOCALAPPDATA%\Programs\Aion 2 Market`). Sihirbazda bir Npcap sayfası var: Npcap kuruluysa canlı kaydın aktif olacağını söyler, değilse Npcap ile daha güncel fiyat alınacağını anlatır ve kurulumdan sonra indirme sayfasını açmayı önerir. Kaldırıcı, uygulamanın veri klasörünü gösteren `SSLKEYLOGFILE` değişkenini siler ve veri klasörünün de silinip silinmeyeceğini sorar.

GitHub'da `v*` etiketi gönderilince [release.yml](.github/workflows/release.yml) testleri çalıştırır, exe'yi ve kurulum dosyasını derler, ikisini de release'e ekler: `git tag v0.1.0 && git push origin v0.1.0`. Npcap'in lisansı kurulum dosyasına gömülmesine izin vermediği için kullanıcı onu kendisi kurar.

### Fırsatlar sayfası

Arayüzde üstteki **Fırsatlar** sekmesi, şu an alınması mantıklı görünen itemleri listeler. Bir item şu durumda listeye girer:

- şu anki fiyatı kendi 7 günlük ortalamasının en az %10 altında,
- son listelemede ya da 7 günde en az %5 düşmüş,
- en az 2 ilanı ve 3 günlük geçmişi var, fiyatı uydurma bir uç değer değil.

Ek olarak:

- **Al-sat kârı:** şimdi alıp 7 gün ortalamasından satarsan, market kesintisinden sonra adet başına kalan (7 gün ort. × (1 − kesinti) − fiyat). Kesinti, oyunun yüklediği market kurallarından okunur (şu an %10 + %2 = %12); sıralama "Al-sat kârına göre" de yapılabilir.
- **Haftalık düzen:** son 30 günde her günün fiyatı, haftanın ortalamasına göre (piyasa geneli; detay panelinde item'ın kendisi için). Şu an en ucuz Çarşamba, en pahalı Perşembe.
- **Odyle dönüştürme farkı:** Odyle aynı seviyedeki cevher/mücevher/kütüğe 1:1 dönüşür. Tablo, üretim için Odyle almanın ne kadar ucuz olduğunu ve Odyle alıp dönüştürüp satmanın vergi sonrası kârını gösterir. Dönüştürmenin kendi maliyeti hesaba katılmaz. Eşleşmeler topluluğun crafting tablosundan.
- **Favori fırsatı bildirimi:** hedef fiyatı olmayan favoriler, fiyat 30 günlük medyanın %20 altına inince bildirim gönderir.
- Oyunun "satışlarım" ve "kazançlarım" yanıtları `responses` tablosuna kaydedilir (ileride kendi ilanlarının ucuzla geçilip geçilmediğini göstermek için).

Puan = indirim % × 30 günlük aralığın dibine yakınlık (1,0–1,5) × ilan sayısı (0,5–1,0). 7 gün ortalaması 30 günlük medyanın belirgin altında kalan itemler "düşüşü sürüyor" diye işaretlenir ve puanları 0,6 ile çarpılır; dibi henüz gelmemiş olabilirler. Her satırda gerekçeler ve uyarılar yazar; satıra tıklayınca detay paneli açılır. Arama, kategori, en az ilan sayısı ve gizleme kuralları bu sayfada da geçerli. Eşikler `dashboard.py` içindeki `DEAL_*` sabitlerinde. Öneriler sadece geçmiş fiyatlara dayanır.

### Envanterim sayfası (ne satılmalı)

Servis, oyunun kendi bağlantısının sunucudan gelen tarafını da pasif olarak okur (ExitLag varsa loopback üzerinden). Oyuna her girişte sunucu envanterin tamamını tek bir mesajla (opcode `0x5611`) gönderir; servis bunu `inventory` tablosuna yazar. Oyuna hiçbir şey gönderilmez. Kapatmak için: `service run --no-inventory`.

**Envanterim** sekmesi, markette ilanı olan her item için şunları gösterir: adet, şu anki fiyat, 7 gün ortalaması, ortalamaya göre fark, son listeleme ve 7 gün değişimi, kesinti sonrası toplam değer ve öneri:

- **Sat:** fiyat 7 gün ortalamasının en az %10 üstünde ya da 7 günde en az %15 yükselmiş. Önerilen ilan fiyatı en ucuz ilanın 1 altı.
- **Bekle:** fiyat 7 gün ortalamasının en az %10 altında.
- **Kontrol et:** en ucuz ilan uydurma görünüyor; 7 gün ortalamasından satmak önerilir.

Varsayılan sıralama 7 günde en çok yükselenden; son listeleme, 7 gün ortalamasının üstünde olma ve toplam değere göre de sıralanabilir. Sağ üstteki kartta haftanın en pahalı günü (satmak için) yazar.

Sınırlar: envanter oyuna girişte güncellenir, oyun içindeki anlık değişiklikler henüz okunmuyor. Depo (stash) ayrı bir mesajla geliyor olmalı; henüz eklenmedi. Kayıtlı bir yakalamadan içe aktarmak için: `.venv\Scripts\python -m aion2market.inventory import captures\<kayıt>`.

### Üretim sayfası (al mı, üret mi)

**Üretim** sekmesi Guard, Earring, Ring, Necklace ve Mace zincirlerinin 4 adımını şu anki market fiyatlarıyla hesaplar. Tarifler, malzeme miktarları ve beklenen deneme sayıları topluluğun crafting tablosundan ([recipes.py](src/aion2market/recipes.py), Mastery 100):

- Her kademe için en ucuz yol: marketten **al** ya da bir önceki kademenin en ucuz yolu + bu adımın malzemesiyle **üret**. Böylece "Artisan's'ı al, 4. adımı üret" gibi karışık yollar da bulunur.
- Üretim maliyeti = bir denemenin malzemesi × beklenen deneme sayısı (her adımda %25 kombo; 4. adımın normal sonucu ~1,06 deneme).
- Bir malzeme, Odyle alıp dönüştürmekle daha ucuza geliyorsa o fiyat kullanılır (mor gösterilir).
- **Üret-sat kârı:** en ucuz yoldan üretip markette satınca kesinti sonrası kalan. Sayfanın başında en kârlı kademeler listelenir.
- Tarif itemleri her zaman aion2.exchange sorgusuna eklenir, fiyatları güncel kalır. Şansa bağlı olduğu için gerçek maliyet sapabilir.

### Item adları ve ikonlar

Market yanıtlarında item adı yok; adlar NCSOFT'un herkese açık resmi item verisinden alınır:
`https://tw.ncsoft.com/aion2/api/gameconst/item?id=<kod>&lang=en` (ad, nadirlik, kategori, ikon).

- `service run` yeni görülen itemleri arka planda, yarım saniyede bir istekle sorgular (`--no-item-info` ile kapatılır). Bu, projenin dışarıya gönderdiği tek istektir; oyuna ya da oyun hesabına dokunmaz.
- Elle hepsini sorgulamak için: `.venv\Scripts\python -m aion2market.iteminfo`
- Resmi veride olmayan kodlar (`id: 0` döner) bir hafta sonra yeniden denenir; bunlara arayüzden ad verebilirsin.
- Senin verdiğin ad resmi adın önüne geçer. Arayüzde adı boş bırakıp kaydedersen resmi ada döner.
- NCSoft'un verisinde olmayan itemler (ör. yeni "Sealed … Wings" kanatları) için ad ve kategori, aion2.exchange'in düzenli sorgusundaki `name` ve `category` alanlarından alınır (`exchange_names` tablosu). Öncelik: senin adın > NCSoft > aion2.exchange. İkisinde de adı olmayan itemler (şu an 4 Artwork) "Adsız" görünür ve kategorileri bilinir.

### Sunucular

Fiyatlar marketin sunucu koduna (`game_server_id`, ör. 12306) göre ayrı tutulur. Arayüz, MCP araçları ve bildirimler varsayılan olarak senin oyun istemcinin en son kullandığı sunucuyu kullanır. Arayüzde sağ üstten başka sunucu seçilebilir ve ✎ ile sunucuya ad verilir. MCP'de `list_servers` ve fiyat araçlarının `server_id` parametresi var.

### Ortak fiyat deposu

Birden fazla kişi kullanıyorsa herkesin gördüğü fiyatlar ortak bir Cloudflare deposunda toplanabilir; kim marketi en son açtıysa herkes o fiyatı görür. Kurulum, kullanıcı anahtarları, ne gönderildiği ve sınırlar: [cloud/README.md](cloud/README.md).

### aion2.exchange'den fiyat alma

[aion2.exchange](https://aion2.exchange/) bütün sunucuların market fiyatlarını tutuyor. Bir sunucunun fiyatlarını oradan da alabilirsin; bunun için oyunun açık olması gerekmez.

```bash
# Sunucu kodu: aion2.exchange'de sunucunu seçince adresteki ?server= değeri (ör. EU Zemurru = 12315)
.venv\Scripts\python -m aion2market.exchange setup <sunucu-id>
.venv\Scripts\python -m aion2market.exchange now        # hemen dene
.venv\Scripts\python -m aion2market.exchange disable
```

- `service run` ayarlıysa 30 dakikada bir alır (site saatte bir örnek alıyor). Bilinen itemleri 100'erli gruplar halinde, istekler arasında 2 saniye bekleyerek sorgular; kendini `aion2market personal price tracker` olarak tanıtır.
- Geçmiş: `.venv\Scripts\python -m aion2market.exchange history` her item için bir kez 30 günlük, 6 saatlik dilimleri (en düşük, en yüksek, ortalama, son fiyat, ilan sayısı) indirir. Item başına bir istek ve aralarında 2 saniye beklediği için ~580 item yaklaşık 20 dakika sürer. Yarıda kesilirse kaldığı yerden devam eder; bir kez yüklenen item tekrar istenmez. Dilimler `price_ranges` tablosuna, dilim sonu fiyatları fiyat geçmişine yazılır. Detay panelindeki grafikte mavi bant olarak görünür. Sitenin geçmişi 6 Ekim 2026'dan başlıyor, bu yüzden 30 günlük değişim şimdilik `*` ile işaretli kalır.
- Kayıtlar `origin = 'exchange'` olarak saklanır, arayüzde o sunucunun fiyatları arasında görünür. Ortak Cloudflare deposuna asla yüklenmez.
- Kendi sunucunun taze (son 30 dakika) fiyatları izleme listesi bildirimlerini tetikleyebilir.
- Bu, başkasının ücretsiz hizmeti. Sitenin robots.txt dosyası yapay zeka ajanlarını engelliyor ve verinin "referans" amaçlı kullanılmasını istiyor. Kişisel kullanımda tut, aralığı kısaltma; site sahibi itiraz ederse `disable` ile kapat.

## Bildirimler (Faz 4)

`service run` çalışırken, izleme listesindeki bir item'ın gözlenen birim fiyatı hedefin altına (ya da hedefe) inerse bildirim gönderilir. Fiyat hem market açılınca gelen tüm item listesinden hem de item aramalarından okunur; yani izlenen item'ı ayrıca aramana gerek yok, marketi açman yeterli.

- Aynı fiyat için tekrar bildirim gelmez. Fiyat daha da düşerse yeni bildirim gelir.
- Fiyat hedefin üstüne çıkınca sayaç sıfırlanır, sonraki düşüşte yine bildirim gelir. Hedefi değiştirmek de sıfırlar.
- `replay` eski kayıtlar için bildirim göndermez.

Kanallar:
- **Ekran kartı:** varsayılan olarak açık (`--no-popup` ile kapatılır). Kendi penceremiz ([popup.py](src/aion2market/popup.py), tkinter, ek paket yok). Sağ altta, görev çubuğunun üstünde koyu bir kart: item adı, birim fiyat, hedef ve yüzde fark. Birden çok bildirim üst üste dizilir. 12 saniyede kendiliğinden kapanır; fare üstündeyken süre durur, tıklayınca kapanır. Kenarlıksız pencere modunda oyunun üstünde görünür; özel tam ekran modunda görünmeyebilir. Önizleme: `.venv\Scripts\python -m aion2market.popup --demo`
- **Discord:** bir kanal webhook'u verirsen oraya da gönderilir: `--discord-webhook <url>` ya da `AION2_DISCORD_WEBHOOK` ortam değişkeni.

```bash
# Kanalları dene
.venv\Scripts\python -m aion2market.service notify-test
```

Hedef fiyatı MCP'deki `watch_item("Pure Odyle", target_price=55000)` ile verirsin. Gönderilen bildirimler `alerts` tablosunda tutulur.

## Test

```bash
.venv\Scripts\python -m pytest -q
```
