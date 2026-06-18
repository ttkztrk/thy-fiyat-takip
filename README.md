# THY Fiyat Takip Botu (NRW → Sinop)

Dortmund, Düsseldorf ve Köln/Bonn'dan Sinop'a (NOP) uçuşları otomatik olarak
tarar; tahmini toplam fiyat 200€ altına düştüğünde Telegram ve e-posta ile
haber verir. Ücretsiz çalışır, bilgisayarının açık olmasına gerek yoktur —
GitHub'ın sunucularında günlük olarak otomatik çalışır.

## Önemli not — veri kaynağı hakkında

Sinop Havalimanı'na sadece İstanbul üzerinden aktarmalı uçulabiliyor ve çok
az aranan bir rota olduğu için, fiyat verisi sağlayan servislerin
cache'inde "NRW havalimanı → Sinop" için direkt veri bulunmuyor olabilir.
Bu yüzden script rotayı ikiye bölüyor:

1. Kalkış havalimanın → İstanbul (çok aranan, bol veri)
2. İstanbul → Sinop (THY'nin iç hat seferi)

ve iki bacağın en ucuz fiyatlarını toplayarak **tahmini** bir toplam
hesaplıyor. Bu, THY'den tek bilet (PNR) olarak alınacak gerçek birleşik
fiyattan farklı olabilir — genelde birleşik bilet iki ayrı bilete göre daha
ucuzdur. Bu yüzden bot **erken uyarı** amaçlıdır: bildirim aldığında bileti
almadan önce mutlaka THY'nin sitesinden gerçek fiyatı teyit et.

## Nasıl çalışıyor?

1. `main.py`, Travelpayouts'un (Aviasales) ücretsiz **Data API**'sine
   bağlanıp her bir kalkış havalimanı ve önümüzdeki aylar için iki bacağın
   cache'teki en ucuz fiyatlarını çeker.
2. İki bacağın fiyatlarını toplar; toplam 200€ altındaysa listeye ekler.
3. Bulduğunda Telegram mesajı ve e-posta gönderir.
4. `.github/workflows/check_flights.yml` bu scripti her gün otomatik
   tetikler (GitHub Actions ücretsiz).

## Kurulum (tek seferlik, yaklaşık 15-20 dakika sürer)

### 1. Travelpayouts hesabı ve API token'ı al (ücretsiz)
1. https://www.travelpayouts.com adresine girip ücretsiz "partner" hesabı aç
   ("Join now" / "Şimdi katıl").
2. Kayıt formunda bir "website/proje" alanı çıkabilir — kişisel kullanım
   için bunu doldurman gerekiyorsa GitHub repo linkini ya da kişisel bir
   açıklama yazabilirsin; bu alan komisyon/ortaklık tarafıyla ilgili,
   Data API'ye erişimini engellemiyor.
3. Hesabına girdikten sonra **Tools → API** (veya "Geliştirici araçları")
   bölümünden API token'ını al ve not et.

> Not: Bu API'yi senin token'ın olmadan benim tarafımdan test etmem mümkün
> değil. İlk "Run workflow" denemesinde çıkan log'u birlikte kontrol edip
> gerekirse (örn. para birimi veya veri bulunamaması durumunda) küçük
> ayarlar yapacağız.

### 2. Telegram botu oluştur
1. Telegram'da **@BotFather** ile sohbet başlat, `/newbot` yaz, bir isim ver.
2. Sana verdiği **bot token**'ı not al (örn. `123456:ABC-DEF...`).
3. Oluşturduğun bota Telegram'dan bir mesaj gönder (örn. "merhaba").
4. Tarayıcında şu adresi aç (TOKEN yerine kendi token'ını yaz):
   `https://api.telegram.org/botTOKEN/getUpdates`
5. Çıkan JSON içinde `"chat":{"id": ...}` kısmındaki sayıyı **chat ID** olarak not al.

### 3. E-posta için Gmail Uygulama Şifresi al
1. Bildirim göndermek istediğin Gmail hesabında 2 adımlı doğrulamayı aç
   (Google Hesabı → Güvenlik).
2. https://myaccount.google.com/apppasswords adresinden bir
   **Uygulama Şifresi (App Password)** oluştur, 16 haneli kodu not al.

### 4. GitHub'a yükle
1. https://github.com üzerinde ücretsiz hesabınla yeni bir **private** repo aç
   (örn. `thy-fiyat-takip`).
2. Bu klasördeki tüm dosyaları (main.py, requirements.txt, .github klasörü,
   bu README) o repo'ya yükle (GitHub web arayüzünden "Add file → Upload
   files" ile de yapılabilir, Git bilmen gerekmiyor).

### 5. Bilgileri GitHub'a güvenli şekilde ekle (Secrets)
Repo içinde **Settings → Secrets and variables → Actions → New repository
secret** yoluyla aşağıdakileri tek tek ekle:

| Secret adı            | Değer                                      |
|------------------------|---------------------------------------------|
| `TRAVELPAYOUTS_TOKEN`   | Adım 1'deki API token                       |
| `TELEGRAM_BOT_TOKEN`    | Adım 2'deki bot token                       |
| `TELEGRAM_CHAT_ID`      | Adım 2'deki chat ID                         |
| `GMAIL_ADDRESS`         | Bildirim gönderecek Gmail adresi            |
| `GMAIL_APP_PASSWORD`    | Adım 3'teki 16 haneli uygulama şifresi      |
| `EMAIL_TO`              | Bildirimin gideceği e-posta adresi (kendi adresin olabilir) |

### 6. Test et
Repo içinde **Actions** sekmesine git, "THY Fiyat Takip" workflow'unu seç,
**"Run workflow"** butonuna basarak manuel olarak bir kere çalıştır.
Loglardan her şeyin doğru çalıştığını ve veri bulunup bulunmadığını
görebilirsin. "Bu ay için yeterli cache verisi yok" mesajını çok görürsen,
bu rotanın cache'te az veri olduğu anlamına gelir — bana haber verirsen
alternatif bir yaklaşım (örn. ayrı ayrı her iki bacağı izleyip sana iki
ayrı bildirim olarak gösterme) üzerinde çalışabiliriz.

Bundan sonra script her gün otomatik olarak (varsayılan: TR saatiyle
~09:00-10:00) kendiliğinden çalışacak.

## Ayarları değiştirmek istersen

`.github/workflows/check_flights.yml` dosyasındaki `env:` kısmından:
- `PRICE_THRESHOLD`: Eşik fiyatı (varsayılan 200)
- `ORIGIN_AIRPORTS`: Kalkış havalimanları (varsayılan `DTM,DUS,CGN`)
- `MONTHS_AHEAD`: Kaç ay ileriye bakılsın (varsayılan 4)
- Cron satırını değiştirerek çalışma sıklığını ayarlayabilirsin
  (örn. günde 2 kez için `"0 7,17 * * *"`).

## Sınırlamalar
- Bu, gerçek zamanlı bir fiyat değil; Aviasales kullanıcılarının geçmiş
  aramalarından oluşan bir **cache**'tir. Sinop gibi az aranan bir rotada
  veri seyrek olabilir.
- İki bacağın toplamı, THY'nin tek PNR ile sunduğu gerçek birleşik bilet
  fiyatından **farklı** olabilir (genelde birleşik bilet daha ucuzdur).
  Bu yüzden bot sadece erken uyarı amaçlıdır.
- Script her çalıştırmada eşik altı bulduğu her şeyi tekrar bildirir; aynı
  ucuz kombinasyonu her gün tekrar görebilirsin (istersen "daha önce
  bildirildi mi" kontrolü ekleyebiliriz).
