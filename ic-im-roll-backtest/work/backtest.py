"""IC/IM roll research. Historical scenarios, not an execution engine."""
import pathlib,json,calendar,math,functools
import numpy as np,pandas as pd,statsmodels.api as sm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from types import SimpleNamespace
ROOT=pathlib.Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'
F=pd.read_csv(OUT/'futures_clean.csv',parse_dates=['date']); S=pd.read_csv(OUT/'spot_indices.csv',parse_dates=['date'])
RF=.02; MULT=200; COST=.0001
@functools.lru_cache(None)
def expiry(c):
 y=2000+int(c[2:4]);m=int(c[4:6]);a=pd.Timestamp(y,m,1);e=a+pd.Timedelta(days=(4-a.weekday())%7+14)
 # Official holiday adjustment uses observed exchange calendar, not future prices.
 cal=sorted(F.date.unique());after=[pd.Timestamp(d) for d in cal if pd.Timestamp(d)>=e]
 return after[0] if after else e
F['expiry']=F.contract.map({c:expiry(c) for c in F.contract.unique()})
LOOK={p:g.set_index(['date','contract']) for p,g in F.groupby('product')}
PRICES={p:SimpleNamespace(loc={(r.date,r.contract):r for r in g.itertuples(index=False)}) for p,g in F.groupby('product')}
@functools.lru_cache(None)
def schedule(product,rule,roll=7):
 g=F[F['product']==product];dates=sorted(g.date.unique());spot=S[S.symbol=={'IC':'sh000905','IM':'sh000852'}[product]].set_index('date').close
 assert all(pd.Timestamp(d) in spot.index for d in dates),'Missing benchmark date'
 out=[];last=None
 for i,d in enumerate(dates):
  d=pd.Timestamp(d)
  if i==0:out.append(None);continue
  prev=pd.Timestamp(dates[i-1]);a=g[g.date==prev].copy();a['dte']=(a.expiry-d).dt.days
  a=a[(a.dte>roll)&(a.volume>0)&(a.oi>0)].sort_values('expiry')
  if last is not None:a=a[a.expiry>=expiry(last)] # Never roll backwards.
  assert len(a),f'No eligible contract {product} {d}'
  if rule=='front':c=a.iloc[0].contract
  elif rule=='next':
   # Keep the selected second-nearest until its scheduled roll date.
   if last in a.contract.values:c=last
   else:c=a.iloc[min(1,len(a)-1)].contract
  elif rule=='far':
   if last in a.contract.values:c=last
   else:c=a.iloc[-1].contract
  elif rule=='carry':
   # Choose only at scheduled rolls, reducing noisy daily switching.
   if last in a.contract.values:c=last
   else:
    aa=a[(a.dte>=20)&(a.volume>=100)&(a.oi>=1000)].copy()
    if len(aa)==0:aa=a.copy()
    aa['score']=(spot.loc[prev]/aa.close-1)*365/aa.dte;c=aa.sort_values(['score','expiry'],ascending=[False,True]).iloc[0].contract
  elif rule=='liquid':c=a.sort_values(['oi','expiry'],ascending=[False,True]).iloc[0].contract
  else:raise ValueError(rule)
  assert (d,c) in LOOK[product].index
  out.append(c);last=c
 return pd.Series(out,index=pd.DatetimeIndex(dates)),spot

def simulate(product,rule='front',L=1,cost=COST,roll=7,capital=1e7,integer=False,rebalance='daily',margin=None,stop=False,cash_rate=0):
 sched,spot=schedule(product,rule,roll);lk=PRICES[product];equity=capital;cash=capital;q=0.;held=None;records=[];events=[];dead=False
 for i,d in enumerate(sched.index):
  before=equity;pnl=market=basis=vm=0.;loweq=equity;low_notional=0.;oldq=q;old=held;first_breach=False
  if i>0 and q:
   prev=sched.index[i-1];r=lk.loc[(d,held)];pr=lk.loc[(prev,held)]
   pnl=q*MULT*(r.close-pr.close);market=q*MULT*(spot.loc[d]-spot.loc[prev]);basis=pnl-market
   vm=q*MULT*(r.settle-pr.settle);cash+=vm
   loweq=before+q*MULT*(r.low-pr.close);low_notional=q*MULT*r.low
  equity+=pnl
  # Cash yield scenario credits total equity daily; baseline zero, no assumption of interest on exchange deposits.
  interest=max(before,0)*cash_rate*((d-sched.index[i-1]).days/365 if i else 0);equity+=interest;cash+=interest
  chosen=sched.loc[d];fees=turnover=0.;rolled=False
  intrabreach=bool(margin is not None and oldq and loweq<margin*low_notional)
  if equity<=0:dead=True
  if stop and intrabreach:dead=True;first_breach=True
  if dead:chosen=None
  if i==0:chosen=None
  if chosen is not None:
   px=lk.loc[(d,chosen)].close
   change=(chosen!=held)
   newq=(L*max(equity,0)/(MULT*px)) if (change or rebalance=='daily') else q
   if integer:newq=math.floor(newq)
   if change:
    turnover=(q*MULT*lk.loc[(d,held)].close if held else 0)+newq*MULT*px
    rolled=held is not None
   else:turnover=abs(newq-q)*MULT*px
   fees=turnover*cost
   # Reconcile daily settlement cash against close-marked total equity.
   if held:cash+=q*MULT*(lk.loc[(d,held)].close-lk.loc[(d,held)].settle)
   cash+=newq*MULT*(lk.loc[(d,chosen)].settle-px)-fees
   equity-=fees;q=newq;held=chosen
  elif held is not None:
   turnover=q*MULT*lk.loc[(d,held)].close;fees=turnover*cost;equity-=fees
   cash+=q*MULT*(lk.loc[(d,held)].close-lk.loc[(d,held)].settle)-fees;q=0;held=None
  notional=q*MULT*lk.loc[(d,held)].settle if held else 0
  checkeq=cash+(q*MULT*(lk.loc[(d,held)].close-lk.loc[(d,held)].settle) if held else 0)
  assert abs(checkeq-equity)<max(.0001,abs(equity)*1e-9),'Settlement/close reconciliation failed'
  eodbreach=bool(margin is not None and cash<margin*notional)
  if rolled or (old is None and held):events.append(dict(date=d,old_contract=old,new_contract=held,old_quantity=oldq,new_quantity=q,turnover=turnover,cost=fees,old_close=lk.loc[(d,old)].close if old else None,new_close=lk.loc[(d,held)].close))
  records.append(dict(date=d,product=product,rule=rule,held_contract=held,quantity=q,nav=equity/capital,equity=equity,settlement_cash=cash,return_net=equity/before-1 if before>0 else 0,return_gross=pnl/before if before>0 else 0,market_contribution=market/before if before>0 else 0,basis_contribution=basis/before if before>0 else 0,cost_return=fees/before if before>0 else 0,interest_return=interest/before if before>0 else 0,spot_return=spot.loc[d]/spot.loc[sched.index[i-1]]-1 if i else 0,turnover=turnover,fees=fees,roll=rolled,notional=notional,leverage=notional/equity if equity>0 else np.nan,intraday_low_equity=loweq,low_notional=low_notional,intraday_breach=intrabreach,eod_breach=eodbreach,stopped=dead,vm=vm))
 a=pd.DataFrame(records).set_index('date')
 assert np.allclose(a.return_gross,a.market_contribution+a.basis_contribution,atol=1e-10)
 assert np.allclose(a.return_net,a.return_gross-a.cost_return+a.interest_return,atol=1e-10) or (a.nav<=0).any()
 return a,pd.DataFrame(events)

def stats(a):
 r=a.return_net.iloc[1:];nav=a.nav;years=(a.index[-1]-a.index[0]).days/365.25;vol=r.std(ddof=1)*np.sqrt(252);dd=nav/nav.cummax()-1
 trough=dd.idxmin();peak=nav.loc[:trough].idxmax();post=nav.loc[trough:];recovered=post[post>=nav.loc[peak]]
 return dict(start=str(a.index[0].date()),end=str(a.index[-1].date()),observations=len(r),total_return=nav.iloc[-1]/nav.iloc[0]-1,cagr=(nav.iloc[-1]/nav.iloc[0])**(1/years)-1 if nav.iloc[-1]>0 else -1,volatility=vol,sharpe=(r.mean()*252-RF)/vol if vol else np.nan,max_drawdown=dd.min(),worst_day=r.min(),best_day=r.max(),calmar=((nav.iloc[-1]/nav.iloc[0])**(1/years)-1)/abs(dd.min()) if nav.iloc[-1]>0 and dd.min()<0 else np.nan,dd_peak=str(peak.date()),dd_trough=str(trough.date()),dd_recovery=str(recovered.index[0].date()) if len(recovered) else 'unrecovered',rolls=int(a['roll'].sum()),mean_leverage=a.leverage.mean())

def regression(a):
 b=a.iloc[1:];x=b.spot_return;y=b.return_net
 reg=sm.OLS(y-RF/252,sm.add_constant(x-RF/252)).fit(cov_type='HAC',cov_kwds={'maxlags':5})
 ci=reg.conf_int().iloc[0]*252
 monthly=pd.DataFrame({'f':(1+y).resample('ME').prod()-1,'s':(1+x).resample('ME').prod()-1}).iloc[1:-1]
 rm=sm.OLS(monthly.f-RF/12,sm.add_constant(monthly.s-RF/12)).fit(cov_type='HAC',cov_kwds={'maxlags':3})
 return dict(beta=reg.params.iloc[1],correlation=x.corr(y),r_squared=reg.rsquared,alpha_annual_arithmetic=reg.params.iloc[0]*252,alpha_ci_low=ci.iloc[0],alpha_ci_high=ci.iloc[1],alpha_t_hac=reg.tvalues.iloc[0],monthly_beta=rm.params.iloc[1],monthly_alpha=rm.params.iloc[0]*12,monthly_alpha_t_hac=rm.tvalues.iloc[0],mean_basis_contribution_annual=b.basis_contribution.mean()*252,mean_market_contribution_annual=b.market_contribution.mean()*252,mean_cost_annual=b.cost_return.mean()*252)

if __name__=='__main__':
 allstats=[];base={};daily=[];trades=[];annual=[];regress=[];sensitivity=[];margins=[];integer=[];rulemap={'front':'近月','next':'次近月持有','far':'远月持有','carry':'最大年化贴水持有','liquid':'持仓量主力'}
 for product in ['IC','IM']:
  for rule in rulemap:
   a,t=simulate(product,rule);base[(product,rule)]=a;allstats.append(dict(product=product,rule=rule,**stats(a)));daily.append(a.reset_index());t['product']=product;t['rule']=rule;trades.append(t)
   regress.append(dict(product=product,rule=rule,**regression(a)))
   for year,g in a.iloc[1:].groupby(a.index[1:].year):
    r=g.return_net;sr=g.spot_return;annual.append(dict(product=product,rule=rule,year=year,return_net=(1+r).prod()-1,spot_return=(1+sr).prod()-1,volatility=r.std()*np.sqrt(252),basis_arithmetic=g.basis_contribution.sum(),cost=g.cost_return.sum(),days=len(g)))
  a=base[(product,'front')];r=a.spot_return;bench=a.copy();bench['return_net']=r;bench['nav']=(1+r).cumprod();allstats.append(dict(product=product,rule='spot_price',**stats(bench)))
  for L in [.5,1,1.5,2,2.5,3,4,5]:
   a,t=simulate(product,L=L)
   sensitivity.append(dict(product=product,scenario='leverage',parameter=L,**stats(a)))
   for m in [.08,.12,.15,.20,.30,.40]:
    intra=(a.intraday_low_equity<m*a.low_notional)&(a.low_notional>0);eod=(a.settlement_cash<m*a.notional)&(a.notional>0);breach=intra|eod
    margins.append(dict(product=product,leverage=L,margin_rate=m,initial_target_usage=L*m,initial_feasible=L*m<1,breach_days=int(breach.sum()),first_breach=str(a.index[breach][0].date()) if breach.any() else '',max_eod_usage=(m*a.notional/a.settlement_cash.replace(0,np.nan)).max(),min_intraday_buffer=(a.intraday_low_equity-m*a.low_notional).min()/1e7))
  for c in [0,.00005,.0001,.0002,.0005,.001]:
   a,t=simulate(product,cost=c);sensitivity.append(dict(product=product,scenario='one_way_cost',parameter=c,**stats(a)))
  for roll in [3,7,10,14]:
   a,t=simulate(product,roll=roll);sensitivity.append(dict(product=product,scenario='roll_calendar_days',parameter=roll,**stats(a)))
  for capital in [1e6,5e6,1e7]:
   for L in [1,2]:
    a,t=simulate(product,L=L,capital=capital,integer=True,rebalance='roll');integer.append(dict(product=product,capital=capital,target_leverage=L,**stats(a)))
  for rate in [.01,.02]:
   a,t=simulate(product,cash_rate=rate);sensitivity.append(dict(product=product,scenario='cash_yield_on_total_equity',parameter=rate,**stats(a)))
 for name,data in [('summary',allstats),('regression',regress),('annual_returns',annual),('sensitivity',sensitivity),('margin_sensitivity',margins),('integer_accounts',integer)]:pd.DataFrame(data).to_csv(OUT/f'{name}.csv',index=False,encoding='utf-8-sig')
 pd.concat(daily).to_csv(OUT/'daily_backtests.csv',index=False,encoding='utf-8-sig');pd.concat(trades).to_csv(OUT/'roll_trades.csv',index=False,encoding='utf-8-sig')
 # Compare products on shared sample without IC's pre-IM history.
 common=[]
 for p in ['IC','IM']:
  for rule in ['front','far','carry']:
   a=base[(p,rule)].loc['2022-07-25':].copy();a['nav']=(1+a.return_net).cumprod();a['nav']/=a.nav.iloc[0];common.append(dict(product=p,rule=rule,**stats(a),**regression(a)))
 pd.DataFrame(common).to_csv(OUT/'common_period.csv',index=False,encoding='utf-8-sig')
 plt.rcParams.update({'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.2,'figure.facecolor':'white'})
 fig,ax=plt.subplots(2,2,figsize=(14,9),height_ratios=[1.3,1])
 colors={'front':'#2463a5','next':'#228b75','far':'#b67823','carry':'#ab4875','liquid':'#777777'}
 for j,p in enumerate(['IC','IM']):
  for rule in ['front','next','far','carry']:
   a=base[(p,rule)];ax[0,j].plot(a.index,a.nav,label=rule,color=colors[rule],lw=1.4)
  a=base[(p,'front')];bn=(1+a.spot_return).cumprod();ax[0,j].plot(a.index,bn,label='spot price',c='black',ls='--',lw=1.2);ax[0,j].set_title(f'{p}: fully funded, 1x daily target');ax[0,j].set_ylabel('Net asset value');ax[0,j].legend(fontsize=9)
  ax[1,j].fill_between(a.index,(a.nav/a.nav.cummax()-1)*100,0,color=colors['front'],alpha=.35,label='front');ax[1,j].plot(a.index,(bn/bn.cummax()-1)*100,c='black',ls='--',label='spot price');ax[1,j].set_ylabel('Drawdown (%)');ax[1,j].legend()
 fig.suptitle('IC / IM rolling futures | 1 bp one-way costs | no cash interest',fontsize=15);fig.tight_layout();fig.savefig(OUT/'performance.png',dpi=170);plt.close(fig)
 fig,ax=plt.subplots(1,2,figsize=(13,4.5))
 for p in ['IC','IM']:
  g=pd.DataFrame(sensitivity).query("product==@p and scenario=='leverage'")
  ax[0].plot(g.parameter,g.cagr*100,marker='o',label=p);ax[1].plot(g.parameter,g.max_drawdown*100,marker='o',label=p)
 for a in ax:a.set_xlabel('Daily target notional / equity');a.legend()
 ax[0].set_ylabel('CAGR (%)');ax[1].set_ylabel('Maximum drawdown (%)');fig.suptitle('Theoretical leverage sensitivity before forced liquidation');fig.tight_layout();fig.savefig(OUT/'leverage.png',dpi=170);plt.close(fig)
 print(pd.DataFrame(allstats)[['product','rule','cagr','volatility','sharpe','max_drawdown']].to_string(index=False));print(pd.DataFrame(regress).to_string(index=False));print('DONE')
