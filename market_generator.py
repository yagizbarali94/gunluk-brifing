# -*- coding: utf-8 -*-
"""
Piyasa Rejimi — üretici script
==============================
Günde bir kez çalışır (hisse brifingiyle aynı workflow). "Piyasanın yönü ne olur"
tahmini DEĞİL; piyasanın şu an hangi rejimde olduğunu gösteren göstergeleri toplar:
  1. Trend & rejim (endeksler + 50/200 gün ortalama)
  2. Korku (VIX + vade yapısı)
  3. Genişlik / breadth (eşit-ağırlık vs cap-ağırlık, 200g üstü sektör oranı)
  4. Sektör rotasyonu (defansif mi döngüsel mi önde)
  5. Makro arka plan (faiz, getiri eğrisi, dolar, altın, petrol, kredi)
  6. Takvim (makro olaylar + bu haftaki mega-cap bilançoları)
  7. Claude sentezi (Türkçe rejim okuması, al/sat yok, tahmin yok)

Çıktı: site/market.json  (Netlify otomatik yayınlar)

Kullanım:
  python3 market_generator.py            # gerçek veri
  python3 market_generator.py --mock     # ağ yok, temsili veri
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def tr_date(d):
    return f"{d.day} {TR_MONTHS[d.month - 1]}"


def pct(x, dec=1, signed=True):
    if x is None:
        return "—"
    s = "+" if (signed and x >= 0) else ("-" if x < 0 else "")
    return f"{s}%{abs(x):.{dec}f}"


# ----------------------------------------------------------------------
# VERİ TOPLAMA
# ----------------------------------------------------------------------

def fetch_prices(tickers, period="1y"):
    import yfinance as yf
    data = yf.download(list(tickers), period=period, progress=False,
                       auto_adjust=True)["Close"]
    return data


def _series(data, t):
    try:
        s = data[t].dropna()
        return s if len(s) else None
    except Exception:
        return None


def _last(data, t):
    s = _series(data, t)
    return float(s.iloc[-1]) if s is not None else None


def _ma(data, t, n):
    s = _series(data, t)
    return float(s.tail(n).mean()) if (s is not None and len(s) >= n) else None


def _chg(data, t, days):
    s = _series(data, t)
    if s is None or len(s) <= days:
        return None
    return float((s.iloc[-1] / s.iloc[-1 - days] - 1) * 100)


def _chg_period(data, t, lookback):
    s = _series(data, t)
    if s is None or len(s) < 2:
        return None
    ref = s.iloc[-min(lookback, len(s))]
    return float((s.iloc[-1] / ref - 1) * 100) if ref else None


# ----------------------------------------------------------------------
# GÖSTERGELER
# ----------------------------------------------------------------------

def build_trend(data):
    """Endekslerin 50/200 gün ortalamaya göre durumu + zirveden uzaklık."""
    rows = []
    above200 = 0
    for t, name in config.MARKET_INDICES.items():
        s = _series(data, t)
        if s is None:
            continue
        last = float(s.iloc[-1])
        ma50 = _ma(data, t, 50)
        ma200 = _ma(data, t, 200)
        hi = float(s.tail(252).max())
        frm_hi = (last / hi - 1) * 100
        a200 = ma200 is not None and last > ma200
        a50 = ma50 is not None and last > ma50
        above200 += 1 if a200 else 0
        state = ("yükseliş trendi" if a200 and a50
                 else "zayıflıyor" if a200 else "düşüş trendi")
        tone = "green" if (a200 and a50) else "amber" if not a200 else "gray"
        rows.append({"ticker": t, "name": name, "last": round(last, 2),
                     "chg_1d": round(_chg(data, t, 1) or 0, 2),
                     "above_50": a50, "above_200": a200,
                     "from_high": round(frm_hi, 1), "state": state, "tone": tone})
    return {"rows": rows, "above_200_count": above200,
            "total": len(rows)}


def build_fear(data):
    vix = _last(data, "^VIX")
    vix3m = _last(data, "^VIX3M")
    zone = "—"
    tone = "gray"
    if vix is not None:
        for lvl, z in config.VIX_ZONES:
            if vix < lvl:
                zone = z
                break
        tone = ("green" if vix < 20 else "gray" if vix < 28 else "amber")
    # Vade yapısı: VIX > VIX3M ise backwardation (akut stres)
    term = None
    if vix is not None and vix3m is not None:
        term = "backwardation" if vix > vix3m else "contango"
    return {"vix": round(vix, 2) if vix else None,
            "vix3m": round(vix3m, 2) if vix3m else None,
            "zone": zone, "term": term, "tone": tone,
            "vix_chg_5d": round(_chg(data, "^VIX", 5) or 0, 1) if vix else None}


def build_breadth(data):
    """Eşit-ağırlık vs cap-ağırlık + 200g üstü sektör oranı."""
    rsp = _chg_period(data, "RSP", 63)  # ~3 ay
    spy = _chg_period(data, "SPY", 63)
    spread = (rsp - spy) if (rsp is not None and spy is not None) else None
    # 200g üstündeki sektör oranı
    n_above = 0
    n_total = 0
    for t in config.MARKET_SECTORS:
        s = _series(data, t)
        if s is None or len(s) < 200:
            continue
        n_total += 1
        if float(s.iloc[-1]) > float(s.tail(200).mean()):
            n_above += 1
    pct_above = (n_above / n_total * 100) if n_total else None
    if spread is None:
        tone, verdict = "gray", "veri yok"
    elif spread > -1:
        tone, verdict = "green", "geniş — yükseliş tabana yayılmış"
    elif spread > -4:
        tone, verdict = "gray", "orta — birkaç dev öne çıkıyor"
    else:
        tone, verdict = "amber", "dar — piyasayı birkaç mega-cap taşıyor"
    return {"rsp_3m": round(rsp, 1) if rsp is not None else None,
            "spy_3m": round(spy, 1) if spy is not None else None,
            "spread": round(spread, 1) if spread is not None else None,
            "pct_sectors_above_200": round(pct_above) if pct_above is not None else None,
            "verdict": verdict, "tone": tone}


def build_sectors(data):
    """Sektör performans sıralaması + defansif/döngüsel eğilim."""
    lb = config.MARKET_LOOKBACK_DAYS
    rows = []
    for t, name in config.MARKET_SECTORS.items():
        c = _chg_period(data, t, lb)
        if c is None:
            continue
        grp = ("defansif" if t in config.DEFENSIVE_SECTORS else "döngüsel")
        rows.append({"ticker": t, "name": name, "chg": round(c, 1), "group": grp})
    rows.sort(key=lambda r: r["chg"], reverse=True)
    defs = [r["chg"] for r in rows if r["group"] == "defansif"]
    cycs = [r["chg"] for r in rows if r["group"] == "döngüsel"]
    def_avg = sum(defs) / len(defs) if defs else None
    cyc_avg = sum(cycs) / len(cycs) if cycs else None
    tilt, tone = "—", "gray"
    if def_avg is not None and cyc_avg is not None:
        if cyc_avg - def_avg > 1:
            tilt, tone = "risk-açık — döngüseller önde", "green"
        elif def_avg - cyc_avg > 1:
            tilt, tone = "risk-kapalı — defansifler önde", "amber"
        else:
            tilt, tone = "karışık — net liderlik yok", "gray"
    return {"rows": rows, "lookback_days": lb, "tilt": tilt, "tone": tone,
            "def_avg": round(def_avg, 1) if def_avg is not None else None,
            "cyc_avg": round(cyc_avg, 1) if cyc_avg is not None else None}


def build_macro(data):
    """Faiz, getiri eğrisi, dolar, altın, petrol, kredi."""
    tnx = _last(data, "^TNX")   # 10Y
    irx = _last(data, "^IRX")   # 3ay
    curve = (tnx - irx) if (tnx is not None and irx is not None) else None
    hyg = _chg_period(data, "HYG", config.MARKET_LOOKBACK_DAYS)
    tlt = _chg_period(data, "TLT", config.MARKET_LOOKBACK_DAYS)
    rows = [
        {"metric": "10 yıllık faiz", "value": f"%{tnx:.2f}" if tnx else "—",
         "note": ("son 1 ay " + pct(_chg_period(data, "^TNX", config.MARKET_LOOKBACK_DAYS)))
                 if tnx else "", "tone": "gray"},
        {"metric": "Getiri eğrisi (10Y − 3ay)",
         "value": (f"{'+' if curve >= 0 else ''}{curve:.2f} puan") if curve is not None else "—",
         "note": ("normal (pozitif)" if (curve or 0) > 0 else "ters (resesyon sinyali)"),
         "tone": "gray" if (curve or 0) > 0 else "amber"},
        {"metric": "Dolar endeksi (DXY)", "value": f"{_last(data, 'DX-Y.NYB'):.1f}" if _last(data, 'DX-Y.NYB') else "—",
         "note": "son 1 ay " + pct(_chg_period(data, "DX-Y.NYB", config.MARKET_LOOKBACK_DAYS)), "tone": "gray"},
        {"metric": "Altın", "value": f"${_last(data, 'GLD'):.0f}" if _last(data, 'GLD') else "—",
         "note": "son 1 ay " + pct(_chg_period(data, "GLD", config.MARKET_LOOKBACK_DAYS)), "tone": "gray"},
        {"metric": "Petrol (WTI)", "value": f"${_last(data, 'CL=F'):.1f}" if _last(data, 'CL=F') else "—",
         "note": "son 1 ay " + pct(_chg_period(data, "CL=F", config.MARKET_LOOKBACK_DAYS)), "tone": "gray"},
        {"metric": "Kredi iştahı (HYG)",
         "value": pct(hyg) if hyg is not None else "—",
         "note": ("yüksek getirili tahvil güçlü — kredi sakin" if (hyg or 0) >= 0
                  else "yüksek getirili tahvil zayıf — kredi stresine dikkat"),
         "tone": "green" if (hyg or 0) >= 0 else "amber"},
    ]
    return {"rows": rows, "curve_inverted": (curve is not None and curve < 0)}


def build_calendar(ref_date):
    """Makro olaylar (config) + bu haftaki mega-cap bilançoları."""
    import yfinance as yf
    events = []
    # Makro olaylar (elle girilen)
    for ds, label in sorted(getattr(config, "MACRO_EVENTS", {}).items()):
        try:
            d = datetime.fromisoformat(ds).date()
        except Exception:
            continue
        delta = (d - ref_date).days
        if -1 <= delta <= 14:
            events.append({"date": ds, "label": label, "days": delta,
                           "date_label": tr_date(d), "kind": "makro"})
    # Mega-cap bilançoları (önümüzdeki 10 gün)
    for t in config.MARKET_EARNINGS_WATCH:
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=4)
            if ed is None or ed.empty:
                continue
            now = datetime.now(timezone.utc)
            fut = [d for d in ed.index if d.to_pydatetime() > now]
            if not fut:
                continue
            nd = min(fut).date()
            delta = (nd - ref_date).days
            if 0 <= delta <= 10:
                events.append({"date": nd.isoformat(), "label": f"{t} bilanço",
                               "days": delta, "date_label": tr_date(nd), "kind": "bilanço"})
        except Exception:
            continue
    events.sort(key=lambda e: e["date"])
    return events


# ----------------------------------------------------------------------
# REJİM ÖZETİ (sayısal skor)
# ----------------------------------------------------------------------

def build_regime(trend, fear, breadth, sectors):
    """Basit bir rejim etiketi: göstergeleri birleştir."""
    score = 0
    # trend
    if trend["total"]:
        score += (trend["above_200_count"] / trend["total"] - 0.5) * 4  # -2..+2
    # fear
    if fear.get("vix") is not None:
        score += 1.5 if fear["vix"] < 18 else 0.5 if fear["vix"] < 22 else \
                 -1 if fear["vix"] < 28 else -2.5
    if fear.get("term") == "backwardation":
        score -= 1
    # breadth
    if breadth.get("spread") is not None:
        score += 1 if breadth["spread"] > -1 else 0 if breadth["spread"] > -4 else -1
    # sektör eğilimi
    if sectors.get("tone") == "green":
        score += 1
    elif sectors.get("tone") == "amber":
        score -= 1
    if score >= 3:
        label, tone = "Risk-açık — trend yukarı", "green"
    elif score >= 0.5:
        label, tone = "Nötr-olumlu — temkinli iyimser", "green"
    elif score >= -1.5:
        label, tone = "Nötr — kararsız", "gray"
    elif score >= -3.5:
        label, tone = "Risk-kapalı — savunma modu", "amber"
    else:
        label, tone = "Stres — belirgin baskı", "amber"
    return {"label": label, "tone": tone, "score": round(score, 1)}


# ----------------------------------------------------------------------
# CLAUDE SENTEZİ
# ----------------------------------------------------------------------

CLAUDE_SYSTEM = """Sen deneyimli, sakin bir piyasa stratejistisin. Görevin piyasanın YÖNÜNÜ
TAHMİN ETMEK DEĞİL; verilen göstergelerden bugünkü REJİMİ (koşulları) sade Türkçeyle
okumak. Al/sat tavsiyesi verme, "yükselecek/düşecek" deme. Uzun vadeli yatırımcının
bağlam kurmasına yardım et: rüzgâr arkadan mı esiyor, breadth sağlıklı mı, faizler
zemini nasıl etkiliyor. Dengeli ol, belirsizliği kabul et.
SADECE geçerli JSON döndür — markdown yok."""

CLAUDE_PROMPT = """Bugünün tarihi: {date}

Piyasa göstergeleri:
{metrics}

Şu şemada JSON üret (Türkçe, kısa, net):
{{
  "headline": "bugünkü rejimi tek cümlede özetle (ör. 'Trend yukarı ama teknolojide soğuma ve yükselen faizler temkin gerektiriyor')",
  "read": "3-4 cümlelik rejim okuması: trend, korku, breadth ve makro zemini birleştir. Tahmin yok, koşul tespiti.",
  "watch": ["önümüzdeki günlerde izlenecek 1", "izlenecek 2", "izlenecek 3"],
  "concept": {{"title": "bugünle ilgili bir piyasa kavramı", "body": "2 cümle açıklama"}}
}}"""


def metrics_text(doc):
    L = []
    t = doc["trend"]
    L.append(f"- Trend: {t['above_200_count']}/{t['total']} endeks 200 gün ortalama üstünde")
    for r in t["rows"]:
        L.append(f"    {r['name']}: {r['state']}, zirveden {pct(r['from_high'])}")
    f = doc["fear"]
    L.append(f"- VIX: {f['vix']} ({f['zone']}), vade yapısı {f['term']}")
    b = doc["breadth"]
    L.append(f"- Breadth: eşit-ağırlık 3 ay {pct(b['rsp_3m'])} vs cap-ağırlık {pct(b['spy_3m'])} "
             f"(fark {pct(b['spread'])}) → {b['verdict']}; sektörlerin %{b['pct_sectors_above_200']}'i 200g üstünde")
    s = doc["sectors"]
    L.append(f"- Sektör eğilimi: {s['tilt']} (döngüsel ort {pct(s['cyc_avg'])}, defansif ort {pct(s['def_avg'])})")
    top = ", ".join(f"{r['name']} {pct(r['chg'])}" for r in s["rows"][:3])
    bot = ", ".join(f"{r['name']} {pct(r['chg'])}" for r in s["rows"][-3:])
    L.append(f"    Önde: {top} | Geride: {bot}")
    for r in doc["macro"]["rows"]:
        L.append(f"- {r['metric']}: {r['value']} ({r['note']})")
    if doc["calendar"]:
        ev = "; ".join(f"{e['date_label']} {e['label']}" for e in doc["calendar"][:6])
        L.append(f"- Yaklaşan olaylar: {ev}")
    L.append(f"- Genel rejim skoru: {doc['regime']['label']}")
    return "\n".join(L)


def call_claude(doc):
    import requests
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("  ANTHROPIC_API_KEY yok — AI sentezi atlanıyor")
        return None
    model = os.environ.get("CLAUDE_MODEL", config.CLAUDE_MODEL_DEFAULT)
    prompt = CLAUDE_PROMPT.format(date=doc["date"], metrics=metrics_text(doc))
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": 1200, "system": CLAUDE_SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", [])
                       if b.get("type") == "text")
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:
        log(f"  Claude çağrısı başarısız: {e}")
        return None


# ----------------------------------------------------------------------
# ÇIKTI + MOCK + ANA AKIŞ
# ----------------------------------------------------------------------

def _json_safe(o):
    """numpy sayılarını (float64 vb.) native tipe çevir."""
    if hasattr(o, "item"):
        return o.item()
    raise TypeError(f"JSON'a çevrilemedi: {type(o)}")


def write_output(doc):
    path = os.path.join(BASE_DIR, config.MARKET_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1, default=_json_safe)
    log(f"Yazıldı: {config.MARKET_FILE}")


def mock_doc(date_str):
    return {
        "date": date_str, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mock": True,
        "regime": {"label": "Nötr-olumlu — temkinli iyimser", "tone": "green", "score": 1.5},
        "trend": {"total": 3, "above_200_count": 3, "rows": [
            {"ticker": "^GSPC", "name": "S&P 500", "last": 7575.4, "chg_1d": 0.3, "above_50": True,
             "above_200": True, "from_high": -0.5, "state": "yükseliş trendi", "tone": "green"},
            {"ticker": "^IXIC", "name": "Nasdaq 100", "last": 26281.6, "chg_1d": -0.2, "above_50": True,
             "above_200": True, "from_high": -3.0, "state": "yükseliş trendi", "tone": "green"},
            {"ticker": "^RUT", "name": "Russell 2000", "last": 2977.8, "chg_1d": 0.5, "above_50": True,
             "above_200": True, "from_high": -1.5, "state": "yükseliş trendi", "tone": "green"}]},
        "fear": {"vix": 15.03, "vix3m": 18.57, "zone": "sakin", "term": "contango",
                 "tone": "green", "vix_chg_5d": -8.0},
        "breadth": {"rsp_3m": 4.2, "spy_3m": 4.5, "spread": -0.3, "pct_sectors_above_200": 82,
                    "verdict": "geniş — yükseliş tabana yayılmış", "tone": "green"},
        "sectors": {"lookback_days": 30, "tilt": "risk-açık — döngüseller önde", "tone": "green",
                    "def_avg": 1.5, "cyc_avg": 2.8, "rows": [
                        {"ticker": "XLF", "name": "Finans", "chg": 6.2, "group": "döngüsel"},
                        {"ticker": "XLV", "name": "Sağlık", "chg": 4.8, "group": "defansif"},
                        {"ticker": "XLI", "name": "Sanayi", "chg": 4.1, "group": "döngüsel"},
                        {"ticker": "XLU", "name": "Kamu hizmetleri", "chg": 3.7, "group": "defansif"},
                        {"ticker": "XLK", "name": "Teknoloji", "chg": 1.5, "group": "döngüsel"},
                        {"ticker": "XLE", "name": "Enerji", "chg": -2.9, "group": "döngüsel"}]},
        "macro": {"curve_inverted": False, "rows": [
            {"metric": "10 yıllık faiz", "value": "%4.57", "note": "son 1 ay +%2.1", "tone": "gray"},
            {"metric": "Getiri eğrisi (10Y − 3ay)", "value": "+0.87 puan", "note": "normal (pozitif)", "tone": "gray"},
            {"metric": "Dolar endeksi (DXY)", "value": "101.0", "note": "son 1 ay +%1.3", "tone": "gray"},
            {"metric": "Altın", "value": "$377", "note": "son 1 ay -%6.1", "tone": "gray"},
            {"metric": "Petrol (WTI)", "value": "$71.5", "note": "son 1 ay -%3.2", "tone": "gray"},
            {"metric": "Kredi iştahı (HYG)", "value": "+%0.4", "note": "yüksek getirili tahvil güçlü — kredi sakin", "tone": "green"}]},
        "calendar": [
            {"date": date_str, "label": "MSFT bilanço", "days": 2, "date_label": "12 Temmuz", "kind": "bilanço"},
            {"date": date_str, "label": "ABD TÜFE (CPI)", "days": 4, "date_label": "14 Temmuz", "kind": "makro"}],
        "ai": {
            "headline": "Trend yukarı ve korku düşük, ama teknolojide soğuma ve yükselen faizler temkin gerektiriyor.",
            "read": "Üç ana endeks de 200 gün ortalamanın üzerinde ve zirveye yakın; VIX 15 ile piyasa oldukça rahat. Breadth sağlıklı — yükseliş birkaç deve değil tabana yayılmış. Ancak 10 yıllık faizin yükselmesi ve teknolojinin zirveden geri çekilmesi, rehavete karşı uyanık olmayı gerektiriyor.",
            "watch": ["10 yıllık faizin %4.6 üstünü kalıcı kırıp kırmayacağı",
                      "Teknoloji liderliğinin geri gelip gelmediği",
                      "CPI sonrası VIX tepkisi"],
            "concept": {"title": "Breadth (piyasa genişliği)",
                        "body": "Yükselişe kaç hissenin katıldığını ölçer. Dar bir yükseliş (birkaç mega-cap) kırılgandır; geniş bir yükseliş daha sağlıklıdır."}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--date")
    args = ap.parse_args()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.mock:
        log("MOCK mod")
        write_output(mock_doc(date_str))
        return

    ref_date = datetime.fromisoformat(date_str).date()
    log("Fiyatlar çekiliyor…")
    all_tickers = (list(config.MARKET_INDICES) + list(config.MARKET_SECTORS)
                   + list(config.MARKET_MACRO))
    data = fetch_prices(all_tickers, period="1y")

    trend = build_trend(data)
    fear = build_fear(data)
    breadth = build_breadth(data)
    sectors = build_sectors(data)
    macro = build_macro(data)
    calendar = build_calendar(ref_date)
    regime = build_regime(trend, fear, breadth, sectors)

    doc = {"date": date_str,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "mock": False, "regime": regime, "trend": trend, "fear": fear,
           "breadth": breadth, "sectors": sectors, "macro": macro, "calendar": calendar}
    doc["ai"] = call_claude(doc)
    write_output(doc)
    log("Tamamlandı.")


if __name__ == "__main__":
    main()
