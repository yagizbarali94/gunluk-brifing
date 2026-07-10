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

# Haberler
NEWS_LOOKBACK_DAYS = 7
NEWS_LIMIT = 10                 # Alpaca'dan çekilecek ham haber sayısı
NEWS_SHOWN = 4                  # dashboard'da gösterilecek haber sayısı

# Claude
CLAUDE_MODEL_DEFAULT = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 1600

# Karne eşikleri (çekirdek şablon v1) — yeşil / gri / sarı sınırları
THRESHOLDS = {
    "revenue_yoy":   {"green": 15.0, "amber": 0.0},    # y/y %
    "netinc_yoy":    {"green": 15.0, "amber": 0.0},    # y/y %
    "gm_qoq_pts":    {"green": 0.3,  "amber": -0.3},   # ç/ç puan
    "opm_yoy_pts":   {"green": 0.5,  "amber": -0.5},   # y/y puan
    "fcf_margin":    {"green": 10.0, "amber": 0.0},    # FCF / gelir %
}

# Dosya yolları (script'in bulunduğu klasöre göre)
SITE_DIR = "site"
BRIEFINGS_DIR = "site/briefings"
STATE_FILE = "state.json"
