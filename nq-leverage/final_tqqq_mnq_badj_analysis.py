from pathlib import Path
import json
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
INPUT = DATA / "input"
INTERIM = DATA / "interim"
OUTPUT = DATA / "output"
CHARTS = ROOT / "charts_final"
INTERIM.mkdir(parents=True, exist_ok=True)
OUTPUT.mkdir(parents=True, exist_ok=True)
CHARTS.mkdir(parents=True, exist_ok=True)

TARGET_LEVERAGE = 3.0
CASH_WEIGHTS = {
    "MNQ 3x, no cash": 0.00,
    "MNQ 3x + 55% BIL": 0.55,
    "MNQ 3x + 70% BIL": 0.70,
}

TOKENS = {
    "surface": "#FCFCFD",
    "panel": "#FFFFFF",
    "ink": "#1F2430",
    "muted": "#6F768A",
    "grid": "#E6E8F0",
    "axis": "#D7DBE7",
    "blue": "#5477C4",
    "orange": "#CC6F47",
    "olive": "#71B436",
    "gold": "#B8A037",
    "neutral": "#7A828F",
}


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    integrated = pd.read_csv(INPUT / "nq1_continuous_badj_nonbadj.csv", parse_dates=["date"])
    tqqq = pd.read_csv(INPUT / "raw_TQQQ.csv", parse_dates=["date"])
    bil = pd.read_csv(INPUT / "raw_BIL.csv", parse_dates=["date"])
    return integrated, tqqq, bil


def max_drawdown(nav: pd.Series) -> dict:
    high = nav.cummax()
    dd = nav / high - 1
    trough = dd.idxmin()
    peak = nav.loc[:trough].idxmax()
    rec = nav.loc[trough:][nav.loc[trough:] >= high.loc[trough]]
    return {
        "max_drawdown": dd.min(),
        "peak_date": peak,
        "trough_date": trough,
        "recovery_date": rec.index[0] if not rec.empty else pd.NaT,
    }


def stats(nav: pd.Series, ret: pd.Series, rf: pd.Series) -> dict:
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    total = nav.iloc[-1] / nav.iloc[0] - 1
    cagr = nav.iloc[-1] ** (1 / years) - 1
    vol = ret.std(ddof=1) * math.sqrt(252)
    excess = ret - rf.reindex(ret.index).fillna(0)
    sharpe = excess.mean() * 252 / vol if vol else np.nan
    return {
        "start": nav.index[0],
        "end": nav.index[-1],
        "final_multiple": nav.iloc[-1],
        "total_return": total,
        "cagr": cagr,
        "ann_vol": vol,
        "excess_sharpe_vs_bil": sharpe,
        **max_drawdown(nav),
    }


def pct(x: float, digits: int = 1) -> str:
    if pd.isna(x):
        return "n/a"
    return f"{x * 100:.{digits}f}%"


def mult(x: float) -> str:
    return f"{x:.2f}x"


def set_theme():
    plt.rcParams.update(
        {
            "figure.facecolor": TOKENS["surface"],
            "axes.facecolor": TOKENS["panel"],
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


def plot_growth(nav: pd.DataFrame) -> Path:
    set_theme()
    fig, ax = plt.subplots(figsize=(10.5, 6))
    series = [
        ("TQQQ", TOKENS["blue"], "-"),
        ("MNQ 3x + 55% BIL", TOKENS["orange"], "-"),
        ("MNQ 3x + 70% BIL", TOKENS["olive"], "--"),
        ("MNQ 3x, no cash", TOKENS["neutral"], ":"),
    ]
    for col, color, style in series:
        ax.plot(nav.index, nav[col], label=col, color=color, linestyle=style, linewidth=1.25)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0f}x" if y >= 1 else f"{y:.1f}x"))
    ax.set_ylabel("Growth of $1, log scale")
    ax.grid(True, axis="y")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False, ncol=4)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    add_header(fig, ax, "Growth paths", "MNQ returns use B-ADJ point PnL divided by unadjusted prior NQ close.")
    path = CHARTS / "final_growth_paths.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_ratio(nav: pd.DataFrame) -> Path:
    set_theme()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    for col, color in [("MNQ 3x + 55% BIL", TOKENS["orange"]), ("MNQ 3x + 70% BIL", TOKENS["olive"]), ("MNQ 3x, no cash", TOKENS["neutral"])]:
        ax.plot(nav.index, nav[col] / nav["TQQQ"], label=f"{col} / TQQQ", color=color, linewidth=1.15)
    ax.axhline(1, color=TOKENS["muted"], linewidth=1, linestyle=":")
    ax.set_ylabel("Relative wealth ratio")
    ax.grid(True, axis="y")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False, ncol=3)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    add_header(fig, ax, "Relative wealth versus TQQQ", "Above 1 means the simulated MNQ path has accumulated more wealth than TQQQ.")
    path = CHARTS / "final_relative_ratio.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_drawdown(nav: pd.DataFrame) -> Path:
    set_theme()
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    for col, color in [("TQQQ", TOKENS["blue"]), ("MNQ 3x + 70% BIL", TOKENS["olive"]), ("MNQ 3x + 55% BIL", TOKENS["orange"])]:
        dd = nav[col] / nav[col].cummax() - 1
        ax.plot(nav.index, dd, label=col, color=color, linewidth=1.15)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    ax.set_ylabel("Drawdown")
    ax.grid(True, axis="y")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), frameon=False, ncol=3)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    add_header(fig, ax, "Drawdowns", "Peak-to-trough drawdown from each path's own prior high.")
    path = CHARTS / "final_drawdowns.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def html_table(df: pd.DataFrame) -> str:
    out = ["<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in df.columns) + "</tr></thead><tbody>"]
    for _, row in df.iterrows():
        out.append("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def build_report(nav: pd.DataFrame, ret: pd.DataFrame, summary: pd.DataFrame, yearly: pd.DataFrame):
    t = summary.loc["TQQQ"]
    m55 = summary.loc["MNQ 3x + 55% BIL"]
    m70 = summary.loc["MNQ 3x + 70% BIL"]
    no_cash = summary.loc["MNQ 3x, no cash"]
    gap = (ret["MNQ 3x + 70% BIL"] - ret["TQQQ"]).mean() * 252
    te = (ret["MNQ 3x + 70% BIL"] - ret["TQQQ"]).std(ddof=1) * math.sqrt(252)
    corr = ret["MNQ 3x + 70% BIL"].corr(ret["TQQQ"])

    table = pd.DataFrame(
        {
            "Metric": ["Final multiple", "CAGR", "Annualized vol", "Max drawdown", "Sharpe vs BIL"],
            "TQQQ": [mult(t.final_multiple), pct(t.cagr), pct(t.ann_vol), pct(t.max_drawdown), f"{t.excess_sharpe_vs_bil:.2f}"],
            "MNQ 55% BIL": [mult(m55.final_multiple), pct(m55.cagr), pct(m55.ann_vol), pct(m55.max_drawdown), f"{m55.excess_sharpe_vs_bil:.2f}"],
            "MNQ 70% BIL": [mult(m70.final_multiple), pct(m70.cagr), pct(m70.ann_vol), pct(m70.max_drawdown), f"{m70.excess_sharpe_vs_bil:.2f}"],
            "MNQ no cash": [mult(no_cash.final_multiple), pct(no_cash.cagr), pct(no_cash.ann_vol), pct(no_cash.max_drawdown), f"{no_cash.excess_sharpe_vs_bil:.2f}"],
        }
    )

    yearly_tail = yearly.tail(10).copy()
    for c in yearly_tail.columns:
        yearly_tail[c] = yearly_tail[c].map(lambda x: pct(x))
    yearly_tail = yearly_tail.reset_index().rename(columns={"date": "Year", "index": "Year"})

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TQQQ 与 MNQ 每日三倍路径比较 - B-ADJ 版</title>
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
    code {{ background:#f5f7fb; padding:2px 4px; border-radius:4px; }}
  </style>
</head>
<body>
<main>
  <h1>TQQQ 与 MNQ 每日三倍路径比较 - B-ADJ 版</h1>
  <h2>Executive Summary</h2>
  <div class="summary">
    <p><strong>用更干净的 B-ADJ 点数 PnL 后，MNQ 模拟路径仍明显优于 TQQQ。</strong>共同样本为 {nav.index[0].date()} 到 {nav.index[-1].date()}；TQQQ 最终为 {mult(t.final_multiple)}，MNQ 3x + 55% BIL 为 {mult(m55.final_multiple)}，MNQ 3x + 70% BIL 为 {mult(m70.final_multiple)}。</p>
    <p><strong>这版避免了直接用主连百分比收益带来的换月跳点问题。</strong>MNQ 日收益用 <code>3 × ΔB-ADJ close / 非B-ADJ前收</code>，现金部分用 BIL 调整收盘价近似短债收益。</p>
    <p><strong>差异仍不是无风险套利。</strong>MNQ 70% BIL 与 TQQQ 的日收益相关性为 {corr:.3f}，年化跟踪误差约 {pct(te)}；它更像自己运营一个期货杠杆账户，而不是购买 TQQQ 产品。</p>
  </div>

  <h2>结果汇总</h2>
  {html_table(table)}

  <h2>长期净值路径</h2>
  <p>MNQ 路径的主要优势来自三个部分：没有 TQQQ 基金内部融资/互换/费用摩擦，短债现金收益可留在账户里，以及期货路径和 ETF 产品路径的实现方式不同。70% BIL 是更接近你现在讨论的 SGOV/cash 实操思路，55% BIL 是较保守的保证金占用口径。</p>
  <figure><img src="charts_final/final_growth_paths.png" alt="Growth paths"><figcaption>所有路径从 1 开始，纵轴为对数刻度。</figcaption></figure>

  <h2>相对 TQQQ 的路径差异</h2>
  <p>MNQ 70% BIL 相对 TQQQ 的平均年化日收益差为 {pct(gap)}，但这个差异是路径型的，换月、保证金、现金管理和实际执行都会影响最终结果。</p>
  <figure><img src="charts_final/final_relative_ratio.png" alt="Relative ratio"><figcaption>比值高于 1 表示 MNQ 模拟路径累计领先 TQQQ。</figcaption></figure>

  <h2>回撤仍然接近产品级灾难风险</h2>
  <p>MNQ 路径的最大回撤和 TQQQ 同量级。即使收益更高，也不改变 3x Nasdaq 策略在长熊市里可能出现 70%-80% 级回撤的事实。</p>
  <figure><img src="charts_final/final_drawdowns.png" alt="Drawdowns"><figcaption>每条曲线按自身历史高点计算回撤。</figcaption></figure>

  <h2>近十年年度收益</h2>
  {html_table(yearly_tail)}

  <h2>方法说明</h2>
  <ul>
    <li>TQQQ 和 BIL 使用 Yahoo 调整收盘价。</li>
    <li>MNQ 使用 TradingView B-ADJ 与非 B-ADJ 综合文件：B-ADJ 用于点数 PnL，非 B-ADJ 用于真实前收分母。</li>
    <li>本报告没有扣除 MNQ 佣金、滑点、税务、整数合约误差和 IBKR 实际保证金动态变化。</li>
    <li>BIL 是短债收益 proxy；实际用 SGOV 或 T-bills 会有轻微差异。</li>
  </ul>
</main>
</body>
</html>"""
    (ROOT / "report_badj_final.html").write_text(html, encoding="utf-8")


def main():
    integrated, tqqq, bil = load_inputs()
    integrated = integrated.sort_values("date").copy()
    integrated["unadj_prev_close"] = integrated["unadj_close"].shift(1)
    integrated["badj_close_delta"] = integrated["badj_close"].diff()
    integrated["continuous_return"] = integrated["badj_close_delta"] / integrated["unadj_prev_close"]
    integrated["unadj_raw_return"] = integrated["unadj_close"].pct_change()
    integrated["estimated_roll_effect_return"] = integrated["unadj_raw_return"] - integrated["continuous_return"]

    tqqq = tqqq[["date", "adjclose"]].rename(columns={"adjclose": "TQQQ"})
    bil = bil[["date", "adjclose"]].rename(columns={"adjclose": "BIL"})
    nq = integrated[["date", "continuous_return", "unadj_close", "badj_close_delta", "estimated_roll_effect_return"]]

    df = nq.merge(tqqq, on="date", how="inner").merge(bil, on="date", how="inner").sort_values("date")
    df["TQQQ_ret"] = df["TQQQ"].pct_change()
    df["BIL_ret"] = df["BIL"].pct_change()
    df = df.dropna(subset=["continuous_return", "TQQQ_ret", "BIL_ret"]).copy()

    ret = pd.DataFrame(index=df["date"])
    ret.index.name = "date"
    ret["TQQQ"] = df["TQQQ_ret"].to_numpy()
    for name, cash_weight in CASH_WEIGHTS.items():
        ret[name] = TARGET_LEVERAGE * df["continuous_return"].to_numpy() + cash_weight * df["BIL_ret"].to_numpy()
    ret["BIL"] = df["BIL_ret"].to_numpy()

    nav = (1 + ret[["TQQQ", *CASH_WEIGHTS.keys(), "BIL"]]).cumprod()
    nav = pd.concat([pd.DataFrame([[1] * len(nav.columns)], columns=nav.columns, index=[ret.index[0] - pd.Timedelta(days=1)]), nav])
    nav.index.name = "date"

    summary = pd.DataFrame({col: stats(nav[col], ret[col].reindex(ret.index), ret["BIL"]) for col in ["TQQQ", *CASH_WEIGHTS.keys()]}).T
    yearly = (1 + ret[["TQQQ", "MNQ 3x + 55% BIL", "MNQ 3x + 70% BIL", "MNQ 3x, no cash"]]).groupby(ret.index.year).prod() - 1
    yearly.index.name = "year"

    # Keep an audit table with both raw and model returns.
    audit_base = df.set_index("date")[["continuous_return", "estimated_roll_effect_return", "badj_close_delta", "unadj_close", "TQQQ", "BIL"]]
    audit_base = audit_base.rename(columns={"TQQQ": "TQQQ_adjclose", "BIL": "BIL_adjclose"})
    audit = audit_base.join(ret)
    audit.to_csv(INTERIM / "tqqq_mnq_badj_daily_model.csv")
    nav.to_csv(OUTPUT / "tqqq_mnq_badj_nav_paths.csv")
    ret.to_csv(OUTPUT / "tqqq_mnq_badj_daily_returns.csv")
    summary.to_csv(OUTPUT / "tqqq_mnq_badj_summary.csv")
    yearly.to_csv(OUTPUT / "tqqq_mnq_badj_yearly_returns.csv")

    plot_growth(nav)
    plot_ratio(nav)
    plot_drawdown(nav)
    build_report(nav, ret, summary, yearly)

    notes = {
        "sample_start": str(nav.index[0].date()),
        "sample_end": str(nav.index[-1].date()),
        "method": "MNQ return = 3 * (B-ADJ close delta / unadjusted prior close) + cash_weight * BIL adjusted-close return.",
        "cash_weights": CASH_WEIGHTS,
        "outputs": {
            "report": str(ROOT / "report_badj_final.html"),
            "summary": str(OUTPUT / "tqqq_mnq_badj_summary.csv"),
            "nav": str(OUTPUT / "tqqq_mnq_badj_nav_paths.csv"),
        },
    }
    (OUTPUT / "tqqq_mnq_badj_source_notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")

    print(summary[["final_multiple", "cagr", "ann_vol", "max_drawdown", "excess_sharpe_vs_bil"]].to_string())
    print("Report:", ROOT / "report_badj_final.html")
    print("Interim data dir:", INTERIM)
    print("Output data dir:", OUTPUT)


if __name__ == "__main__":
    main()
