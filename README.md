# Gold-miner portfolio monitor

Static dashboard with an automated, privacy-preserving data pipeline. ISA + SIPP basis.

## Layout
```
index.html                 dashboard (reads data/data.json)
edit.html                  editor for judgment inputs (reads data/manual_inputs.json)
data/
  manual_inputs.json       hand-maintained judgment inputs (committed, anonymised)
  model_snapshot.json      valuation layer from the spreadsheet (committed, anonymised)
  data.json                generated, rendered by the dashboard (never hand-edit)
  holdings.local.json      tickers/shares/prices — GITIGNORED, local only
scraper/
  config.py                metric registry: themes, weights, thresholds, public tickers
  update_data.py           fetch prices + rates, auto-trailing, merge, score → data.json
  import_model.py          LOCAL: read portfolio_v21.xlsx → model_snapshot.json
.github/workflows/update.yml   scheduled scraper run + commit
```

## Three data sources merged into data.json
- **Auto-fetched (scraper):** gold spot, DXY, VIX, Brent, GDX, GDXJ, NDX + FRED rates; and the 24-month trailing gold price, computed as the **monthly average of daily closes over the last 24 completed months**.
- **Model (importer):** NPV £/share, scenario £m grid, 2029 income — pulled from the spreadsheet locally into `model_snapshot.json`.
- **Judgment (you, via editor):** jurisdiction score/signal, catalysts, actions, and the manual metrics (WGC, PBoC, ETF, COFER, GPR, deficit, COT, GVZ, Brent).

## Privacy
The public site and every committed file are anonymised: holdings show as **Africa / Asia** with **£ value + % only**. Tickers, share counts, per-share prices and jurisdiction notes never appear in the repo or the rendered site. Identifying data lives only in:
- `data/holdings.local.json` (gitignored), for local scraper runs, and
- the **HOLDINGS** GitHub Actions Secret, used by the cloud job.

### HOLDINGS secret
Settings → Secrets and variables → Actions → New repository secret. Name `HOLDINGS`, value:
```json
{"africa":{"ticker":"<AIM_TICKER>.L","shares":<COUNT>,"px_fallback":<PENCE>},
 "asia":{"ticker":"<AIM_TICKER>.L","shares":<COUNT>,"px_fallback":<PENCE>}}
```
The job reads it, fetches live prices, computes £ value, and publishes value + % under Africa / Asia. The count never reaches a committed file or the site.

## Updating
- **Prices / thesis / trailing:** automatic on the weekday schedule (or Actions → Run workflow).
- **Judgment inputs:** edit in `edit.html` → Download → commit `data/manual_inputs.json`.
- **Valuations (NPV/scenarios/income):** when you re-run the model, open + recalc it in Excel (so the live-gold base cases populate), then locally:
  ```
  pip install openpyxl
  python scraper/import_model.py /path/to/portfolio_v21.xlsx
  ```
  Commit the updated `data/model_snapshot.json`. Cells that read #VALUE!/blank are skipped and the previous value kept (the importer reports how many).

## Composite (keep reproducible)
16 scored metrics, weights sum to 100, signal ∈ {bull +1, base 0, bear −1}; composite = Σ weight·signal. Seed: bull = WGC (19) + spot/24m (6) + GDX/gold (3) = 28; bear = PBoC (7) → **+21 (Bullish)**.

## Keeping future edits compatible
`data.json` is the contract between scraper and dashboard. A new field must be added in the scraper output, the `index.html` reader, and — if hand-set — the editor + `manual_inputs.json`; a new scored metric goes in `config.py` (weights still sum to 100) with a seeded fallback signal. Never hand-edit `data.json`; never commit the `.xlsx` or `holdings.local.json`.
