# Günlük Şirket Brifingi

Her sabah watchlist'ten bir hisse seçer (bilanço açıklayan > önümüzdeki 7 günde
bilanço açıklayacak > büyük hareket eden > rotasyondaki sıradaki), yfinance +
Alpaca News'ten veriyi toplar, Claude'a Türkçe
yorum yazdırır ve sonucu `site/briefings/` altına JSON olarak işler. Netlify bu
depoya bağlı olduğu için her commit otomatik yayınlanır:

**Canlı site:** https://gunluk-brifing.netlify.app

## Nasıl çalışıyor (sunucusuz)

1. GitHub Actions, hafta içi her sabah ~08:45'te (İstanbul) `brifing.yml`
   workflow'unu çalıştırır — `05:45 UTC` (Türkiye yıl boyu UTC+3).
2. Workflow `briefing_generator.py`'yi çalıştırır: hisse seçimi → yfinance
   finansalları → Alpaca haberleri → Claude yorumu.
3. Üretilen `site/briefings/YYYY-MM-DD.json`, güncellenen `manifest.json` ve
   rotasyon durumunu tutan `state.json` depoya commit'lenir.
4. Netlify push'u görür, `site/` klasörünü yayınlar. Bitti.

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
kutusuna hisse yazarak seçimi elle yapabilirsin (boş bırakırsan otomatik seçer).

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
