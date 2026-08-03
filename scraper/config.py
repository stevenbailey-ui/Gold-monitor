"""
Gold-thesis metric configuration. Weights sum to 100. Each metric -> signal in
{+1 bull, 0 base, -1 bear}; composite = sum(weight*signal) (-100..+100). Four themes roll up.

No holding identities live here. The two portfolio holdings (their tickers, share counts and
prices) come from the HOLDINGS secret / data/holdings.local.json, never from this file. The
symbols below are public gold-thesis instruments only.

v22 (2026-08-03) rationalisation, 16 metrics -> 9:
  - Weight follows measured explanatory power, not topic coverage.
  - ETF flows raised 6 -> 20 (contemporaneous R2 0.432 post-2022 vs monthly gold return,
    n=54, t +6.4 - the best-evidenced series available).
  - spot_trailing raised 7 -> 16 (only metric with measurable FORWARD content:
    fwd-12m R2 0.098, t +2.88; every flow specification tested at ~0.01 and insignificant).
  - wgc_cb_purchases_t cut 20 -> 8 (quarterly, ~1mo publication lag, Q1-26 revised 244t->57t).
  - real_curve_slope added at 12 (30y-10y TIPS; d-slope vs gold return t +4.64, n=196;
    rolling-36m levels corr with log(gold) +0.95).
  - Dropped: pboc_holdings_delta_t (subcomponent of the WGC series - double count),
    cofer_usd_share (moves ~0.3pp/qtr, a constant offset not a classifier),
    gdx_gold (collinear with gdxj_gold), real_yield + fed_funds (both duplicated the
    rates channel; 10y real R2 has decayed to 0.075 on the trailing 36m window),
    vix, gpr_index, opp_cost (each too small to change a verdict on a 100pt scale).
  - Manual share of composite cut 42% -> 28%.
"""

THEMES = ["demand_flows", "macro_rates", "usd_geo", "mining_equities"]
THEME_LABELS = {
    "demand_flows":    "Demand & flows",
    "macro_rates":     "Macro & rates",
    "usd_geo":         "USD & geopolitics",
    "mining_equities": "Sector re-rate",
}

# Public gold-thesis instruments (Yahoo symbols). NOT the portfolio holdings.
# ndx/gdxj are retained for the opportunity-cost DIAGNOSTIC panel, which survives as a
# read-only block in data.json even though opp_cost is no longer a scored metric.
PRICE_SYMBOLS = {
    "gold": "GC=F", "dxy": "DX-Y.NYB", "brent": "BZ=F",
    "gdxj": "GDXJ", "ndx": "^NDX",
}
# dfii10 is retained for the divergence diagnostic even though the real_yield METRIC is gone.
FRED_SERIES = {"dfii10": "DFII10", "dfii30": "DFII30", "deficit_gdp": "FYFSGDA188S"}

# Trailing-average gold: monthly average of daily closes, last 24 completed months.
TRAILING_MONTHS = 24
TRAILING_RANGE_DAYS = 800   # ~26 months of daily bars to cover 24 completed months

# Real-curve-slope lookback, in FRED observations (business days). 63 ~ 3 months.
SLOPE_LOOKBACK_OBS = 63

# Exit-liquidity model. Days-to-exit = shares / (participation * median daily volume).
LIQ_PARTICIPATION = 0.20    # share of daily volume assumed takeable without moving price
LIQ_DAYS_BASE = 5.0         # <= this many days to exit -> base
LIQ_DAYS_BEAR = 20.0        # >= this many days to exit -> bear
LIQ_WINDOW_LONG = 60        # sessions for the headline median volume
LIQ_WINDOW_SHORT = 20       # sessions for the deterioration/improvement trend

METRICS = [
    # --- Demand & flows -------------------------------------------------- 38
    {"id": "etf_aum_delta_t", "theme": "demand_flows", "weight": 20, "kind": "manual",
     "label": "Gold ETF holdings change / demand (t/mo)"},
    {"id": "cot_mm_net_pct_oi", "theme": "demand_flows", "weight": 10, "kind": "level",
     "src": "cot", "bull_at": 0.10, "bear_at": 0.35, "higher_is_bull": False,
     "label": "COMEX Managed Money net % OI [contrarian: <=0.10 bull, >=0.35 bear]"},
    {"id": "wgc_cb_purchases_t", "theme": "demand_flows", "weight": 8, "kind": "manual",
     "label": "WGC central-bank net purchases (t/qtr) [quarterly, lagged, revision-prone]"},

    # --- Macro & rates --------------------------------------------------- 18
    {"id": "real_curve_slope", "theme": "macro_rates", "weight": 12, "kind": "slope3m",
     "bull_at": 10.0, "bear_at": -10.0,
     "label": "Real curve slope 30y-10y TIPS, 3m change (bp) [steepening = bull]"},
    {"id": "deficit_pct_gdp", "theme": "macro_rates", "weight": 6, "kind": "level",
     "src": "deficit_gdp", "bull_at": -6, "bear_at": -3, "higher_is_bull": False,
     "label": "US federal deficit (% GDP) [FRED signed: -6=6% deficit; bull <=-6, bear >=-3]"},

    # --- USD & geopolitics ----------------------------------------------- 18
    {"id": "dxy", "theme": "usd_geo", "weight": 12, "kind": "delta",
     "src": "dxy", "bull_at": -2, "bear_at": 2, "higher_is_bull": False,
     "label": "DXY (delta index pts)"},
    {"id": "brent", "theme": "usd_geo", "weight": 6, "kind": "band",
     "src": "brent", "lo": 50, "hi": 70,
     "below_lo": "bear", "mid": "base", "above_hi": "bear",
     "label": "Brent crude ($/bbl) [band: <50 or >=70 bear, else base]"},

    # --- Sector re-rate --------------------------------------------------- 26
    {"id": "spot_trailing", "theme": "mining_equities", "weight": 16, "kind": "ratio_trailing",
     "bull_lo": 0.90, "bull_hi": 1.40, "bear_at": 1.55,
     "label": "Gold spot / 24m trailing [momentum - only forward-looking metric]"},
    {"id": "gdxj_gold", "theme": "mining_equities", "weight": 10, "kind": "ratio",
     "num": "gdxj", "den": "gold", "bull_at": 0.022, "bear_at": 0.026, "higher_is_bull": False,
     "label": "GDXJ / gold [inverted: low=bull]"},
]
assert sum(m["weight"] for m in METRICS) == 100, "weights must sum to 100"
assert all(m["theme"] in THEMES for m in METRICS), "metric assigned to unknown theme"


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
DIVERGENCE_BETA_REAL_YIELD = -10.0   # gold % per +1.00pp 10Y real yield
DIVERGENCE_BETA_DXY        = -0.9    # gold % per +1.0 DXY point
DIVERGENCE_BAND_PP         = 0.5     # |residual| within this = tracking textbook
