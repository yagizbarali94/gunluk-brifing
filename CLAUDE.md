# gunluk-brifing

## Sistem ne yapıyor

Her sabah (~08:45 İstanbul saati) GitHub Actions tetiklenir, watchlist'ten
**2 hisse** seçer, her biri için yfinance + Alpaca News'ten veri toplar, Claude
API'ye Türkçe yatırım yorumu yazdırır ve sonuçları JSON olarak `site/briefings/`
altına commit'ler. Netlify bu depoya bağlı olduğu için **main'e giden her push
otomatik olarak yayına alınır** — ayrı bir deploy adımı yok.

Canlı site: https://gunluk-brifing.netlify.app

Uçtan uca akış:
1. `.github/workflows/brifing.yml` cron ile (`45 5 * * *` UTC, her gün) veya elle
   (`workflow_dispatch`, opsiyonel `ticker` girdisiyle) tetiklenir.
2. `briefing_generator.py` çalışır:
   - Hisse seçimi (`select_tickers()`): **iki bağımsız slot**.
     - `upcoming`: önümüzdeki 7 gün içinde bilanço açıklayacak, en yakın tarihli hisse.
     - `reported`: son 2 gün içinde bilanço açıklamış hisse.
     - Her slot kendi doğal adayını bulamazsa günlük |%4+| hareket eden > yoksa
       `config.py`'deki `WATCHLIST` sırasında rotasyona düşer (`state.json`'da tutulur).
     - İki slot asla aynı hisseyi seçmez (çakışırsa bir sonraki adaya geçilir).
     - `pinned.json`'da ({"YYYY-MM-DD": ["TICKER", ...]}) o günün tarihi varsa,
       listelenen hisseler için otomatik seçime EK olarak `pinned` slotlu brifingler
       üretilir (dosya: `YYYY-MM-DD-pinned-<TICKER>.json`; otomatik seçimle çakışan
       yinelenmez). Tarihi geçen kayıtlar her çalıştırmada otomatik temizlenir.
       Sabitleme, sitedeki "⭐ Sabitle" panelinden yapılır (`netlify/functions/pin.mjs`
       GitHub API ile pinned.json'ı commit'ler; `GITHUB_TOKEN` + `CHAT_PASS` gerekir).
     - Paneldeki "⚡ Hemen" butonu tarihi beklemeden üretir: pin.mjs
       `repository_dispatch` (event: `pin-now`) gönderir → workflow
       `briefing_generator.py --pin TICKER` çalıştırır → bugünün tarihiyle
       `pinned` slotlu brifing üretilir (rotasyon/state'e dokunmaz).
     - Elle tetiklemede (`--ticker` / `workflow_dispatch` ticker girdisi) bu iki-slot
       mantığı atlanır, tek hisse için tek brifing üretilir (slot yok).
   - Her seçilen hisse için ayrı ayrı: `yfinance` ile finansallar (gelir, marj, FCF,
     EPS, bilanço takvimi + derin metrikler), Alpaca News API ile son 7 günün haberleri çekilir.
   - `build_quality()` derin metrikleri hesaplar: çeyreklik trend serileri (sparkline),
     sermaye getirisi (ROIC/ROE/ROA), kazanç kalitesi (nakit dönüşümü FCF/net kâr,
     hisse seyrelmesi, Rule of 40), bilanço sağlığı (net nakit), değerleme çarpanları
     (F/K cari-ileri, FD/Satış, FD/FAVÖK, Fiyat/FCF), beat/miss geçmişi. Bunlar hem
     karneye ("derin şablon v2": Büyüme/Kârlılık/Sermaye getirisi/Kazanç kalitesi/Bilanço
     grupları + satır içi sparkline'lar) hem de ayrı "Değerleme çarpanları" kartına yansır.
   - Toplanan veriler (derin metrikler dahil) + haberler Claude API'ye
     (`claude-sonnet-4-6`) gönderilir; model Türkçe "about / note / counter /
     diagnosis (5 maddelik sağlık teşhisi: her boyut için güçlü/nötr/zayıf) /
     watch / concept / guidance / haber özetleri" içeren JSON döner.
   - Çıktı `site/briefings/YYYY-MM-DD-<slot>.json` olarak yazılır (elle tetiklemede
     slot'suz `YYYY-MM-DD.json`), `manifest.json` güncellenir, rotasyon durumu
     `state.json`'a kaydedilir.
3. Workflow bu dosyaları (`site/briefings/*`, `state.json`) commit'leyip
   `main`'e push'lar (değişiklik yoksa commit atlanır).
4. **Netlify push'u görür ve `site/` klasörünü otomatik yayınlar** — Netlify
   tarafında ayrı bir token/tetikleyici gerekmez, repo bağlantısı yeterli.
5. Frontend'deki "Gün" seçicisinin yanında bir **Odak** filtresi var — o günün
   iki brifinginden (yaklaşan bilanço / yeni açıklanan) hangisini görmek
   istediğini seçtirir. Tek slotlu (eski/elle) günlerde bu filtre gizlenir.

## Dosyaların rolleri

| Dosya | Rol |
|---|---|
| `.github/workflows/brifing.yml` | Cron + manuel tetikleme; Python kurar, `briefing_generator.py`'yi çalıştırır, çıktıyı commit+push eder. |
| `briefing_generator.py` | Ana üretici script: iki-slot hisse seçimi (`select_tickers`), her hisse için veri toplama (yfinance/Alpaca) + Claude çağrısı + JSON çıktı yazımı (`generate_for_ticker`, `write_output`). `--ticker`, `--mock`, `--date` argümanlarıyla elle/test modunda (tek slot) da çalışır. |
| `config.py` | `WATCHLIST` (rotasyon sırası), seçim eşikleri (`EARNINGS_LOOKBACK_DAYS`, `EARNINGS_UPCOMING_DAYS`, `MOVER_THRESHOLD_PCT`), haber ayarları, Claude model/token ayarları, karne renk eşikleri (`THRESHOLDS`), dosya yolları. |
| `pinned.json` | Tarihe sabitlenmiş ek hisseler: `{"YYYY-MM-DD": ["TICKER", ...]}`. Sitedeki "⭐ Sabitle" paneli (pin.mjs) veya GitHub'dan elle güncellenir; geçmiş tarihler her sabah otomatik silinir. |
| `netlify/functions/pin.mjs` | "⭐ Sabitle" panelinin arka ucu (`/api/pin`): pinned.json'ı GitHub Contents API ile okur/commit'ler. Netlify env: `GITHUB_TOKEN` (fine-grained PAT, Contents RW) + `CHAT_PASS` (erişim kelimesi). |
| `state.json` | Rotasyonun kaldığı yeri tutar: `last_index`, `last_ticker`. Workflow tarafından otomatik güncellenir. |
| `site/index.html` | Netlify'da yayınlanan frontend — brifingleri okuyup gösteren tek sayfa; "Gün" + "Odak" (slot) filtreleriyle gezinilir. |
| `site/briefings/YYYY-MM-DD-<slot>.json` | Her gün, her slot (`upcoming`/`reported`) için üretilen brifing verisi (fiyat, KPI'lar, karne, grafikler, haberler, Claude yorumu). Elle tetiklemede slot'suz `YYYY-MM-DD.json` (geriye dönük uyum). |
| `site/briefings/manifest.json` | Mevcut brifing kayıtlarının listesi — `{id, date, ticker, name, slot?}`; frontend hangi gün/slot kombinasyonlarının mevcut olduğunu buradan öğrenir. |
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
