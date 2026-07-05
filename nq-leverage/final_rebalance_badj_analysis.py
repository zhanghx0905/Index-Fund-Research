from pathlib import Path
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INTERIM = DATA / "interim"
OUTPUT = DATA / "output"
CHARTS = ROOT / "charts_final"
INTERIM.mkdir(parents=True, exist_ok=True)
OUTPUT.mkdir(parents=True, exist_ok=True)
CHARTS.mkdir(parents=True, exist_ok=True)

TARGET_LEVERAGE = 3.0
MNQ_MULTIPLIER = 2.0
CASH_WEIGHT_MAIN = 0.70

TOKENS = {
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
    "blue": "#5477C4",
    "orange": "#CC6F47",
    "olive": "#71B436",
    "gold": "#B8A037",
}


def is_rebalance_day(dates: pd.DatetimeIndex, i: int, rule: str) -> bool:
    if i == 0:
        return True
    if rule == "Daily":
        return True
    if i == len(dates) - 1:
        return True
    today = dates[i]
    tomorrow = dates[i + 1]
    if rule == "Weekly":
        return today.isocalendar().week != tomorrow.isocalendar().week or today.year != tomorrow.year
    if rule == "Monthly":
        return today.month != tomorrow.month or today.year != tomorrow.year
    raise ValueError(rule)


def simulate(source: pd.DataFrame, rule: str, cash_weight: float) -> pd.DataFrame:
    dates = pd.DatetimeIndex(source.index)
    equity = 1.0
    contracts = 0.0
    rows = []

    for i, date in enumerate(dates):
        row = source.loc[date]
        if i > 0:
            # Fractional MNQ equivalent. PnL uses B-ADJ point delta, not raw pct change.
            equity += contracts * MNQ_MULTIPLIER * row["badj_close_delta"]
            equity += cash_weight * equity * row["BIL_ret"]

        pre_lev = contracts * MNQ_MULTIPLIER * row["unadj_close"] / equity if equity > 0 else float("inf")
        rebalanced = is_rebalance_day(dates, i, rule)
        if rebalanced and equity > 0:
            contracts = TARGET_LEVERAGE * equity / (MNQ_MULTIPLIER * row["unadj_close"])
        post_lev = contracts * MNQ_MULTIPLIER * row["unadj_close"] / equity if equity > 0 else float("inf")

        rows.append(
            {
                "date": date,
                "equity": equity,
                "pre_rebalance_leverage": pre_lev,
                "post_rebalance_leverage": post_lev,
                "contracts_fractional": contracts,
                "rebalanced": rebalanced,
            }
        )
    return pd.DataFrame(rows).set_index("date")


def max_drawdown(nav: pd.Series) -> float:
    return (nav / nav.cummax() - 1).min()


def calc_stats(rule: str, path: pd.DataFrame) -> dict:
    equity = path["equity"]
    daily = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cal = (1 + daily).groupby(daily.index.year).prod() - 1
    leverage = path["pre_rebalance_leverage"].iloc[1:]
    return {
        "rule": rule,
        "final_multiple": equity.iloc[-1],
        "cagr": equity.iloc[-1] ** (1 / years) - 1,
        "ann_vol": daily.std(ddof=1) * math.sqrt(252),
        "max_drawdown": max_drawdown(equity),
        "worst_calendar_year": cal.min(),
        "worst_year": int(cal.idxmin()),
        "pre_lev_min": leverage.min(),
        "pre_lev_mean": leverage.mean(),
        "pre_lev_max": leverage.max(),
        "rebalance_count": int(path["rebalanced"].sum()),
        "rebalances_per_year": path["rebalanced"].sum() / years,
    }


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def mult(x: float) -> str:
    return f"{x:.2f}x"


def set_theme():
    plt.rcParams.update(
        {
            "figure.facecolor": "#FCFCFD",
            "axes.facecolor": "#FFFFFF",
            "axes.edgecolor": TOKENS["axis"],
            "axes.labelcolor": TOKENS["ink"],
            "xtick.color": TOKENS["muted"],
            "ytick.color": TOKENS["muted"],
            "grid.color": TOKENS["grid"],
            "grid.linewidth": 0.8,
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def add_header(fig, ax, title: str, subtitle: str):
    left = ax.get_position().x0
    fig.text(left, 0.975, title, ha="left", va="top", fontsize=13, fontweight="semibold", color=TOKENS["ink"])
    fig.text(left, 0.925, subtitle, ha="left", va="top", fontsize=9, color=TOKENS["muted"])
    fig.subplots_adjust(top=0.84)


def plot_paths(nav: pd.DataFrame) -> Path:
    set_theme()
    fig, ax = plt.subplots(figsize=(10.5, 6))
    for col, color, style in [
        ("TQQQ", TOKENS["blue"], "-"),
        ("Daily", TOKENS["orange"], "-"),
        ("Weekly", TOKENS["olive"], "--"),
        ("Monthly", TOKENS["gold"], ":"),
    ]:
        ax.plot(nav.index, nav[col], label=col, color=color, linestyle=style, linewidth=1.25)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}x" if y >= 1 else f"{y:.1f}x"))
    ax.set_ylabel("Growth of $1, log scale")
    ax.grid(True, axis="y")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False, ncol=4)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    add_header(fig, ax, "Daily, weekly, and monthly rebalancing", "Correct B-ADJ point-PnL model, 70% BIL cash sleeve.")
    path = CHARTS / "rebalance_growth_paths.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_leverage(paths: dict[str, pd.DataFrame]) -> Path:
    set_theme()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    for rule, color in [("Daily", TOKENS["orange"]), ("Weekly", TOKENS["olive"]), ("Monthly", TOKENS["gold"])]:
        path = paths[rule].iloc[1:]
        ax.plot(path.index, path["pre_rebalance_leverage"], label=rule, color=color, linewidth=1.1)
    ax.axhline(3, color=TOKENS["muted"], linestyle=":", linewidth=1)
    ax.set_ylabel("Pre-rebalance leverage")
    ax.grid(True, axis="y")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False, ncol=3)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    add_header(fig, ax, "Leverage drift before rebalance", "Weekly/monthly rules allow leverage to drift between scheduled rebalance dates.")
    path = CHARTS / "rebalance_leverage_drift.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def html_table(df: pd.DataFrame) -> str:
    rows = ["<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr></thead><tbody>"]
    for _, row in df.iterrows():
        rows.append("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>")
    rows.append("</tbody></table>")
    return "\n".join(rows)


def build_report(summary: pd.DataFrame, nav: pd.DataFrame):
    daily = summary.loc["Daily"]
    weekly = summary.loc["Weekly"]
    monthly = summary.loc["Monthly"]
    tqqq_final = nav["TQQQ"].iloc[-1]
    table = pd.DataFrame(
        {
            "Metric": ["Final multiple", "CAGR", "Annualized vol", "Max drawdown", "Worst year", "Leverage range", "Rebalances / year"],
            "Daily": [
                mult(daily.final_multiple),
                pct(daily.cagr),
                pct(daily.ann_vol),
                pct(daily.max_drawdown),
                f"{daily.worst_year}: {pct(daily.worst_calendar_year)}",
                f"{daily.pre_lev_min:.2f}x - {daily.pre_lev_max:.2f}x",
                f"{daily.rebalances_per_year:.1f}",
            ],
            "Weekly": [
                mult(weekly.final_multiple),
                pct(weekly.cagr),
                pct(weekly.ann_vol),
                pct(weekly.max_drawdown),
                f"{weekly.worst_year}: {pct(weekly.worst_calendar_year)}",
                f"{weekly.pre_lev_min:.2f}x - {weekly.pre_lev_max:.2f}x",
                f"{weekly.rebalances_per_year:.1f}",
            ],
            "Monthly": [
                mult(monthly.final_multiple),
                pct(monthly.cagr),
                pct(monthly.ann_vol),
                pct(monthly.max_drawdown),
                f"{monthly.worst_year}: {pct(monthly.worst_calendar_year)}",
                f"{monthly.pre_lev_min:.2f}x - {monthly.pre_lev_max:.2f}x",
                f"{monthly.rebalances_per_year:.1f}",
            ],
        }
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MNQ 3x 再平衡频率比较 - B-ADJ 版</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; color:#1f2430; background:#fbfcfe; line-height:1.58; }}
    main {{ max-width:1080px; margin:0 auto; padding:36px 22px 56px; }}
    h1 {{ font-size:30px; margin:0 0 20px; line-height:1.18; }}
    h2 {{ font-size:20px; margin:32px 0 12px; }}
    p, li {{ font-size:15px; }}
    .summary {{ border-left:4px solid #cc6f47; padding:4px 0 4px 16px; margin-bottom:20px; }}
    .summary p {{ margin:8px 0; }}
    figure {{ margin:20px 0 26px; background:#fff; border:1px solid #e3e7ef; border-radius:8px; padding:12px; }}
    figure img {{ width:100%; height:auto; display:block; }}
    figcaption {{ color:#5f6675; font-size:13px; margin-top:8px; }}
    table {{ width:100%; border-collapse:collapse; margin:14px 0 22px; background:#fff; border:1px solid #e3e7ef; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid #e3e7ef; text-align:right; font-size:14px; }}
    th:first-child,td:first-child {{ text-align:left; }}
    th {{ background:#f5f7fb; color:#5f6675; }}
  </style>
</head>
<body>
<main>
  <h1>MNQ 3x 再平衡频率比较 - B-ADJ 版</h1>
  <h2>Executive Summary</h2>
  <div class="summary">
    <p><strong>固定频率里，周平衡是更稳的折中。</strong>共同样本为 {nav.index[0].date()} 到 {nav.index[-1].date()}。日平衡最终 {mult(daily.final_multiple)}，周平衡 {mult(weekly.final_multiple)}，月平衡 {mult(monthly.final_multiple)}，TQQQ 为 {mult(tqqq_final)}。</p>
    <p><strong>月平衡历史收益最高，但不是免费收益。</strong>月平衡的调仓前杠杆最高到 {monthly.pre_lev_max:.2f}x，显著高于周平衡的 {weekly.pre_lev_max:.2f}x；它是在趋势上涨阶段多吃了漂移杠杆，代价是保证金压力和路径风险更高。</p>
    <p><strong>日平衡最接近“产品化 3x”，但操作最多且波动损耗更完整。</strong>真实账户如果不想每天调仓，周平衡或“每周检查 + 杠杆带宽触发”更合理。</p>
  </div>
  <h2>结果汇总</h2>
  {html_table(table)}
  <h2>净值路径</h2>
  <figure><img src="charts_final/rebalance_growth_paths.png" alt="Rebalance growth paths"><figcaption>MNQ 规则均使用 B-ADJ 点数 PnL，并假设 70% BIL 现金收益。</figcaption></figure>
  <h2>杠杆漂移</h2>
  <figure><img src="charts_final/rebalance_leverage_drift.png" alt="Leverage drift"><figcaption>调仓前杠杆越高，越可能在真实账户里带来保证金压力和被迫减仓。</figcaption></figure>
  <h2>实操结论</h2>
  <ul>
    <li>如果必须选固定频率：优先选周平衡。</li>
    <li>如果追求最高历史收益：月平衡更高，但要接受更大的杠杆漂移。</li>
    <li>如果追求贴近 TQQQ 的每日 3x 产品路径：日平衡最干净，但交易频率过高。</li>
    <li>对 140k 这类账户，周平衡更适合实际执行；月平衡需要明确上限，比如调仓前杠杆超过 3.5x 或 4.0x 就提前降回 3x。</li>
  </ul>
</main>
</body>
</html>"""
    (ROOT / "report_rebalance_badj_final.html").write_text(html, encoding="utf-8")


def main():
    model = pd.read_csv(INTERIM / "tqqq_mnq_badj_daily_model.csv", parse_dates=["date"]).set_index("date").sort_index()
    model = model.dropna(subset=["badj_close_delta", "unadj_close", "BIL"])
    model["BIL_ret"] = model["BIL"]

    tqqq_nav = (1 + model["TQQQ"]).cumprod()
    paths = {}
    no_cash_paths = {}
    for rule in ["Daily", "Weekly", "Monthly"]:
        paths[rule] = simulate(model, rule, CASH_WEIGHT_MAIN)
        no_cash_paths[rule] = simulate(model, rule, 0.0)

    nav = pd.DataFrame(index=model.index)
    nav["TQQQ"] = tqqq_nav
    for rule, path in paths.items():
        nav[rule] = path["equity"]

    no_cash_nav = pd.DataFrame({rule: path["equity"] for rule, path in no_cash_paths.items()})
    summary = pd.DataFrame([calc_stats(rule, paths[rule]) for rule in ["Daily", "Weekly", "Monthly"]]).set_index("rule")
    no_cash_summary = pd.DataFrame([calc_stats(rule, no_cash_paths[rule]) for rule in ["Daily", "Weekly", "Monthly"]]).set_index("rule")

    nav.to_csv(OUTPUT / "tqqq_mnq_rebalance_nav_paths.csv")
    no_cash_nav.to_csv(OUTPUT / "tqqq_mnq_rebalance_nav_paths_no_cash.csv")
    summary.to_csv(OUTPUT / "tqqq_mnq_rebalance_summary_70pct_bil.csv")
    no_cash_summary.to_csv(OUTPUT / "tqqq_mnq_rebalance_summary_no_cash.csv")
    pd.concat({rule: path for rule, path in paths.items()}, names=["rule", "date"]).to_csv(OUTPUT / "tqqq_mnq_rebalance_detail_70pct_bil.csv")

    plot_paths(nav)
    plot_leverage(paths)
    build_report(summary, nav)

    notes = {
        "method": "Fractional MNQ. Rebalance sets notional back to 3x equity. Daily PnL = contracts * 2 * B-ADJ point delta. Leverage measured with unadjusted NQ close.",
        "cash_weight_main": CASH_WEIGHT_MAIN,
        "sample_start": str(model.index[0].date()),
        "sample_end": str(model.index[-1].date()),
    }
    (OUTPUT / "tqqq_mnq_rebalance_source_notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")

    print(summary[["final_multiple", "cagr", "ann_vol", "max_drawdown", "pre_lev_min", "pre_lev_max", "rebalances_per_year"]].round(4).to_string())
    print("Report:", ROOT / "report_rebalance_badj_final.html")


if __name__ == "__main__":
    main()
