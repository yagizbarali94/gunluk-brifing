# -*- coding: utf-8 -*-
"""
Günlük Şirket Brifingi — yapılandırma
Watchlist'i istediğin gibi düzenle; sıra, rotasyon sırasıdır.
"""

# AI odaklı takip listesi (rotasyon bu sırayla döner)
WATCHLIST = [
    "NVDA", "AMD", "AVGO", "TSM", "MU", "ARM", "QCOM", "ANET", "VRT", "SMCI",
    "MSFT", "GOOGL", "META", "AMZN", "ORCL", "NOW", "CRM", "PLTR",
    "SNOW", "DDOG", "MDB", "NET", "CRWD", "PANW",
]

# Hisse seçim öncelikleri
EARNINGS_LOOKBACK_DAYS = 2      # son N gün içinde bilanço açıklayan öne geçer
EARNINGS_UPCOMING_DAYS = 7      # önümüzdeki N gün içinde bilanço açıklayacak olan öne geçer
MOVER_THRESHOLD_PCT = 4.0       # tek günde |değişim| >= bu ise "büyük hareket"

# Belirli günlere hisse sabitleme: pinned.json dosyasında tutulur
# ({"YYYY-MM-DD": ["NVDA", ...]}). Sitedeki "⭐ Sabitle" panelinden veya
# GitHub'da pinned.json'ı düzenleyerek yönetilir; tarihi geçen kayıtlar
# her sabah otomatik temizlenir.

# Haberler
NEWS_LOOKBACK_DAYS = 7
NEWS_LIMIT = 10                 # Alpaca'dan çekilecek ham haber sayısı
NEWS_SHOWN = 4                  # dashboard'da gösterilecek haber sayısı

# Claude
CLAUDE_MODEL_DEFAULT = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 2400

# Karne eşikleri (çekirdek şablon v1) — yeşil / gri / sarı sınırları
THRESHOLDS = {
    "revenue_yoy":   {"green": 15.0, "amber": 0.0},    # y/y %
    "netinc_yoy":    {"green": 15.0, "amber": 0.0},    # y/y %
    "gm_qoq_pts":    {"green": 0.3,  "amber": -0.3},   # ç/ç puan
    "opm_yoy_pts":   {"green": 0.5,  "amber": -0.5},   # y/y puan
    "fcf_margin":    {"green": 10.0, "amber": 0.0},    # FCF / gelir %
}

# ----------------------------------------------------------------------
# PİYASA REJİMİ SAYFASI (market_generator.py)
# ----------------------------------------------------------------------
MARKET_INDICES = {"^GSPC": "S&P 500", "^NDX": "Nasdaq 100", "^RUT": "Russell 2000"}

# 11 SPDR sektör ETF'i (ısı haritası + rotasyon)
MARKET_SECTORS = {
    "XLK": "Teknoloji", "XLC": "İletişim", "XLY": "Tüketici (döngüsel)",
    "XLF": "Finans", "XLI": "Sanayi", "XLB": "Malzeme", "XLE": "Enerji",
    "XLV": "Sağlık", "XLP": "Tüketici (temel)", "XLU": "Kamu hizmetleri",
    "XLRE": "Gayrimenkul",
}
DEFENSIVE_SECTORS = ["XLU", "XLP", "XLV", "XLRE"]        # defansif (risk-kapalı lideri)
CYCLICAL_SECTORS = ["XLK", "XLY", "XLF", "XLI", "XLB", "XLE", "XLC"]  # döngüsel (risk-açık lideri)

# Makro arka plan sembolleri
MARKET_MACRO = {
    "^TNX": "10 yıllık tahvil faizi", "^IRX": "3 aylık tahvil faizi",
    "DX-Y.NYB": "Dolar endeksi (DXY)", "GLD": "Altın", "CL=F": "Petrol (WTI)",
    "HYG": "Yüksek getirili tahvil", "TLT": "Uzun vadeli tahvil",
    "^VIX": "VIX (korku)", "^VIX3M": "VIX 3 ay",
    "RSP": "S&P eşit-ağırlık", "SPY": "S&P cap-ağırlık",
}

# Bu hafta izlenecek mega-cap bilançoları (piyasayı oynatabilir)
MARKET_EARNINGS_WATCH = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META",
                         "AVGO", "TSLA", "JPM", "LLY"]

# Kullanıcının elle güncelleyebileceği makro takvim ("YYYY-MM-DD": "açıklama").
# Fed faiz kararı, TÜFE, istihdam gibi bilinen tarihleri buraya ekle.
MACRO_EVENTS = {}

MARKET_LOOKBACK_DAYS = 30       # sektör/breadth performans penceresi

# VIX bölge eşikleri
VIX_ZONES = [(15, "sakin"), (20, "normal"), (28, "tedbirli"), (999, "stres")]

# Dosya yolları (script'in bulunduğu klasöre göre)
SITE_DIR = "site"
BRIEFINGS_DIR = "site/briefings"
STATE_FILE = "state.json"
PINNED_FILE = "pinned.json"
MARKET_FILE = "site/market.json"
