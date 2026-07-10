# -*- coding: utf-8 -*-
"""
Günlük Şirket Brifingi — üretici script
=======================================
Her sabah cron tarafından çalıştırılır. Her gün 2 hisseye bakar — iki bağımsız slot:
  - "upcoming": bilançosuna en fazla 7 gün kalan, en yakın tarihli hisse
  - "reported": son 2 gün içinde bilanço açıklamış hisse
  Her slot kendi doğal adayını bulamazsa büyük hareket > rotasyona düşer; iki slot
  asla aynı hisseyi seçmez (select_tickers()).
Akış (her slot için ayrı ayrı):
  1. Hisse seç
  2. yfinance'ten finansallar + Alpaca'dan haberler
  3. Claude API ile Türkçe yorum, karşı argüman, günün kavramı
  4. site/briefings/YYYY-MM-DD-<slot>.json + manifest.json yaz

Kullanım:
  python3 briefing_generator.py                 # normal (gerçek veri)
  python3 briefing_generator.py --ticker NVDA   # hisseyi elle seç
  python3 briefing_generator.py --mock NVDA     # ağ yok, temsili veri üret
  python3 briefing_generator.py --date 2026-07-09  # tarih override (test)

Gerekli ortam değişkenleri (.env — deploy.sh yükler):
  ANTHROPIC_API_KEY, ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY
  (opsiyonel) CLAUDE_MODEL
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tr_date(d):
    return f"{d.day} {TR_MONTHS[d.month - 1]}"


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------

def load_state():
    path = os.path.join(BASE_DIR, config.STATE_FILE)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": -1, "last_ticker": None}


def save_state(state):
    with open(os.path.join(BASE_DIR, config.STATE_FILE), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def tone_from_threshold(value, key, invert=False):
    """Eşiklere göre yeşil/gri/sarı. invert=True ise düşük değer iyidir."""
    if value is None:
        return "gray"
    t = config.THRESHOLDS[key]
    v = -value if invert else value
    if v >= t["green"]:
        return "green"
    if v < t["amber"]:
        return "amber"
    return "gray"


def fmt_usd(n):
    """Ham USD -> $46.7B / $312M gibi."""
    if n is None:
        return "veri yok"
    a = abs(n)
    if a >= 1e12:
        return f"${n / 1e12:.2f}T"
    if a >= 1e9:
        return f"${n / 1e9:.1f}B"
    if a >= 1e6:
        return f"${n / 1e6:.0f}M"
    return f"${n:,.0f}"


def pct_str(x, signed=True, decimals=0):
    if x is None:
        return "—"
    s = "+" if (signed and x >= 0) else ""
    return f"{s}%{abs(x):.{decimals}f}" if x >= 0 else f"-%{abs(x):.{decimals}f}"


# ----------------------------------------------------------------------
# 1) HİSSE SEÇİMİ
# ----------------------------------------------------------------------

def _scan_earnings():
    """Watchlist'i tek geçişte tarar.
    reported: watchlist sırasıyla, son EARNINGS_LOOKBACK_DAYS gün içinde bilanço
      açıklayanlar (delta, ticker, tarih).
    upcoming: önümüzdeki EARNINGS_UPCOMING_DAYS gün içinde bilanço açıklayacaklar,
      en yakın tarihliden başlayarak sıralı (days_until, ticker, tarih).
    """
    import yfinance as yf

    today = datetime.now(timezone.utc).date()
    reported, upcoming = [], []
    for t in config.WATCHLIST:
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=8)
            if ed is None or ed.empty:
                continue
            for d in ed.index:
                dd = d.date()
                delta = (today - dd).days
                if 0 <= delta <= config.EARNINGS_LOOKBACK_DAYS:
                    reported.append((delta, t, dd))
                days_until = -delta
                if 0 < days_until <= config.EARNINGS_UPCOMING_DAYS:
                    upcoming.append((days_until, t, dd))
            time.sleep(0.3)
        except Exception as e:
            log(f"  bilanço kontrolü atlandı ({t}): {e}")

    upcoming.sort(key=lambda c: c[0])
    return reported, upcoming


def _mover_or_rotation(state, exclude=()):
    """Eski zincirin geri kalanı: büyük hareket > rotasyon. exclude'daki hisseleri atlar."""
    import yfinance as yf

    try:
        data = yf.download(config.WATCHLIST, period="5d", progress=False,
                           auto_adjust=True)["Close"].dropna(how="all")
        if len(data) >= 2:
            chg = (data.iloc[-1] / data.iloc[-2] - 1.0) * 100.0
            chg = chg.dropna().drop(index=[t for t in exclude if t in chg.index])
            if not chg.empty:
                top = chg.abs().idxmax()
                if abs(chg[top]) >= config.MOVER_THRESHOLD_PCT:
                    log(f"Seçim: {top} — dün %{chg[top]:.1f} hareket etti")
                    yon = "yükseldi" if chg[top] > 0 else "düştü"
                    return top, {"reason_code": "mover",
                                 "text": f"Dün %{abs(chg[top]):.1f} {yon} — büyük hareket"}
    except Exception as e:
        log(f"  hareket taraması atlandı: {e}")

    idx = state.get("last_index", -1)
    for _ in range(len(config.WATCHLIST)):
        idx = (idx + 1) % len(config.WATCHLIST)
        t = config.WATCHLIST[idx]
        if t not in exclude:
            state["last_index"] = idx
            log(f"Seçim: {t} — sıralı rotasyon ({idx + 1}/{len(config.WATCHLIST)})")
            return t, {"reason_code": "rotation", "text": "Sıralı rotasyon — düzenli check-up"}
    # watchlist'in tamamı exclude ise (pratikte olmaz) ilk elemana düş
    return config.WATCHLIST[0], {"reason_code": "rotation", "text": "Sıralı rotasyon — düzenli check-up"}


def select_tickers(state):
    """Günde 2 hisse seçer — bağımsız iki slot:
      upcoming: önümüzdeki 7 gün içinde bilanço açıklayacak, en yakın tarihli olan.
      reported: son 2 gün içinde bilanço açıklamış olan.
    Her ikisi de doğal aday bulamazsa eski zincire (büyük hareket > rotasyon) düşer.
    İki slot da asla aynı hisseyi seçmez.
    """
    reported_list, upcoming_list = _scan_earnings()

    reported_pick = None
    if reported_list:
        delta, t, dd = reported_list[0]
        log(f"Seçim (yeni açıklanan): {t} — {dd} tarihinde bilanço açıkladı")
        ne_zaman = ("Bugün" if delta == 0
                    else "Dün" if delta == 1
                    else f"{delta} gün önce")
        reported_pick = (t, {"reason_code": "earnings",
                             "text": f"{ne_zaman} bilanço açıkladı ({tr_date(dd)})"})

    upcoming_pick = None
    reported_ticker = reported_pick[0] if reported_pick else None
    for days_until, t, dd in upcoming_list:
        if t == reported_ticker:
            continue
        log(f"Seçim (yaklaşan): {t} — {dd} tarihinde bilanço açıklayacak ({days_until} gün kaldı)")
        kalan = "yarın" if days_until == 1 else f"{days_until} gün sonra"
        upcoming_pick = (t, {"reason_code": "upcoming_earnings",
                             "text": f"Bilanço {kalan} açıklanacak ({tr_date(dd)}) — beklentileri incele"})
        break

    if upcoming_pick is None:
        exclude = {reported_ticker} if reported_ticker else set()
        upcoming_pick = _mover_or_rotation(state, exclude=exclude)

    if reported_pick is None:
        exclude = {upcoming_pick[0]}
        reported_pick = _mover_or_rotation(state, exclude=exclude)

    return [
        {"slot": "upcoming", "ticker": upcoming_pick[0], "why": upcoming_pick[1]},
        {"slot": "reported", "ticker": reported_pick[0], "why": reported_pick[1]},
    ]


# ----------------------------------------------------------------------
# 2) VERİ TOPLAMA (yfinance + Alpaca)
# ----------------------------------------------------------------------

def _row(df, *names):
    """DataFrame'de verilen isimlerden ilk bulunan satırı liste olarak döndür."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            return [None if (v != v) else float(v) for v in df.loc[n].tolist()]
    return None


def fetch_financials(ticker):
    """yfinance'ten şirket verilerini topla. Eksikler None kalır."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    out = {"ticker": ticker}

    try:
        info = t.info or {}
    except Exception:
        info = {}
    out["name"] = info.get("shortName") or info.get("longName") or ticker
    out["sector"] = info.get("sector") or "—"
    out["industry"] = info.get("industry") or ""
    out["market_cap"] = info.get("marketCap")

    # Fiyat
    try:
        fi = t.fast_info
        last = float(fi["last_price"])
        prev = float(fi["previous_close"])
        out["price"] = {"last": round(last, 2),
                        "change_pct": round((last / prev - 1) * 100, 2)}
    except Exception:
        out["price"] = {"last": None, "change_pct": None}

    # Çeyreklik gelir tablosu (yfinance: en yeni sütun solda)
    try:
        inc = t.quarterly_income_stmt
        out["q_labels"] = [c.strftime("%b'%y") for c in inc.columns][::-1]
        out["revenue"] = (_row(inc, "Total Revenue") or [])[::-1]
        out["gross"] = (_row(inc, "Gross Profit") or [])[::-1]
        out["opinc"] = (_row(inc, "Operating Income") or [])[::-1]
        out["netinc"] = (_row(inc, "Net Income",
                              "Net Income Common Stockholders") or [])[::-1]
    except Exception as e:
        log(f"  gelir tablosu alınamadı: {e}")
        out.update({"q_labels": [], "revenue": [], "gross": [],
                    "opinc": [], "netinc": []})

    # Nakit akışı + bilanço
    try:
        cf = t.quarterly_cashflow
        fcf = _row(cf, "Free Cash Flow")
        out["fcf"] = fcf[0] if fcf else None
    except Exception:
        out["fcf"] = None
    try:
        bs = t.quarterly_balance_sheet
        cash = _row(bs, "Cash And Cash Equivalents",
                    "Cash Cash Equivalents And Short Term Investments")
        out["cash"] = cash[0] if cash else None
    except Exception:
        out["cash"] = None

    # Bilanço tarihleri + EPS beklenti/gerçekleşme
    out["earnings"] = {"last_date": None, "next_date": None,
                       "eps_actual": None, "eps_estimate": None}
    try:
        ed = t.get_earnings_dates(limit=12)
        if ed is not None and not ed.empty:
            now = datetime.now(timezone.utc)
            past = [d for d in ed.index if d.to_pydatetime() <= now]
            future = [d for d in ed.index if d.to_pydatetime() > now]
            if past:
                lastd = max(past)
                out["earnings"]["last_date"] = lastd.date().isoformat()
                row = ed.loc[lastd]
                if hasattr(row, "iloc") and getattr(row, "ndim", 1) > 1:
                    row = row.iloc[0]
                ra = row.get("Reported EPS")
                re_ = row.get("EPS Estimate")
                out["earnings"]["eps_actual"] = None if ra != ra else float(ra)
                out["earnings"]["eps_estimate"] = None if re_ != re_ else float(re_)
            if future:
                out["earnings"]["next_date"] = min(future).date().isoformat()
    except Exception as e:
        log(f"  bilanço takvimi alınamadı: {e}")

    return out


def fetch_news(ticker):
    """Alpaca News API — paper trading anahtarlarıyla çalışır."""
    import requests

    key = os.environ.get("ALPACA_API_KEY_ID")
    sec = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not sec:
        log("  Alpaca anahtarları yok — haberler atlanıyor")
        return []
    start = (datetime.now(timezone.utc)
             - timedelta(days=config.NEWS_LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = requests.get(
            "https://data.alpaca.markets/v1beta1/news",
            params={"symbols": ticker, "limit": config.NEWS_LIMIT,
                    "start": start, "sort": "desc"},
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
            timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("news", [])
        return [{"headline": n.get("headline", ""),
                 "source": n.get("source", ""),
                 "url": n.get("url", ""),
                 "published": n.get("created_at", "")[:10]} for n in items]
    except Exception as e:
        log(f"  Alpaca haberleri alınamadı: {e}")
        return []


# ----------------------------------------------------------------------
# 3) HESAPLAMALAR — KPI + karne + grafikler
# ----------------------------------------------------------------------

def safe_pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1.0) * 100.0


def margin(num, den):
    if num is None or den in (None, 0):
        return None
    return num / den * 100.0


def build_metrics(f):
    rev, gross, opinc, netinc = f["revenue"], f["gross"], f["opinc"], f["netinc"]
    n = len(rev)

    def yoy(series):
        return safe_pct(series[-1], series[-5]) if len(series) >= 5 else \
               safe_pct(series[-1], series[0]) if len(series) >= 2 else None

    rev_yoy = yoy(rev) if n else None
    ni_yoy = yoy(netinc) if netinc else None

    gm = [margin(g, r) for g, r in zip(gross, rev)] if gross and rev else []
    om = [margin(o, r) for o, r in zip(opinc, rev)] if opinc and rev else []
    gm_last = gm[-1] if gm else None
    gm_qoq = (gm[-1] - gm[-2]) if len(gm) >= 2 and None not in (gm[-1], gm[-2]) else None
    om_last = om[-1] if om else None
    om_yoy = (om[-1] - om[-5]) if len(om) >= 5 and None not in (om[-1], om[-5]) else None

    fcf = f.get("fcf")
    fcf_m = margin(fcf, rev[-1]) if (fcf is not None and rev) else None

    eps_a = f["earnings"].get("eps_actual")
    eps_e = f["earnings"].get("eps_estimate")
    eps_beat = None
    if eps_a is not None and eps_e is not None:
        eps_beat = "beat" if eps_a > eps_e else ("miss" if eps_a < eps_e else "inline")

    return {"rev_yoy": rev_yoy, "ni_yoy": ni_yoy, "gm": gm, "om": om,
            "gm_last": gm_last, "gm_qoq": gm_qoq, "om_last": om_last,
            "om_yoy": om_yoy, "fcf": fcf, "fcf_m": fcf_m,
            "eps_a": eps_a, "eps_e": eps_e, "eps_beat": eps_beat}


def build_kpi(f, m):
    rev = f["revenue"]
    eps_sub = "veri yok"
    eps_tone = "neutral"
    eps_val = "—"
    if m["eps_a"] is not None:
        eps_val = f"${m['eps_a']:.2f}"
        if m["eps_beat"] == "beat":
            eps_sub, eps_tone = f"Beat · beklenti ${m['eps_e']:.2f}", "pos"
        elif m["eps_beat"] == "miss":
            eps_sub, eps_tone = f"Miss · beklenti ${m['eps_e']:.2f}", "neg"
        elif m["eps_e"] is not None:
            eps_sub = f"beklentiyle uyumlu (${m['eps_e']:.2f})"
    return [
        {"label": "Gelir (çeyrek)",
         "value": fmt_usd(rev[-1]) if rev else "veri yok",
         "sub": f"{pct_str(m['rev_yoy'])} y/y" if m["rev_yoy"] is not None else "y/y veri yok",
         "tone": "pos" if (m["rev_yoy"] or 0) > 0 else "neg" if m["rev_yoy"] is not None else "neutral"},
        {"label": "EPS", "value": eps_val, "sub": eps_sub, "tone": eps_tone},
        {"label": "Brüt marj",
         "value": f"%{m['gm_last']:.1f}" if m["gm_last"] is not None else "veri yok",
         "sub": (f"{'+' if m['gm_qoq'] >= 0 else ''}{m['gm_qoq']:.1f} puan ç/ç"
                 if m["gm_qoq"] is not None else "ç/ç veri yok"),
         "tone": "pos" if (m["gm_qoq"] or 0) > 0 else "neg" if m["gm_qoq"] is not None else "neutral"},
        {"label": "Serbest nakit akışı",
         "value": fmt_usd(m["fcf"]),
         "sub": f"marj %{m['fcf_m']:.0f}" if m["fcf_m"] is not None else "marj veri yok",
         "tone": "pos" if (m["fcf"] or 0) > 0 else "neg" if m["fcf"] is not None else "neutral"},
    ]


def build_karne(f, m, guidance_row=None):
    rows_growth = [
        {"metric": "Gelir", "value": fmt_usd(f["revenue"][-1]) if f["revenue"] else "veri yok",
         "note": f"{pct_str(m['rev_yoy'])} y/y" if m["rev_yoy"] is not None else "y/y veri yok",
         "tone": tone_from_threshold(m["rev_yoy"], "revenue_yoy")},
        {"metric": "Net kâr", "value": fmt_usd(f["netinc"][-1]) if f["netinc"] else "veri yok",
         "note": f"{pct_str(m['ni_yoy'])} y/y" if m["ni_yoy"] is not None else "y/y veri yok",
         "tone": tone_from_threshold(m["ni_yoy"], "netinc_yoy")},
    ]
    eps_note, eps_tone = "veri yok", "gray"
    if m["eps_beat"] == "beat":
        eps_note, eps_tone = f"beklenti ${m['eps_e']:.2f} — üstünde", "green"
    elif m["eps_beat"] == "miss":
        eps_note, eps_tone = f"beklenti ${m['eps_e']:.2f} — altında", "amber"
    elif m["eps_beat"] == "inline":
        eps_note = "beklentiyle uyumlu"
    rows_growth.append({"metric": "EPS",
                        "value": f"${m['eps_a']:.2f}" if m["eps_a"] is not None else "veri yok",
                        "note": eps_note, "tone": eps_tone})

    rows_prof = [
        {"metric": "Brüt marj",
         "value": f"%{m['gm_last']:.1f}" if m["gm_last"] is not None else "veri yok",
         "note": (f"{'+' if m['gm_qoq'] >= 0 else ''}{m['gm_qoq']:.1f} puan ç/ç"
                  if m["gm_qoq"] is not None else "ç/ç veri yok"),
         "tone": tone_from_threshold(m["gm_qoq"], "gm_qoq_pts")},
        {"metric": "Faaliyet marjı",
         "value": f"%{m['om_last']:.1f}" if m["om_last"] is not None else "veri yok",
         "note": (f"{'+' if m['om_yoy'] >= 0 else ''}{m['om_yoy']:.1f} puan y/y"
                  if m["om_yoy"] is not None else "y/y veri yok"),
         "tone": tone_from_threshold(m["om_yoy"], "opm_yoy_pts")},
    ]

    rows_cash = [
        {"metric": "Serbest nakit akışı", "value": fmt_usd(m["fcf"]),
         "note": f"marj %{m['fcf_m']:.0f}" if m["fcf_m"] is not None else "marj veri yok",
         "tone": tone_from_threshold(m["fcf_m"], "fcf_margin")},
        {"metric": "Nakit ve benzerleri", "value": fmt_usd(f.get("cash")),
         "note": "bilanço kalemi", "tone": "gray"},
    ]

    groups = [
        {"name": "Büyüme", "rows": rows_growth},
        {"name": "Kârlılık", "rows": rows_prof},
        {"name": "Nakit", "rows": rows_cash},
    ]
    if guidance_row:
        groups.append({"name": "Guidance", "rows": [guidance_row]})
    return groups


def build_charts(f, m):
    labels = f.get("q_labels", [])
    rev_b = [round(r / 1e9, 1) if r is not None else None for r in f.get("revenue", [])]
    gm = [round(g, 1) if g is not None else None for g in m.get("gm", [])]
    return {"revenue": {"labels": labels, "values": rev_b, "unit": "$B"},
            "gross_margin": {"labels": labels, "values": gm, "unit": "%"}}


def build_calendar(f, ref_date):
    e = f["earnings"]
    cal = {"last_date": e.get("last_date"), "next_date": e.get("next_date"),
           "last_label": None, "next_label": None,
           "days_to_next": None, "progress_pct": None}
    try:
        if cal["last_date"]:
            cal["last_label"] = tr_date(datetime.fromisoformat(cal["last_date"]))
        if cal["next_date"]:
            nd = datetime.fromisoformat(cal["next_date"]).date()
            cal["next_label"] = tr_date(datetime.fromisoformat(cal["next_date"]))
            cal["days_to_next"] = max((nd - ref_date).days, 0)
        if cal["last_date"] and cal["next_date"]:
            ld = datetime.fromisoformat(cal["last_date"]).date()
            nd = datetime.fromisoformat(cal["next_date"]).date()
            span = (nd - ld).days
            if span > 0:
                cal["progress_pct"] = round(
                    min(max((ref_date - ld).days / span * 100, 0), 100))
    except Exception:
        pass
    return cal


# ----------------------------------------------------------------------
# 4) CLAUDE — Türkçe yorum katmanı
# ----------------------------------------------------------------------

CLAUDE_SYSTEM = """Sen deneyimli, uzun vadeli düşünen bir yatırım analistisin. İş modeli kalitesi,
ekonomik hendek (moat), fiyatlama gücü, marj trendi ve serbest nakit akışına odaklanırsın.
Günlük gürültüden çok 3-5 yıllık resme bakarsın; "bu şirket 5 yıl sonra daha mı değerli olur?"
sorusunu önemsersin. Yağız'ın günlük şirket brifingi için yorum üretiyorsun.
Tek taraflı iyimserlikten kaçın, değerlemeyi ihmal etme.
SADECE geçerli JSON döndür — başka hiçbir şey yazma, markdown kod bloğu kullanma."""

CLAUDE_PROMPT = """Şirket: {name} ({ticker}) — sektör: {sector}
Bugünün tarihi: {date}
Neden bugün seçildi: {why}

Finansal özet (son çeyrek):
{metrics}

Son 7 günün haber başlıkları (İngilizce, kaynaklarıyla):
{news}

Şu şemada JSON üret (tüm metinler Türkçe, kısa ve net):
{{
  "about": "şirketin ne iş yaptığını sade Türkçeyle 1-2 cümlede anlat: ürünler, müşteriler, para kazanma modeli",
  "note": "2-3 cümlelik uzun vadeli sentez: iş modelinin kalitesi, moat ve bu çeyreğin 3-5 yıllık yatırım tezine etkisi",
  "counter": "1-2 cümle: uzun vadeli tezi en çok tehdit eden yapısal risk",
  "watch": ["önümüzdeki çeyreklerde izlenecek yapısal gösterge 1", "yapısal gösterge 2"],
  "concept": {{"title": "bugünün finansal kavramı (bu şirketle ilgili)", "body": "2 cümlelik açıklama, mümkünse bu şirketten örnekle"}},
  "guidance": {{"value": "şirketin son guidance'ı haberlerde/verilerde geçiyorsa özetle, yoksa 'veri yok'", "note": "kısa yorum", "tone": "green|gray|amber"}},
  "news": [{{"i": haber_index, "ozet": "tek cümlelik Türkçe özet", "sentiment": "pos|neu|neg"}}]
}}
news dizisinde en fazla {news_shown} haber seç (en önemlileri), i alanı verdiğim listedeki sıra numarası olsun."""


def call_claude(payload_text, news_lines, meta):
    import requests

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("  ANTHROPIC_API_KEY yok — AI yorumu atlanıyor")
        return None
    model = os.environ.get("CLAUDE_MODEL", config.CLAUDE_MODEL_DEFAULT)
    prompt = CLAUDE_PROMPT.format(
        name=meta["name"], ticker=meta["ticker"], sector=meta["sector"],
        date=meta["date"], why=meta["why"], metrics=payload_text,
        news=news_lines or "(haber bulunamadı)", news_shown=config.NEWS_SHOWN)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": config.CLAUDE_MAX_TOKENS,
                  "system": CLAUDE_SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text")
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:
        log(f"  Claude çağrısı başarısız: {e}")
        return None


def metrics_text(f, m):
    lines = []
    if f["revenue"]:
        lines.append(f"- Gelir: {fmt_usd(f['revenue'][-1])} ({pct_str(m['rev_yoy'])} y/y)")
    if m["eps_a"] is not None:
        lines.append(f"- EPS: ${m['eps_a']:.2f} (beklenti: "
                     f"{'$%.2f' % m['eps_e'] if m['eps_e'] is not None else '—'}, {m['eps_beat'] or '—'})")
    if m["gm_last"] is not None:
        lines.append(f"- Brüt marj: %{m['gm_last']:.1f}"
                     + (f" ({'+' if m['gm_qoq'] >= 0 else ''}{m['gm_qoq']:.1f} puan ç/ç)"
                        if m["gm_qoq"] is not None else ""))
    if m["om_last"] is not None:
        lines.append(f"- Faaliyet marjı: %{m['om_last']:.1f}")
    if m["fcf"] is not None:
        lines.append(f"- FCF: {fmt_usd(m['fcf'])}"
                     + (f" (marj %{m['fcf_m']:.0f})" if m["fcf_m"] is not None else ""))
    if f.get("cash") is not None:
        lines.append(f"- Nakit: {fmt_usd(f['cash'])}")
    return "\n".join(lines) or "(finansal veri sınırlı)"


# ----------------------------------------------------------------------
# 5) ÇIKTI
# ----------------------------------------------------------------------

def write_output(date_str, file_suffix, doc):
    """file_suffix=None -> eski tekli davranış (dosya: YYYY-MM-DD.json, geriye dönük uyum).
    file_suffix='upcoming'/'reported'/'pinned-NVDA' -> dosya: YYYY-MM-DD-<suffix>.json.
    Manifest'e yazılan slot etiketi doc["slot"]'tan gelir (upcoming/reported/pinned)."""
    file_id = date_str if file_suffix is None else f"{date_str}-{file_suffix}"
    bdir = os.path.join(BASE_DIR, config.BRIEFINGS_DIR)
    os.makedirs(bdir, exist_ok=True)
    with open(os.path.join(bdir, f"{file_id}.json"), "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1)

    mpath = os.path.join(bdir, "manifest.json")
    manifest = []
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fp:
            manifest = json.load(fp)
    manifest = [e for e in manifest if e.get("id", e.get("date")) != file_id]
    entry = {"id": file_id, "date": date_str, "ticker": doc["ticker"],
             "name": doc["company"]["name"]}
    if doc.get("slot"):
        entry["slot"] = doc["slot"]
    manifest.insert(0, entry)
    manifest.sort(key=lambda e: (e["date"], e.get("slot", "")), reverse=True)
    with open(mpath, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=1)
    log(f"Yazıldı: briefings/{file_id}.json (manifest: {len(manifest)} kayıt)")


# ----------------------------------------------------------------------
# MOCK — ağ olmadan uçtan uca test için temsili veri
# ----------------------------------------------------------------------

def mock_doc(ticker, date_str):
    d = datetime.fromisoformat(date_str)
    return {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mock": True,
        "ticker": ticker,
        "company": {"name": "NVIDIA" if ticker == "NVDA" else f"{ticker} Corp.",
                    "sector": "Technology", "industry": "Semiconductors", "market_cap": 4.5e12},
        "why_today": {"reason_code": "earnings", "text": "Dün bilanço açıkladı"},
        "price": {"last": 184.20, "change_pct": 4.8},
        "earnings_calendar": {"last_date": "2026-05-27", "last_label": "27 Mayıs",
                              "next_date": "2026-08-26", "next_label": "26 Ağustos",
                              "days_to_next": 48, "progress_pct": 47},
        "kpi": [
            {"label": "Gelir (çeyrek)", "value": "$46.7B", "sub": "+%62 y/y", "tone": "pos"},
            {"label": "EPS", "value": "$1.42", "sub": "Beat · beklenti $1.29", "tone": "pos"},
            {"label": "Brüt marj", "value": "%72.4", "sub": "+1.1 puan ç/ç", "tone": "pos"},
            {"label": "Serbest nakit akışı", "value": "$16.8B", "sub": "marj %36", "tone": "pos"},
        ],
        "karne": {"template": "çekirdek şablon v1",
                  "period_label": f"Son bilanço dönemi ({tr_date(d)} itibarıyla)",
                  "groups": [
                      {"name": "Büyüme", "rows": [
                          {"metric": "Gelir", "value": "$46.7B", "note": "+%62 y/y", "tone": "green"},
                          {"metric": "Net kâr", "value": "$26.4B", "note": "+%80 y/y", "tone": "green"},
                          {"metric": "EPS", "value": "$1.42", "note": "beklenti $1.29 — üstünde", "tone": "green"}]},
                      {"name": "Kârlılık", "rows": [
                          {"metric": "Brüt marj", "value": "%72.4", "note": "+1.1 puan ç/ç", "tone": "green"},
                          {"metric": "Faaliyet marjı", "value": "%62.0", "note": "+2.4 puan y/y", "tone": "green"}]},
                      {"name": "Nakit", "rows": [
                          {"metric": "Serbest nakit akışı", "value": "$16.8B", "note": "marj %36", "tone": "green"},
                          {"metric": "Nakit ve benzerleri", "value": "$53.0B", "note": "bilanço kalemi", "tone": "gray"}]},
                      {"name": "Guidance", "rows": [
                          {"metric": "Gelecek çeyrek gelir", "value": "$54B ±%2",
                           "note": "konsensüs üstü", "tone": "green"}]},
                  ]},
        "charts": {
            "revenue": {"labels": ["Eyl'24", "Ara'24", "Mar'25", "Haz'25", "Eyl'25", "Ara'25", "Mar'26", "Haz'26"],
                        "values": [18.1, 22.1, 26.0, 30.0, 35.1, 39.3, 44.1, 46.7], "unit": "$B"},
            "gross_margin": {"labels": ["Eyl'24", "Ara'24", "Mar'25", "Haz'25", "Eyl'25", "Ara'25", "Mar'26", "Haz'26"],
                             "values": [66.1, 67.0, 68.9, 68.2, 69.8, 70.6, 71.3, 72.4], "unit": "%"},
        },
        "news": [
            {"headline_tr": "Data center gelirinde yeni rekor; hyperscaler talebi 2027'ye kadar dolu görünüyor",
             "source": "Reuters", "published": date_str, "url": "https://example.com/1", "sentiment": "pos"},
            {"headline_tr": "Yeni nesil çip mimarisinin üretim takvimi teyit edildi, ilk sevkiyat 4. çeyrek",
             "source": "Bloomberg", "published": date_str, "url": "https://example.com/2", "sentiment": "neu"},
            {"headline_tr": "Çin'e ihracat kısıtlamalarında yeni belirsizlik; gelirin ~%9'u risk altında",
             "source": "FT", "published": date_str, "url": "https://example.com/3", "sentiment": "neg"},
        ],
        "ai": {
            "about": "Veri merkezleri ve yapay zeka için grafik işlemcileri (GPU) tasarlar; gelirinin büyük kısmı bulut devlerinin AI altyapı yatırımlarından gelir.",
            "note": "Rakamlar güçlü ama asıl hikâye marjda: sekiz çeyrektir yükselen brüt marj, fiyatlama gücünün hâlâ elde olduğunu söylüyor. Neden şimdi sorusunun cevabı bilanço sonrası momentum — ancak Çin riskinin guidance'a ne kadar yedirildiğine bakmadan pozisyon açmak aceleci olur.",
            "counter": "Beklenti o kadar yüksek ki beat bile fiyatın içinde olabilir — 45x ileri F/K'da hata payı dar.",
            "watch": ["Gelecek çeyrek guidance'ı Çin'siz senaryoyu içeriyor mu",
                      "Envanter büyümesi gelir büyümesini aşarsa erken uyarı sinyali"],
            "concept": {"title": "Operating leverage",
                        "body": "Gelir büyürken sabit maliyetlerin aynı kalması sayesinde kârın gelirden daha hızlı büyümesi. Bu çeyrekte gelir +%62 iken net kârın +%80 artmasının sebebi bu."},
        },
    }


# ----------------------------------------------------------------------
# ANA AKIŞ
# ----------------------------------------------------------------------

def generate_for_ticker(ticker, why, date_str, ref_date, slot=None, file_suffix=None):
    """Tek bir hisse için tüm veri toplama + Claude yorumu + JSON çıktı akışı.
    file_suffix verilmezse slot kullanılır (pinned'de 'pinned-NVDA' gibi ayrışır)."""
    if file_suffix is None:
        file_suffix = slot
    log(f"Veri çekiliyor: {ticker}" + (f" [{slot}]" if slot else ""))
    f = fetch_financials(ticker)
    news_raw = fetch_news(ticker)
    m = build_metrics(f)

    news_lines = "\n".join(f"{i}. [{n['source']} {n['published']}] {n['headline']}"
                           for i, n in enumerate(news_raw))
    ai = call_claude(metrics_text(f, m), news_lines,
                     {"name": f["name"], "ticker": ticker, "sector": f["sector"],
                      "date": date_str, "why": why["text"]})

    # Haberleri Claude'un seçimiyle eşle; Claude yoksa ham başlıkları göster
    news_out = []
    if ai and ai.get("news"):
        for item in ai["news"][:config.NEWS_SHOWN]:
            i = item.get("i")
            if isinstance(i, int) and 0 <= i < len(news_raw):
                src = news_raw[i]
                news_out.append({"headline_tr": item.get("ozet", src["headline"]),
                                 "source": src["source"], "published": src["published"],
                                 "url": src["url"],
                                 "sentiment": item.get("sentiment", "neu")})
    if not news_out:
        news_out = [{"headline_tr": n["headline"], "source": n["source"],
                     "published": n["published"], "url": n["url"], "sentiment": "neu"}
                    for n in news_raw[:config.NEWS_SHOWN]]

    guidance_row = None
    if ai and ai.get("guidance") and ai["guidance"].get("value") not in (None, "", "veri yok"):
        g = ai["guidance"]
        guidance_row = {"metric": "Guidance", "value": g.get("value", "—"),
                        "note": g.get("note", ""),
                        "tone": g.get("tone", "gray") if g.get("tone") in ("green", "gray", "amber") else "gray"}

    doc = {
        "date": date_str,
        "slot": slot,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mock": False,
        "ticker": ticker,
        "company": {"name": f["name"], "sector": f["sector"], "industry": f.get("industry", ""), "market_cap": f["market_cap"]},
        "why_today": why,
        "price": f["price"],
        "earnings_calendar": build_calendar(f, ref_date),
        "kpi": build_kpi(f, m),
        "karne": {"template": "çekirdek şablon v1",
                  "period_label": (f"Son bilanço: {tr_date(datetime.fromisoformat(f['earnings']['last_date']))}"
                                   if f["earnings"].get("last_date") else "Son çeyrek"),
                  "groups": build_karne(f, m, guidance_row)},
        "charts": build_charts(f, m),
        "news": news_out,
        "ai": ai and {"about": ai.get("about", ""), "note": ai.get("note", ""), "counter": ai.get("counter", ""),
                      "watch": ai.get("watch", [])[:3],
                      "concept": ai.get("concept", {})} or None,
    }

    write_output(date_str, file_suffix, doc)
    return ticker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="Hisseyi elle seç (otomatik iki-hisse seçimini atlar)")
    ap.add_argument("--mock", metavar="TICKER", help="Ağ kullanmadan temsili veri üret")
    ap.add_argument("--date", help="YYYY-MM-DD (varsayılan: bugün)")
    args = ap.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    ref_date = datetime.fromisoformat(date_str).date()

    if args.mock:
        log(f"MOCK mod: {args.mock} / {date_str}")
        write_output(date_str, None, mock_doc(args.mock.upper(), date_str))
        return

    state = load_state()

    if args.ticker:
        ticker = args.ticker.upper()
        why = {"reason_code": "manual", "text": "Elle seçildi"}
        generate_for_ticker(ticker, why, date_str, ref_date, slot=None)
        state["last_ticker"] = ticker
        save_state(state)
        log("Tamamlandı.")
        return

    picks = select_tickers(state)

    # Bugün için sabitlenmiş hisseler (config.PINNED) — otomatik seçime EK brifing
    auto_tickers = {p["ticker"] for p in picks}
    for t in getattr(config, "PINNED", {}).get(date_str, []):
        t = t.upper()
        if t in auto_tickers:
            log(f"Sabitlenen {t} zaten otomatik seçildi — yinelenmiyor")
            continue
        log(f"Seçim (sabitlenen): {t} — {date_str} için config.PINNED'de")
        picks.append({"slot": "pinned", "ticker": t,
                      "why": {"reason_code": "pinned",
                              "text": "Bugün için senin sabitlediğin hisse"},
                      "file_suffix": f"pinned-{t}"})
        auto_tickers.add(t)

    for p in picks:
        generate_for_ticker(p["ticker"], p["why"], date_str, ref_date,
                            slot=p["slot"], file_suffix=p.get("file_suffix"))
    state["last_ticker"] = [p["ticker"] for p in picks]
    save_state(state)
    log("Tamamlandı.")


if __name__ == "__main__":
    main()
