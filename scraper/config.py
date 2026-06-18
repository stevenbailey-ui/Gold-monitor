"""
Gold thesis metric configuration. Mirrors the portfolio model's Gold Thesis Dashboard.
Each metric: theme, weight, how it is scored, and where its value comes from.

Scoring: every metric resolves to a signal in {+1 bull, 0 base, -1 bear}; the
composite is sum(weight * signal), range -100..+100. Weights sum to 100.

'kind':
  'level_band'  -> bull if value >= bull_at (or <= for inverted); bear at the far side; else base
  'manual'      -> signal supplied directly in manual_inputs (string), no threshold math
Edit thresholds/weights here to recalibrate; nothing else needs to change.
"""

# Primary EOD price source: Yahoo Finance chart API (no key, works from CI).
YAHOO = {
    "gold":  "GC=F",       # COMEX gold front future ≈ spot
    "dxy":   "DX-Y.NYB",   # ICE US dollar index
    "vix":   "^VIX",
    "brent": "BZ=F",       # Brent crude front future
    "gdx":   "GDX",
    "gdxj":  "GDXJ",
    "ndx":   "^NDX",
    "thx":   "THX.L",      # Thor Explorations, AIM (pence)
    "mtl":   "MTL.L",      # Metals Exploration, AIM (pence)
}

# Fallback EOD price source (Stooq CSV). Used only if Yahoo fails for a symbol.
STOOQ = {
    "gold":  "xauusd",
    "dxy":   "^dxy",     # US dollar index
    "vix":   "^vix",
    "brent": "cb.f",     # Brent crude front future
    "gdx":   "gdx.us",
    "gdxj":  "gdxj.us",
    "ndx":   "^ndx",
    "thx":   "thx.uk",   # Thor Explorations, AIM (pence)
    "mtl":   "mtl.uk",   # Metals Exploration, AIM (pence)
}

# FRED series (needs free API key in env FRED_API_KEY).
FRED = {
    "us10y_nominal": "DGS10",
    "us10y_real":    "DFII10",
    "breakeven10y":  "T10YIE",
    "fed_funds_upper": "DFEDTARU",
    "deficit_pct_gdp_proxy": "MTSDS133FMS",
}

# Six themes -> ordered for display.
THEMES = ["central_bank", "macro_rates", "usd_fx", "geopolitics", "mining_equities", "positioning"]

THEME_LABELS = {
    "central_bank":    "Central-bank bid",
    "macro_rates":     "Macro & rates",
    "usd_fx":          "USD / FX",
    "geopolitics":     "Geopolitics",
    "mining_equities": "Mining equities",
    "positioning":     "Positioning",
}

# Metric definitions. 'src' tells the scraper where to read the live value.
METRICS = {
    # --- Central bank / structural demand ---
    "wgc_cb_purchases_t":   {"theme": "central_bank", "weight": 19, "kind": "level_band",
                             "bull_at": 200, "bear_at": 150, "src": "manual:wgc_cb_purchases_t"},
    "pboc_holdings_delta_t":{"theme": "central_bank", "weight": 7,  "kind": "level_band",
                             "bull_at": 15,  "bear_at": 5,   "src": "manual:pboc_holdings_delta_t"},
    "etf_aum_delta_t":      {"theme": "central_bank", "weight": 6,  "kind": "level_band",
                             "bull_at": 16,  "bear_at": -16, "src": "manual:etf_aum_delta_t"},

    # --- Macro / rates (real-yield correlation broken post-2022; lightly weighted) ---
    "us10y_real":           {"theme": "macro_rates", "weight": 5, "kind": "level_band", "inverted": True,
                             "bull_at": -0.2, "bear_at": 0.2, "src": "fred:us10y_real"},
    "fed_funds_upper":      {"theme": "macro_rates", "weight": 3, "kind": "level_band", "inverted": True,
                             "bull_at": -0.25, "bear_at": 0.25, "src": "fred_delta:fed_funds_upper"},
    "deficit_pct_gdp":      {"theme": "macro_rates", "weight": 5, "kind": "level_band",
                             "bull_at": 6, "bear_at": 4, "src": "manual:deficit_pct_gdp"},

    # --- USD / FX ---
    "dxy":                  {"theme": "usd_fx", "weight": 9, "kind": "level_band", "inverted": True,
                             "bull_at": -2, "bear_at": 2, "src": "stooq_delta:dxy"},
    "cofer_usd_share_delta":{"theme": "usd_fx", "weight": 7, "kind": "level_band", "inverted": True,
                             "bull_at": -0.5, "bear_at": 0.5, "src": "manual:cofer_usd_share_delta"},

    # --- Geopolitics / tail risk ---
    "brent":                {"theme": "geopolitics", "weight": 6, "kind": "level_band",
                             "bull_at": 75, "bear_at": 45, "src": "stooq:brent"},
    "vix":                  {"theme": "geopolitics", "weight": 2, "kind": "level_band",
                             "bull_at": 25, "bear_at": 15, "src": "stooq:vix"},
    "gpr_index":            {"theme": "geopolitics", "weight": 2, "kind": "level_band",
                             "bull_at": 200, "bear_at": 75, "src": "manual:gpr_index"},

    # --- Mining equity confirmation ---
    "gdxj_gold_ratio":      {"theme": "mining_equities", "weight": 8, "kind": "level_band", "inverted": True,
                             "bull_at": 0.016, "bear_at": 0.026, "src": "ratio:gdxj/gold"},
    "gdx_gold_ratio":       {"theme": "mining_equities", "weight": 3, "kind": "level_band",
                             "bull_at": 0.020, "bear_at": 0.012, "src": "ratio:gdx/gold"},
    "spot_24m_ratio":       {"theme": "mining_equities", "weight": 6, "kind": "level_band", "inverted": True,
                             "bull_at": 1.40, "bear_at": 1.55, "src": "ratio:spot24m"},

    # --- Positioning (contrarian) ---
    "cot_mm_net_pct_oi":    {"theme": "positioning", "weight": 6, "kind": "level_band",
                             "bull_at": 0.25, "bear_at": 0.45, "src": "manual:cot_mm_net_pct_oi"},
    "gvz":                  {"theme": "positioning", "weight": 2, "kind": "level_band",
                             "bull_at": 15, "bear_at": 32, "src": "manual:gvz"},
    "ndx_gdxj_ratio":       {"theme": "positioning", "weight": 4, "kind": "level_band", "inverted": True,
                             "bull_at": 284, "bear_at": 334, "src": "ratio:ndx/gdxj"},
}

assert sum(m["weight"] for m in METRICS.values()) == 100, "weights must sum to 100"
