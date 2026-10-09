import pathlib,json
import pandas as pd,numpy as np
from backtest import F,S,OUT,schedule,PRICES,MULT,COST,stats,regression,simulate

def open_execution(product,L=1,integer=False,capital=1e7,rule='front',cost=COST,roll=7,rebalance='daily'):
 sched,spot=schedule(product,rule,roll);lk=PRICES[product].loc;E=capital;q=0;held=None;result=[];turns=0
 spotopen=S[S.symbol=={'IC':'sh000905','IM':'sh000852'}[product]].set_index('date').open
 for i,d in enumerate(sched.index):
  before=E;gross=0;fee=0;rolled=False;market=0;loweq=E;lownotional=0;cash=E;notional=0;turnover=0
  if i:
   prev=sched.index[i-1];c=sched.loc[d]
   # All quantity inputs are fixed at yesterday's close; execution today's open.
   newq=L*before/(MULT*lk[(prev,c)].close) if (rebalance=='daily' or c!=held) else q
   if integer:newq=np.floor(newq)
   if held:
    gross+=q*MULT*(lk[(d,held)].open-lk[(prev,held)].close)
    market+=q*MULT*(spotopen.loc[d]-spot.loc[prev])
   turnover=(q*MULT*lk[(d,held)].open+newq*MULT*lk[(d,c)].open) if held and c!=held else abs(newq-q)*MULT*lk[(d,c)].open
   fee=cost*turnover
   loweq=before+gross-fee+newq*MULT*(lk[(d,c)].low-lk[(d,c)].open);lownotional=newq*MULT*lk[(d,c)].low
   gross+=newq*MULT*(lk[(d,c)].close-lk[(d,c)].open)
   market+=newq*MULT*(spot.loc[d]-spotopen.loc[d])
   rolled=held is not None and c!=held;held=c;q=newq;E+=gross-fee
   cash=E+q*MULT*(lk[(d,held)].settle-lk[(d,held)].close);notional=q*MULT*lk[(d,held)].settle
  result.append({'date':d,'product':product,'rule':rule,'nav':E/capital,'equity':E,'quantity':q,'held_contract':held,'return_net':E/before-1,'return_gross':gross/before,'market_contribution':market/before,'basis_contribution':(gross-market)/before,'cost_return':fee/before,'spot_return':(spot.loc[d]/(spotopen.loc[d] if i==1 else spot.loc[sched.index[i-1]])-1) if i else 0,'roll':rolled,'leverage':q*MULT*lk[(d,held)].close/E if held else 0,'intraday_low_equity':loweq,'low_notional':lownotional,'settlement_cash':cash,'notional':notional,'turnover':turnover,'fees':fee})
 return pd.DataFrame(result).set_index('date')

audit=json.loads((OUT/'data_audit.json').read_text(encoding='utf-8'))
audit['ohlc_invalid_rows']=int(((F.high<F.low)|(F.close>F.high+.001)|(F.close<F.low-.001)|(F.open>F.high+.001)|(F.open<F.low-.001)).sum())
audit['missing_spot_dates']={p:len(set(g.date)-set(S[S.symbol=={'IC':'sh000905','IM':'sh000852'}[p]].date)) for p,g in F.groupby('product')}
audit['missing_futures_vs_spot_calendar']={p:len(set(S[(S.symbol=={'IC':'sh000905','IM':'sh000852'}[p])&(S.date>=g.date.min())&(S.date<=g.date.max())].date)-set(g.date)) for p,g in F.groupby('product')}
(OUT/'data_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
res=[];regs=[];ds=[];sens=[];ms=[];ints=[]
for p in ['IC','IM']:
 for rule in ['front','next','far','carry','liquid']:
  a=open_execution(p,rule=rule);res.append(dict(product=p,rule=rule,**stats(a)));regs.append(dict(product=p,rule=rule,**regression(a)));ds.append(a.reset_index())
  assert np.allclose(a.return_gross,a.market_contribution+a.basis_contribution)
  assert np.allclose(a.return_net,a.return_gross-a.cost_return)
  if rule=='front':
   a.to_csv(OUT/f'{p}_next_open_daily.csv',encoding='utf-8-sig');b=a.copy();b['return_net']=a.spot_return;b['nav']=(1+b.return_net).cumprod();res.append(dict(product=p,rule='spot_price',**stats(b)))
 for L in [.5,1,1.5,2,2.5,3,4,5]:
  a=open_execution(p,L=L);sens.append(dict(product=p,scenario='leverage',parameter=L,**stats(a)))
  for m in [.08,.12,.15,.2,.3,.4]:
   intra=(a.intraday_low_equity<m*a.low_notional)&(a.low_notional>0);eod=(a.settlement_cash<m*a.notional)&(a.notional>0);breach=intra|eod
   ms.append(dict(product=p,leverage=L,margin_rate=m,initial_target_usage=L*m,initial_feasible=L*m<1,breach_days=int(breach.sum()),first_breach=str(a.index[breach][0].date()) if breach.any() else '',max_eod_usage=(m*a.notional/a.settlement_cash.replace(0,np.nan)).max(),min_intraday_buffer=(a.intraday_low_equity-m*a.low_notional).min()/1e7))
 for c in [0,.00005,.0001,.0002,.0005,.001]:
  a=open_execution(p,cost=c);sens.append(dict(product=p,scenario='one_way_cost',parameter=c,**stats(a)))
 for roll in [3,7,10,14]:
  a=open_execution(p,roll=roll);sens.append(dict(product=p,scenario='roll_calendar_days',parameter=roll,**stats(a)))
 for capital in [1e6,5e6,1e7]:
  for L in [1,2]:
   a=open_execution(p,L=L,capital=capital,integer=True,rebalance='roll');ints.append(dict(product=p,capital=capital,target_leverage=L,**stats(a)))
pd.DataFrame(res).to_csv(OUT/'execution_sensitivity.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(res).to_csv(OUT/'open_summary.csv',index=False,encoding='utf-8-sig');pd.DataFrame(regs).to_csv(OUT/'open_regression.csv',index=False,encoding='utf-8-sig');pd.DataFrame(sens).to_csv(OUT/'open_sensitivity.csv',index=False,encoding='utf-8-sig');pd.DataFrame(ms).to_csv(OUT/'open_margin_sensitivity.csv',index=False,encoding='utf-8-sig');pd.DataFrame(ints).to_csv(OUT/'open_integer_accounts.csv',index=False,encoding='utf-8-sig')
pd.concat(ds).to_csv(OUT/'open_daily_backtests.csv',index=False,encoding='utf-8-sig')

daily=pd.read_csv(OUT/'daily_backtests.csv',parse_dates=['date']);basis=[];neutral=[];regimes=[]
for p in ['IC','IM']:
 g=F[F['product']==p].merge(S[S.symbol=={'IC':'sh000905','IM':'sh000852'}[p]][['date','close']].rename(columns={'close':'spot'}),on='date',validate='many_to_one')
 g['basis_points']=g.close-g.spot;g['discount']=1-g.close/g.spot;g['dte']=(g.expiry-g.date).dt.days;g['annualized_discount']=(g.spot/g.close-1)*365/g.dte.replace(0,np.nan);g.to_csv(OUT/f'{p}_basis_panel.csv',index=False,encoding='utf-8-sig')
 for rule in ['front','next','far','carry','liquid']:
  a=daily[(daily['product']==p)&(daily.rule==rule)].set_index('date')
  # Fixed point-matched short spot removes q*dS; diagnostic only, before shorting/dividends/funding.
  r=a.basis_contribution-a.cost_return; b=a.copy();b['return_net']=r;b['nav']=(1+r).cumprod();neutral.append(dict(product=p,rule=rule,label='point_matched_spot_hedge_diagnostic',**stats(b),correlation_to_spot=r.corr(a.spot_return)))
  for start,end,label in [('2015-04-16','2018-12-31','2015-2018'),('2019-01-01','2022-12-31','2019-2022'),('2023-01-01','2026-09-07','2023-2026'),('2022-07-25','2026-09-07','shared_since_IM')]:
   z=a.loc[start:end].copy()
   if len(z)<30:continue
   z['nav']=(1+z.return_net).cumprod();z['nav']/=z.nav.iloc[0];regimes.append(dict(product=p,rule=rule,period=label,**stats(z),**regression(z)))
  merged=a.reset_index().merge(g[['date','contract','discount','annualized_discount','dte']],left_on=['date','held_contract'],right_on=['date','contract'],how='left')
  basis.append(dict(product=p,rule=rule,discount_mean=merged.discount.mean(),discount_median=merged.discount.median(),discount_fraction=(merged.discount.dropna()>0).mean(),annualized_discount_median=merged.annualized_discount.median(),dte_mean=merged.dte.mean()))
pd.DataFrame(basis).to_csv(OUT/'basis_summary.csv',index=False,encoding='utf-8-sig');pd.DataFrame(neutral).to_csv(OUT/'hedged_diagnostic.csv',index=False,encoding='utf-8-sig');pd.DataFrame(regimes).to_csv(OUT/'regime_analysis.csv',index=False,encoding='utf-8-sig')
print(pd.DataFrame(res).to_string(index=False));print(pd.DataFrame(neutral)[['product','rule','cagr','volatility','max_drawdown','correlation_to_spot']].to_string(index=False));print(json.dumps(audit,ensure_ascii=False))
