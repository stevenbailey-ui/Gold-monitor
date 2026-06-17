# Gold portfolio monitor

End-of-day monitoring dashboard for a THX / MTL gold-miner portfolio. Distils the
portfolio model's Summary and Gold Thesis tabs into one readable screen: current
and 2029 portfolio value, 2029 income, the six-driver gold thesis composite, the
two holdings with editable share counts, a scenario range, a catalyst timeline and
an alerts feed.

Read-only with respect to the Excel model — it never writes back to the workbook.

## How it works (zero running cost)

```
GitHub Actions (daily cron)         GitHub Pages (static host)
  └─ scraper/update_data.py            └─ index.html  ← reads data/data.json
       fetches EOD prices + rates
       scores the composite
       commits data/data.json  ─────────────┘
```

- The scraper runs in CI where the network is open, so API keys live in GitHub
  Secrets and never reach the browser. No server, no proxy, no CORS problem.
- The front end is a single static file that reads the committed `data/data.json`.
- Everything stays inside free tiers: Actions minutes for one daily job, Pages for
  a static site. Data sources (FRED, Stooq, manual inputs) are free.

## Deploy (about 10 minutes)

1. Create a new GitHub repo and push this folder.
2. Get a free FRED API key: https://fredaccount.stlouisfed.org/apikeys
   Add it under **Settings → Secrets and variables → Actions → New secret**,
   named `FRED_API_KEY`.
3. Enable Pages: **Settings → Pages → Source: Deploy from a branch → main / root.**
   Your dashboard will be at `https://<you>.github.io/<repo>/`.
4. Run the job once: **Actions → Update EOD data → Run workflow.** It refreshes
   `data/data.json`; thereafter it runs automatically every weekday at 21:30 UTC.

Before the first run, the dashboard already works off the seeded `data/data.json`.
You can also just open `index.html` locally — it falls back to an embedded snapshot.

## Updating your data

| What | Where | Cadence |
|---|---|---|
| Share quantities | edit live in the dashboard (saved in your browser), or `data/holdings.json` to change the committed value | when you trade |
| Low-frequency / judgment metrics (WGC, PBoC, COFER, GPR, COT, GVZ, deficit, jurisdiction signals, catalysts, alerts) | `data/manual_inputs.json` | weekly–quarterly |
| Scenario grid + 2029 income | `data/scenarios.json` | when you rerun the Excel model |
| Composite weights / thresholds | `scraper/config.py` | as you recalibrate |

## Data sources

- **Automated (EOD):** gold spot + 24-month trailing average, DXY, VIX, Brent, GDX,
  GDXJ, NDX, THX.L, MTL.L via Stooq; 10Y nominal/real/breakeven, Fed funds, via FRED.
- **Manual:** the structural and judgment metrics above — surfaced by RNS/OFAC alerts
  but scored by you, exactly as the model's risk discipline intends.

## Composite scoring

Each metric resolves to bull (+1) / base (0) / bear (−1) against the bands in
`config.py`, weighted, summed to a −100…+100 composite and the five-band verdict —
the same logic as the Gold Thesis Dashboard. Every fetch degrades gracefully: an
unreachable source falls back to its last value, so the dashboard never breaks.

## Notes

- Prices for THX/MTL are in pence; current value = shares × pence ÷ 100.
- `data.json` carries a `fetch_notes` list; if any source fell back, the dashboard
  shows a small note so you know the figure is stale.
