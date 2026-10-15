"""Optional read-only eBay US Browse source. Never posts or labels offers as sales."""
import hashlib,json,os,threading,time
from urllib.parse import quote
import requests
from dotenv import dotenv_values
import store

_lock=threading.Lock()
_token={}
BASE='https://api.ebay.com'

def config():
    values={**os.environ,**{k:v for k,v in dotenv_values(store.ROOT/'.env').items() if k.startswith('EBAY_BROWSE_') and v is not None}}
    return {'enabled':values.get('EBAY_BROWSE_ENABLED','false').lower()=='true','client_id':values.get('EBAY_BROWSE_CLIENT_ID',''),'client_secret':values.get('EBAY_BROWSE_CLIENT_SECRET','')}

def configured():
    c=config();return bool(c['enabled'] and c['client_id'] and c['client_secret'])

def request(path,params=None):
    c=config()
    if not configured():raise RuntimeError('eBay Browse requires separate Production application keys and explicit enabling.')
    with _lock:
        if _token.get('client_id')!=c['client_id'] or time.time()>=_token.get('expires_at',0):
            try:r=requests.post(BASE+'/identity/v1/oauth2/token',auth=(c['client_id'],c['client_secret']),data={'grant_type':'client_credentials','scope':'https://api.ebay.com/oauth/api_scope'},timeout=(10,30))
            except requests.RequestException:raise RuntimeError('eBay Browse authorization could not be reached.') from None
            if not r.ok:raise RuntimeError('eBay Browse authorization failed. Check Production keys and API access.')
            value=r.json();_token.update(client_id=c['client_id'],access_token=value['access_token'],expires_at=time.time()+int(value['expires_in'])-60)
        token=_token['access_token']
    try:r=requests.get(BASE+'/buy/browse/v1'+path,params=params,headers={'Authorization':'Bearer '+token,'X-EBAY-C-MARKETPLACE-ID':'EBAY_US'},timeout=(10,30))
    except requests.RequestException:raise RuntimeError('eBay Browse source is unavailable.') from None
    if not r.ok:raise RuntimeError(f'eBay Browse returned HTTP {r.status_code}; no API price was accepted.')
    return r.json()

def collect(item):
    import research,faults
    import ebay_notifications
    rows=[];sources=[]
    try:
        if not ebay_notifications.sync():raise RuntimeError('eBay notification inbox must sync before price research can continue.')
        condition_filter='conditionIds:{7000}' if item.get('specs',{}).get('working')=='No' else 'conditions:{USED}'
        query=item['title']+' '+str(item.get('specs',{}).get('storage',''))+' '+faults.terms(item,'US')
        result=request('/item_summary/search',{'q':query.strip(),'limit':10,'filter':'priceCurrency:USD,itemLocationCountry:US,buyingOptions:{FIXED_PRICE},'+condition_filter})
        for summary in result.get('itemSummaries',[])[:10]:
            details=request('/item/'+quote(summary['itemId'],safe=''))
            name=str(details.get('title',''));url=details.get('itemWebUrl','');reason=None
            description=str(details.get('condition',''))+' '+str(details.get('shortDescription',''))+' '+json.dumps(details.get('localizedAspects',[]),ensure_ascii=False)
            matched,reason=research.model_match(item,name,description)
            condition=research.condition_from(details.get('condition',''),name+' '+description)
            available=any(a.get('estimatedAvailabilityStatus')=='IN_STOCK' for a in details.get('estimatedAvailabilities',[]))
            if not matched or condition in ['New','Unknown'] or not available or details.get('itemLocation',{}).get('country')!='US':
                sources.append({'url':url,'status':'rejected','reason':reason if not matched else 'Current available US pre-owned offer not confirmed.'});continue
            price=details.get('price',{})
            try:value=research.amount(price.get('value'))
            except (ValueError,TypeError):continue
            username=details.get('seller',{}).get('username')
            if price.get('currency')!='USD' or value<=0 or not username:continue
            if not ebay_notifications.allowed_seller(username):continue
            proof={k:details.get(k) for k in ['itemId','title','price','condition','localizedAspects','itemLocation','estimatedAvailabilities','shippingOptions']}
            proof['description']=description[:3000]
            row=dict(title=name,model_key=item['model_key'],price=value,currency='USD',market='US',match_level=item.get('_research_mode','exact'),kind='asking',condition=condition,source='verified_api',source_name='eBay',seller_id='ebay:'+username,url=research.canonical(url),observed_at=store.now(),age_days=0,page_sha256=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest(),evidence=proof,verification='Official eBay Browse getItem response',availability='InStock',match_reason=reason,transaction_verified=False,shipping='Delivery and taxes not verified')
            for option in details.get('shippingOptions',[]):
                cost=option.get('shippingCost',{})
                if option.get('shipToLocationUsedForEstimate',{}).get('country')!='US' or cost.get('currency')!='USD':continue
                try:shipping=research.amount(cost.get('value'))
                except (ValueError,TypeError):continue
                if shipping>=0 and shipping<row.get('shipping_amount',float('inf')):row.update(shipping_amount=shipping,shipping_currency='USD',shipping='Source-backed US delivery estimate')
            rows.append(row);sources.append({'url':url,'status':'verified','reason':'Official current asking price; not a completed transaction.'})
    except RuntimeError as exc:sources.append({'url':'https://developer.ebay.com/develop/api/buy/browse_api','status':'unavailable','reason':str(exc)})
    return rows,sources
