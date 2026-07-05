# 历史利率条件下的 NDX/SPX 最佳杠杆率

本研究用 NDX/SPX 指数价格收益和 Yahoo `^IRX` 13 周国库券收益率，估算不同每日再平衡杠杆在历史短端利率条件下的表现。模拟加入年化 `0.9%` 费率拖累，并按交易日每日扣除。

样本起点：

- `NDX`：1985-10-02
- `SPX`：1985-01-03
- 利率代理 `^IRX`：1985-01-02

## 主要结论

最大化历史 CAGR 会选择很高的杠杆。下表先给出同一收益序列下的 1x 指数价格路径作为 baseline；baseline 不扣 `0.9%` 费率，杠杆策略扣费。

| 标的 | 样本 | 1x 指数倍数 | CAGR | 最大回撤 |
|---|---|---:|---:|---:|
| NDX | 1985-10-02 至 2026-07-02 | 261.54x | 14.6% | -82.9% |
| SPX | 1985-01-03 至 2026-07-02 | 45.25x | 9.6% | -56.8% |

最大 CAGR 杠杆策略相对 baseline 的变化：

| 标的 | 最大 CAGR 杠杆 | 策略倍数 | 策略 CAGR | 策略最大回撤 | 相对 1x 指数 |
|---|---:|---:|---:|---:|---|
| NDX | 2.05x | 889.88x | 18.1% | -99.0% | 终值 `3.40x`，CAGR `+3.5pct`，回撤加深 `16.1pct` |
| SPX | 2.25x | 99.94x | 11.7% | -94.1% | 终值 `2.21x`，CAGR `+2.1pct`，回撤加深 `37.3pct` |

但这类路径有接近清零的历史回撤，更适合作为理论上限，不适合作为直接配置建议。

![NDX/SPX 最佳杠杆率](outputs/optimal_leverage_rates.png)

## 方法

```text
strategy_return = L * index_return + (1 - L) * rf_daily - fee_daily
```

- 数据源：Yahoo Finance Chart API。
- 标的：`^NDX`、`^GSPC`。
- 利率代理：`^IRX`，转换为每日现金/融资收益。
- 费率：年化 0.9%，按 252 个交易日折算为每日费用扣除。
- 杠杆网格：0x 到 5x，步长 0.05x。
- 默认只保存图表，不保存原始数据和 CSV 表格。

## 复现

```powershell
python scripts\optimal_leverage_rates.py
```

如需缓存原始 Yahoo JSON：

```powershell
python scripts\optimal_leverage_rates.py --cache-data
```

如需输出 CSV 审计表：

```powershell
python scripts\optimal_leverage_rates.py --write-tables
```

## 限制

这里使用的是价格指数，不是总回报指数；这会低估含股息再投资的 SPX 实现。模型已扣除 0.9% 年化费率，但没有计入税、佣金、滑点、融资利差、保证金规则变化或强平机制。
