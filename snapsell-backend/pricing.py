"""No LLM in the numeric path: robust comparable estimates + constrained logistic regression."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit,urlunsplit
import numpy as np
import store
import markets
import faults

CONDITION = {'Not verified':None,'For parts / not working':None,'Damaged / faulty':None,'Like new':None,'Excellent':None,'Good':None,'Fair':None,'Refurbished':None}

def key(text):
    return re.sub(r'[\W_]+','-',text.casefold(),flags=re.UNICODE).strip('-')

def completeness(item):
    specs=item.get('specs',{})
    required=['screen','included','battery'] if item['category']=='Laptop' else ['screen','included','pixel_test'] if item['category']=='Monitor' else ['included','size','material']
    known=sum(bool(specs.get(k)) and not any(s in str(specs.get(k)).lower() for s in ['not tested','not verified','unknown']) for k in required)
    return min(1, .4+.6*known/len(required))

def quantile(values, weights, q):
    order=np.argsort(values); v=np.asarray(values)[order]; w=np.asarray(weights)[order]
    return float(np.interp(q,(np.cumsum(w)-.5*w)/sum(w),v))

def comparables(item,market='US',mode='exact',basis='item'):
    currency=markets.get(market)['currency']
    if mode not in ['exact','similar'] or basis not in ['item','delivered']:raise ValueError('Unsupported research matching mode or price basis.')
    from research import fingerprint,unknown
    rows=[dict(r) for r in store.all_rows('comparables') if r.get('source')!='synthetic' and key(r['model_key'])==key(item['model_key']) and r.get('item_id') in [None,item['id']]]
    selected=[]
    def page_id(row):
        if not row.get('url'):return row['id']
        p=urlsplit(row['url']);return urlunsplit((p.scheme.lower(),p.netloc.lower().removeprefix('www.'),p.path.rstrip('/'),'',''))
    def seller(row):return row.get('seller_id') or str(row.get('source_name') or 'Seller import').casefold().removeprefix('www.')
    for row in rows:
        reason=None
        if mode=='exact' and unknown(item.get('model_key')):reason='Confirm an exact model before using exact-model valuations.'
        elif row.get('market','US')!=market or row.get('currency','USD')!=currency:reason='Different research market or currency.'
        elif row.get('match_level','exact')!=mode:reason='Different product matching mode.'
        elif row.get('source') in ['verified_web','verified_api']:
            if row.get('item_fingerprint')!=fingerprint(item):reason='The item identity or specifications changed. Run research again.'
            elif not row.get('evidence') or not row.get('page_sha256') or row.get('kind')!='asking':reason='Source verification is missing.'
            try:
                stamp=datetime.fromisoformat(row['observed_at'])
                if stamp.tzinfo is None:raise ValueError('Timezone missing')
                row['age_days']=(datetime.now(timezone.utc)-stamp).total_seconds()/86400
                if not 0<=row['age_days']<=7:reason=reason or 'Source observation is expired or has a future timestamp.'
            except (ValueError,KeyError,TypeError):reason=reason or 'Verification date is missing or invalid.'
        condition=row.get('condition','Unknown')
        source_faulty=condition in ['For parts / not working','Damaged / faulty'] or faults.source(row.get('title',''),str(row.get('evidence',{}).get('description',row.get('evidence',{}).get('description_quote',''))))['faulty']
        if faults.profile(item)['faulty']!=source_faulty:reason=reason or 'Working and faulty units are separate price comparisons.'
        if faults.profile(item)['faulty'] and not faults.match(item,row.get('title',''),str(row.get('evidence',{}).get('description',row.get('evidence',{}).get('description_quote',''))))[0]:reason=reason or 'The disclosed fault type is not confirmed on the source offer.'
        if not faults.profile(item)['faulty'] and (item['condition']=='Refurbished')!=(condition=='Refurbished'):reason=reason or 'Refurbished retail and used inventory are separate condition classes.'
        if row.get('comparison_differences'):reason=reason or 'Source colour differs; reference only.'
        if condition in ['Unknown','New']:reason=reason or 'Comparable pre-owned condition is not confirmed.'
        if row.get('kind')=='sold' and not row.get('transaction_verified'):reason=reason or 'Completed transaction value is not independently confirmed.'
        elif row.get('kind')=='sold':reason=reason or 'Completed transaction prices are separate from current asking-price comparisons.'
        try:
            price=float(row['price'])
            if not math.isfinite(price) or price<=0:raise ValueError('Invalid price')
            if basis=='delivered':
                shipping=float(row['shipping_amount'])
                if row.get('shipping_currency')!=currency or not math.isfinite(shipping) or shipping<0:raise ValueError('Unverified shipping')
                price+=shipping
            row['comparison_price']=price
        except (ValueError,TypeError,KeyError):reason=reason or 'Valid price and requested shipping evidence are missing.'
        row.update(included=reason is None,exclusion_reason=reason)
        if reason is None:selected.append(row)
    # Count each source product page once, preferring the matching recorded grade.
    independent={}
    for row in sorted(selected,key=lambda r:(r.get('condition')==item['condition'],str(r.get('observed_at',''))),reverse=True):
        identity=page_id(row)
        if identity in independent:row.update(included=False,exclusion_reason='Duplicate product page or variant; not an independent observation.')
        else:independent[identity]=row
    selected=list(independent.values())
    values=np.array([r['comparison_price'] for r in selected])
    if len(values)>=3:
        median=float(np.median(values));mad=float(np.median(np.abs(values-median)))
        width=3.5*1.4826*mad if mad else max(1,median*.875)
        retained=[]
        for row in selected:
            if abs(row['comparison_price']-median)>width:row.update(included=False,exclusion_reason='Price outside the robust observed range; excluded as an outlier.')
            else:retained.append(row)
        selected=retained
    sellers={seller(r) for r in selected};pages={page_id(r) for r in selected}
    verified=any(r.get('source') in ['verified_web','verified_api'] for r in selected)
    market_info=markets.get(market)
    result=dict(rows=rows,available=False,source='verified_api' if any(r.get('source')=='verified_api' for r in selected) else 'verified_web' if verified else 'imported',market=market,currency=currency,match_level=mode,price_basis=basis,sample_count=len(selected),independent_pages=len(pages),independent_merchants=len(sellers),reference_band=None,shipping_observations=sum(r.get('shipping_currency')==currency and r.get('shipping_amount') is not None for r in selected),basis='At least three independent offers and two sellers are needed for automatic web/API estimates. Asking prices are not completed sales. Taxes remain unverified.')
    condition_references=[r['comparison_price'] for r in rows if r.get('exclusion_reason')=='Refurbished retail and used inventory are separate condition classes.' and r.get('comparison_price')]
    if condition_references:
        result['reference_band']={'low':min(condition_references),'median':float(np.median(condition_references)),'high':max(condition_references),'count':len(condition_references),'label':'Other-condition offers; not a direct valuation of this item.'}
    import assessment
    result['preliminary']=assessment.reference(item,result)
    fault_profile=faults.profile(item)
    result['assessment']={'fault_profile':fault_profile,'message':'Describe the current fault or choose its type; research now searches damaged whole items.' if fault_profile['faulty'] and not fault_profile['types'] else 'Research compares the same disclosed fault type; working-device offers are excluded.' if fault_profile['faulty'] else 'Current operation is separate from repair history. Unknown battery health limits confidence, not whether the item can be listed.'}
    if item.get('category')=='Phone' and (any(k in assessment.uncertainties(item) for k in ['storage','working']) or (result['preliminary'] and result['preliminary']['suggested_price'] is None)):
        result['basis']='Complete the key phone checks before setting a single price. Current checked offers remain visible as references.'
        return result
    if len(selected)<3 or len(pages)<3 or (verified and len(sellers)<2):return result
    counts={name:sum(seller(r)==name for r in selected) for name in sellers}
    weights=[math.exp(-min(r.get('age_days',0),365)/7)/counts[seller(r)] for r in selected]
    values=[r['comparison_price'] for r in selected];effective=sum(weights)**2/sum(w*w for w in weights)
    band=dict(low=round(quantile(values,weights,.25),2),median=round(quantile(values,weights,.5),2),high=round(quantile(values,weights,.75),2))
    stamps=[datetime.fromisoformat(r['observed_at']) for r in selected if r.get('source') in ['verified_web','verified_api']]
    result.update(**band,effective_samples=round(effective,1),domain_count=len(sellers),confidence='Moderate' if verified and effective>=8 and len(sellers)>=3 else 'Low',kind='asking',expires_at=(min(stamps)+timedelta(days=7)).isoformat() if stamps else None)
    if mode=='similar':
        result.update(reference_band={**band,'count':len(selected),'label':'Similar-product asking-price reference; exact model is unconfirmed.'},basis='Similar offers only. This is not an exact-model valuation and cannot set a listing price automatically.')
    else:result['available']=True
    return result

def features(row):
    return [1,row['price_ratio']-1,row['age_days']/60,row['excellent'],row['monitor'],row['completeness']-.7]

_cache={}

def fit_model():
    rows=store.all_rows('history')
    real=[r for r in rows if r['source']!='synthetic' and r.get('market','US')=='US' and r.get('currency','USD')=='USD']
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
    if any(len({r['sold_within_7_days'] for r in part})<2 for part in [calibration,test]):return None
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
    if report['brier']>=report['baseline_brier']:return None
    report.update(source='observed_and_imported' if any(r['source']=='seller_reported_observed' for r in real) else 'imported',source_counts={source:sum(r['source']==source for r in real) for source in {r['source'] for r in real}},limitation='Seller-reported observations and imported labels are not independently audited transactions. Associations do not establish causal uplift. Foreign markets and other categories are not covered.')
    _cache.clear(); _cache[digest]=model
    return model

def probability(item,price,market,model):
    ratio=price/market
    if not .65<=ratio<=1.4:
        return None
    r=dict(price_ratio=ratio,age_days=item.get('age_days',0),excellent=int(item['condition'] in ['Excellent','Like new']),monitor=int(item['category']=='Monitor'),completeness=completeness(item))
    beta,temp,_=model
    return float(1/(1+math.exp(-float(np.array(features(r))@beta/temp))))

def evaluate(item,market='US',mode='exact',basis='item'):
    comp=comparables(item,market,mode,basis); model=fit_model() if market=='US' and mode=='exact' and basis=='item' and item['category'] in ['Laptop','Monitor'] else None
    if not comp['available']:
        return dict(comparables=comp,strategies=[],curve=[],model=model[2] if model else None)
    if basis=='delivered':
        return dict(comparables=comp,strategies=[],curve=[],model=None,limitation='Delivered totals are comparison references, not item asking-price recommendations. Taxes remain unverified.')
    if markets.get(market)['currency']!=item.get('currency','USD'):
        return dict(comparables=comp,strategies=[],curve=[],model=None,limitation='Research currency differs from inventory accounting. No currency conversion or price application is performed.')
    market=comp['median']; floor=max(item['reserve'],math.ceil(item['cost']/(1-item['fee_rate'])))
    # Price recommendation cannot violate the merchant floor or the training support.
    low=max(floor,round(market*.70)); high=min(100000,round(market*1.35))
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
            strategies=[dict(id=s,title=t,price=round(max(floor,value)),sale_probability=None,expected_contribution=None,net_margin=round(max(floor,value)*(1-item['fee_rate'])-item['cost'],2),basis='Observed asking-price position; no sale-speed or demand forecast.') for s,t,value in [('fast','Lower market quartile',comp['low']),('balanced','Market median',comp['median']),('premium','Upper market quartile',comp['high'])] if max(floor,value)<=100000]
    currentp=probability(item,item['price'],market,model) if model else None
    currentmargin=item['price']*(1-item['fee_rate'])-item['cost']
    return dict(comparables=comp,strategies=strategies,curve=curve,model=model[2] if model else None,floor=floor,current=dict(price=item['price'],sale_probability=round(currentp,4) if currentp is not None else None,net_margin=round(currentmargin,2)),objective='7-day expected contribution = P(sale) × (price × (1 − fee) − cost) − 7 × daily holding cost × (1 − P(sale)). Excludes unsold asset value; use to compare the same item over a fixed horizon.')
