# Research Method

This repository studies QQQ volatility regimes from Yahoo Finance chart API data. Use the checked-in `raw_data/` files as the source of truth unless the user explicitly asks to refresh the market data.

## Calculation

- Use adjusted close prices.
- Compute daily log returns.
- Calculate 20-trading-day rolling realized volatility.
- Annualize rolling volatility with 252 trading days.
- Express volatility as a percentage.

## Regime Rules

- Low-volatility regimes are observations at or below the 25th percentile.
- High-volatility regimes are observations at or above the 75th percentile.
- Percentile thresholds are calculated within the selected sample window.
- Adjacent regime runs separated by gaps of up to three trading days are merged.
- Segment tables keep runs with at least 10 trading days.
- Chart labels emphasize longer runs, currently at least 30 trading days.

## Reproducibility Notes

- Main script: `scripts/qqq_volatility_study.py`.
- Default input: `raw_data/qqq_5y_yahoo_chart.json`.
- Default output directory: `outputs/`.
- Dependencies are listed in `requirements.txt`.
- Do not hand-edit generated CSV or PNG files; regenerate them from the script.

## Interpretation Notes

Compare each result to its own window. A volatility level can be high for the five-year sample while still ordinary in the full-history sample. The full-history QQQ distribution is heavily shaped by the dot-com unwind, the 2008 crisis, and the 2020 shock.
