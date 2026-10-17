"""Optional read-only eBay US Browse source. Never posts or labels offers as sales."""
import hashlib,json,os,re,threading,time
from datetime import datetime,timezone
from urllib.parse import quote,urlsplit,urlunsplit,parse_qsl,urlencode
import requests
from dotenv import dotenv_values
import store

_lock=threading.Lock()
_token={}
BASE='https://api.ebay.com'

def queries(item):
    """Search product identity rather than the seller's marketing description."""
    import research,faults
    identity=item.get('model_key','')
    if research.unknown(identity):identity=item.get('title','')
    identity=re.sub(r'[-_]+',' ',identity).strip()
    brand=item.get('brand','')
    if not research.unknown(brand) and research.norm(brand) not in research.norm(identity):identity=brand+' '+identity
    specs=item.get('specs',{})
    configuration=' '.join(str(specs[k]) for k in ['processor','memory','storage'] if not research.unknown(specs.get(k)))
    fault=faults.terms(item,'US')
    return list(dict.fromkeys(q[:100].strip() for q in [f'{identity} {configuration} {fault}',f'{identity} {fault}'] if q.strip()))

def condition(details):
    """Category-independent eBay condition IDs take priority over prose."""
    value=str(details.get('conditionId',''))
    if value in ['1000','1500','1750']:return 'New'
    if value in ['2000','2010','2020','2030','2500']:return 'Refurbished'
    if value=='7000':return 'For parts / not working'
    import research
    return research.condition_from(details.get('condition',''),details.get('title',''))

def offer(item,details):
    """Validate one live getItem record without storing it or estimating prices."""
    import research,ebay_notifications
    name=str(details.get('title',''));url=details.get('itemWebUrl','')
    description=str(details.get('condition',''))+' '+str(details.get('conditionDescription',''))+' '+str(details.get('shortDescription',''))+' '+json.dumps(details.get('localizedAspects',[]),ensure_ascii=False)
    matched,reason=research.model_match(item,name,description)
    if not matched:return None,reason
    normalized=research.norm(name)
    if item.get('category') not in ['Accessory','Parts'] and re.search(r'\b(?:stand only|base only|panel only|motherboard only|box only|parts only|replacement (?:stand|base|panel|motherboard|power supply)|(?:stand|base|motherboard|power supply) for)\b',normalized):
        return None,'An accessory or replacement part is not a whole-item comparison.'
    grade=condition(details)
    if grade in ['New','Unknown']:return None,'Comparable pre-owned condition is not confirmed.'
    if 'FIXED_PRICE' not in details.get('buyingOptions',[]):return None,'A current fixed-price offer is required; auction bids are not asking-price evidence.'
    try:
        # Live Browse responses use 0 for listings that are not lots.
        lot_size=int(details.get('lotSize',0))
        if lot_size>1:return None,'Multi-unit lots are not single-item comparisons.'
        if lot_size<0:return None,'The number of units is not confirmed.'
    except (ValueError,TypeError):return None,'The number of units is not confirmed.'
    if not any(a.get('estimatedAvailabilityStatus')=='IN_STOCK' for a in details.get('estimatedAvailabilities',[])):return None,'Current in-stock availability is not confirmed.'
    if details.get('itemEndDate'):
        try:
            end=datetime.fromisoformat(details['itemEndDate'].replace('Z','+00:00'))
            if end<=datetime.now(timezone.utc):return None,'The source listing has ended.'
        except (ValueError,TypeError):return None,'Listing end date is invalid.'
    if details.get('itemLocation',{}).get('country')!='US':return None,'The source item is not located in the US.'
    try:value=research.amount(details.get('price',{}).get('value'))
    except (ValueError,TypeError):return None,'A valid current item price is missing.'
    username=details.get('seller',{}).get('username')
    if details.get('price',{}).get('currency')!='USD' or value<=0 or not username:return None,'USD price and independent seller identity are required.'
    if not ebay_notifications.allowed_seller(username):return None,'Source seller is no longer eligible for research.'
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ['www.ebay.com','ebay.com'] or not parsed.path.startswith('/itm/'):return None,'A canonical US eBay listing URL is required.'
    url=urlunsplit(('https','www.ebay.com',parsed.path,urlencode([(k,v) for k,v in parse_qsl(parsed.query) if k=='var']),''))
    proof={k:details.get(k) for k in ['itemId','title','price','condition','conditionId','conditionDescription','localizedAspects','itemLocation','estimatedAvailabilities','shippingOptions','buyingOptions','itemEndDate','lotSize']}
    proof['description']=description[:6000]
    row=dict(title=name,model_key=item['model_key'],price=value,currency='USD',market='US',match_level=item.get('_research_mode','exact'),kind='asking',condition=grade,source='verified_api',source_name='eBay',seller_id='ebay:'+username,url=research.canonical(url),observed_at=store.now(),age_days=0,page_sha256=hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest(),evidence=proof,verification='Official eBay Browse getItem response',availability='InStock',match_reason=reason,transaction_verified=False,shipping='Delivery and taxes not verified')
    for option in details.get('shippingOptions',[]):
        cost=option.get('shippingCost',{})
        if option.get('shipToLocationUsedForEstimate',{}).get('country')!='US' or cost.get('currency')!='USD':continue
        if option.get('quantityUsedForEstimate',1)!=1:continue
        try:shipping=research.amount(cost.get('value'))
        except (ValueError,TypeError):continue
        if shipping>=0 and shipping<row.get('shipping_amount',float('inf')):row.update(shipping_amount=shipping,shipping_currency='USD',shipping='Source-backed US delivery estimate; taxes excluded')
    return row,'Official current asking price; not a completed transaction.'

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
            try:r=requests.post(BASE+'/identity/v1/oauth2/token',auth=(c['client_id'],c['client_secret']),data={'grant_type':'client_credentials','scope':'https://api.ebay.com/oauth/api_scope'},timeout=(10,30),allow_redirects=False)
            except requests.RequestException:raise RuntimeError('eBay Browse authorization could not be reached.') from None
            if not r.ok:raise RuntimeError('eBay Browse authorization failed. Check Production keys and API access.')
            value=r.json();_token.update(client_id=c['client_id'],access_token=value['access_token'],expires_at=time.time()+int(value['expires_in'])-60)
        token=_token['access_token']
    try:r=requests.get(BASE+'/buy/browse/v1'+path,params=params,headers={'Authorization':'Bearer '+token,'X-EBAY-C-MARKETPLACE-ID':'EBAY_US'},timeout=(10,30),allow_redirects=False)
    except requests.RequestException:raise RuntimeError('eBay Browse source is unavailable.') from None
    if not r.ok:raise RuntimeError(f'eBay Browse returned HTTP {r.status_code}; no API price was accepted.')
    return r.json()

def collect(item):
    import faults,ebay_notifications
    rows=[];sources=[];seen=set()
    try:
        if not ebay_notifications.sync():raise RuntimeError('eBay notification inbox must sync before price research can continue.')
        condition_filter='conditionIds:{7000}' if faults.profile(item)['faulty'] else 'conditions:{USED}'
        filters='priceCurrency:USD,itemLocationCountry:US,buyingOptions:{FIXED_PRICE},'+condition_filter
        for query in queries(item):
            result=request('/item_summary/search',{'q':query,'limit':30,'filter':filters})
            for summary in result.get('itemSummaries',[])[:30]:
                item_id=summary.get('itemId')
                if not item_id or item_id in seen:continue
                seen.add(item_id)
                # Fetch no more than 30 unique detailed offers across all searches.
                if len(seen)>30:break
                url=summary.get('itemWebUrl','https://www.ebay.com')
                try:
                    details=request('/item/'+quote(item_id,safe=''))
                    row,reason=offer(item,details)
                    if row:rows.append(row)
                    sources.append({'url':details.get('itemWebUrl',url),'status':'verified' if row else 'rejected','reason':reason})
                except (RuntimeError,ValueError,TypeError,KeyError):
                    sources.append({'url':url,'status':'unavailable','reason':'This eBay listing could not be verified; its price was not accepted.'})
            if len(rows)>=12 or len(seen)>=30:break
    except RuntimeError as exc:sources.append({'url':'https://developer.ebay.com/develop/api/buy/browse_api','status':'unavailable','reason':str(exc)})
    return rows,sources
