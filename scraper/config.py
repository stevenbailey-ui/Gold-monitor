"""
Gold thesis metric configuration. Mirrors the portfolio model's Gold Thesis Dashboard
(v20, post-2022 correlation-break regime). Weights sum to 100.

Each metric resolves to a signal in {+1 bull, 0 base, -1 bear}. Composite = sum(weight*signal),
range -100..+100. Six themes roll the metrics up for display.

kind:
  'delta'  -> signal from (current - prior); bull if move past bull_at toward the bull side
  'level'  -> signal from absolute level vs bands
  'ratio'  -> value computed from two fetched prices, scored on level
  'manual' -> signal supplied directly in manual_inputs (no live fetch)
Edit thresholds/weights here to recalibrate; nothing else needs to change.
"""

THEMES = ["central_bank", "macro_rates", "usd_fx", "geopolitics", "mining_equities", "positioning"]
THEME_LABELS = {
    "central_bank":    "Central-bank bid",
    "macro_rates":     "Macro & rates",
    "usd_fx":          "USD / FX",
    "geopolitics":     "Geopolitics",
    "mining_equities": "Mining equities",
    "positioning":     "Positioning",
}

# Yahoo Finance chart-API symbols (primary). Stooq symbols are the fallback in update_data.py.
PRICE_SYMBOLS = {
    "gold": "GC=F", "dxy": "DX-Y.NYB", "vix": "^VIX", "brent": "BZ=F",
    "gdx": "GDX", "gdxj": "GDXJ", "ndx": "^NDX",
    "thx": "THX.L", "mtl": "MTL.L",
}
# FRED series (free API key in env FRED_API_KEY; falls back to manual/prior if absent).
FRED_SERIES = {"dgs10": "DGS10", "dfii10": "DFII10", "t10yie": "T10YIE", "dfedtaru": "DFEDTARU"}

# id, theme, weight, kind, and scoring params. higher_is_bull governs delta/level direction.
METRICS = [
    {"id": "wgc_cb_purchases_t", "theme": "central_bank", "weight": 19, "kind": "manual",
     "label": "WGC central-bank net purchases (t/qtr)"},
    {"id": "pboc_holdings_delta_t", "theme": "central_bank", "weight": 7, "kind": "manual",
     "label": "PBoC reported holdings (delta t)"},
    {"id": "etf_aum_delta_t", "theme": "central_bank", "weight": 6, "kind": "manual",
     "label": "Gold ETF AUM change (t/mo)"},

    {"id": "real_yield", "theme": "macro_rates", "weight": 5, "kind": "delta",
     "src": "dfii10", "bull_at": -0.2, "bear_at": 0.2, "higher_is_bull": False,
     "label": "US 10Y real yield (delta %)"},
    {"id": "fed_funds", "theme": "macro_rates", "weight": 3, "kind": "delta",
     "src": "dfedtaru", "bull_at": -0.25, "bear_at": 0.25, "higher_is_bull": False,
     "label": "Fed funds upper bound (delta %)"},
    {"id": "deficit_pct_gdp", "theme": "macro_rates", "weight": 5, "kind": "manual",
     "label": "US federal deficit (% GDP)"},

    {"id": "dxy", "theme": "usd_fx", "weight": 9, "kind": "delta",
     "src": "dxy", "bull_at": -2, "bear_at": 2, "higher_is_bull": False,
     "label": "DXY (delta index pts)"},
    {"id": "cofer_usd_share", "theme": "usd_fx", "weight": 7, "kind": "manual",
     "label": "USD share of FX reserves (COFER %)"},

    {"id": "brent", "theme": "geopolitics", "weight": 6, "kind": "manual",
     "label": "Brent crude ($/bbl) [non-monotonic]"},
    {"id": "vix", "theme": "geopolitics", "weight": 2, "kind": "level",
     "src": "vix", "bull_at": 25, "bear_at": 15, "higher_is_bull": True,
     "label": "VIX (level)"},
    {"id": "gpr_index", "theme": "geopolitics", "weight": 2, "kind": "manual",
     "label": "Geopolitical Risk Index (level)"},

    {"id": "gdxj_gold", "theme": "mining_equities", "weight": 8, "kind": "ratio",
     "num": "gdxj", "den": "gold", "bull_at": 0.022, "bear_at": 0.026, "higher_is_bull": False,
     "label": "GDXJ / gold [inverted: low=bull]"},
    {"id": "gdx_gold", "theme": "mining_equities", "weight": 3, "kind": "ratio",
     "num": "gdx", "den": "gold", "bull_at": 0.020, "bear_at": 0.012, "higher_is_bull": True,
     "label": "GDX / gold [senior confirmation]"},
    {"id": "spot_trailing", "theme": "mining_equities", "weight": 6, "kind": "ratio_trailing",
     "bull_lo": 0.90, "bull_hi": 1.40, "bear_at": 1.55,
     "label": "Gold spot / 24m trailing [momentum]"},
    {"id": "ndx_gdxj", "theme": "mining_equities", "weight": 4, "kind": "ratio",
     "num": "ndx", "den": "gdxj", "bull_at": 284, "bear_at": 334, "higher_is_bull": False,
     "label": "NDX / GDXJ [AI-rotation contra]"},

    {"id": "cot_mm_net_pct_oi", "theme": "positioning", "weight": 6, "kind": "manual",
     "label": "COMEX Managed Money net % OI [contrarian]"},
    {"id": "gvz", "theme": "positioning", "weight": 2, "kind": "manual",
     "label": "Gold volatility (GVZ)"},
]

assert sum(m["weight"] for m in METRICS) == 100, "weights must sum to 100"

# Composite verdict bands (matches model scale).
def verdict(composite):
    if composite >= 30:  return "Strongly bullish", "BULL"
    if composite >= 10:  return "Bullish", "BULL"
    if composite > -10:  return "Balanced", "BASE"
    if composite > -30:  return "Bearish", "BEAR"
    return "Strongly bearish", "BEAR"

# Theme signal: net weighted score vs 15% of theme's max weight.
def theme_signal(net, max_w):
    if net > 0.15 * max_w:  return "bull"
    if net < -0.15 * max_w: return "bear"
    return "base"
