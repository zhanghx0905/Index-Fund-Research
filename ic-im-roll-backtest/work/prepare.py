import pathlib,zipfile,io,re,json,concurrent.futures
import pandas as pd,numpy as np,requests
ROOT=pathlib.Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'; OUT.mkdir(exist_ok=True)
SRC=pathlib.Path(r'C:/Users/zhx09/Desktop/cffex_history_zip')
rows=[]; errors=[]; dates=[]
source_zips=sorted(SRC.glob('*.zip'))
for p in source_zips:
 try:
  with zipfile.ZipFile(p) as z:
   for n in z.namelist():
    if not re.search(r'\d{8}.*\.csv$',n):continue
    date=pd.to_datetime(re.search(r'(\d{8})',n)[1]); dates.append(date)
    b=z.read(n)
    for enc in ['utf-8-sig','gb18030']:
     try: s=b.decode(enc);break
     except UnicodeDecodeError:pass
    df=pd.read_csv(io.StringIO(s),dtype=str)
    # Positional exchange daily schema, preserve actual source headers in audit.
    df=df.iloc[:,:11]; df.columns=['contract','open','high','low','volume','turnover','oi','oi_change','close','settle','prev_settle']
    df['contract']=df.contract.str.strip();df=df[df.contract.str.fullmatch(r'(IC|IM)\d{4}',na=False)].copy()
    df['date']=date;df['source_zip']=p.name;df['source_file']=n
    rows.append(df)
 except Exception as e:errors.append([p.name,str(e)])
d=pd.concat(rows,ignore_index=True)
for c in ['open','high','low','volume','turnover','oi','oi_change','close','settle','prev_settle']:d[c]=pd.to_numeric(d[c],errors='coerce')
d['product']=d.contract.str[:2];d=d.sort_values(['date','contract'])
dup=d.duplicated(['date','contract'],False);dups=d[dup];dups.to_csv(OUT/'duplicate_rows.csv',index=False,encoding='utf-8-sig')
if len(dups):
 assert not d.groupby(['date','contract'])[['open','close','settle']].nunique().gt(1).any().any(),'Conflicting duplicate prices'
d=d.drop_duplicates(['date','contract'])
bad=(d[['close','settle','prev_settle']].isna().any(axis=1)|(d[['close','settle','prev_settle']]<=0).any(axis=1)|(d.date>pd.Timestamp('2026-09-07')))
d[bad].to_csv(OUT/'quarantined_rows.csv',index=False,encoding='utf-8-sig');clean=d[~bad].copy()
clean.to_csv(OUT/'futures_clean.csv',index=False,encoding='utf-8-sig')
audit={'zip_count':len(source_zips),'csv_files':len(dates),'source_dates':len(set(dates)),'raw_target_rows':len(d),'duplicate_rows':len(dups),'quarantined_rows':int(bad.sum()),'errors':errors,'coverage':{p:{'start':str(g.date.min().date()),'end':str(g.date.max().date()),'days':g.date.nunique(),'rows':len(g),'contracts':g.contract.nunique(),'zero_volume':int((g.volume==0).sum())} for p,g in clean.groupby('product')}}
prev=clean.groupby('contract').settle.shift();gap=(clean.prev_settle-prev).abs();audit['prev_settle_mismatches']=int((gap>0.11).sum())
clean[gap>0.11].assign(prior_observed_settle=prev[gap>0.11]).to_csv(OUT/'settlement_discrepancies.csv',index=False,encoding='utf-8-sig')
def fetch(arg):
 symbol,start,end=arg;url='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get';params={'param':f'{symbol},day,{start},{end},2000,qfq'}
 r=requests.get(url,params=params,timeout=40);r.raise_for_status();j=r.json();p=ROOT/'work'/f'{symbol}_{start}.json';p.write_text(json.dumps(j,ensure_ascii=False),encoding='utf-8'); x=j['data'][symbol];a=x.get('day',x.get('qfqday',[]));return symbol,a,r.url
args=[(s,a,b) for s in ['sh000905','sh000852'] for a,b in [('2015-01-01','2020-12-31'),('2021-01-01','2026-09-07')]]
spot=[];sources=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 for symbol,a,url in pool.map(fetch,args):
  sources.append(url)
  for row in a:spot.append({'date':row[0],'symbol':symbol,'open':float(row[1]),'close':float(row[2]),'high':float(row[3]),'low':float(row[4])})
s=pd.DataFrame(spot).drop_duplicates(['date','symbol']).sort_values(['symbol','date']);s.to_csv(OUT/'spot_indices.csv',index=False,encoding='utf-8-sig')
audit['spot_sources']=sources;audit['spot_coverage']={p:{'start':g.date.min(),'end':g.date.max(),'days':len(g)} for p,g in s.groupby('symbol')}
(OUT/'data_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2,default=int),encoding='utf-8');print(json.dumps(audit,ensure_ascii=False,indent=2,default=int))
