# Ortak fiyat deposu (Cloudflare Workers + D1)

Uygulamayı kuran herkes kendi oyun istemcisinin gördüğü market fiyatlarını buraya yükler ve diğerlerinin yüklediklerini indirir. Böylece kim marketi en son açtıysa herkes o güncel fiyatı görür. Fiyatlar sunucu bazında ayrı tutulur.

## Ne gönderilir

Sadece market verisi: sunucu kodu (`game_server_id`), item kodu, zaman, en düşük birim fiyat, ilan sayısı ve arama sonucu ilanlarının kodu, adedi ve fiyatı. Karakter, hesap ya da oturum bilgisi saklanmaz. İlanlarda satıcı bilgisi zaten yoktur.

IP adresi saklanmaz. Sadece kayıt sınırı için, IP'nin gizli bir değerle (ADMIN_TOKEN) karıştırılmış SHA-256 özeti o gün boyunca tutulur. Ertesi gün silinir.

## Kurulum (depo sahibi, bir kez)

Bir Cloudflare hesabı gerekir. Ücretsiz plan yeterlidir.

```bash
cd cloud
npm install
npx wrangler login
npx wrangler d1 create aion2-market
```

Son komutun yazdığı `database_id` değerini [wrangler.toml](wrangler.toml) dosyasına yapıştır.

```bash
npx wrangler d1 execute aion2-market --remote --file=schema.sql
npx wrangler secret put ADMIN_TOKEN
npx wrangler deploy
```

- `ADMIN_TOKEN` en az 16 karakterlik, kimseyle paylaşmayacağın rastgele bir değer olmalı. Yönetici işlemleri yalnızca bununla yapılır; otomatik kayıt da bu değer olmadan çalışmaz.
- `deploy` komutu adresi yazar, ör. `https://aion2-market.<hesabın>.workers.dev`.
- Bu adresi [sync.py](../src/aion2market/sync.py) içindeki `DEFAULT_URL` değerine yaz. Uygulama (ve ondan derlenen exe) bu adresi kullanır.

Bu sürümden önce oluşturulmuş bir veritabanı varsa bir kez `--file=migrate-001.sql`, sonra yine `--file=schema.sql` çalıştır.

## Kullanıcılar nasıl katılır

Kendiliğinden. Uygulama ilk açılışta depodan kendi anahtarını alır (`POST /v1/register`) ve dakikada bir eşitler. Kullanıcı arayüzde sağ üstteki "Ortak veri" yazısına tıklayıp paylaşımı kapatabilir; kapatınca ne gönderilir ne alınır, anahtar ise saklanır.

Kayıt sınırları: aynı adresten günde en fazla 3, toplamda günde en fazla 500 yeni anahtar. Kaydı tamamen kapatmak için [wrangler.toml](wrangler.toml) içinde `OPEN_REGISTRATION = "false"` yapıp yeniden `deploy` et. O zaman sadece elle verilen anahtarlar çalışır.

## Bozuk fiyat koruması

- Her item için depo, kabul edilen fiyatlardan yavaş değişen bir "normal fiyat" tutar. Bir item'ın en az 3 kabul edilmiş fiyatı olduktan sonra, normal fiyatın 10 katından fazla ya da 10'da birinden az olan fiyatlar reddedilir. Yükleme cevabında `outliers` olarak sayılır.
- Gerçek fiyat 10 kattan fazla değişirse: 3 gün boyunca hiç fiyat kabul edilmeyen item'ın normal fiyatı sıfırlanır ve yeniden öğrenilir.
- Bir anahtar saatte en fazla 20.000 satır (fiyat + ilan) yükleyebilir. Bir market açılışı yaklaşık 600 satırdır.
- Bunlara rağmen bozuk veri gelirse: her satır kimin yüklediğiyle birlikte saklanır, aşağıdaki `revoke` ve `purge` ile o anahtar kapatılıp yüklediği her şey silinir.

## Yönetici komutları

```bash
.venv\Scripts\python -m aion2market.sync admin --url <adres> --admin-token <token> list                # anahtarlar, yükledikleri, son görülme
... admin --url <adres> --admin-token <token> create-key "Ali"    # elle anahtar (kayıt kapalıyken)
... admin --url <adres> --admin-token <token> revoke 3            # anahtarı iptal et
... admin --url <adres> --admin-token <token> purge 3             # o anahtarın yüklediği her şeyi sil
... admin --url <adres> --admin-token <token> server-name 12306 "Sunucu adı"
```

## Komut satırından (geliştirici)

```bash
.venv\Scripts\python -m aion2market.sync status
.venv\Scripts\python -m aion2market.sync now                  # hemen eşitle
.venv\Scripts\python -m aion2market.sync disable | enable
.venv\Scripts\python -m aion2market.sync setup <adres> [anahtar]   # başka bir depo; anahtar verilmezse kendisi alır
```

`AION2_SHARE_URL` ortam değişkeni `DEFAULT_URL`'nin yerine geçer.

## Sınırlar

Ücretsiz Cloudflare planı kabaca şunları kaldırır:

| Sınır | Ücretsiz plan | Bu uygulamada |
|---|---|---|
| Worker isteği | 100.000 / gün | kullanıcı başına ~4.400 / gün (dakikada bir eşitleme) |
| D1 yazılan satır | 100.000 / gün | her market açılışı ~560 fiyat, artı normal fiyat güncellemesi; dizinler bunu birkaç katına çıkarır |
| D1 okunan satır | 5 milyon / gün | indirmeler sadece yeni satırları okur |

Kullanıcılar toplamda günde 100-150 kez market açarsa günlük yazma sınırına yaklaşılır. O durumda Workers Paid planı (ayda 5 $, 50 milyon yazma) gerekir.

## Yerel deneme

```bash
cd cloud
echo ADMIN_TOKEN=<uzun-rastgele-değer> > .dev.vars
npx wrangler d1 execute aion2-market --local --file=schema.sql
npx wrangler dev --local --port 8787
```

Bu durumda adres `http://127.0.0.1:8787` olur; uygulamayı `AION2_SHARE_URL=http://127.0.0.1:8787` ile çalıştır.
