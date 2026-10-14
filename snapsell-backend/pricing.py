"""No LLM in the numeric path: robust comparable estimates + constrained logistic regression."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit,urlunsplit
import numpy as np
import store

CONDITION = {'Like new':None,'Excellent':None,'Good':None,'Fair':None,'Refurbished':None}

def key(text):
    return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')

def completeness(item):
    specs=item.get('specs',{})
    required=['screen','included','battery'] if item['category']=='Laptop' else ['screen','included','pixel_test'] if item['category']=='Monitor' else ['included','size','material']
    known=sum(bool(specs.get(k)) and not any(s in str(specs.get(k)).lower() for s in ['not tested','not verified','unknown']) for k in required)
    return min(1, .4+.6*known/len(required))

def quantile(values, weights, q):
    order=np.argsort(values); v=np.asarray(values)[order]; w=np.asarray(weights)[order]
    return float(np.interp(q,(np.cumsum(w)-.5*w)/sum(w),v))

def comparables(item):
    rows=[dict(r) for r in store.all_rows('comparables') if r.get('source')!='synthetic' and key(r['model_key'])==key(item['model_key']) and (r.get('item_id') in [None,item['id']])]
    selected=[]
    for row in rows:
        reason=None
        if row['source']=='verified_web':
            from research import fingerprint
            if row.get('item_fingerprint')!=fingerprint(item): reason='The item model, configuration or condition changed. Run research again.'
            if not row.get('page_sha256') or not row.get('evidence') or row.get('kind')!='asking': reason='Source-page verification is missing.'
            try:
                row['age_days']=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(row['observed_at'])).total_seconds()/86400)
                if row['age_days']>7: reason='Web observation is older than seven days. Run research again.'
            except (ValueError,KeyError): reason='Verification date is missing.'
        c=row.get('condition','Unknown')
        if (item['condition']=='Refurbished') != (c=='Refurbished'): reason=reason or 'Refurbished retail and used inventory are separate condition classes.'
        if c in ['Unknown','New']: reason='Comparable pre-owned condition is not confirmed.'
        if row.get('kind')=='sold' and not row.get('transaction_verified'): reason='Completed transaction value is not independently confirmed.'
        row['included']=reason is None
        row['exclusion_reason']=reason
        if reason is None: selected.append(row)
    sold=[r for r in selected if r['kind']=='sold']
    if len(sold)>=3: selected=sold
    def page_identity(row):
        if not row.get('url'):return row['id']
        p=urlsplit(row['url']);return urlunsplit((p.scheme.lower(),p.netloc.lower().removeprefix('www.'),p.path.rstrip('/'),'',''))
    independent_pages=len({page_identity(r) for r in selected})
    independent_merchants=len({str(r.get('source_name') or 'Seller import').lower().removeprefix('www.') for r in selected})
    reference_rows=[r for r in rows if r.get('exclusion_reason')=='Refurbished retail and used inventory are separate condition classes.']
    reference=None
    if reference_rows:
        reference={'low':min(r['price'] for r in reference_rows),'high':max(r['price'] for r in reference_rows),'count':len(reference_rows),'label':'Refurbished retail references; not a direct used-item valuation.'}
    base=dict(rows=rows,available=False,source='verified_web' if any(r['source']=='verified_web' for r in rows) else 'imported',sample_count=len(selected),independent_pages=independent_pages,independent_merchants=independent_merchants,reference_band=reference,basis='At least three distinct product pages from two merchants are required for an automatic estimate. Individual verified offers remain available as evidence. No numeric condition adjustment is invented.')
    if len(selected)<3 or independent_pages<3 or (any(r['source']=='verified_web' for r in selected) and independent_merchants<2): return base
    # No condition multipliers: source condition is retained and different grades remain visible.
    values=[r['price'] for r in selected]
    domain_counts={r.get('source_name','Seller import'):sum(x.get('source_name','Seller import')==r.get('source_name','Seller import') for x in selected) for r in selected}
    weights=[math.exp(-min(r.get('age_days',0),365)/45)/domain_counts[r.get('source_name','Seller import')] for r in selected]
    median=float(np.median(values)); mad=float(np.median(np.abs(np.asarray(values)-median)))
    keep=[i for i,v in enumerate(values) if mad==0 or abs(v-median)<=3.5*1.4826*mad]
    values=[values[i] for i in keep]; weights=[weights[i] for i in keep]
    effective=sum(weights)**2/sum(w*w for w in weights)
    if len(values)<3: return {**base,'basis':'Fewer than three observations survived the outlier check. No price estimate is published.'}
    return dict(available=True,median=round(quantile(values,weights,.5),2),low=round(quantile(values,weights,.25),2),high=round(quantile(values,weights,.75),2),sample_count=len(values),domain_count=len(domain_counts),independent_pages=independent_pages,independent_merchants=independent_merchants,reference_band=reference,effective_samples=round(effective,1),source=base['source'],kind='sold' if len(sold)>=3 else 'asking',confidence='Moderate' if effective>=8 and len(domain_counts)>=3 else 'Low',rows=rows,basis='Exact model and recorded capacity matching; source condition retained without numeric adjustment; per-merchant balancing; recency weights; MAD outlier filter; weighted median and interquartile range. Asking prices exclude unverified shipping and taxes. This is not a completed-sale valuation or a confidence interval.')

def features(row):
    return [1,row['price_ratio']-1,row['age_days']/60,row['excellent'],row['monitor'],row['completeness']-.7]

_cache={}

def fit_model():
    rows=store.all_rows('history')
    real=[r for r in rows if r['source']!='synthetic']
    using_real=len(real)>=120 and len({r['sold_within_7_days'] for r in real})==2
    if not using_real: return None
    candidates=real
    digest=hashlib.sha256(json.dumps(candidates,sort_keys=True).encode()).hexdigest()
    if digest in _cache:
        return _cache[digest]
    if len(candidates)<120:
        return None
    candidates=sorted(candidates,key=lambda r:r['observed_at'])
    n=len(candidates); cut=int(n*.7); valcut=int(n*.85)
    train=candidates[:cut]; calibration=candidates[cut:valcut]; test=candidates[valcut:]
    if len({r['sold_within_7_days'] for r in train})<2:
        return None
    x=np.array([features(r) for r in train]); y=np.array([r['sold_within_7_days'] for r in train])
    beta=np.zeros(6)
    for _ in range(1800):
        p=1/(1+np.exp(-np.clip(x@beta,-25,25)))
        grad=x.T@(p-y)/len(y)+.002*np.r_[0,beta[1:]]
        beta-=.45*grad
        beta[1]=min(0,beta[1])  # sale probability must not increase when price rises
    vx=np.array([features(r) for r in calibration]); vy=np.array([r['sold_within_7_days'] for r in calibration])
    temperatures=[.7,1,1.3,1.6,2]
    temp=min(temperatures,key=lambda t:float(np.mean((1/(1+np.exp(-np.clip(vx@beta/t,-25,25)))-vy)**2)))
    tx=np.array([features(r) for r in test]); ty=np.array([r['sold_within_7_days'] for r in test])
    prediction=1/(1+np.exp(-np.clip(tx@beta/temp,-25,25)))
    baseline=float(y.mean()); bins=[]
    for lo in np.arange(0,1,.2):
        mask=(prediction>=lo)&(prediction<lo+.2)
        if mask.any():
            bins.append({'predicted':round(float(prediction[mask].mean()),3),'observed':round(float(ty[mask].mean()),3),'n':int(mask.sum())})
    report=dict(source='imported' if using_real else 'synthetic',rows=n,train_rows=cut,calibration_rows=valcut-cut,test_rows=n-valcut,brier=round(float(np.mean((prediction-ty)**2)),4),baseline_brier=round(float(np.mean((baseline-ty)**2)),4),log_loss=round(float(-np.mean(ty*np.log(prediction+1e-9)+(1-ty)*np.log(1-prediction+1e-9))),4),temperature=temp,coefficients=[round(float(b),4) for b in beta],calibration=bins,method='L2-regularized logistic regression, non-positive price coefficient, chronological 70/15/15 split, temperature chosen on calibration set; final test set used only for reporting.',limitation='Associational prediction, not causal uplift. Synthetic validation does not establish real market performance.',pending_real_rows=len(real) if not using_real else 0)
    model=(beta,temp,report)
    _cache.clear(); _cache[digest]=model
    return model

def probability(item,price,market,model):
    ratio=price/market
    if not .65<=ratio<=1.4:
        return None
    r=dict(price_ratio=ratio,age_days=item.get('age_days',0),excellent=int(item['condition'] in ['Excellent','Like new']),monitor=int(item['category']=='Monitor'),completeness=completeness(item))
    beta,temp,_=model
    return float(1/(1+math.exp(-float(np.array(features(r))@beta/temp))))

def evaluate(item):
    comp=comparables(item); model=fit_model() if item['category'] in ['Laptop','Monitor'] else None
    if not comp['available']:
        return dict(comparables=comp,strategies=[],curve=[],model=model[2] if model else None)
    market=comp['median']; floor=max(item['reserve'],math.ceil(item['cost']/(1-item['fee_rate'])))
    # Price recommendation cannot violate the merchant floor or the training support.
    low=max(floor,round(market*.70)); high=round(market*1.35)
    curve=[]
    for price in np.linspace(low,high,45) if low<=high else []:
        price=round(float(price)); p=probability(item,price,market,model) if model else None
        margin=price*(1-item['fee_rate'])-item['cost']
        ev=margin*p-item.get('holding_cost',.35)*7*(1-p) if p is not None else None
        curve.append(dict(price=price,sale_probability=round(p,4) if p is not None else None,net_margin=round(margin,2),expected_contribution=round(ev,2) if ev is not None else None))
    strategies=[]
    if curve and model:
        selected=[('fast','Sell sooner',max(curve,key=lambda r:r['sale_probability'])),('balanced','Best expected return',max(curve,key=lambda r:r['expected_contribution'])),('premium','Aim higher',max([r for r in curve if r['sale_probability']>=.30] or curve,key=lambda r:r['price']))]
        strategies=[dict(id=s,title=t,**r) for s,t,r in selected]
    elif not model:
        curve=[]
        if comp['high']>=floor:
            strategies=[dict(id=s,title=t,price=round(max(floor,value)),sale_probability=None,expected_contribution=None,net_margin=round(max(floor,value)*(1-item['fee_rate'])-item['cost'],2),basis='Observed asking-price position; no sale-speed or demand forecast.') for s,t,value in [('fast','Lower market quartile',comp['low']),('balanced','Market median',comp['median']),('premium','Upper market quartile',comp['high'])]]
    currentp=probability(item,item['price'],market,model) if model else None
    currentmargin=item['price']*(1-item['fee_rate'])-item['cost']
    return dict(comparables=comp,strategies=strategies,curve=curve,model=model[2] if model else None,floor=floor,current=dict(price=item['price'],sale_probability=round(currentp,4) if currentp is not None else None,net_margin=round(currentmargin,2)),objective='7-day expected contribution = P(sale) × (price × (1 − fee) − cost) − 7 × daily holding cost × (1 − P(sale)). Excludes unsold asset value; use to compare the same item over a fixed horizon.')
