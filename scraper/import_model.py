#!/usr/bin/env python3
"""
Local model importer — v25 layout (portfolio_dashboard_v23/v24/v25 family).

Reads the portfolio model (.xlsx) and writes data/model_snapshot.json: the valuation
layer the scraper merges into the public dashboard (NAV £/share, the scenario £m grid,
the 2029 gold assumption, and 2029 exit income/yield).

Runs LOCALLY only — never in the GitHub Action — so the spreadsheet never leaves your
machine. Requires openpyxl.

    python scraper/import_model.py /path/to/portfolio_dashboard_v25.xlsx

CHANGED FROM THE v22 IMPORTER
-----------------------------
v22 had THX_NAV / MTL_NAV / Forecast / Portfolio / Valuation sheets. The v23+ model has
Dashboard / Inputs / THX DCF / MTL DCF / FCF Cross-check / Notes, so every cell
reference below is new:

  * NAV per share (£) now — 'THX DCF' / 'MTL DCF' C34:C36 (Bear/Base/Bull, by ROW,
    not by column as in v22).
  * Discount rate — single flat rate for both names, Inputs C11 (8%). Jurisdiction
    risk is an explicit NAV haircut (Inputs C23 / C33), not a rate premium.
  * `pfcf_mult` keeps its v22 meaning for front-end compatibility: the 2030 BASE
    P/NAV multiple (Inputs G56 / G62). npv_wt pinned to 1.0, pfcf_wt to 0.0.
  * `pnav_anchor` — today's P/NAV, self-calibrated to the live price (Inputs C56 / C62).
  * Scenario £ grid — Dashboard C59:G61 (rows Bear/Base/Bull, cols Now/2027/2028/2029/
    2030). "Now" is published under the key "2026" so the dashboard's year ordering holds.
  * 2029 gold — v25 uses a FLAT nominal gold deck (a settled modelling decision), so the
    2029 figure is the base-case deck, Inputs C7.
  * Rotation — Dashboard H4 (THX P/NAV ÷ MTL P/NAV) vs tranche-1 trigger Inputs D45.
    The v25 model notes the trigger as FROZEN pending the Segilola resource update and
    La India first pour; that flag is carried into the snapshot.
  * 2029 income is computed here, as before, from the 2029 base portfolio value and the
    exit_plan block in data/manual_inputs.json.

The scenario £ grid uses the share counts typed on the Inputs sheet (HOLDINGS & PRICES).
Update those to match the HOLDINGS secret before importing, or the £ grid will not
match the live holdings.

Cells that read #VALUE!/blank are skipped and the previous snapshot value is kept.
Open + recalculate the model in Excel and save before importing.
"""
import json, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SNAP = os.path.join(DATA, "model_snapshot.json")
MANUAL = os.path.join(DATA, "manual_inputs.json")

# Anonymised holding keys. No tickers, no jurisdictions, no share counts in this file.
HOLD = ["africa", "asia"]

# --- v25 cell map -----------------------------------------------------------
REQUIRED = ("Dashboard", "Inputs", "THX DCF", "MTL DCF")

DCF_SHEET = {"africa": "THX DCF", "asia": "MTL DCF"}
NAV_NOW = {"bear": "C34", "base": "C35", "bull": "C36"}          # £/share, valuation date Now

DISC_CELL = "C11"                                                # Inputs, both names
HAIRCUT_CELL = {"africa": "C23", "asia": "C33"}                  # Inputs, jurisdiction haircut
TERM_PNAV = {"africa": "G56", "asia": "G62"}                     # Inputs, 2030 base P/NAV
ANCHOR_PNAV = {"africa": "C56", "asia": "C62"}                   # Inputs, today's P/NAV

SCEN_ROW = {"bear": 59, "base": 60, "bull": 61}                  # Dashboard, £
SCEN_COL = {"2026": "C", "2027": "D", "2028": "E", "2029": "F", "2030": "G"}

GOLD_BASE_CELL = "C7"                                            # Inputs, flat base deck
CROSS_CELL = "H4"                                                # Dashboard
THRESH_CELL = "D45"                                              # Inputs, tranche-1 trigger
SEGI_CASE_CELL = "C24"                                           # Inputs (v25+), 1 or 2

FELL_BACK = []


def num(ws, coord, prior, allow_zero=True):
    v = ws[coord].value
    if isinstance(v, (int, float)) and not isinstance(v, bool) and (allow_zero or v != 0):
        return float(v)
    FELL_BACK.append(f"{ws.title}!{coord}")
    return prior


def rnd(v, n):
    return round(v, n) if isinstance(v, (int, float)) else v


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python scraper/import_model.py /path/to/portfolio_dashboard_v25.xlsx")
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl required:  pip install openpyxl")

    path = sys.argv[1]
    wb = openpyxl.load_workbook(path, data_only=True)

    missing = [s for s in REQUIRED if s not in wb.sheetnames]
    if missing:
        sys.exit(f"not a v23+ model — missing sheet(s): {', '.join(missing)}. "
                 "The v22 importer read THX_NAV/MTL_NAV/Portfolio; that map no longer applies.")

    inp, dash = wb["Inputs"], wb["Dashboard"]

    prior = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    pv = prior.get("valuation", {})
    ps = prior.get("scenarios", {})

    disc = num(inp, DISC_CELL, None)
    val = {}
    for key in HOLD:
        ws = wb[DCF_SHEET[key]]
        p = pv.get(key, {})
        val[key] = {
            "npv_bull": rnd(num(ws, NAV_NOW["bull"], p.get("npv_bull")), 3),
            "npv_base": rnd(num(ws, NAV_NOW["base"], p.get("npv_base")), 3),
            "npv_bear": rnd(num(ws, NAV_NOW["bear"], p.get("npv_bear")), 3),
            "disc": rnd(disc if disc is not None else p.get("disc"), 4),
            "haircut": rnd(num(inp, HAIRCUT_CELL[key], p.get("haircut")), 3),
            # Retained key, v22 meaning: terminal (2030) base P/NAV, not a P/FCF multiple.
            "pfcf_mult": rnd(num(inp, TERM_PNAV[key], p.get("pfcf_mult")), 3),
            "pnav_anchor": rnd(num(inp, ANCHOR_PNAV[key], p.get("pnav_anchor")), 3),
            "npv_wt": 1.0,
            "pfcf_wt": 0.0,
        }

    scen = {}
    for yr, col in SCEN_COL.items():
        pp = ps.get(yr, {})
        row = {}
        for s in ("bear", "base", "bull"):
            v = num(dash, f"{col}{SCEN_ROW[s]}", None)
            row[s] = round(v / 1e6, 2) if v is not None else pp.get(s)
        scen[yr] = row

    gold_fc = num(inp, GOLD_BASE_CELL, prior.get("gold_2029_forecast"), allow_zero=False)

    # 2029 exit income, computed here rather than read from a model cell.
    inc = prior.get("income_2029_base")
    yld = prior.get("income_2029_yield")
    try:
        man = json.load(open(MANUAL))
        ep = man.get("exit_plan", {})
        share = float(ep.get("transfer_share", 0.5))
        fyield = float(ep.get("fund_yield", 0.045))
        miner_yield = float(ep.get("miner_net_yield", 0.037))
        v29 = scen["2029"]["base"]
        if v29:
            gross = v29 * 1e6 * (share * fyield + (1 - share) * miner_yield)
            inc = int(round(gross))
            yld = round(100 * gross / (v29 * 1e6), 2)
    except Exception as e:
        FELL_BACK.append(f"exit_plan ({e})")

    cross = num(dash, CROSS_CELL, None)
    thresh = num(inp, THRESH_CELL, None)
    segi = inp[SEGI_CASE_CELL].value
    segi_case = int(segi) if isinstance(segi, (int, float)) and segi in (1, 2) else None
    frozen = segi_case is not None          # v25+ model: trigger frozen pending resource update

    signal = None
    if cross and thresh:
        signal = "ROTATE" if cross >= thresh else "HOLD"

    out = {
        "model_as_of": datetime.date.today().isoformat(),
        "source": os.path.basename(path),
        "schema": "v25",
        "valuation": val,
        "scenarios": scen,
        "gold_2029_forecast": round(gold_fc) if gold_fc else prior.get("gold_2029_forecast"),
        "income_2029_base": inc,
        "income_2029_yield": yld,
        "rotation": {
            "cross_ratio": round(cross, 3) if cross else None,
            "threshold": round(thresh, 3) if thresh else None,
            "signal": signal,
            "frozen": frozen,
        },
        "producer_case": ({1: "documented ounces only", 2: "mine-life target case (unproven)"}
                          .get(segi_case) if segi_case else None),
        "method_note": (
            "Both holdings discounted at a flat {}. Jurisdiction risk is an explicit NAV haircut "
            "(africa {}, asia {}), not a rate premium. Flat nominal gold deck. Rotation trigger "
            "frozen in the model pending the producer resource update and the developer's first pour."
        ).format(f"{round(disc*100)}%" if disc else "rate",
                 f"{round(val['africa']['haircut']*100)}%" if val['africa'].get('haircut') is not None else "n/a",
                 f"{round(val['asia']['haircut']*100)}%" if val['asia'].get('haircut') is not None else "n/a"),
    }
    json.dump(out, open(SNAP, "w"), indent=2)

    n = len(FELL_BACK)
    print(f"wrote model_snapshot.json from {out['source']} (schema v25) — "
          + ("all cells resolved." if n == 0 else
             f"{n} unresolved: {', '.join(FELL_BACK[:6])}. Recalculate the model and re-run."))
    if out["rotation"]["signal"]:
        print(f"  rotation: cross {out['rotation']['cross_ratio']} vs threshold "
              f"{out['rotation']['threshold']} -> {out['rotation']['signal']}"
              + ("  (FROZEN in model)" if frozen else ""))


if __name__ == "__main__":
    main()
