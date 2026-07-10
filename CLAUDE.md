# gunluk-brifing

## Sistem ne yapıyor

Hafta içi her sabah (~08:45 İstanbul saati) GitHub Actions tetiklenir, watchlist'ten
bir hisse seçer, yfinance + Alpaca News'ten veri toplar, Claude API'ye Türkçe yatırım
yorumu yazdırır ve sonucu JSON olarak `site/briefings/` altına commit'ler. Netlify bu
depoya bağlı olduğu için **main'e giden her push otomatik olarak yayına alınır** —
ayrı bir deploy adımı yok.

Canlı site: https://gunluk-brifing.netlify.app

Uçtan uca akış:
1. `.github/workflows/brifing.yml` cron ile (`45 5 * * 1-5` UTC) veya elle
   (`workflow_dispatch`, opsiyonel `ticker` girdisiyle) tetiklenir.
2. `briefing_generator.py` çalışır:
   - Hisse seçimi: son 2 günde bilanço açıklayan > önümüzdeki 7 gün içinde bilanço
     açıklayacak (varsa en yakın tarihli) > günlük |%4+| hareket eden > yoksa
     `config.py`'deki `WATCHLIST` sırasında rotasyon (`state.json`'da tutulur).
   - `yfinance` ile finansallar (gelir, marj, FCF, EPS, bilanço takvimi),
     Alpaca News API ile son 7 günün haberleri çekilir.
   - Toplanan veriler + haberler Claude API'ye (`claude-sonnet-4-6`) gönderilir;
     model Türkçe "about / note / counter / watch / concept / guidance / haber
     özetleri" içeren JSON döner.
   - Çıktı `site/briefings/YYYY-MM-DD.json` olarak yazılır, `manifest.json`
     güncellenir, rotasyon durumu `state.json`'a kaydedilir.
3. Workflow bu üç dosyayı (`site/briefings/*`, `state.json`) commit'leyip
   `main`'e push'lar (değişiklik yoksa commit atlanır).
4. **Netlify push'u görür ve `site/` klasörünü otomatik yayınlar** — Netlify
   tarafında ayrı bir token/tetikleyici gerekmez, repo bağlantısı yeterli.

## Dosyaların rolleri

| Dosya | Rol |
|---|---|
| `.github/workflows/brifing.yml` | Cron + manuel tetikleme; Python kurar, `briefing_generator.py`'yi çalıştırır, çıktıyı commit+push eder. |
| `briefing_generator.py` | Ana üretici script: hisse seçimi, veri toplama (yfinance/Alpaca), Claude çağrısı, JSON çıktı yazımı. `--ticker`, `--mock`, `--date` argümanlarıyla elle/test modunda da çalışır. |
| `config.py` | `WATCHLIST` (rotasyon sırası), seçim eşikleri (`EARNINGS_LOOKBACK_DAYS`, `EARNINGS_UPCOMING_DAYS`, `MOVER_THRESHOLD_PCT`), haber ayarları, Claude model/token ayarları, karne renk eşikleri (`THRESHOLDS`), dosya yolları. |
| `state.json` | Rotasyonun kaldığı yeri tutar: `last_index`, `last_ticker`. Workflow tarafından otomatik güncellenir. |
| `site/index.html` | Netlify'da yayınlanan frontend — brifingleri okuyup gösteren tek sayfa. |
| `site/briefings/YYYY-MM-DD.json` | Her gün üretilen brifing verisi (fiyat, KPI'lar, karne, grafikler, haberler, Claude yorumu). |
| `site/briefings/manifest.json` | Mevcut brifing tarihlerinin listesi (frontend'in hangi günleri gösterebileceğini bilmesi için). |
| `netlify.toml` | Netlify build ayarı — `site/` klasörünü publish dizini olarak işaretler. |
| `netlify/functions/chat.mjs` | Netlify serverless function: site içi sohbet için Claude API'ye proxy. Anahtar tarayıcıya inmez (Netlify env: `ANTHROPIC_API_KEY`), opsiyonel `CHAT_PASS` ile korunur. |
| `requirements.txt` | Python bağımlılıkları (`yfinance`, `requests`). |
| `README.md` | Kurulum, gerekli GitHub Actions secrets'ları (`ANTHROPIC_API_KEY`, `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`) ve elle tetikleme talimatları. |

## Önemli not

Bu depoda ayrı bir "deploy" adımı yoktur. Netlify, repoya doğrudan bağlı
olduğu için **main branch'ine giden her push'u (workflow'un otomatik commit'i
dahil) algılayıp `site/` klasörünü otomatik olarak yeniden yayınlar.** Yani
`config.py`'deki watchlist'i elle değiştirip push'lamak da, workflow'un günlük
ürettiği brifing commit'i de aynı şekilde siteyi güncelleştirir — Netlify
tarafında tıklanacak bir şey yoktur.
