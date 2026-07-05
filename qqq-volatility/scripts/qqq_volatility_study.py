import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = ROOT / "raw_data"
OUTPUTS_DIR = ROOT / "outputs"
DEFAULT_INPUT = RAW_DATA_DIR / "qqq_5y_yahoo_chart.json"

WINDOW = 20
MIN_SEGMENT_DAYS = 10
DISPLAY_SEGMENT_DAYS = 30
MERGE_GAP_DAYS = 3
TRADING_DAYS = 252

TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
}

BLUE = {"xlight": "#EAF1FE", "light": "#CEDFFE", "base": "#A3BEFA", "mid": "#5477C4", "dark": "#2E4780"}
GOLD = {"xlight": "#FFF4C2", "light": "#FFEA8F", "base": "#FFE15B", "mid": "#B8A037", "dark": "#736422"}
ORANGE = {"xlight": "#FFEDDE", "light": "#FFBDA1", "base": "#F0986E", "mid": "#CC6F47", "dark": "#804126"}
OLIVE = {"xlight": "#D8ECBD", "light": "#BEEB96", "base": "#A3D576", "mid": "#71B436", "dark": "#386411"}
NEUTRAL = {"xlight": "#F4F5F7", "light": "#E2E5EA", "base": "#C5CAD3", "mid": "#7A828F", "dark": "#464C55"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate and chart QQQ trailing volatility regimes.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Yahoo Finance chart JSON file.")
    parser.add_argument("--output-dir", default=str(OUTPUTS_DIR), help="Directory for generated CSV and PNG outputs.")
    parser.add_argument("--prefix", default="qqq_5y", help="Output filename prefix.")
    parser.add_argument("--scope", default="the last five years", help="Human-readable title scope.")
    parser.add_argument("--symbol", default="QQQ", help="Yahoo symbol to download when --input is unavailable.")
    parser.add_argument("--start", default="1999-03-10", help="Download start date when --input is unavailable.")
    parser.add_argument("--end", default=None, help="Download end date when --input is unavailable; defaults to now.")
    parser.add_argument("--cache-data", action="store_true", help="Save downloaded Yahoo Chart API response to --input.")
    parser.add_argument("--write-tables", action="store_true", help="Write daily and segment CSV outputs.")
    return parser.parse_args()


def fetch_chart(symbol: str, start: str, end: str | None) -> dict:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime.now(timezone.utc)
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        f"?period1={int(start_dt.timestamp())}&period2={int(end_dt.timestamp())}"
        "&interval=1d&events=history&includeAdjustedClose=true"
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def load_prices(input_path: Path, symbol: str, start: str, end: str | None, cache_data: bool) -> pd.DataFrame:
    if input_path.exists():
        data = json.loads(input_path.read_text(encoding="utf-8"))
    else:
        data = fetch_chart(symbol, start, end)
        if cache_data:
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = data["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"]["adjclose"][0]["adjclose"]
    timestamps = result["timestamp"]

    rows = []
    for ts, adj, close, volume in zip(timestamps, adjclose, quote["close"], quote["volume"]):
        if adj is None or close is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).date(),
                "adj_close": float(adj),
                "close": float(close),
                "volume": int(volume) if volume is not None else np.nan,
            }
        )

    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    df["log_return"] = np.log(df["adj_close"] / df["adj_close"].shift(1))
    df["vol20"] = df["log_return"].rolling(WINDOW).std() * math.sqrt(TRADING_DAYS)
    df["vol20_pct"] = df["vol20"] * 100
    df["price_index"] = df["adj_close"] / df["adj_close"].iloc[0] * 100
    return df


def make_segments(df: pd.DataFrame, label: str, mask: pd.Series, min_days: int, merge_gap: int) -> list[dict]:
    valid = df.loc[df["vol20"].notna(), ["date", "vol20", "vol20_pct"]].copy()
    valid["flag"] = mask.loc[valid.index].to_numpy()

    runs = []
    current = []
    for _, row in valid.iterrows():
        if row["flag"]:
            current.append(row)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    merged = []
    for run in runs:
        if not merged:
            merged.append(run)
            continue
        prev = merged[-1]
        gap = valid.index[valid["date"].eq(run[0]["date"])][0] - valid.index[valid["date"].eq(prev[-1]["date"])][0] - 1
        if gap <= merge_gap:
            merged[-1] = prev + run
        else:
            merged.append(run)

    segments = []
    for run in merged:
        if len(run) < min_days:
            continue
        vols = np.array([r["vol20_pct"] for r in run])
        segments.append(
            {
                "regime": label,
                "start": run[0]["date"].date().isoformat(),
                "end": run[-1]["date"].date().isoformat(),
                "trading_days": len(run),
                "avg_vol_pct": round(float(vols.mean()), 1),
                "min_vol_pct": round(float(vols.min()), 1),
                "max_vol_pct": round(float(vols.max()), 1),
            }
        )
    return segments


def add_segment_shading(ax, segments: list[dict]) -> None:
    for seg in segments:
        start = pd.to_datetime(seg["start"])
        end = pd.to_datetime(seg["end"])
        if seg["regime"] == "High vol":
            color = ORANGE["xlight"]
            alpha = 0.78
        else:
            color = OLIVE["xlight"]
            alpha = 0.72
        ax.axvspan(start, end, color=color, alpha=alpha, lw=0, zorder=0)


def annotate_segment(ax, seg: dict, y: float, dy: float) -> None:
    start = pd.to_datetime(seg["start"])
    end = pd.to_datetime(seg["end"])
    mid = start + (end - start) / 2
    color = ORANGE["dark"] if seg["regime"] == "High vol" else OLIVE["dark"]
    text = f"{seg['start'][2:7]} to {seg['end'][2:7]}\n{seg['avg_vol_pct']:.1f}% avg"
    ax.text(
        mid,
        y + dy,
        text,
        ha="center",
        va="bottom" if dy >= 0 else "top",
        fontsize=8.5,
        color=color,
        linespacing=1.15,
        path_effects=[pe.withStroke(linewidth=3, foreground=TOKENS["panel"])],
    )


def style_axis(ax) -> None:
    ax.set_facecolor(TOKENS["panel"])
    ax.grid(True, color=TOKENS["grid"], linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(TOKENS["axis"])
    ax.spines["bottom"].set_color(TOKENS["axis"])
    ax.tick_params(colors=TOKENS["muted"], labelsize=9, length=0)
    ax.yaxis.label.set_color(TOKENS["ink"])
    ax.xaxis.label.set_color(TOKENS["ink"])


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    daily_csv = output_dir / f"{args.prefix}_volatility_daily.csv"
    segments_csv = output_dir / f"{args.prefix}_volatility_segments.csv"
    png = output_dir / f"{args.prefix}_volatility_study.png"

    df = load_prices(input_path, args.symbol, args.start, args.end, args.cache_data)
    valid = df.loc[df["vol20"].notna()].copy()
    q10, q25, q50, q75, q90 = valid["vol20_pct"].quantile([0.10, 0.25, 0.50, 0.75, 0.90])

    high_segments = make_segments(df, "High vol", df["vol20_pct"] >= q75, MIN_SEGMENT_DAYS, MERGE_GAP_DAYS)
    low_segments = make_segments(df, "Low vol", df["vol20_pct"] <= q25, MIN_SEGMENT_DAYS, MERGE_GAP_DAYS)
    segments = sorted(high_segments + low_segments, key=lambda x: x["start"])

    if args.write_tables:
        daily_out = df.copy()
        daily_out["date"] = daily_out["date"].dt.date.astype(str)
        daily_out.to_csv(daily_csv, index=False)
        pd.DataFrame(segments).to_csv(segments_csv, index=False)

    plt.rcParams.update(
        {
            "figure.facecolor": TOKENS["surface"],
            "savefig.facecolor": TOKENS["surface"],
            "axes.edgecolor": TOKENS["axis"],
            "axes.labelcolor": TOKENS["ink"],
            "font.family": "DejaVu Sans",
            "font.size": 10,
        }
    )

    fig = plt.figure(figsize=(16, 9.5), dpi=160)
    gs = fig.add_gridspec(2, 1, height_ratios=[4.4, 1.35], hspace=0.11)
    ax = fig.add_subplot(gs[0, 0])
    ax_price = fig.add_subplot(gs[1, 0], sharex=ax)

    display_segments = [seg for seg in segments if seg["trading_days"] >= DISPLAY_SEGMENT_DAYS]

    for target_ax in (ax, ax_price):
        style_axis(target_ax)
        add_segment_shading(target_ax, display_segments)

    ax.axhspan(q25, q75, color=BLUE["xlight"], alpha=0.52, lw=0, zorder=0.1)
    ax.axhspan(q75, max(valid["vol20_pct"].max() * 1.08, q90), color=ORANGE["xlight"], alpha=0.36, lw=0, zorder=0.1)
    ax.axhspan(0, q25, color=OLIVE["xlight"], alpha=0.36, lw=0, zorder=0.1)

    ax.plot(valid["date"], valid["vol20_pct"], color=BLUE["dark"], linewidth=1.45, zorder=3, label="20d trailing volatility")
    ax.plot(
        valid["date"],
        valid["vol20_pct"].rolling(10, min_periods=1).mean(),
        color=BLUE["mid"],
        linewidth=2.6,
        alpha=0.55,
        zorder=2.8,
        label="10d smoothed path",
    )

    for value, label, color, linestyle in [
        (q10, "P10", OLIVE["dark"], ":"),
        (q25, "P25 low-vol threshold", OLIVE["dark"], "--"),
        (q50, "Median", NEUTRAL["dark"], ":"),
        (q75, "P75 high-vol threshold", ORANGE["dark"], "--"),
        (q90, "P90", ORANGE["dark"], ":"),
    ]:
        ax.axhline(value, color=color, linestyle=linestyle, linewidth=1.05, alpha=0.95, zorder=2)
        ax.text(
            valid["date"].iloc[-1] + pd.Timedelta(days=18),
            value,
            f"{label} {value:.1f}%",
            va="center",
            ha="left",
            fontsize=8.3,
            color=color,
        )

    high_y = min(valid["vol20_pct"].max() * 0.93, q90 + 9)
    low_y = max(valid["vol20_pct"].min() * 1.12, q10 - 1)
    top_high = sorted(
        [seg for seg in high_segments if seg["trading_days"] >= DISPLAY_SEGMENT_DAYS],
        key=lambda s: (s["trading_days"], s["avg_vol_pct"]),
        reverse=True,
    )[:3]
    top_low = sorted(
        [seg for seg in low_segments if seg["trading_days"] >= DISPLAY_SEGMENT_DAYS],
        key=lambda s: (s["trading_days"], -s["avg_vol_pct"]),
        reverse=True,
    )[:4]
    for i, seg in enumerate(top_high):
        annotate_segment(ax, seg, high_y - i * 3.2, 0)
    for i, seg in enumerate(top_low):
        annotate_segment(ax, seg, low_y + (i % 2) * 1.9, -0.9)

    latest = valid.iloc[-1]
    ax.scatter([latest["date"]], [latest["vol20_pct"]], s=46, color=ORANGE["base"], edgecolor=ORANGE["dark"], zorder=4)
    ax.annotate(
        f"Latest {latest['vol20_pct']:.1f}%",
        xy=(latest["date"], latest["vol20_pct"]),
        xytext=(-88, 24),
        textcoords="offset points",
        fontsize=9,
        color=ORANGE["dark"],
        arrowprops={"arrowstyle": "-", "color": ORANGE["dark"], "lw": 1.0},
        path_effects=[pe.withStroke(linewidth=3, foreground=TOKENS["panel"])],
    )

    ax.set_ylim(0, max(valid["vol20_pct"].max() * 1.13, 45))
    ax.set_ylabel("Annualized volatility")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100, decimals=0))
    ax.tick_params(axis="x", labelbottom=False)

    ax_price.plot(df["date"], df["price_index"], color=NEUTRAL["dark"], linewidth=1.25)
    ax_price.fill_between(df["date"], 100, df["price_index"], color=NEUTRAL["light"], alpha=0.42)
    ax_price.axhline(100, color=TOKENS["ink"], linewidth=0.9, linestyle=":")
    ax_price.set_ylabel("QQQ index")
    ax_price.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    years = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25
    if years > 10:
        locator = mdates.YearLocator(base=2)
        ax_price.xaxis.set_major_locator(locator)
        ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    else:
        locator = mdates.MonthLocator(interval=6)
        ax_price.xaxis.set_major_locator(locator)
        ax_price.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    title = f"QQQ volatility regimes over {args.scope}"
    subtitle = (
        f"20-trading-day trailing annualized volatility from adjusted closes, "
        f"{df['date'].iloc[0].date()} to {df['date'].iloc[-1].date()}; "
        f"low/high regimes use P25/P75 thresholds; chart highlights runs of at least {DISPLAY_SEGMENT_DAYS} trading days."
    )
    fig.text(0.075, 0.965, title, fontsize=17, fontweight="semibold", color=TOKENS["ink"], ha="left", va="top")
    fig.text(0.075, 0.928, subtitle, fontsize=9.5, color=TOKENS["muted"], ha="left", va="top")

    handles = [
        Patch(facecolor=OLIVE["xlight"], edgecolor=OLIVE["dark"], label="Low-vol regime"),
        Patch(facecolor=ORANGE["xlight"], edgecolor=ORANGE["dark"], label="High-vol regime"),
        Patch(facecolor=BLUE["xlight"], edgecolor=BLUE["mid"], label="Middle 50% band"),
    ]
    line_handles, line_labels = ax.get_legend_handles_labels()
    ax.legend(
        handles=line_handles + handles,
        loc="upper left",
        bbox_to_anchor=(0, 1.055),
        ncol=5,
        frameon=False,
        fontsize=8.5,
        labelcolor=TOKENS["ink"],
        handlelength=2.2,
        columnspacing=1.25,
    )

    stats = (
        f"Latest: {latest['vol20_pct']:.1f}%\n"
        f"Median: {q50:.1f}%\n"
        f"Low threshold: {q25:.1f}%\n"
        f"High threshold: {q75:.1f}%\n"
        f"Max: {valid['vol20_pct'].max():.1f}%"
    )
    ax.text(
        0.018,
        0.93,
        stats,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        color=TOKENS["ink"],
        bbox={"boxstyle": "round,pad=0.45,rounding_size=0.03", "facecolor": TOKENS["panel"], "edgecolor": TOKENS["axis"]},
    )

    source = "Source: Yahoo Finance chart API. Calculations use adjusted close log returns."
    fig.text(0.075, 0.035, source, fontsize=8.2, color=TOKENS["muted"], ha="left")
    fig.subplots_adjust(left=0.075, right=0.89, top=0.855, bottom=0.08)
    fig.savefig(png, dpi=160)
    plt.close(fig)

    print(f"rows={len(df)} valid_vol_rows={len(valid)}")
    print(f"date_start={df['date'].iloc[0].date()} date_end={df['date'].iloc[-1].date()}")
    print(f"latest_vol_pct={latest['vol20_pct']:.2f} latest_close={df['close'].iloc[-1]:.2f}")
    print(f"q10={q10:.2f} q25={q25:.2f} median={q50:.2f} q75={q75:.2f} q90={q90:.2f}")
    print("segments")
    for seg in segments:
        print(seg)
    print(png)


if __name__ == "__main__":
    main()
