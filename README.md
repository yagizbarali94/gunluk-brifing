# Günlük Şirket Brifingi

Her sabah watchlist'ten **2 hisse** seçer — biri bilançosuna en fazla 7 gün kalan
(beklentileri önceden incelemek için), diğeri son 2 gün içinde bilanço açıklamış
olan. İkisi de doğal aday bulamazsa büyük hareket eden > rotasyondaki sıradaki
hisseye düşer; iki slot asla aynı hisseyi seçmez. Her hisse için yfinance +
Alpaca News'ten veri toplanır, Claude'a Türkçe yorum yazdırılır ve sonuç
`site/briefings/` altına JSON olarak işlenir. Netlify bu depoya bağlı olduğu
için her commit otomatik yayınlanır:

**Canlı site:** https://gunluk-brifing.netlify.app

## Nasıl çalışıyor (sunucusuz)

1. GitHub Actions, hafta içi her sabah ~08:45'te (İstanbul) `brifing.yml`
   workflow'unu çalıştırır — `05:45 UTC` (Türkiye yıl boyu UTC+3).
2. Workflow `briefing_generator.py`'yi çalıştırır: 2 hisse seçilir (yaklaşan
   bilanço + yeni açıklanan bilanço slotları) → her biri için yfinance
   finansalları → Alpaca haberleri → Claude yorumu.
3. Üretilen `site/briefings/YYYY-MM-DD-upcoming.json` ve
   `site/briefings/YYYY-MM-DD-reported.json`, güncellenen `manifest.json` ve
   rotasyon durumunu tutan `state.json` depoya commit'lenir.
4. Netlify push'u görür, `site/` klasörünü yayınlar. Bitti.
5. Sitede "Gün" seçicisinin yanındaki **Odak** filtresiyle o günün hangi
   brifingini (yaklaşan bilanço mu, yeni açıklanan mı) görmek istediğini
   seçebilirsin.

Not: GitHub'ın zamanlayıcısı dakikası dakikasına değildir; 08:45 yerine
08:50–09:00 arası normaldir.

## Gerekli secrets (Settings → Secrets and variables → Actions)

| Secret | Nereden |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com (trading botundakiyle aynı) |
| `ALPACA_API_KEY_ID` | Alpaca paper hesabın |
| `ALPACA_API_SECRET_KEY` | Alpaca paper hesabın |

Netlify token'ı **gerekmez** — yayın, Netlify'ın depo bağlantısı üzerinden olur.

## Elle tetikleme / test

Actions sekmesi → **Günlük brifing** → **Run workflow**. İstersen `ticker`
kutusuna hisse yazarak seçimi elle yapabilirsin (boş bırakırsan otomatik 2 hisse
seçer). Elle seçimde tek brifing üretilir, iki slotlu otomatik akış atlanır.

## Ayarlar

- **Watchlist ve eşikler:** `config.py` — GitHub'da dosyaya girip kalem
  ikonuyla tarayıcıdan düzenleyebilirsin; commit ettiğinde bir sonraki sabah
  yeni liste geçerli olur.
- **Saat/sıklık:** `.github/workflows/brifing.yml` içindeki `cron` satırı.

## Notlar

- Site linki herkese açıktır (`noindex` etiketli); portföy detayı içermez.
- yfinance bazı şirketlerde eksik satır döndürebilir; ilgili karne satırı
  "veri yok" olarak düşer, akış durmaz.
- GitHub, 60 gün hareketsiz kalan depolarda zamanlanmış workflow'ları
  durdurabilir; günlük commit'ler sayesinde pratikte oluşmaz, olursa e-posta
  gelir ve tek tıkla yeniden etkinleştirilir.
- Sıradaki adım: sektör şablonları (Layer 2) karne bölümünü sektöre göre
  özelleştirecek; advisory sistemi aynı JSON'ları `briefings/` üzerinden
  okuyabilir.
