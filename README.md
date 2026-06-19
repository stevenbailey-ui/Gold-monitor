# Gold-miner portfolio monitor (THX / MTL)

Static dashboard with an automated data pipeline. ISA + SIPP basis (GIA excluded).

## How it fits together

```
index.html          ← dashboard; reads data/data.json
edit.html           ← form editor; reads + writes data/manual_inputs.json
data/
  manual_inputs.json  ← hand-maintained judgment inputs (you edit this)
  data.json           ← generated; what the dashboard renders (never hand-edit)
scraper/
  config.py           ← metric registry: themes, weights, thresholds, tickers
  update_data.py      ← fetches prices/rates, merges manual inputs, scores, writes data.json
.github/workflows/
  update.yml          ← runs the scraper on a schedule and commits data.json
```

Flow: **you edit `manual_inputs.json` (via `edit.html`) → commit → the Action runs `update_data.py` → it fetches live prices + merges your inputs → writes `data/data.json` → the dashboard shows it.**

## Data layers

- **Auto-fetched (scraper):** gold spot, DXY, VIX, Brent, GDX, GDXJ, NDX, THX, MTL prices (Yahoo Finance, Stooq fallback); FRED rates DGS10 / DFII10 / T10YIE / DFEDTARU. These need no manual entry.
- **Manual (you):** share counts, NPV ranges, scenario £m grid, income, jurisdiction scores, 24m trailing gold, catalysts, actions, and the judgment metrics (WGC purchases, PBoC, ETF, COFER, GPR, deficit, COT, GVZ, Brent reading). Every metric also carries a `signal` used as a last-known-good fallback so the composite always reconciles even if a feed is down.

## Composite scoring (must stay reproducible)

16 scored metrics, weights sum to 100, each signal ∈ {bull +1, base 0, bear −1}; composite = Σ weight·signal (−100…+100). Six themes roll up for display. Seeded state: bull = WGC (19) + spot/24m (6) + GDX/gold (3) = 28; bear = PBoC (7); rest base → **composite +21 (Bullish)**. Verdict bands: ≥+30 Strongly bullish · +10…+30 Bullish · −10…+10 Balanced · −10…−30 Bearish · ≤−30 Strongly bearish.

## Run locally

```bash
python scraper/update_data.py          # writes data/data.json
python -m http.server 8000             # then open http://localhost:8000
```

Offline / no FRED key: every fetch falls back to the manual signal, and the run still completes and reconciles to the seeded composite.

## GitHub setup

1. Push this folder to a repo; enable **Pages** (deploy from the branch root).
2. Optional: add repo secret `FRED_API_KEY` (free from FRED) for live rate metrics. Without it, rate metrics use their manual fallback.
3. The workflow runs weekdays at 21:30 UTC and on the **Run workflow** button. It commits `data/data.json`; Pages redeploys automatically.

## Keeping future edits compatible

`data/data.json` is the contract between scraper and dashboard. If you add a field, add it in **all three** of: the scraper output (`update_data.py`), the dashboard reader (`index.html`), and — if it's hand-set — the editor (`edit.html`) and `manual_inputs.json`. New scored metric → add to `config.py.METRICS` (keep weights summing to 100) and seed a fallback `signal` in `manual_inputs.json`. Do not hand-edit `data.json`; it is regenerated every run.
