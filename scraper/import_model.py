#!/usr/bin/env python3
"""
Local model importer. Reads the portfolio model (.xlsx) and writes data/model_snapshot.json
— the valuation layer the scraper merges into the public dashboard (NPV £/share, the blended
scenario £m grid, and 2029 base income/yield).

Runs LOCALLY only — never in the GitHub Action — so the spreadsheet never leaves your machine.
Requires openpyxl.  Usage:

    python scraper/import_model.py /path/to/portfolio_v21.xlsx

Cells that read #VALUE!/blank (the live-gold-linked base cases populate only when the file has
been recalculated in Excel with your data connection) are skipped and the previous snapshot
value is kept. Open + save the model in Excel before importing to capture the base cases.
"""
import json, os, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SNAP = os.path.join(DATA, "model_snapshot.json")

# Anonymised holding keys (NPV rows below are keyed to these, in spreadsheet order).
HOLD = ["africa", "asia"]

# Cell map (Summary sheet). NPV rows: B=Bull C=Base D=Bear. Scenario Total Value = col H.
NPV_ROW = {"africa": 44, "asia": 45}          # B/C/D = bull/base/bear
SCEN_ROWS = {  # (bear,base,bull) row in section 47, Total Value (ISA+SIPP) = col I
    "2026": (49, 50, 51), "2027": (53, 54, 55), "2028": (57, 58, 59),
    "2029": (61, 62, 63), "2030": (65, 66, 67),
}
INCOME_ROW, INCOME_COL, YIELD_COL = 21, "J", "K"   # 2029 base
GOLD_FC_SHEET, GOLD_FC_CELL = "24 month ave", "C31"  # "Target 2029 avg ($/oz)" (scenario-flexed)


FELL_BACK = []

def num(ws, coord, prior, allow_zero=True):
    v = ws[coord].value
    if isinstance(v, (int, float)) and (allow_zero or v != 0):
        return float(v)
    FELL_BACK.append(coord)   # #VALUE!, None, text, or disallowed zero → keep prior/seed
    return prior


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python scraper/import_model.py /path/to/portfolio_v21.xlsx")
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl required:  pip install openpyxl")

    path = sys.argv[1]
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Summary"]

    prior = json.load(open(SNAP)) if os.path.exists(SNAP) else {}
    pv = prior.get("valuation", {})
    ps = prior.get("scenarios", {})

    val, scen, kept = {}, {}, 0
    for key in HOLD:
        r = NPV_ROW[key]
        p = pv.get(key, {})
        val[key] = {
            "npv_bull": round(num(ws, f"B{r}", p.get("npv_bull")), 3),
            "npv_base": round(num(ws, f"C{r}", p.get("npv_base")), 3),
            "npv_bear": round(num(ws, f"D{r}", p.get("npv_bear")), 3),
        }
    for yr, (rb, rba, rbu) in SCEN_ROWS.items():
        pp = ps.get(yr, {})
        def m(row, fb):
            v = num(ws, f"I{row}", None)
            return round(v / 1e6, 2) if v is not None else fb
        scen[yr] = {"bear": m(rb, pp.get("bear")), "base": m(rba, pp.get("base")),
                    "bull": m(rbu, pp.get("bull"))}

    inc = num(ws, f"{INCOME_COL}{INCOME_ROW}", prior.get("income_2029_base"), allow_zero=False)
    yld = num(ws, f"{YIELD_COL}{INCOME_ROW}", None, allow_zero=False)
    yld = round(yld * 100, 1) if (yld is not None and yld < 1) else (yld if yld is not None else prior.get("income_2029_yield"))

    gld = wb[GOLD_FC_SHEET]
    gold_fc = num(gld, GOLD_FC_CELL, prior.get("gold_2029_forecast"), allow_zero=False)

    out = {
        "model_as_of": datetime.date.today().isoformat(),
        "source": os.path.basename(path),
        "valuation": val,
        "scenarios": scen,
        "gold_2029_forecast": round(gold_fc) if gold_fc else prior.get("gold_2029_forecast"),
        "income_2029_base": int(inc) if inc else prior.get("income_2029_base"),
        "income_2029_yield": yld,
    }
    json.dump(out, open(SNAP, "w"), indent=2)
    n = len(FELL_BACK)
    print(f"wrote model_snapshot.json from {out['source']} — "
          + ("all cells resolved from the model." if n == 0 else
             f"{n} cell(s) unresolved (#VALUE!/blank); kept seeded values for those. "
             "Open + recalc the model in Excel, then re-run to capture the base cases."))


if __name__ == "__main__":
    main()
