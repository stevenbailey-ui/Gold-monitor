#!/usr/bin/env python3
"""
EOD updater for the gold portfolio monitor (public, anonymised output).

Fetches gold-thesis prices (Yahoo, Stooq fallback) + FRED rates, auto-computes the 24-month
trailing gold price (monthly average of daily closes), reads the portfolio holdings from the
HOLDINGS secret / data/holdings.local.json, merges valuations from data/model_snapshot.json,
scores the six-theme composite, and writes data/data.json.

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


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 gold-monitor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_last(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    res = json.loads(_get(url))["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    return float(closes[-1])


def yahoo_daily(symbol, rng_days):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng_days}d&interval=1d"
    res = json.loads(_get(url))["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    return [(datetime.datetime.utcfromtimestamp(t), c) for t, c in zip(ts, closes) if c is not None]


def stooq_last(symbol):
    line = _get(f"https://stooq.com/q/l/?s={symbol}&f=sd2t2c&h&e=csv").strip().splitlines()[-1].split(",")
    return float(line[-1])


def fetch_price(key, notes):
    sym = C.PRICE_SYMBOLS[key]
    try:
        return yahoo_last(sym)
    except Exception as e:
        notes.append(f"{key}:yahoo:{type(e).__name__}")
    try:
        return stooq_last(sym.lower().replace("^", "").replace("=f", ".f"))
    except Exception as e:
        notes.append(f"{key}:stooq:{type(e).__name__}")
    return None


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


def trailing_24m(manual, notes):
    """Monthly average of daily closes, last 24 completed months. Fallback to manual."""
    try:
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
    if k == "delta":
        cur = fred.get(m["src"]) if m["src"] in C.FRED_SERIES else px.get(m["src"])
        prior = prev.get("_raw", {}).get(m["id"])
        if cur is None or prior is None:
            return fb
        d = cur - prior
        bull = d <= m["bull_at"] if not m["higher_is_bull"] else d >= m["bull_at"]
        bear = d >= m["bear_at"] if not m["higher_is_bull"] else d <= m["bear_at"]
        return "bull" if bull else "bear" if bear else "base"
    if k == "level":
        cur = px.get(m["src"])
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
    if k == "ratio_trailing":
        spot, trail = px.get("gold"), px.get("_trailing")
        if not spot or not trail: return fb
        r = spot / trail
        if r >= m["bear_at"]: return "bear"
        return "bull" if m["bull_lo"] <= r <= m["bull_hi"] else "base"
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
    gold = px.get("gold") or manual.get("gold_fallback", 4360)
    px["gold"] = gold
    trail, n_months = trailing_24m(manual, notes)
    px["_trailing"] = trail

    # Composite + themes
    raw_next, theme_net, theme_max, composite = {}, {t: 0.0 for t in C.THEMES}, {t: 0.0 for t in C.THEMES}, 0
    for m in C.METRICS:
        sig = score_metric(m, px, fred, manual, prev)
        composite += m["weight"] * SIG[sig]
        theme_net[m["theme"]] += m["weight"] * SIG[sig]
        theme_max[m["theme"]] += m["weight"]
        if m.get("kind") == "delta":
            src = m["src"]; v = fred.get(src) if src in C.FRED_SERIES else px.get(src)
            if v is not None: raw_next[m["id"]] = v
    composite = int(round(composite))
    vname, tag = C.verdict(composite)

    mm = manual["metrics"]
    readings = {
        "central_bank":    f"WGC {mm['wgc_cb_purchases_t']['value']} t/qtr",
        "macro_rates":     "Fed hold; real-yield link broken",
        "usd_fx":          f"DXY {round(px.get('dxy') or 0,1)} . COFER {mm['cofer_usd_share']['value']}%",
        "geopolitics":     f"VIX {round(px.get('vix') or 0,1)} . GPR {mm['gpr_index']['value']} . Brent ${mm['brent']['value']}",
        "mining_equities": "GDX/gold confirm . GDXJ catch-up",
        "positioning":     f"COT {round(mm['cot_mm_net_pct_oi']['value']*100,1)}% OI . GVZ {mm['gvz']['value']}",
    }
    themes = [{"id": t, "label": C.THEME_LABELS[t], "signal": C.theme_signal(theme_net[t], theme_max[t]),
               "reading": readings[t]} for t in C.THEMES]

    # Holdings -> GBP value + %, anonymised. No shares, no per-share price published.
    H = load_holdings(notes)
    vals = {}
    for key in ("africa", "asia"):
        h = H.get(key, {})
        live = fetch_holding_price(h["ticker"], notes) if h.get("ticker") else None
        pence = live if live else h.get("px_fallback")
        vals[key] = round(h.get("shares", 0) * pence / 100) if (h.get("shares") and pence) else None
    total = sum(v for v in vals.values() if v) or 0
    pct = lambda v: round(100 * v / total, 1) if (v and total) else None

    val, jur = snap["valuation"], manual["jurisdiction"]
    desc = {"africa": "Gold producer + developer", "asia": "Gold developer (construction)"}
    holdings = {}
    for key in ("africa", "asia"):
        holdings[key] = {
            "name": key.capitalize(), "desc": desc[key],
            "value": vals[key], "pct": pct(vals[key]),
            "npv": f"{val[key]['npv_bear']} - {val[key]['npv_bull']}",
            "jur": f"{jur[key]['score']}/10 . {jur[key]['signal']}", "jsig": jur[key]["signal"],
            "next": manual["catalysts"][0]["label"] if key == "africa" else manual["catalysts"][1]["label"],
        }

    out = {
        "as_of": datetime.date.today().isoformat(),
        "manual_as_of": manual.get("manual_as_of"),
        "model_as_of": snap.get("model_as_of"),
        "gold": {"spot": round(gold), "trailing24": round(trail) if trail else None,
                 "ratio": round(gold / trail, 2) if trail else None,
                 "trailing_months": n_months, "verdict": vname, "tag": tag, "composite": composite},
        "themes": themes,
        "divergence": divergence(px, fred, prev, notes),
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
