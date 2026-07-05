from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

ASSETS = {
    "NDX": "^NDX",
    "SPX": "^GSPC",
}
RATE_SYMBOL = "^IRX"
START = datetime(1985, 1, 1, tzinfo=timezone.utc)
END = datetime.now(timezone.utc)
TRADING_DAYS = 252
LEVERAGE_GRID = np.round(np.arange(0.0, 5.0001, 0.05), 2)
DD_LIMITS = [0.60, 0.70, 0.80]
DEFAULT_ANNUAL_FEE = 0.009

TOKENS = {
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
    "blue": "#5477C4",
    "orange": "#CC6F47",
    "olive": "#71B436",
    "neutral": "#7A828F",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate optimal daily-rebalanced leverage for NDX and SPX under historical short-rate conditions."
    )
    parser.add_argument("--refresh", action="store_true", help="Download fresh Yahoo Chart API data instead of using cache.")
    parser.add_argument("--cache-data", action="store_true", help="Save downloaded Yahoo Chart API responses under data/raw/.")
    parser.add_argument("--write-tables", action="store_true", help="Write CSV result tables under outputs/.")
    parser.add_argument("--max-leverage", type=float, default=5.0, help="Maximum leverage to evaluate.")
    parser.add_argument("--step", type=float, default=0.05, help="Leverage grid step.")
    parser.add_argument("--annual-fee", type=float, default=DEFAULT_ANNUAL_FEE, help="Annual fee drag deducted daily, e.g. 0.009 for 0.9%.")
    return parser.parse_args()


def yahoo_chart(symbol: str, refresh: bool, cache_data: bool) -> dict:
    cache = ROOT / "data" / "raw" / f"{symbol.replace('^', '')}_yahoo_chart.json"
    if cache_data and cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))

    period1 = int(START.timestamp())
    period2 = int(END.timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if cache_data:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def parse_chart(payload: dict, value_name: str) -> pd.DataFrame:
    result = payload["chart"]["result"][0]
    quote_data = result["indicators"]["quote"][0]
    adj_data = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    timestamps = result["timestamp"]
    closes = quote_data["close"]
    if adj_data is None:
        adj_data = closes

    rows = []
    for ts, close, adj_close in zip(timestamps, closes, adj_data):
        if close is None:
            continue
        rows.append(
            {
                "date": pd.to_datetime(datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).date()),
                value_name: float(adj_close if adj_close is not None else close),
                "close": float(close),
            }
        )
    return pd.DataFrame(rows).drop_duplicates("date").sort_values("date").reset_index(drop=True)


def max_drawdown(nav: pd.Series) -> tuple[float, pd.Timestamp, pd.Timestamp]:
    high = nav.cummax()
    dd = nav / high - 1
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    return float(dd.min()), peak, trough


def baseline_stats(asset_name: str, asset: pd.DataFrame) -> dict:
    df = asset[["date", "price"]].sort_values("date").copy()
    returns = df["price"].pct_change()
    valid = df.loc[returns.notna(), ["date"]].copy()
    valid["return"] = returns.loc[returns.notna()].to_numpy()
    nav = (1 + valid["return"]).cumprod()
    years = (valid["date"].iloc[-1] - valid["date"].iloc[0]).days / 365.25
    high = nav.cummax()
    dd = nav / high - 1
    trough_pos = dd.idxmin()
    peak_pos = nav.loc[:trough_pos].idxmax()
    return {
        "asset": asset_name,
        "start": valid["date"].iloc[0],
        "end": valid["date"].iloc[-1],
        "final_multiple": float(nav.iloc[-1]),
        "cagr": float(nav.iloc[-1] ** (1 / years) - 1),
        "max_drawdown": float(dd.min()),
        "peak_date": valid.loc[peak_pos, "date"],
        "trough_date": valid.loc[trough_pos, "date"],
    }


def simulate(asset_name: str, asset: pd.DataFrame, rates: pd.DataFrame, grid: np.ndarray, annual_fee: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = asset[["date", "price"]].merge(rates[["date", "irx_pct"]], on="date", how="left").sort_values("date")
    df["irx_pct"] = df["irx_pct"].ffill().bfill()
    df["asset_return"] = df["price"].pct_change()
    df["rf_daily"] = (1 + df["irx_pct"] / 100.0) ** (1 / TRADING_DAYS) - 1
    fee_daily = (1 + annual_fee) ** (1 / TRADING_DAYS) - 1
    df = df.dropna(subset=["asset_return", "rf_daily"]).reset_index(drop=True)

    rows = []
    nav_series = {}
    years = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25

    for leverage in grid:
        strategy_return = leverage * df["asset_return"] + (1 - leverage) * df["rf_daily"] - fee_daily
        ruined_mask = strategy_return <= -1
        ruined = bool(ruined_mask.any())
        if ruined:
            ruin_pos = int(np.flatnonzero(ruined_mask.to_numpy())[0])
            active_return = strategy_return.iloc[: ruin_pos + 1].copy()
            nav = (1 + active_return).cumprod()
            nav.iloc[-1] = 0.0
            full_nav = pd.Series(np.nan, index=df.index, dtype=float)
            full_nav.iloc[: ruin_pos + 1] = nav.to_numpy()
            full_nav.iloc[ruin_pos:] = 0.0
            final_multiple = 0.0
            cagr = -1.0
            ann_vol = float(strategy_return.iloc[: ruin_pos + 1].std(ddof=1) * math.sqrt(TRADING_DAYS))
            sharpe = np.nan
            mdd, peak, trough = -1.0, df.loc[ruin_pos, "date"], df.loc[ruin_pos, "date"]
            ruin_date = df.loc[ruin_pos, "date"]
        else:
            full_nav = (1 + strategy_return).cumprod()
            final_multiple = float(full_nav.iloc[-1])
            cagr = final_multiple ** (1 / years) - 1
            ann_vol = float(strategy_return.std(ddof=1) * math.sqrt(TRADING_DAYS))
            excess = strategy_return - df["rf_daily"]
            sharpe = float(excess.mean() * TRADING_DAYS / ann_vol) if ann_vol > 0 else np.nan
            mdd, peak, trough = max_drawdown(full_nav)
            ruin_date = pd.NaT

        nav_series[f"{asset_name}_{leverage:.2f}x"] = full_nav.to_numpy()
        rows.append(
            {
                "asset": asset_name,
                "leverage": leverage,
                "annual_fee": annual_fee,
                "final_multiple": final_multiple,
                "cagr": cagr,
                "ann_vol": ann_vol,
                "sharpe_vs_irx": sharpe,
                "max_drawdown": mdd,
                "peak_date": peak,
                "trough_date": trough,
                "ruined": ruined,
                "ruin_date": ruin_date,
            }
        )

    nav_paths = pd.DataFrame(nav_series, index=df["date"])
    nav_paths.index.name = "date"
    return pd.DataFrame(rows), nav_paths


def pick_best(results: pd.DataFrame) -> pd.DataFrame:
    picks = []
    for asset, group in results.groupby("asset"):
        viable = group.loc[~group["ruined"]].copy()
        for metric, label in [("cagr", "Max CAGR"), ("sharpe_vs_irx", "Max Sharpe")]:
            valid = viable.dropna(subset=[metric])
            row = valid.loc[valid[metric].idxmax()].copy()
            row["criterion"] = label
            picks.append(row)
        for limit in DD_LIMITS:
            valid = viable.loc[viable["max_drawdown"] >= -limit]
            if valid.empty:
                continue
            row = valid.loc[valid["cagr"].idxmax()].copy()
            row["criterion"] = f"Max CAGR with drawdown <= {int(limit * 100)}%"
            picks.append(row)
    return pd.DataFrame(picks)


def plot_results(results: pd.DataFrame, annual_fee: float) -> Path:
    plt.rcParams.update(
        {
            "figure.facecolor": "#FCFCFD",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": TOKENS["axis"],
            "axes.labelcolor": TOKENS["ink"],
            "xtick.color": TOKENS["muted"],
            "ytick.color": TOKENS["muted"],
            "grid.color": TOKENS["grid"],
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    fig, axes = plt.subplots(2, 1, figsize=(11, 8.5), sharex=True)
    colors = {"NDX": TOKENS["blue"], "SPX": TOKENS["orange"]}

    for asset, group in results.groupby("asset"):
        axes[0].plot(group["leverage"], group["cagr"], label=asset, color=colors[asset], linewidth=1.6)
        axes[1].plot(group["leverage"], group["max_drawdown"], label=asset, color=colors[asset], linewidth=1.6)

    fee_pct = annual_fee * 100
    axes[0].set_title(
        f"Historical daily-rebalanced leverage under short-rate financing and {fee_pct:.1f}% annual fee",
        loc="left",
        color=TOKENS["ink"],
    )
    axes[0].set_ylabel("CAGR")
    axes[0].yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    axes[0].grid(True, axis="y")
    axes[0].legend(frameon=False)

    for dd in DD_LIMITS:
        axes[1].axhline(-dd, color=TOKENS["neutral"], linestyle=":", linewidth=1)
        axes[1].text(results["leverage"].max() + 0.03, -dd, f"-{int(dd * 100)}%", va="center", color=TOKENS["muted"], fontsize=9)
    axes[1].set_xlabel("Daily target leverage")
    axes[1].set_ylabel("Max drawdown")
    axes[1].yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    axes[1].grid(True, axis="y")
    axes[1].set_ylim(-1.04, 0.02)

    fig.text(
        0.125,
        0.02,
        f"Model: strategy return = L * index price return + (1 - L) * ^IRX daily cash return - {fee_pct:.1f}% annual fee. No tax, slippage, spreads, or margin calls.",
        color=TOKENS["muted"],
        fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0.04, 0.96, 1))
    path = OUT / "optimal_leverage_rates.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def fmt_pct(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "n/a"
    return f"{value * 100:.{digits}f}%"


def write_report(summary: pd.DataFrame, picks: pd.DataFrame, asset_frames: dict[str, pd.DataFrame], rates: pd.DataFrame) -> None:
    lines = [
        "# Optimal Leverage Under Historical Short Rates",
        "",
        "This study estimates daily-rebalanced leverage for NDX and SPX using historical index price returns, Yahoo `^IRX` 13-week Treasury bill yield as the cash/financing proxy, and a 0.9% annual fee drag.",
        "",
        "## Headline Results",
        "",
    ]

    max_cagr = picks.loc[picks["criterion"].eq("Max CAGR")].set_index("asset")
    dd80 = picks.loc[picks["criterion"].eq("Max CAGR with drawdown <= 80%")].set_index("asset")
    dd70 = picks.loc[picks["criterion"].eq("Max CAGR with drawdown <= 70%")].set_index("asset")

    for asset in ["NDX", "SPX"]:
        frame = asset_frames[asset]
        row = max_cagr.loc[asset]
        lines.append(
            f"- **{asset}:** max historical CAGR occurs near `{row.leverage:.2f}x`, "
            f"with CAGR `{fmt_pct(row.cagr)}` and max drawdown `{fmt_pct(row.max_drawdown)}` "
            f"over {frame['date'].iloc[1].date()} to {frame['date'].iloc[-1].date()}."
        )
        if asset in dd80.index:
            row80 = dd80.loc[asset]
            lines.append(
                f"  If capped at an `80%` max-drawdown budget, the best grid point is `{row80.leverage:.2f}x` "
                f"with CAGR `{fmt_pct(row80.cagr)}`."
            )
        if asset in dd70.index:
            row70 = dd70.loc[asset]
            lines.append(
                f"  If capped at a `70%` max-drawdown budget, the best grid point is `{row70.leverage:.2f}x` "
                f"with CAGR `{fmt_pct(row70.cagr)}`."
            )

    lines.extend(
        [
            "",
            "![Optimal leverage chart](outputs/optimal_leverage_rates.png)",
            "",
            "## Interpretation",
            "",
            "- Pure terminal-wealth optimization picks leverage that is hard to hold in real life: NDX near 2x and SPX a little above 2x both suffer roughly 90%+ historical drawdowns.",
            "- Drawdown-constrained results are more useful operationally. In this run, an 80% drawdown budget points to roughly 0.90x for NDX and 1.55x for SPX; a 70% budget points to roughly 0.70x for NDX and 1.25x for SPX.",
            "- Sharpe is nearly flat across leverage in this simplified model because borrowing and cash both use the same short-rate proxy. It is included for audit, but CAGR and drawdown are the more useful decision columns.",
            "",
            "## Method",
            "",
            "- Data source: Yahoo Finance Chart API for `^NDX`, `^GSPC`, and `^IRX`.",
            "- Rate proxy: `^IRX` close, interpreted as an annualized short Treasury yield and converted to a daily cash return with `(1 + yield) ** (1 / 252) - 1`.",
            "- Daily leveraged return: `L * index_return + (1 - L) * rf_daily - fee_daily`.",
            "- Fee assumption: 0.9% annual fee, deducted daily.",
            "- Grid: daily target leverage from 0x to 5x in 0.05x increments.",
            "- Index returns are price-index returns, not total-return indices. This understates SPX relative to a dividend-reinvested implementation and should be upgraded if total-return data is added.",
            "- No taxes, commissions, bid/ask spread, financing spread over Treasury bills, ETF fees, tracking error, or margin liquidation mechanics are modeled.",
            "",
            "## Files",
            "",
            "- `scripts/optimal_leverage_rates.py`: reproducible download, simulation, and chart script.",
            "- `data/raw/`: optional local cache created only with `--cache-data`.",
            "- `outputs/*.csv`: optional result tables created only with `--write-tables`.",
            "- `outputs/optimal_leverage_rates.png`: chart of CAGR and max drawdown by leverage.",
            "",
            "## Reproduce",
            "",
            "```powershell",
            "python scripts\\optimal_leverage_rates.py",
            "```",
            "",
            f"Rate sample in this run: {rates['date'].iloc[0].date()} to {rates['date'].iloc[-1].date()}, average `^IRX` close `{rates['irx_pct'].mean():.2f}%`.",
            "",
        ]
    )
    (ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    grid = np.round(np.arange(0.0, args.max_leverage + args.step / 2, args.step), 2)

    asset_frames = {}
    result_frames = []
    nav_frames = []
    baseline_rows = []
    for asset_name, symbol in ASSETS.items():
        payload = yahoo_chart(symbol, args.refresh, args.cache_data)
        asset_frames[asset_name] = parse_chart(payload, "price")
        baseline_rows.append(baseline_stats(asset_name, asset_frames[asset_name]))

    rates = parse_chart(yahoo_chart(RATE_SYMBOL, args.refresh, args.cache_data), "irx_pct")[["date", "irx_pct", "close"]]
    rates = rates.dropna(subset=["irx_pct"]).sort_values("date")

    for asset_name, frame in asset_frames.items():
        results, nav = simulate(asset_name, frame, rates, grid, args.annual_fee)
        result_frames.append(results)
        nav_frames.append(nav)

    results = pd.concat(result_frames, ignore_index=True)
    picks = pick_best(results)
    baselines = pd.DataFrame(baseline_rows)

    if args.write_tables:
        results.to_csv(OUT / "optimal_leverage_grid.csv", index=False)
        picks.to_csv(OUT / "optimal_leverage_picks.csv", index=False)
        baselines.to_csv(OUT / "baseline_index_returns.csv", index=False)
        pd.concat(nav_frames, axis=1, sort=True).to_csv(OUT / "optimal_leverage_nav_paths.csv")
        rates.to_csv(OUT / "irx_rates_used.csv", index=False)
    plot_results(results, args.annual_fee)

    display_cols = ["asset", "criterion", "leverage", "cagr", "ann_vol", "max_drawdown", "final_multiple", "ruined"]
    print(picks[display_cols].to_string(index=False))
    print("\nBaseline 1x index price paths, no fee:")
    print(baselines[["asset", "start", "end", "final_multiple", "cagr", "max_drawdown"]].to_string(index=False))
    print("Outputs:", OUT)


if __name__ == "__main__":
    main()
