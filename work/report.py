import pathlib,json,base64,shutil,zipfile,platform
import pandas as pd,numpy as np,markdown
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from backtest import stats,regression
ROOT=pathlib.Path(__file__).resolve().parents[1];O=ROOT/'outputs'
summary=pd.read_csv(O/'open_summary.csv');reg=pd.read_csv(O/'open_regression.csv');sens=pd.read_csv(O/'open_sensitivity.csv');margin=pd.read_csv(O/'open_margin_sensitivity.csv');ints=pd.read_csv(O/'open_integer_accounts.csv');daily=pd.read_csv(O/'open_daily_backtests.csv',parse_dates=['date']);audit=json.loads((O/'data_audit.json').read_text(encoding='utf-8'))
names={'front':'近月滚动','next':'次近月买入持有至换月','far':'远月买入持有至换月','carry':'最大年化贴水（换月时选择）','liquid':'昨日持仓量主力','spot_price':'现货价格指数'}
def pct(x):return f'{x:.2%}'
def table(df,cols,percent=(),digits=2):
 x=df[list(cols)].copy()
 for c in x.columns:
  if c in percent:x[c]=x[c].map(lambda v:pct(v) if pd.notna(v) else '—')
  elif pd.api.types.is_float_dtype(x[c]):x[c]=x[c].map(lambda v:f'{v:.{digits}f}' if pd.notna(v) else '—')
  if c=='rule':x[c]=x[c].map(names)
 x=x.rename(columns=cols).fillna('—');return x.to_markdown(index=False)
common=[];annual=[];period=[];neutral=[]
for (p,r),g in daily.groupby(['product','rule'],sort=False):
 a=g.set_index('date')
 for year,z in a.iloc[1:].groupby(a.index[1:].year):annual.append(dict(product=p,rule=r,year=year,return_net=(1+z.return_net).prod()-1,spot_return=(1+z.spot_return).prod()-1,basis_contribution=z.basis_contribution.sum(),cost=z.cost_return.sum(),days=len(z)))
 for start,end,label in [('2015-04-16','2018-12-31','2015—2018'),('2019-01-01','2022-12-31','2019—2022'),('2023-01-01','2026-09-07','2023—2026/09'),('2022-07-25','2026-09-07','共同区间')]:
  z=a.loc[start:end].copy()
  if len(z)<60:continue
  z['nav']=(1+z.return_net).cumprod();z['nav']/=z.nav.iloc[0];row=dict(product=p,rule=r,period=label,**stats(z),**regression(z));period.append(row)
  if label=='共同区间':common.append(row)
 b=a.copy();b['return_net']=a.basis_contribution-a.cost_return;b['nav']=(1+b.return_net).cumprod();neutral.append(dict(product=p,rule=r,**stats(b),correlation=a.spot_return.corr(b.return_net)))
pd.DataFrame(annual).to_csv(O/'open_annual_returns.csv',index=False,encoding='utf-8-sig');pd.DataFrame(period).to_csv(O/'open_regime_analysis.csv',index=False,encoding='utf-8-sig');pd.DataFrame(common).to_csv(O/'open_common_period.csv',index=False,encoding='utf-8-sig');pd.DataFrame(neutral).to_csv(O/'open_hedged_diagnostic.csv',index=False,encoding='utf-8-sig')
# Independent checks against raw contract prices and reported NAV, including roll dates.
raw=pd.read_csv(O/'futures_clean.csv',parse_dates=['date']);quotes={(r.date,r.contract):r for r in raw.itertuples(index=False)};checks={};maxerr=0;count=0
for (p,r),g in daily.groupby(['product','rule']):
 a=g.set_index('date');assert np.allclose(a.nav,(1+a.return_net).cumprod(),rtol=1e-9)
 for i in range(1,len(a)):
  now=a.iloc[i];prev=a.iloc[i-1];d=a.index[i];pd_=a.index[i-1];cur=quotes[(d,now.held_contract)];pnl=now.quantity*200*(cur.close-cur.open)
  if pd.notna(prev.held_contract):pnl+=prev.quantity*200*(quotes[(d,prev.held_contract)].open-quotes[(pd_,prev.held_contract)].close)
  err=abs((now.equity-prev.equity)-(pnl-now.fees));maxerr=max(maxerr,err);count+=1
  assert err<.0001,'Independent trade P&L reconciliation'
  assert (pd_,now.held_contract) in quotes,'Contract absent from decision-date universe'
  if now['roll']:
   assert now.held_contract>=prev.held_contract,'Backwards roll'
  expected=prev.equity/(quotes[(pd_,now.held_contract)].close*200)
  assert abs(expected-now.quantity)<1e-7,'Position uses future information'
checks.update(daily_pnl_checks=count,max_pnl_error_yuan=maxerr,nav_compounding='passed',prior_day_contract_availability='passed',prior_day_sizing='passed',no_backward_roll='passed',attribution_identity='passed',settlement_reconciliation='passed in close ledger engine',ohlc_invalid_rows=audit['ohlc_invalid_rows'],missing_benchmark_dates=audit['missing_spot_dates'])
(O/'validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
plt.rcParams.update({'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.18,'figure.facecolor':'white'})
fig,ax=plt.subplots(2,2,figsize=(14,9),height_ratios=[1.3,1]);colors={'front':'#2463a5','next':'#228b75','far':'#b67823','carry':'#ab4875'}
for j,p in enumerate(['IC','IM']):
 for r in colors:
  a=daily[(daily['product']==p)&(daily.rule==r)].set_index('date');ax[0,j].plot(a.index,a.nav,label=r,color=colors[r],lw=1.4)
 a=daily[(daily['product']==p)&(daily.rule=='front')].set_index('date');bn=(1+a.spot_return).cumprod();ax[0,j].plot(a.index,bn,label='spot price',color='#333333',ls='--',lw=1.2);ax[0,j].set_title(f'{p}: 1x target, next-open execution');ax[0,j].set_ylabel('Net asset value');ax[0,j].legend(fontsize=9)
 ax[1,j].fill_between(a.index,(a.nav/a.nav.cummax()-1)*100,0,color=colors['front'],alpha=.35,label='front');ax[1,j].plot(a.index,(bn/bn.cummax()-1)*100,color='#333333',ls='--',label='spot price');ax[1,j].set_ylabel('Drawdown (%)');ax[1,j].legend()
fig.suptitle('IC / IM rolling futures | 1 bp one-way costs | no cash interest',fontsize=15);fig.tight_layout();fig.savefig(O/'open_performance.png',dpi=170);plt.close(fig)
fig,ax=plt.subplots(1,2,figsize=(13,4.5))
for p in ['IC','IM']:
 g=sens[(sens['product']==p)&(sens.scenario=='leverage')];ax[0].plot(g.parameter,g.cagr*100,marker='o',label=p);ax[1].plot(g.parameter,g.max_drawdown*100,marker='o',label=p)
for a in ax:a.set_xlabel('Target notional / equity');a.legend()
ax[0].set_ylabel('CAGR (%)');ax[1].set_ylabel('Maximum drawdown (%)');fig.suptitle('Next-open leverage sensitivity, before forced liquidation');fig.tight_layout();fig.savefig(O/'open_leverage.png',dpi=170);plt.close(fig)
front=summary[summary.rule=='front'];rfront=reg[reg.rule=='front'];lev=sens[(sens.scenario=='leverage')&sens.parameter.isin([.5,1,1.5,2,3,5])]
ann=pd.DataFrame(annual);ann=ann[ann.rule=='front'].pivot(index='year',columns='product',values=['return_net','spot_return']);ann.columns=['IC期货','IM期货','中证500','中证1000'];ann=ann[['IC期货','中证500','IM期货','中证1000']].reset_index()
close=pd.read_csv(O/'summary.csv');comparison=front[['product','cagr','max_drawdown']].merge(close[close.rule=='front'][['product','cagr','max_drawdown']],on='product',suffixes=('_open','_close'))
report=f'''# IC / IM「滚贴水」策略回测

数据截至 **2026-09-07**。主结果采用**前日决策、次日开盘成交**，1倍目标名义敞口，单边综合成本1bp，总账户权益计收益，不计现金利息。IC样本为2015-04-16起，IM为2022-07-22起；首次交易分别为下一交易日2015-04-17和2022-07-25。

## 核心结论

长期滚动持有IC或IM，在这段样本中获得了明显的现货价格指数之上的超额收益；**“整个策略与大盘无关”不成立**。它仍是小盘股票风险敞口，基差收益叠加其上。1倍近月策略的年化收益约10%—11%，年化波动约26%—29%，最大回撤约39%—52%。历史较深的贴水没有阻止净值大幅下跌。

{table(front,{'product':'品种','cagr':'年化复合收益','volatility':'年化波动','sharpe':'夏普','max_drawdown':'最大回撤','total_return':'累计收益'},['cagr','volatility','max_drawdown','total_return'])}

![净值与回撤](open_performance.png)

图例：front=近月，next=次近月买入持有，far=远月买入持有，carry=换月时选择最大年化贴水，spot price=现货价格指数。各品种按各自上市时间归一化，不能凭累计净值高低比较IC和IM。

## 数据与清洗

读取用户提供的138个月度ZIP、2,782个逐日CSV；仅保留正则匹配`IC/IM+四位年月`的期货合约，排除小计、合计、其他品种和期权。直接在压缩包内读取，不修改原文件。按UTF-8/GB18030解码、去除合约空格、转数值、按日期及合约排序，并保留源ZIP、CSV文件名。

| 检查 | IC | IM |
|---|---:|---:|
| 有效交易日 | 2,772 | 1,002 |
| 合约日记录 | 11,088 | 4,008 |
| 不同合约 | 140 | 53 |
| 重复日期合约键 | 0 | 0 |
| 零成交量 | 0 | 0 |
| 相对现货交易日缺失 | 0 | 0 |

全样本无非正/缺失收盘价或结算价，无OHLC区间异常；每个合约的当日前结算价与上个记录的结算价全部衔接，容差0.11点。没有填充缺失交易日或用连续主力价格替代真实合约。保留原ZIP的SHA-256清单，支持重跑核对。异常输出为空表，表示检查未发现该类异常，不是遗漏检查。

现货从腾讯行情接口补充中证500（sh000905）和中证1000（sh000852）日线，期货样本交易日全部覆盖。指数价格未做股票式复权；请求参数虽含qfq，返回的是指数`day`字段。现货为第三方行情，未逐日与中证指数官方授权数据库双源核验。它是**价格指数，不含分红再投资**。因此不能把对价格指数的超额收益完全称为投资者可得的纯alpha。

## 可复现的交易规则

1. 当天开盘前，只使用上一交易日已经发布的合约、收盘价、成交量、持仓量和现货收盘价。到期日按合约月份第三个周五、遇假日顺延到交易日确定；交易日历只用于到期日期，不读取未来行情作信号。
2. 可选合约距离执行日到期须**大于7个自然日**，上一日成交量和持仓量均大于0，不允许往更早到期月份换回。近月规则选择其中最近到期者，因此通常在到期前一周换月，避免现金交割。
3. 次近月/远月规则仅在首次建仓或旧合约进入换月窗口时，分别选候选中的第二近/最远到期合约，其余日子持有原合约。它们不是每天强制保持固定期限。
4. 贴水规则同样只在换月时选择，优先筛选剩余至少20天、上一日成交量≥100手、持仓量≥1,000手的合约，然后最大化`(现货昨收/期货昨收−1)×365/距到期天数`。若筛选为空，退回基本候选集合。期限用执行日计算，行情仍用前日。没有候选贴水为正的择时门槛，即所有合约升水时也会持仓。主力规则每天按上一日持仓量最大选择，也禁止反向换回。
5. 基准为每天调整目标手数：`手数_t = L × 昨日账户权益 / (200 × 所选合约昨收)`，按当日开盘价成交。每日收盘按实际持有合约计价；有旧合约时先计旧持仓昨收到今开的损益，再计新持仓今开到今收的损益。**卖出旧合约和买入更便宜的新合约不会立即产生换月利润。**
6. 每手乘数200元。开、平仓及每日增减仓均按交易名义金额收取单边1bp（0.01%）综合成本，换月两腿分别收费；这是统一手续费与滑点情景，不是复原逐年费率。期末按收盘市值估值，未强制平仓，也未收取期末退出费。

基准允许小数手，用于比较策略的单位风险收益。它不是100万元账户可以精确执行的实盘。开盘价成交仍是日线模型假设，无法验证盘口容量、涨跌停排队和开盘滑点。代码提供整数手版本及更高成本测试。

## 不同换月方式

{table(summary,{'product':'品种','rule':'策略','cagr':'年化收益','volatility':'波动','sharpe':'夏普','max_drawdown':'最大回撤'},['cagr','volatility','max_drawdown'])}

策略表现没有支持“买最深贴水的远月就一定最好”。远月降低换月次数，但同时改变基差波动和流动性暴露。以上参数预先固定比较，未通过全样本搜索最优参数；它们仍属于样本内描述，不构成独立样本外验证。

共同区间按2022-07-25收盘归一化，收益统计从下一交易日开始，各规则继承当时已经持有的合约：

{table(pd.DataFrame(common).query("rule=='front'"),{'product':'品种','cagr':'共同区间年化','volatility':'波动','max_drawdown':'最大回撤','correlation':'指数相关性'},['cagr','volatility','max_drawdown'])}

## 「alpha」与股市风险的分离

对近月策略日收益做单因子回归：`期货组合收益−rf = alpha + beta×(对应现货价格指数收益−rf) + 残差`。rf设为年化2%，日化按252；标准误用Newey–West/HAC（5个交易日滞后）。alpha为截距×252的**算术年化**，不是年化复合收益。95%区间仅反映该统计设定下的抽样误差，不涵盖成本、数据源和执行模型误差。

{table(rfront,{'product':'品种','beta':'beta','correlation':'日收益相关性','alpha_annual_arithmetic':'年化alpha','alpha_ci_low':'95%下界','alpha_ci_high':'95%上界','alpha_t_hac':'HAC t值'},['alpha_annual_arithmetic','alpha_ci_low','alpha_ci_high'])}

IC约88%、IM约95%的日收益方差被对应指数这一因子解释。样本确实存在正的回归截距，同时beta仍约为1；**有超额收益和市场中性是两件不同的事**。控制单一价格指数后的截距还可能包含分红差异、风格风险、期货与指数收盘时点差异、流动性补偿等，不能证明无风险套利。尤其2015年部分时段期货和股票收盘时间不一致。

为减少收盘时点错配影响，另用完整月收益回归、HAC滞后3个月，排除首尾不完整月：

{table(rfront,{'product':'品种','monthly_beta':'月频beta','monthly_alpha':'月频年化alpha','monthly_alpha_t_hac':'月频HAC t值'},['monthly_alpha'])}

对每段实际持仓，恒等式为`ΔF = ΔS + Δ(F−S)`，按该段真实手数乘200、再除以前日权益。开盘换月时旧合约隔夜段和新合约日内段分别拆分。因此以下是逐日贡献的算术均值×252，可以加总为算术平均收益，但不能直接相加得到CAGR：

{table(rfront,{'product':'品种','mean_market_contribution_annual':'指数变动贡献','mean_basis_contribution_annual':'基差变化贡献','mean_cost_annual':'交易成本扣减'},['mean_market_contribution_annual','mean_basis_contribution_annual','mean_cost_annual'])}

贴水的到期收敛在股价不变时有利于期货多头，但现货跌幅可以远大于贴水。买入贴水合约不锁定全账户正收益。样本附有“扣除点数匹配现货损益”的基差诊断序列，只用于解释贡献，**没有加入真实卖空股票/ETF的借券成本、分红补偿、融资、现货交易成本和保证金，所以不是可执行的市场中性回测**。对价格指数的超额若改用全收益指数，通常会下降；例如仅以年化1%—3%分红作假设，相关超额量级需相应下调，不能把假设当作实测股息。

## 杠杆与保证金

杠杆L定义为目标名义敞口/总权益。保证金率m主要约束资金占用，约为`m×L`，**不会在同一L下自动提高收益**。如果只放入15%保证金就持有完整合约，敞口相当于约6.67倍总权益，而不是1倍策略。

{table(lev,{'product':'品种','parameter':'目标杠杆','cagr':'年化收益','volatility':'年化波动','max_drawdown':'最大回撤'},['cagr','volatility','max_drawdown'])}

![杠杆敏感性](open_leverage.png)

这些是**没有执行强平**的理论净值。高杠杆下波动拖累非常大：IC从1倍到2倍，年化收益改善有限，最大回撤却扩大到约83%；5倍几乎损失全部净值。IM也呈现显著的回撤放大。样本内最高CAGR所在杠杆不是建议杠杆，更不能当作未来最优值。

保证金压力测试将全部权益视为可及时用于追保，无外部注资。使用当天开盘后的实际手数和日内最低价估算最低权益，并与该价格下的保证金要求比较；日终再检查`结算资金 < 保证金率×结算名义市值`。未模拟开盘减仓完成前的瞬时追保、转账时限、经纪商提前强平阈值或同一时点换月两腿并存的资金占用。

{table(margin[margin.margin_rate.isin([.15,.4])&margin.leverage.isin([1,2,2.5,5])],{'product':'品种','leverage':'杠杆','margin_rate':'固定保证金率','initial_target_usage':'目标占用比例','breach_days':'触发日数','first_breach':'首次触发'},['margin_rate','initial_target_usage'])}

保证金率15%情景下，5倍IC首次触发为2015-05-28，IM为2022-11-08；此后净值只能视为理论延续。40%情景下2.5倍已经耗尽目标保证金空间，费用和波动会使其不可维持，3倍以上更不具备初始资金可行性。无触发只表示在本日线条件模型中未穿线，不代表安全。

**此表为固定8%、12%、15%、20%、30%、40%压力情景，不是历史保证金制度的逐日复原。** 例如2015年9月IC非套保持仓保证金曾提高到40%，还存在开仓限制；不能把今天的低保证金率外推到整个样本。因此高杠杆全样本不应被称为历史可实施业绩。账户还可能有经纪商加收，真实要求应代入相应情景。

## 执行、成本与资金规模

下面对比严格前日信号次日开盘，与理想化当日收盘定仓并成交的近月模型。两者都扣费，后者小数手调仓依赖当日收盘权益和成交价，应主要作为理论参照：

{table(comparison,{'product':'品种','cagr_open':'次日开盘年化','cagr_close':'收盘模型年化','max_drawdown_open':'开盘模型回撤','max_drawdown_close':'收盘模型回撤'},['cagr_open','cagr_close','max_drawdown_open','max_drawdown_close'])}

仅改变单边综合成本，其他规则不变：

{table(sens[(sens.scenario=='one_way_cost')&sens.parameter.isin([0,.0001,.0005,.001])],{'product':'品种','parameter':'单边成本','cagr':'年化收益','sharpe':'夏普'},['parameter','cagr'])}

换月提前天数为自然日；不存在以事后最优换月日选成绩的操作：

{table(sens[sens.scenario=='roll_calendar_days'],{'product':'品种','parameter':'到期前天数','cagr':'年化收益','max_drawdown':'最大回撤'},['cagr','max_drawdown'])}

整数账户只在首次建仓/换月时向下取整并调整手数，中间持仓不变，因此同时反映取整和低频再平衡影响，不是对小数手基准只改一个参数：

{table(ints,{'product':'品种','capital':'初始资金/元','target_leverage':'目标杠杆','mean_leverage':'实际平均杠杆','cagr':'年化收益','max_drawdown':'最大回撤'},['cagr','max_drawdown'])}

100万元可能连1手都买不到，未建仓时等待下一次换月窗口再判断，造成现金择时效应。此类账户的较高收益或较小回撤不能归因于贴水更有效，要结合实际平均杠杆看。主模型默认现金收益0%，夏普仍扣2%机会成本；附带收盘模型按总权益计1%/2%现金收益的理想敏感性，仅作为现金管理上界参照，实际保证金及闲置资金能否计息须另行核实。

## 年度收益与阶段稳定性

{table(ann,{c:c for c in ann.columns},['IC期货','中证500','IM期货','中证1000'])}

2015、2022年IM以及2026年都是不完整年份；“—”代表尚未上市或无该品种样本。年度收益按该年实际日收益复利计算，不能相加得到累计收益。

{table(pd.DataFrame(period).query("rule=='front' and period!='共同区间'"),{'product':'品种','period':'阶段','cagr':'年化收益','max_drawdown':'阶段最大回撤','alpha_annual_arithmetic':'价格指数alpha'},['cagr','max_drawdown','alpha_annual_arithmetic'])}

阶段统计各自从区间首日收盘重设净值，首日收益不计入该阶段指标。IC含2015年极端市场和制度变化，IM没有经历这一阶段，直接拿两者全样本风险高低作选择会有样本偏差。分段结果仍是事后描述。

近月IC的最大回撤从2015-06-12高点到2015-09-01低点，至2020-02-21才恢复；IM从2022-08-18到2024-02-05，至2024-11-11恢复。即使最终赚钱，持有人也可能经历多年低于历史高点的净值。

## 指标定义与验证

CAGR按实际日历天数/365.25计算；波动为每日净收益样本标准差×√252；夏普为`(平均日收益×252−2%)/年化波动`。最大回撤为每日收盘NAV相对此前高点的最小跌幅，包含初始权益；日内追保采用另一套低价压力计算，不能与收盘回撤混为一谈。年化系数252为统一惯例，不等于本样本每年实际交易日数。

独立核验了{count:,}条每日组合损益，用源合约今开/今收/昨收和实际手数逐条重算，最大资金误差小于0.0001元；校验净值复利、前日可交易合约集合、前日权益定仓、禁止反向换月、指数与基差贡献加总。收盘模型还逐日核对了现金结算和按收盘估值的权益衔接。详见`validation.json`，该核验不代表行情本身已经由第二官方数据源审计。

本轮完成了日线历史研究。尚未完成的实盘级要素是：全收益指数/真实ETF基准、完整逐日保证金与费率/开仓限制表、期货公司加收、盘口或分钟级成交及强平模拟。它们对“可实现的纯alpha”和高杠杆可行性有直接影响；本报告不把这些缺项默认为已满足。

## 文件与重跑

主结果以`open_`开头：`open_summary.csv`、`open_daily_backtests.csv`、`open_sensitivity.csv`、`open_margin_sensitivity.csv`、`open_regression.csv`、`open_annual_returns.csv`、`open_integer_accounts.csv`、`open_common_period.csv`。没有`open_`前缀的对应结果主要是收盘成交参照模型。`futures_clean.csv`是清洗后的期货明细，`spot_indices.csv`是现货基准，`source_manifest.csv`记录原ZIP摘要。

下载研究包后，在包根目录安装`requirements.txt`中的Python依赖，依次运行`python work/backtest.py`、`python work/extra_analysis.py`、`python work/report.py`即可基于随包清洗数据重算，不需要联网。若更新原始数据，先修改`work/prepare.py`的SRC目录及截至日期，再运行清洗脚本；联网请求响应缓存已随包保存。

## 来源

- 期货行情：用户提供的中金所逐日行情ZIP，源文件路径和SHA-256见清单；本轮未重新下载这些期货行情。
- 现货行情：[腾讯行情接口](https://web.ifzq.gtimg.cn/appstock/app/fqkline/get)，具体请求URL见`data_audit.json`，原始JSON随研究包保存，获取日期2026-09-07。
- 合约乘数、到期及交割规则：[中金所IC产品](https://www.cffex.com.cn/cn/zz500.html)、[中金所IM产品](https://www.cffex.com.cn/zz1000/)。产品合约表最低保证金8%不等于所有历史时点实际执行比例。
- 上市时间：[证监会关于IM上市的公告](https://www.csrc.gov.cn/csrc/c100028/c4576490/content.shtml)。
- 费用背景：[中金所2024年收费一览表](https://www.cffex.com.cn/cn/zjssf/20240701/39212.html)。本报告使用统一综合成本情景，未将这一时点费率回填所有年份。
- 历史保证金变动实例：[国联期货转发2015年9月保证金调整通知](https://www.glqh.com/jygz/38404.jhtml)，用于说明制度约束，并未据此伪造完整历史保证金曲线。
'''
(O/'回测报告.md').write_text(report,encoding='utf-8')
html=markdown.markdown(report,extensions=['tables','fenced_code'])
for name in ['open_performance.png','open_leverage.png']:html=html.replace(f'src="{name}"',f'src="data:image/png;base64,{base64.b64encode((O/name).read_bytes()).decode()}"')
css='body{font-family:"Microsoft YaHei",system-ui,sans-serif;max-width:1100px;margin:auto;padding:38px 24px;color:#203047;line-height:1.8;background:#fafbfc}h1{font-size:32px;color:#15365b}h2{margin-top:44px;border-bottom:2px solid #dbe5ef;padding-bottom:8px;font-size:23px}table{border-collapse:collapse;width:100%;font-size:13px;margin:18px 0;background:white}th{background:#1d4169;color:white;text-align:left}td,th{padding:8px 10px;border-bottom:1px solid #e3e9ef}tr:nth-child(even){background:#f0f4f8}img{width:100%;height:auto}code{background:#eaf0f5;padding:2px 4px;overflow-wrap:anywhere}a{color:#1663a0}p,li{overflow-wrap:anywhere}strong{color:#173e65}@media print{body{max-width:none;padding:0;font-size:11px}h2{break-after:avoid}table,img{break-inside:avoid}a{color:inherit}}'
(O/'回测报告.html').write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IC与IM滚贴水回测</title><style>{css}</style><body>{html}</body></html>',encoding='utf-8')
(O/'requirements.txt').write_text('pandas>=2.2,<3\nnumpy>=1.26\nstatsmodels>=0.14\nmatplotlib>=3.8\nrequests>=2.31\nMarkdown>=3.5\ntabulate>=0.9\n',encoding='utf-8')
print('Report written. Independent checks:',json.dumps(checks,ensure_ascii=False));print(pd.DataFrame(period).query("rule=='front'")[['product','period','cagr','alpha_annual_arithmetic']].to_string(index=False))
