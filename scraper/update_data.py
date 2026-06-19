#!/usr/bin/env python3
"""
EOD updater for the gold portfolio monitor.

Pulls end-of-day prices (Yahoo Finance chart API, Stooq fallback), rate series
(FRED, free key in env FRED_API_KEY), merges the hand-maintained manual_inputs.json,
scores the six-theme gold-thesis composite, and writes data/data.json which index.html
reads. Every fetch degrades gracefully: an unreachable source falls back to the manual
signal / prior value so the dashboard never breaks and the composite stays reconcilable.

Run:  python scraper/update_data.py
"""
import json, os, sys, datetime, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SIG = {"bull": 1, "base": 0, "bear": -1}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 gold-monitor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_last(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    d = json.loads(_get(url))
    res = d["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    return float(closes[-1])


def stooq_last(symbol):
    txt = _get(f"https://stooq.com/q/l/?s={symbol}&f=sd2t2c&h&e=csv")
    line = txt.strip().splitlines()[-1].split(",")
    return float(line[-1])


def fetch_price(key, notes):
    sym = C.PRICE_SYMBOLS[key]
    for name, fn, s in (("yahoo", yahoo_last, sym), ("stooq", stooq_last, sym.lower().replace("^", "").replace("=f", ".f"))):
        try:
            return fn(s)
        except Exception as e:
            notes.append(f"{key}:{name}:{type(e).__name__}")
    return None


def fetch_fred(series_id, notes):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        notes.append(f"{series_id}:no_FRED_key")
        return None
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
               f"&api_key={key}&file_type=json&sort_order=desc&limit=1")
        obs = json.loads(_get(url))["observations"][0]["value"]
        return float(obs)
    except Exception as e:
        notes.append(f"{series_id}:FRED:{type(e).__name__}")
        return None


def score_metric(m, px, fred, manual, prev, notes):
    """Return signal string. Live computation where possible, else manual fallback."""
    man = manual.get("metrics", {}).get(m["id"], {})
    fallback = man.get("signal", "base")
    k = m["kind"]

    if k == "manual":
        # Non-fetchable judgment input; signal lives in manual_inputs.
        return fallback

    if k == "delta":
        cur = fred.get(m["src"]) if m["src"] in C.FRED_SERIES else px.get(m["src"])
        prior = prev.get("_raw", {}).get(m["id"])
        if cur is None or prior is None:
            return fallback
        d = cur - prior
        bull = d <= m["bull_at"] if not m["higher_is_bull"] else d >= m["bull_at"]
        bear = d >= m["bear_at"] if not m["higher_is_bull"] else d <= m["bear_at"]
        return "bull" if bull else "bear" if bear else "base"

    if k == "level":
        cur = px.get(m["src"])
        if cur is None:
            return fallback
        if m["higher_is_bull"]:
            return "bull" if cur >= m["bull_at"] else "bear" if cur <= m["bear_at"] else "base"
        return "bull" if cur <= m["bull_at"] else "bear" if cur >= m["bear_at"] else "base"

    if k == "ratio":
        n, dn = px.get(m["num"]), px.get(m["den"])
        if not n or not dn:
            return fallback
        r = n / dn
        if m["higher_is_bull"]:
            return "bull" if r >= m["bull_at"] else "bear" if r <= m["bear_at"] else "base"
        return "bull" if r <= m["bull_at"] else "bear" if r >= m["bear_at"] else "base"

    if k == "ratio_trailing":
        spot, trail = px.get("gold"), manual.get("trailing24")
        if not spot or not trail:
            return fallback
        r = spot / trail
        if r >= m["bear_at"]:
            return "bear"
        return "bull" if m["bull_lo"] <= r <= m["bull_hi"] else "base"

    return fallback


def main():
    manual = json.load(open(os.path.join(DATA, "manual_inputs.json")))
    try:
        prev = json.load(open(os.path.join(DATA, "data.json")))
    except Exception:
        prev = {}

    notes = []
    px = {k: fetch_price(k, notes) for k in C.PRICE_SYMBOLS}
    fred = {k: fetch_fred(v, notes) for k, v in C.FRED_SERIES.items()}

    # Prices fall back to manual seed if both feeds fail.
    pf = manual.get("prices_fallback", {})
    thx_p = (px.get("thx") if px.get("thx") else pf.get("thx_pence", 65.6))
    mtl_p = (px.get("mtl") if px.get("mtl") else pf.get("mtl_pence", 13.9))
    gold = px.get("gold") or pf.get("gold", 4360)
    px["gold"] = gold
    trail = manual.get("trailing24", 3408)

    # Score metrics + roll up to themes.
    raw_for_next = {}
    theme_net = {t: 0.0 for t in C.THEMES}
    theme_max = {t: 0.0 for t in C.THEMES}
    composite = 0
    for m in C.METRICS:
        sig = score_metric(m, px, fred, manual, prev, notes)
        composite += m["weight"] * SIG[sig]
        theme_net[m["theme"]] += m["weight"] * SIG[sig]
        theme_max[m["theme"]] += m["weight"]
        # remember live raw values for next run's delta metrics
        if m.get("kind") == "delta":
            src = m["src"]
            v = fred.get(src) if src in C.FRED_SERIES else px.get(src)
            if v is not None:
                raw_for_next[m["id"]] = v

    composite = int(round(composite))
    verdict, tag = C.verdict(composite)

    readings = {
        "central_bank":    f"WGC {manual['metrics']['wgc_cb_purchases_t']['value']} t/qtr",
        "macro_rates":     "Fed hold; real-yield link broken",
        "usd_fx":          f"DXY {round(px.get('dxy') or 0,1)} · COFER {manual['metrics']['cofer_usd_share']['value']}%",
        "geopolitics":     f"VIX {round(px.get('vix') or 0,1)} · GPR {manual['metrics']['gpr_index']['value']} · Brent ${manual['metrics']['brent']['value']}",
        "mining_equities": "GDX/gold confirm · GDXJ catch-up",
        "positioning":     f"COT {round(manual['metrics']['cot_mm_net_pct_oi']['value']*100,1)}% OI · GVZ {manual['metrics']['gvz']['value']}",
    }
    themes = [{"id": t, "label": C.THEME_LABELS[t], "signal": C.theme_signal(theme_net[t], theme_max[t]),
               "reading": readings[t]} for t in C.THEMES]

    # Portfolio mark-to-market (ISA + SIPP only).
    H = manual["holdings"]
    thx_val = round(H["THX"]["shares"] * thx_p / 100)
    mtl_val = round(H["MTL"]["shares"] * mtl_p / 100)
    total = thx_val + mtl_val
    pct = lambda v: round(100 * v / total, 1) if total else 0

    val = manual["valuation"]
    jur = manual["jurisdiction"]
    out = {
        "as_of": datetime.date.today().isoformat(),
        "manual_as_of": manual.get("manual_as_of"),
        "gold": {"spot": round(gold), "trailing24": round(trail),
                 "ratio": round(gold / trail, 2) if trail else None,
                 "verdict": verdict, "tag": tag, "composite": composite},
        "themes": themes,
        "portfolio": {"current": total,
                      "v2029_base": manual["scenarios"]["2029"]["base"],
                      "income_2029": manual["income_2029_base"],
                      "income_yield": manual["income_2029_yield"]},
        "holdings": {
            "THX": {"name": "Thor Explorations · Nigeria + Senegal",
                    "price": round(thx_p / 100, 3), "shares": H["THX"]["shares"],
                    "value": thx_val, "pct": pct(thx_val),
                    "npv": f"{val['THX']['npv_bear']} – {val['THX']['npv_bull']}",
                    "jur": f"{jur['THX']['score']}/10 · {jur['THX']['signal']}", "jsig": jur["THX"]["signal"],
                    "next": manual["catalysts"][0]["label"] + " · " + manual["catalysts"][0]["date"]},
            "MTL": {"name": "Metals Exploration · Nicaragua",
                    "price": round(mtl_p / 100, 3), "shares": H["MTL"]["shares"],
                    "value": mtl_val, "pct": pct(mtl_val),
                    "npv": f"{val['MTL']['npv_bear']} – {val['MTL']['npv_bull']}",
                    "jur": f"{jur['MTL']['score']}/10 · {jur['MTL']['signal']}", "jsig": jur["MTL"]["signal"],
                    "next": manual["catalysts"][1]["label"] + " · " + manual["catalysts"][1]["date"]},
        },
        "scenarios": manual["scenarios"],
        "catalysts": manual["catalysts"],
        "actions": manual["actions"],
        "fetch_notes": notes,
        "_raw": raw_for_next,
    }
    json.dump(out, open(os.path.join(DATA, "data.json"), "w"), indent=2)
    print(f"wrote data.json — composite {composite:+d} ({verdict}); value £{total:,}; {len(notes)} fallbacks")
    if notes:
        print("fallbacks:", "; ".join(notes), file=sys.stderr)


if __name__ == "__main__":
    main()
