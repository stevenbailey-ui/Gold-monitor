"""
Gold-thesis metric configuration. Weights sum to 100. Each metric -> signal in
{+1 bull, 0 base, -1 bear}; composite = sum(weight*signal) (-100..+100). Six themes roll up.

No holding identities live here. The two portfolio holdings (their tickers, share counts and
prices) come from the HOLDINGS secret / data/holdings.local.json, never from this file. The
symbols below are public gold-thesis instruments only.
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

# Public gold-thesis instruments (Yahoo symbols). NOT the portfolio holdings.
PRICE_SYMBOLS = {
    "gold": "GC=F", "dxy": "DX-Y.NYB", "vix": "^VIX", "brent": "BZ=F",
    "gdx": "GDX", "gdxj": "GDXJ", "ndx": "^NDX",
}
FRED_SERIES = {"dgs10": "DGS10", "dfii10": "DFII10", "t10yie": "T10YIE", "dfedtaru": "DFEDTARU"}

# Trailing-average gold: monthly average of daily closes, last 24 completed months.
TRAILING_MONTHS = 24
TRAILING_RANGE_DAYS = 800   # ~26 months of daily bars to cover 24 completed months

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


def verdict(composite):
    if composite >= 30:  return "Strongly bullish", "BULL"
    if composite >= 10:  return "Bullish", "BULL"
    if composite > -10:  return "Balanced", "BASE"
    if composite > -30:  return "Bearish", "BEAR"
    return "Strongly bearish", "BEAR"


def theme_signal(net, max_w):
    if net > 0.15 * max_w:  return "bull"
    if net < -0.15 * max_w: return "bear"
    return "base"


# --- Orthodox Divergence Diagnostic ---------------------------------------
# Gold's realised move vs the "textbook" real-yield + USD model.
# expected_gold% = BETA_REAL_YIELD * d(real yield, pp) + BETA_DXY * d(DXY, pts)
# residual = actual_gold% - expected_gold%   (>0 = gold outrunning orthodoxy).
# Coefficients carried over from the portfolio model (Gold Thesis Dashboard B45/B46).
DIVERGENCE_BETA_REAL_YIELD = -10.0   # gold % per +1.00pp 10Y real yield
DIVERGENCE_BETA_DXY        = -0.9    # gold % per +1.0 DXY point
DIVERGENCE_BAND_PP         = 0.5     # |residual| within this = tracking textbook
