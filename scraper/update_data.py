#!/usr/bin/env python3
"""
EOD updater for the gold portfolio monitor.

Pulls end-of-day prices (Yahoo Finance chart API, with Stooq as fallback),
rate series (FRED, free key), merges low-frequency manual inputs, scores the
six-theme gold thesis composite, and writes data/data.json which the static
front end reads. Every fetch degrades gracefully: an unreachable source falls
back to its last known value so the dashboard never breaks.
"""
import csv, io, json, os, sys, urllib.request, urllib.parse, datetime, statistics
from pathlib import Path
import config as C

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")}
TIMEOUT = 20


def _http(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def load_json(name, default=None):
    p = DATA / name
    if p.exists():
        return json.loads(p.read_text())
    return default if default is not None else {}


# ---------- price sources: Yahoo primary, Stooq fallback ----------
def _yahoo_chart(symbol, rng, interval):
    path = f"/v8/finance/chart/{urllib.parse.quote(symbol)}?interval={interval}&range={rng}"
    last = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            d = json.loads(_http(f"https://{host}{path}"))
            return d["chart"]["result"][0]
        except Exception as e:
            last = e
    raise last


def price_last(key):
    ysym = C.YAHOO.get(key)
    if ysym:
        try:
            res = _yahoo_chart(ysym, "5d", "1d")
            mp = res.get("meta", {}).get("regularMarketPrice")
            if mp is not None:
                return float(mp)
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if closes:
                return float(closes[-1])
        except Exception:
            pass
    ssym = C.STOOQ.get(key)
    if ssym:
        txt = _http(f"https://stooq.com/q/l/?s={ssym}&f=sd2t2ohlcv&e=csv")
        return float(list(csv.DictReader(io.StringIO(txt)))[0]["Close"])
    raise RuntimeError("no source for " + key)


def price_monthly(key, months=24):
    ysym = C.YAHOO.get(key)
    if ysym:
        try:
            res = _yahoo_chart(ysym, "3y", "1mo")
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if closes:
                return closes[-months:]
        except Exception:
            pass
    ssym = C.STOOQ.get(key)
    if ssym:
        txt = _http(f"https://stooq.com/q/d/l/?s={ssym}&i=m")
        rows = list(csv.DictReader(io.StringIO(txt)))
        return [float(r["Close"]) for r in rows if r.get("Close") not in (None, "", "N/D")][-months:]
    return []


def fred_last(series, api_key):
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series}"
           f"&api_key={api_key}&file_type=json&sort_order=desc&limit=2")
    obs = json.loads(_http(url))["observations"]
    vals = [float(o["value"]) for o in obs if o["value"] not in (".", "")]
    return vals[0], (vals[0] - vals[1] if len(vals) > 1 else 0.0)


# ---------- scoring ----------
def score_metric(meta, value):
    if value is None:
        return 0
    bull, bear = meta["bull_at"], meta["bear_at"]
    if meta.get("inverted"):
        if value <= bull: return 1
        if value >= bear: return -1
        return 0
    if value >= bull: return 1
    if value <= bear: return -1
    return 0


SIGNAL_WORD = {1: "bull", 0: "base", -1: "bear"}


def main():
    prev = load_json("data.json", {})
    prev_metrics = prev.get("metrics", {})
    manual = load_json("manual_inputs.json")
    holdings = load_json("holdings.json")
    scen = load_json("scenarios.json")
    fred_key = os.environ.get("FRED_API_KEY", "")

    raw, notes = {}, []

    def remember(mid):
        return prev_metrics.get(mid, {}).get("value")

    try:
        gold = price_last("gold")
    except Exception as e:
        gold = remember("_gold") or 4354.0; notes.append(f"gold:{e}")
    try:
        monthly = price_monthly("gold", 24)
        trailing24 = round(statistics.mean(monthly), 1) if monthly else prev.get("gold", {}).get("trailing24", 3408.0)
    except Exception as e:
        trailing24 = prev.get("gold", {}).get("trailing24", 3408.0); notes.append(f"gold24m:{e}")

    px = {}
    for key in ("dxy", "vix", "brent", "gdx", "gdxj", "ndx", "thx", "mtl"):
        try:
            px[key] = price_last(key)
        except Exception as e:
            px[key] = None; notes.append(f"{key}:{e}")

    for mid, meta in C.METRICS.items():
        src = meta["src"]; val = None
        try:
            if src.startswith("manual:"):
                val = manual.get(src.split(":")[1], {}).get("value")
            elif src.startswith("fred:") and fred_key:
                val, _ = fred_last(C.FRED[src.split(":")[1]], fred_key)
            elif src.startswith("fred_delta:") and fred_key:
                _, val = fred_last(C.FRED[src.split(":")[1]], fred_key)
            elif src.startswith("stooq:") or src.startswith("price:"):
                val = px.get(src.split(":")[1])
            elif src.startswith("stooq_delta:") or src.startswith("price_delta:"):
                cur = px.get(src.split(":")[1]); pr = remember(mid + "_level")
                val = (cur - pr) if (cur is not None and pr is not None) else 0.0
                raw[mid + "_level"] = cur
            elif src.startswith("ratio:"):
                expr = src.split(":")[1]
                if expr == "spot24m":
                    val = round(gold / trailing24, 4) if trailing24 else None
                elif expr == "gdxj/gold":
                    val = round(px["gdxj"] / gold, 5) if px.get("gdxj") and gold else None
                elif expr == "gdx/gold":
                    val = round(px["gdx"] / gold, 5) if px.get("gdx") and gold else None
                elif expr == "ndx/gdxj":
                    val = round(px["ndx"] / px["gdxj"], 2) if px.get("ndx") and px.get("gdxj") else None
        except Exception as e:
            notes.append(f"{mid}:{e}")
        if val is None:
            val = remember(mid)
        raw[mid] = val

    metrics_out, theme_score, theme_max = {}, {}, {}
    composite = 0
    for mid, meta in C.METRICS.items():
        v = raw.get(mid); sig = score_metric(meta, v)
        composite += meta["weight"] * sig
        metrics_out[mid] = {"value": v, "signal": SIGNAL_WORD[sig], "theme": meta["theme"], "weight": meta["weight"]}
        t = meta["theme"]
        theme_score[t] = theme_score.get(t, 0) + meta["weight"] * sig
        theme_max[t] = theme_max.get(t, 0) + meta["weight"]
    for k in list(raw):
        if k.endswith("_level"):
            metrics_out[k] = {"value": raw[k]}
    metrics_out["_gold"] = {"value": gold}

    def theme_signal(t):
        s = theme_score[t]
        if s > 0.15 * theme_max[t]: return "bull"
        if s < -0.15 * theme_max[t]: return "bear"
        return "base"

    def rv(mid): return raw.get(mid)
    def fmt(v, nd=0): return ("{:,.%df}" % nd).format(v) if isinstance(v, (int, float)) else "n/a"

    readings = {
        "central_bank":    f"WGC {fmt(rv('wgc_cb_purchases_t'))} t/qtr",
        "macro_rates":     "Fed hold; real-yield link broken",
        "usd_fx":          f"DXY {fmt(rv('dxy_level'),1)}; COFER {fmt(manual.get('cofer_usd_share_delta',{}).get('value'),2)}",
        "geopolitics":     f"VIX {fmt(rv('vix'),1)}; GPR {fmt(rv('gpr_index'))}; Brent ${fmt(rv('brent'))}",
        "mining_equities": "GDXJ/gold catch-up",
        "positioning":     f"COT {fmt((rv('cot_mm_net_pct_oi') or 0)*100,1)}%; GVZ {fmt(rv('gvz'),1)}",
    }
    themes_out = [{"id": t, "label": C.THEME_LABELS[t], "signal": theme_signal(t), "reading": readings[t]} for t in C.THEMES]

    if composite >= 30:   verdict = "Strongly bullish"
    elif composite >= 10: verdict = "Bullish"
    elif composite > -10: verdict = "Balanced"
    elif composite > -30: verdict = "Bearish"
    else:                 verdict = "Strongly bearish"

    thx_p = px.get("thx") or prev.get("holdings", {}).get("THX", {}).get("price_pence", 76)
    mtl_p = px.get("mtl") or prev.get("holdings", {}).get("MTL", {}).get("price_pence", 13)
    cur_val = round(holdings.get("THX", 0) * thx_p / 100 + holdings.get("MTL", 0) * mtl_p / 100)

    out = {
        "as_of": datetime.date.today().isoformat(),
        "gold": {"spot": round(gold), "trailing24": round(trailing24), "ratio": round(gold / trailing24, 2) if trailing24 else None},
        "composite": composite, "verdict": verdict, "themes": themes_out, "metrics": metrics_out,
        "portfolio": {
            "current_value": cur_val,
            "value_2029_base": scen.get("scenarios", {}).get("2029", {}).get("base"),
            "income_2029_base": scen.get("income_2029_base"),
            "income_2029_yield": scen.get("income_2029_yield"),
        },
        "holdings": {
            "THX": {"shares": holdings.get("THX"), "price_pence": round(thx_p, 2),
                    "npv": scen.get("npv_per_share", {}).get("THX"), "jurisdiction": manual.get("jurisdiction", {}).get("THX")},
            "MTL": {"shares": holdings.get("MTL"), "price_pence": round(mtl_p, 2),
                    "npv": scen.get("npv_per_share", {}).get("MTL"), "jurisdiction": manual.get("jurisdiction", {}).get("MTL")},
        },
        "scenarios": scen.get("scenarios"), "catalysts": manual.get("catalysts"),
        "alerts": manual.get("alerts"), "fetch_notes": notes,
    }
    (DATA / "data.json").write_text(json.dumps(out, indent=2))
    print(f"wrote data.json — composite {composite:+d} ({verdict}); {len(notes)} fallbacks")
    if notes:
        print("fallbacks:", "; ".join(notes), file=sys.stderr)


if __name__ == "__main__":
    main()
