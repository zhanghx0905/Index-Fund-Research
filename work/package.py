import pathlib,zipfile,json,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[1];O=ROOT/'outputs'
readme='''IC/IM rolling futures research, snapshot 2026-09-07

Start with outputs/回测报告.html (self-contained charts, opens offline).
Main results use previous-close decisions executed at next open, with 1 bp one-way costs.
Use open_*.csv for the primary results. Non-prefixed results are close-execution comparisons.
No actual forced-liquidation execution is simulated. Margin tables are fixed-rate stress scenarios.
The spot benchmark is a PRICE index and excludes dividends.

Reproduce from the included cleaned data:
  python -m pip install -r outputs/requirements.txt
  python work/backtest.py
  python work/extra_analysis.py
  python work/report.py

Run commands from the extracted package root. Network is not needed for these three steps.
Optional: edit work/prepare.py SRC and run it to reload the original source ZIPs and fetch spot data.
Original user ZIPs are not duplicated in this bundle; their SHA-256 hashes are in outputs/source_manifest.csv.
Raw Tencent responses are in work/sh000*.json.
prepare.py and the report narrative are dated research snapshots; update date cutoffs and narrative when extending data.

Primary files:
open_summary.csv - CAGR, volatility, Sharpe, drawdown, recovery
open_daily_backtests.csv - positions, P&L, costs, attribution, margin inputs
open_regression.csv - price-index beta, alpha and HAC confidence intervals
open_sensitivity.csv - leverage, transaction cost and roll timing
open_margin_sensitivity.csv - fixed-rate margin breach diagnostics
open_integer_accounts.csv - integer contracts and roll-only position resizing
open_annual_returns.csv / open_regime_analysis.csv / open_common_period.csv - period comparisons
open_hedged_diagnostic.csv - mathematical basis residual; NOT an executable market-neutral strategy
futures_clean.csv / spot_indices.csv - cleaned data and benchmarks
data_audit.json / validation.json - data and backtest checks

Rates and returns in CSV are decimal fractions. All futures prices are index points.
Futures multiplier is CNY 200/point. Capital in baseline is CNY 10,000,000 with fractional contracts.
Sharpe assumes 2% annual risk-free opportunity cost; baseline cash yield is zero.
The first date is pre-trade capital; positions begin on the following trading day.
'''
(O/'研究包说明.txt').write_text(readme,encoding='utf-8')
files=[p for p in O.iterdir() if p.is_file() and p.suffix not in ['.zip'] and p.name!='deliverable_manifest.json']
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(O/'deliverable_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(O/'IC_IM_回测研究包.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
 for p in O.iterdir():
  if p.is_file() and p.suffix!='.zip':z.write(p,'outputs/'+p.name)
 for name in ['prepare.py','backtest.py','extra_analysis.py','report.py','package.py']:
  p=ROOT/'work'/name;z.write(p,'work/'+name)
 for p in (ROOT/'work').glob('sh000*.json'):z.write(p,'work/'+p.name)
 z.writestr('README.txt',readme)
with zipfile.ZipFile(O/'IC_IM_回测研究包.zip') as z:
 assert z.testzip() is None
 print('ZIP verified',len(z.namelist()),'entries', (O/'IC_IM_回测研究包.zip').stat().st_size,'bytes')
