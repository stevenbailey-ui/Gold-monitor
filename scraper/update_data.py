#!/usr/bin/env python3
"""
EOD updater for the gold portfolio monitor (public, anonymised output).

Fetches gold-thesis prices (Yahoo) + FRED rates, auto-computes the 24-month trailing gold
price (monthly average of daily closes), reads the portfolio holdings from the HOLDINGS
secret / data/holdings.local.json, merges valuations from data/model_snapshot.json, scores
the six-theme composite, and writes data/data.json.

PRIVACY: the published data.json contains only Africa / Asia labels, GBP value and % weight,
the gold thesis, generic catalysts and actions. It never contains tickers, share counts or
per-share prices. Holdings live only in the secret / local file.

Run:  python scraper/update_data.py
"""
import json, os, sys, datetime, urllib.request
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SIG = {"bull": 1, "base": 0, "bear": -1}


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 gold-monitor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_last(symbol, timeout=12):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    res = json.loads(_get(url, timeout=timeout))["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    return float(closes[-1])


def yahoo_daily(symbol, rng_days, timeout=12):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng_days}d&interval=1d"
    res = json.loads(_get(url, timeout=timeout))["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    return [(datetime.datetime.utcfromtimestamp(t), c) for t, c in zip(ts, closes) if c is not None]


def fetch_price(key, notes):
    sym = C.PRICE_SYMBOLS[key]
    try:
        return yahoo_last(sym)
    except Exception as e:
        notes.append(f"{key}:yahoo:{type(e).__name__}")
    return None   # Stooq fallback removed: blocked on Actions runners, only adds ~20s dead-waits


def fetch_holding_price(ticker, notes):
    try:
        return yahoo_last(ticker)            # pence for .L tickers
    except Exception as e:
        notes.append(f"holding:{type(e).__name__}")
    return None


def fetch_fred(series_id, notes):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        notes.append(f"{series_id}:no_FRED_key"); return None
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
               f"&api_key={key}&file_type=json&sort_order=desc&limit=1")
        return float(json.loads(_get(url))["observations"][0]["value"])
    except Exception as e:
        notes.append(f"{series_id}:FRED:{type(e).__name__}"); return None


def fetch_fred_history(series_id, notes, limit=180):
    """Recent observations for a FRED series, newest first, as [(date_str, value)].
    Missing prints are published as '.' and are dropped."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        notes.append(f"{series_id}:no_FRED_key"); return None
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
               f"&api_key={key}&file_type=json&sort_order=desc&limit={limit}")
        obs = json.loads(_get(url))["observations"]
        return [(o["date"], float(o["value"])) for o in obs
                if o.get("value") not in (".", "", None)]
    except Exception as e:
        notes.append(f"{series_id}:FRED_hist:{type(e).__name__}"); return None


def real_curve_slope(notes):
    """Real curve slope = 30y TIPS - 10y TIPS, and its change over ~3 months.

    Rationale: the 30y real yield adds nothing to the 10y as a standalone regressor
    (post-2022 R2 0.172 vs 0.200; it beats the 10y in 2.5% of rolling 36m windows).
    The SLOPE is a different object - it proxies the term premium, i.e. compensation
    demanded for duration and supply risk. d(slope) vs monthly gold return: t +4.64,
    n=196. Steepening = fiscal risk being priced = gold-supportive.

    Computed statelessly from FRED history, so it survives a missing prior data.json.
    """
    a = fetch_fred_history("DFII30", notes)
    b = fetch_fred_history("DFII10", notes)
    if not a or not b:
        notes.append("slope:no_series"); return None
    d30, d10 = dict(a), dict(b)
    common = sorted(set(d30) & set(d10), reverse=True)      # newest first
    lb = getattr(C, "SLOPE_LOOKBACK_OBS", 63)
    if len(common) < lb + 1:
        notes.append(f"slope:short_history({len(common)})"); return None
    now = d30[common[0]] - d10[common[0]]
    then = d30[common[lb]] - d10[common[lb]]
    chg = (now - then) * 100.0                               # pp -> bp
    return {"as_of": common[0], "prior_as_of": common[lb],
            "slope_now_pp": round(now, 3), "slope_prior_pp": round(then, 3),
            "change_bp": round(chg, 1)}


def fetch_cot(notes):
    """COMEX gold (088691) Managed Money net long as fraction of OI, from CFTC
    Disaggregated Futures-Only (Socrata 72hh-3qpy). No token required."""
    url = ("https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
           "?cftc_contract_market_code=088691"
           "&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1")
    try:
        rec = json.loads(_get(url))[0]
        lo = float(rec["m_money_positions_long_all"])
        sh = float(rec["m_money_positions_short_all"])
        oi = float(rec["open_interest_all"])
        if oi <= 0:
            notes.append("cot:zero_oi"); return None
        return (lo - sh) / oi
    except Exception as e:
        notes.append(f"cot:{type(e).__name__}"); return None


def yahoo_daily_ohlcv(symbol, rng_days, timeout=12):
    """Daily bars including volume. Same endpoint as yahoo_daily; volume lives in
    indicators.quote[0].volume, so this is a field addition, not a new data source."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng_days}d&interval=1d"
    res = json.loads(_get(url, timeout=timeout))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for t, c, v in zip(res["timestamp"], q["close"], q["volume"]):
        if c is not None and v:
            out.append((datetime.datetime.utcfromtimestamp(t), float(c), float(v)))
    return out


def median_volume(bars, n):
    """Median (not mean) of the last n sessions' volume. Median deliberately: a single
    block trade on an illiquid AIM line distorts a mean badly and would flatter the
    days-to-exit figure exactly when it matters most."""
    if not bars or len(bars) < max(5, n // 3):
        return None
    vols = sorted(v for _, _, v in bars[-n:])
    if not vols:
        return None
    k = len(vols)
    return vols[k // 2] if k % 2 else 0.5 * (vols[k // 2 - 1] + vols[k // 2])


def liquidity_profile(ticker, shares, pence, notes):
    """Exit liquidity for one holding: ADTV in GBP, days to exit at a fixed
    participation rate, and a 20d/60d volume trend. Returns None on any failure so a
    dead feed can never block the run."""
    if not ticker or not shares:
        return None
    long_w = getattr(C, "LIQ_WINDOW_LONG", 60)
    short_w = getattr(C, "LIQ_WINDOW_SHORT", 20)
    part = getattr(C, "LIQ_PARTICIPATION", 0.20)
    d_base = getattr(C, "LIQ_DAYS_BASE", 5.0)
    d_bear = getattr(C, "LIQ_DAYS_BEAR", 20.0)
    try:
        bars = yahoo_daily_ohlcv(ticker, long_w * 2, timeout=10)
    except Exception as e:
        notes.append(f"liq:{type(e).__name__}"); return None
    v60, v20 = median_volume(bars, long_w), median_volume(bars, short_w)
    if not v60:
        notes.append("liq:no_volume"); return None
    days = shares / (part * v60) if part * v60 > 0 else None
    if days is None:
        sig = "base"
    elif days <= d_base:
        sig = "bull"          # exitable inside a week at the assumed participation
    elif days >= d_bear:
        sig = "bear"          # a month or more of the tape to clear the position
    else:
        sig = "base"
    trend = round(v20 / v60, 2) if (v20 and v60) else None
    adtv_gbp = round(v60 * (pence or 0) / 100) if pence else None
    return {
        "adtv_gbp": adtv_gbp,
        "days_to_exit": round(days, 1) if days is not None else None,
        "participation": part,
        "trend_20_60": trend,
        "signal": sig,
    }


def n_session_change(sym_key, window, unit, notes):
    """Change in a Yahoo series over `window` completed sessions.

    unit="abs" -> absolute units (DXY index points); unit="pct" -> percent.
    Stateless: computed from a fresh history pull, so it survives a missing or stale
    prior data.json. The old `delta` kind compared today against yesterday's stored
    value, which made the metric hostage to the previous run having succeeded.
    """
    sym = C.PRICE_SYMBOLS.get(sym_key)
    if not sym:
        notes.append(f"chg:{sym_key}:no_symbol"); return None
    rng = max(90, int(window * 2.2) + 30)      # calendar days to cover N sessions
    try:
        bars = yahoo_daily(sym, rng, timeout=10)
    except Exception as e:
        notes.append(f"chg:{sym_key}:{type(e).__name__}"); return None
    closes = [c for _, c in bars]
    if len(closes) < window + 1:
        notes.append(f"chg:{sym_key}:short({len(closes)})"); return None
    now, then = closes[-1], closes[-1 - window]
    if not then:
        return None
    return round(now - then, 3) if unit == "abs" else round((now / then - 1) * 100, 2)


def trailing_24m(manual, notes, bars=None):
    """Monthly average of daily closes, last 24 completed months. Fallback to manual.
    Reuses pre-fetched daily `bars` when supplied (avoids a duplicate gold fetch)."""
    try:
        if bars is None:
            bars = yahoo_daily(C.PRICE_SYMBOLS["gold"], C.TRAILING_RANGE_DAYS)
        by_month = defaultdict(list)
        for dt, c in bars:
            by_month[(dt.year, dt.month)].append(c)
        monthly_avg = {ym: sum(v) / len(v) for ym, v in by_month.items()}
        now = datetime.date.today()
        completed = sorted(k for k in monthly_avg if k < (now.year, now.month))
        window = completed[-C.TRAILING_MONTHS:]
        if len(window) >= 12:
            return round(sum(monthly_avg[k] for k in window) / len(window)), len(window)
        notes.append("trailing:insufficient_months")
    except Exception as e:
        notes.append(f"trailing:{type(e).__name__}")
    return manual.get("trailing24"), 0


def load_holdings(notes):
    raw = os.environ.get("HOLDINGS")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            notes.append("HOLDINGS:bad_json")
    local = os.path.join(DATA, "holdings.local.json")
    if os.path.exists(local):
        return json.load(open(local))
    notes.append("HOLDINGS:absent")
    return {}


def score_metric(m, px, fred, manual, prev):
    man = manual.get("metrics", {}).get(m["id"], {})
    fb = man.get("signal", "base")
    k = m["kind"]
    if k == "manual":
        return fb
    if k == "chg_n":
        # n-session change, precomputed into px by n_session_change(). Falling = bull for
        # both current users (a weaker dollar and cheaper oil are each gold-supportive).
        chg = px.get("_chg_" + m["id"])
        if chg is None: return fb
        if chg <= m["bull_at"]: return "bull"
        if chg >= m["bear_at"]: return "bear"
        return "base"
    if k == "level":
        cur = fred.get(m["src"]) if m["src"] in C.FRED_SERIES else px.get(m["src"])
        if cur is None: return fb
        if m["higher_is_bull"]:
            return "bull" if cur >= m["bull_at"] else "bear" if cur <= m["bear_at"] else "base"
        return "bull" if cur <= m["bull_at"] else "bear" if cur >= m["bear_at"] else "base"
    if k == "ratio":
        n, dn = px.get(m["num"]), px.get(m["den"])
        if not n or not dn: return fb
        r = n / dn
        if m["higher_is_bull"]:
            return "bull" if r >= m["bull_at"] else "bear" if r <= m["bear_at"] else "base"
        return "bull" if r <= m["bull_at"] else "bear" if r >= m["bear_at"] else "base"
    if k == "slope3m":
        chg = px.get("_slope_change_bp")
        if chg is None: return fb
        if chg >= m["bull_at"]: return "bull"
        if chg <= m["bear_at"]: return "bear"
        return "base"
    if k == "ratio_trailing":
        spot, trail = px.get("gold"), px.get("_trailing")
        if not spot or not trail: return fb
        r = spot / trail
        if r >= m["bear_at"]: return "bear"
        return "bull" if m["bull_lo"] <= r <= m["bull_hi"] else "base"
    if k == "opp_cost":
        g1, g3 = px.get("oc_gap_1m"), px.get("oc_gap_3m")
        if g1 is None or g3 is None: return fb
        t1, t3 = m["t1"], m["t3"]
        # Contrarian: fade the recent winner. Tech out-earning gold on BOTH windows
        # (gaps positive & extreme) = stretched -> mean-reversion favours gold = bull.
        # Gold out-earning tech on both = gold stretched = bear.
        if g3 >= t3 and g1 >= t1:    return "bull"
        if g3 <= -t3 and g1 <= -t1:  return "bear"
        return "base"
    return fb


def divergence(px, fred, prev, notes):
    """Orthodox Divergence Diagnostic, computed live from day-over-day deltas.
    Reuses the prior session's stored real-yield/DXY (data.json _raw) and gold spot."""
    pr = prev.get("_raw", {})
    ry_now, ry_prev = fred.get("dfii10"), pr.get("real_yield")
    dxy_now, dxy_prev = px.get("dxy"), pr.get("dxy")
    g_now = px.get("gold")
    g_prev = (prev.get("gold") or {}).get("spot")
    if None in (ry_now, ry_prev, dxy_now, dxy_prev, g_now, g_prev) or not g_prev:
        notes.append("divergence:insufficient_history")
        return None
    d_ry = ry_now - ry_prev                       # percentage points
    d_dxy = dxy_now - dxy_prev                     # DXY index points
    actual = (g_now - g_prev) / g_prev * 100.0     # realised gold move, %
    expected = C.DIVERGENCE_BETA_REAL_YIELD * d_ry + C.DIVERGENCE_BETA_DXY * d_dxy
    resid = actual - expected
    band = C.DIVERGENCE_BAND_PP
    if resid > band:
        signal, verdict = "structural_bid", f"Gold outperforming textbook by {resid:.1f}pp"
    elif resid < -band:
        signal, verdict = "gold_lagging", f"Gold lagging textbook by {abs(resid):.1f}pp"
    else:
        signal, verdict = "textbook", f"Tracking textbook within {abs(resid):.1f}pp"
    return {
        "d_real_yield_bp": round(d_ry * 100, 1),
        "d_dxy_pct": round(d_dxy, 2),
        "expected_gold_pct": round(expected, 2),
        "actual_gold_pct": round(actual, 2),
        "residual_pp": round(resid, 2),
        "verdict": verdict,
        "signal": signal,
    }


def opportunity_cost(notes, gold_bars=None):
    """Return-competition (opportunity cost) of holding gold vs the AI/tech complex.
    Contrarian: a large tech-over-gold return gap = stretched -> mean-reversion
    favours gold. Headline gap NDX vs gold; GDXJ leg for the portfolio read.
    Best-effort: each leg guarded + short timeout so it can never hang the run."""
    out = {"gap_1m": None, "gap_3m": None, "ndx_1m": None, "gold_1m": None,
           "ndx_3m": None, "gold_3m": None, "gdxj_3m": None,
           "verdict": "insufficient history", "signal": "base"}
    n1, n3 = 21, 63                                   # ~1m and ~3m trading days

    def ret(bars, n):
        return None if not bars or len(bars) < n + 1 else (bars[-1][1] / bars[-1 - n][1] - 1.0) * 100.0

    def leg(sym):
        try:
            return yahoo_daily(sym, 150, timeout=8)
        except Exception as e:
            notes.append(f"oppcost:{sym}:{type(e).__name__}"); return None

    ndx = leg(C.PRICE_SYMBOLS["ndx"])
    gld = gold_bars if gold_bars else leg(C.PRICE_SYMBOLS["gold"])
    gdxj = leg(C.PRICE_SYMBOLS["gdxj"])

    out["ndx_1m"], out["ndx_3m"] = ret(ndx, n1), ret(ndx, n3)
    out["gold_1m"], out["gold_3m"] = ret(gld, n1), ret(gld, n3)
    out["gdxj_3m"] = ret(gdxj, n3)
    if None not in (out["ndx_1m"], out["gold_1m"]):
        out["gap_1m"] = round(out["ndx_1m"] - out["gold_1m"], 1)
    if None not in (out["ndx_3m"], out["gold_3m"]):
        out["gap_3m"] = round(out["ndx_3m"] - out["gold_3m"], 1)

    g1, g3 = out["gap_1m"], out["gap_3m"]
    oc_m = next((x for x in C.METRICS if x["id"] == "opp_cost"), None)
    t1, t3 = (oc_m["t1"], oc_m["t3"]) if oc_m else (7, 15)
    if g1 is not None and g3 is not None:
        if g3 >= t3 and g1 >= t1:
            out["signal"], out["verdict"] = "bull", f"Tech stretched vs gold (+{g3:.0f}pp 3m) - contrarian bid"
        elif g3 <= -t3 and g1 <= -t1:
            out["signal"], out["verdict"] = "bear", f"Gold stretched vs tech ({g3:.0f}pp 3m) - contrarian fade"
        else:
            out["signal"], out["verdict"] = "base", f"Gap {g3:+.0f}pp 3m / {g1:+.0f}pp 1m - no extreme"
    for k in ("ndx_1m", "gold_1m", "ndx_3m", "gold_3m", "gdxj_3m"):
        if out[k] is not None: out[k] = round(out[k], 1)
    return out


def main():
    manual = json.load(open(os.path.join(DATA, "manual_inputs.json")))
    snap = json.load(open(os.path.join(DATA, "model_snapshot.json")))
    try:
        prev = json.load(open(os.path.join(DATA, "data.json")))
    except Exception:
        prev = {}

    notes = []
    px = {k: fetch_price(k, notes) for k in C.PRICE_SYMBOLS}
    fred = {k: fetch_fred(v, notes) for k, v in C.FRED_SERIES.items()}
    px["cot"] = fetch_cot(notes)
    slope = real_curve_slope(notes)
    px["_slope_change_bp"] = slope["change_bp"] if slope else None
    for _m in C.METRICS:
        if _m.get("kind") == "chg_n":
            px["_chg_" + _m["id"]] = n_session_change(
                _m["sym"], _m["window"], _m.get("unit", "abs"), notes)
    # One gold daily fetch, shared by trailing-average and the opportunity-cost lens.
    try:
        gold_bars = yahoo_daily(C.PRICE_SYMBOLS["gold"], C.TRAILING_RANGE_DAYS)
    except Exception as e:
        notes.append(f"gold_daily:{type(e).__name__}"); gold_bars = None
    oc = opportunity_cost(notes, gold_bars)
    px["oc_gap_1m"], px["oc_gap_3m"] = oc["gap_1m"], oc["gap_3m"]
    gold = px.get("gold") or manual.get("gold_fallback", 4360)
    px["gold"] = gold
    trail, n_months = trailing_24m(manual, notes, gold_bars)
    px["_trailing"] = trail

    # Composite + themes
    raw_next, theme_net, theme_max, composite = {}, {t: 0.0 for t in C.THEMES}, {t: 0.0 for t in C.THEMES}, 0
    for m in C.METRICS:
        sig = score_metric(m, px, fred, manual, prev)
        composite += m["weight"] * SIG[sig]
        theme_net[m["theme"]] += m["weight"] * SIG[sig]
        theme_max[m["theme"]] += m["weight"]
    composite = int(round(composite))
    vname, tag = C.verdict(composite)

    # The divergence panel needs yesterday's 10y real yield and DXY. Those used to be
    # persisted as a side effect of real_yield/dxy being `delta` METRICS. real_yield is no
    # longer a metric, so persist both explicitly - otherwise the panel silently dies.
    if fred.get("dfii10") is not None: raw_next["real_yield"] = fred["dfii10"]
    if px.get("dxy") is not None:      raw_next["dxy"] = px["dxy"]

    gj = px.get("gdxj")
    mm = manual["metrics"]
    cot_v = px.get("cot")
    if cot_v is None: cot_v = mm["cot_mm_net_pct_oi"]["value"]
    slope_txt = (f"real slope {slope['slope_now_pp']:+.2f}pp ({slope['change_bp']:+.0f}bp 3m)"
                 if slope else "real slope n/a")
    readings = {
        "demand_flows": " . ".join([
            f"ETF {mm['etf_aum_delta_t']['value']:+g} t/mo",
            f"COT {round(cot_v*100,1)}% OI",
            f"CB {mm['wgc_cb_purchases_t']['value']} t/qtr",
        ]),
        "macro_rates": slope_txt,
        "usd_geo": " . ".join([
            (f"DXY {round(px.get('dxy') or 0,1)} ({px['_chg_dxy']:+.1f} 20d)"
             if px.get("_chg_dxy") is not None else f"DXY {round(px.get('dxy') or 0,1)}"),
            (f"Brent ${round(px.get('brent') or mm['brent']['value'])} ({px['_chg_brent']:+.0f}% 3m)"
             if px.get("_chg_brent") is not None else
             f"Brent ${round(px.get('brent') or mm['brent']['value'])}"),
        ]),
        "mining_equities": " . ".join([
            f"spot/24m {gold/trail:.2f}" if (gold and trail) else "spot/24m n/a",
            f"GDXJ/gold {gj/gold:.3f}" if (gj and gold) else "GDXJ/gold n/a",
        ]),
    }
    themes = [{"id": t, "label": C.THEME_LABELS[t], "signal": C.theme_signal(theme_net[t], theme_max[t]),
               "reading": readings[t]} for t in C.THEMES]

    # Holdings -> GBP value + %, anonymised. No shares, no per-share price published.
    H = load_holdings(notes)
    vals, liq = {}, {}
    for key in ("africa", "asia"):
        h = H.get(key, {})
        live = fetch_holding_price(h["ticker"], notes) if h.get("ticker") else None
        pence = live if live else h.get("px_fallback")
        vals[key] = round(h.get("shares", 0) * pence / 100) if (h.get("shares") and pence) else None
        liq[key] = liquidity_profile(h.get("ticker"), h.get("shares"), pence, notes)
    total = sum(v for v in vals.values() if v) or 0
    pct = lambda v: round(100 * v / total, 1) if (v and total) else None

    val = snap["valuation"]
    desc = {"africa": "Gold producer + developer", "asia": "Gold developer (construction)"}
    holdings = {}
    for key in ("africa", "asia"):
        holdings[key] = {
            "name": key.capitalize(), "desc": desc[key],
            "value": vals[key], "pct": pct(vals[key]),
            "npv": f"{val[key]['npv_bear']} - {val[key]['npv_bull']}",
            "jur": (f"{round(val[key]['disc']*100)}% disc" if val[key].get("disc") is not None else "\u2014"),
            "jsig": ("base" if (val[key].get("disc") or 0) <= 0.09 else "bear"),
            "lens": (f"{val[key]['pfcf_mult']:g}\u00d7 P/FCF \u00b7 {round(val[key]['npv_wt']*100)}/{round(val[key]['pfcf_wt']*100)} NPV/P-FCF"
                     if None not in (val[key].get("pfcf_mult"), val[key].get("npv_wt"), val[key].get("pfcf_wt")) else ""),
            "next": manual["catalysts"][0]["label"] if key == "africa" else manual["catalysts"][1]["label"],
            "liq": (f"{liq[key]['days_to_exit']:g}d @ {round(liq[key]['participation']*100)}% ADV"
                    if (liq[key] and liq[key].get("days_to_exit") is not None) else "\u2014"),
            "lsig": (liq[key]["signal"] if liq[key] else "base"),
            "adtv": (liq[key]["adtv_gbp"] if liq[key] else None),
            "ltrend": (liq[key]["trend_20_60"] if liq[key] else None),
        }

    out = {
        "as_of": datetime.date.today().isoformat(),
        "manual_as_of": manual.get("manual_as_of"),
        "model_as_of": snap.get("model_as_of"),
        "gold": {"spot": round(gold), "trailing24": round(trail) if trail else None,
                 "ratio": round(gold / trail, 2) if trail else None,
                 "forecast_2029": snap.get("gold_2029_forecast"),
                 "trailing_months": n_months, "verdict": vname, "tag": tag, "composite": composite},
        "themes": themes,
        "divergence": divergence(px, fred, prev, notes),
        "real_curve_slope": slope,
        "opportunity_cost": oc,
        "portfolio": {"current": total or None,
                      "v2029_base": snap["scenarios"]["2029"]["base"],
                      "income_2029": snap["income_2029_base"], "income_yield": snap["income_2029_yield"]},
        "holdings": holdings,
        "scenarios": snap["scenarios"],
        "catalysts": manual["catalysts"],
        "actions": manual["actions"],
        "fetch_notes": notes,
        "_raw": raw_next,
    }
    json.dump(out, open(os.path.join(DATA, "data.json"), "w"), indent=2)
    print(f"wrote data.json - composite {composite:+d} ({vname}); value GBP {total:,}; "
          f"trailing {trail} ({n_months}m avg); {len(notes)} fallbacks")
    if notes:
        print("fallbacks:", "; ".join(notes), file=sys.stderr)


if __name__ == "__main__":
    main()
