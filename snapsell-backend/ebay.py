"""Single-unit eBay US Inventory API connector. Sandbox is the default.

Only offers created by this connector are managed. Financial completion remains
seller-reported: soldQuantity is not evidence of payment, fees or fulfillment.
"""
import base64
import copy
import hashlib
import json
import os
import secrets
import threading
import time
from functools import wraps
from urllib.parse import quote, urlencode, urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values
import channels
import store

SCOPES=' '.join('https://api.ebay.com/oauth/api_scope'+s for s in ['', '/sell.inventory', '/sell.account.readonly'])
LOCK=threading.RLock()
OFFER_FIELDS={'availableQuantity','categoryId','charity','extendedProducerResponsibility','hideBuyerDetails','includeCatalogProductDetails','listingDescription','listingDuration','listingPolicies','listingStartDate','lotSize','merchantLocationKey','pricingSummary','quantityLimitPerBuyer','regulatory','secondaryCategoryId','storeCategoryNames','tax'}
INVENTORY_FIELDS={'availability','condition','conditionDescription','conditionDescriptors','packageWeightAndSize','product'}
CONDITIONS={'NEW':1000,'NEW_OTHER':1500,'NEW_WITH_DEFECTS':1750,'CERTIFIED_REFURBISHED':2000,'SELLER_REFURBISHED':2500,'LIKE_NEW':2750,'PRE_OWNED_EXCELLENT':2990,'USED_EXCELLENT':3000,'PRE_OWNED_FAIR':3010,'USED_VERY_GOOD':4000,'USED_GOOD':5000,'USED_ACCEPTABLE':6000,'FOR_PARTS_OR_NOT_WORKING':7000,'EXCELLENT_REFURBISHED':2010,'VERY_GOOD_REFURBISHED':2020,'GOOD_REFURBISHED':2030}

def serialized(fn):
    @wraps(fn)
    def run(*args,**kwargs):
        with LOCK:return fn(*args,**kwargs)
    return run

def identity_version(item):
    return hashlib.sha256(json.dumps({k:item.get(k) for k in ['brand','model_key','category','condition','specs','image']},sort_keys=True).encode()).hexdigest()

def acknowledge(row,item,price):
    snapshot={**item,'price':price}
    current=store.get('items',item['id'])
    if channels.version(current)==channels.version(item):
        current['price']=price;store.put('items',current)
    row.update(listing_version=channels.version(snapshot),identity_version=identity_version(snapshot))


def settings():
    values=dict(os.environ)
    values.update({k:v for k,v in dotenv_values(store.ROOT/'.env').items() if k.startswith('EBAY_') and v is not None})
    env=values.get('EBAY_ENVIRONMENT','sandbox').lower()
    if env not in ['sandbox','production']:raise ValueError('EBAY_ENVIRONMENT must be sandbox or production.')
    return {'environment':env,'base':'https://api.sandbox.ebay.com' if env=='sandbox' else 'https://api.ebay.com',
            'auth':'https://auth.sandbox.ebay.com/oauth2/authorize' if env=='sandbox' else 'https://auth.ebay.com/oauth2/authorize',
            'client_id':values.get('EBAY_CLIENT_ID','').strip(),'client_secret':values.get('EBAY_CLIENT_SECRET','').strip(),
            'runame':values.get('EBAY_RUNAME','').strip(),'refresh_token':values.get('EBAY_REFRESH_TOKEN','').strip(),'production_enabled':values.get('EBAY_ENABLE_PRODUCTION','false').lower()=='true'}


def token_path():return store.DATA/('.ebay-'+settings()['environment']+'.token')


def cipher():
    secret=(store.DATA/'.session-secret').read_bytes()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))


def read_tokens():
    if not token_path().exists():
        config=settings()
        return {'refresh_token':config['refresh_token'],'client_id':config['client_id']} if config['refresh_token'] else {}
    try:return json.loads(cipher().decrypt(token_path().read_bytes()))
    except (InvalidToken,ValueError):raise RuntimeError('Reconnect eBay: its saved authorization cannot be decrypted.')


def save_tokens(data):
    old=read_tokens()
    value={**old,**data,'expires_at':time.time()+int(data.get('expires_in',0))-60,'client_id':settings()['client_id']}
    path=token_path();temp=path.with_suffix('.tmp')
    temp.write_bytes(cipher().encrypt(json.dumps(value).encode()))
    temp.replace(path)


def status():
    config=settings();tokens=read_tokens()
    missing=[name for name in ['client_id','client_secret','runame'] if not config[name]]
    return {'environment':config['environment'],'configured':not missing,'connected':bool(tokens.get('refresh_token') and tokens.get('client_id')==config['client_id']),
            'missing':missing,'production_enabled':config['production_enabled'],
            'settings':(store.get('actions','ebay-settings-'+config['environment']) or {}).get('settings',{})}


def authorize_url(state):
    config=settings()
    if not status()['configured']:raise ValueError('Add EBAY_CLIENT_ID, EBAY_CLIENT_SECRET and EBAY_RUNAME to .env.')
    return config['auth']+'?'+urlencode({'client_id':config['client_id'],'redirect_uri':config['runame'],'response_type':'code','scope':SCOPES,'state':state})


def oauth(data):
    config=settings()
    try:r=requests.post(config['base']+'/identity/v1/oauth2/token',auth=(config['client_id'],config['client_secret']),data=data,timeout=(10,45))
    except requests.RequestException:raise RuntimeError('eBay authorization service is unavailable. Try again.') from None
    if not r.ok:raise RuntimeError('eBay authorization failed. Check the environment, keyset and RuName; reconnect if authorization expired.')
    return r.json()


def exchange(code):
    with LOCK:save_tokens(oauth({'grant_type':'authorization_code','code':code,'redirect_uri':settings()['runame']}))


def access_token(force=False):
    with LOCK:
        tokens=read_tokens()
        if not status()['connected']:raise ValueError('Connect the seller account to eBay first.')
        if force or time.time()>=tokens.get('expires_at',0):
            save_tokens(oauth({'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'scope':SCOPES}))
            tokens=read_tokens()
        return tokens['access_token']


class APIError(RuntimeError):
    def __init__(self,message,status_code):super().__init__(message);self.status_code=status_code


def api(method,path,payload=None,files=None):
    config=settings()
    if method not in ['GET','HEAD'] and config['environment']=='production' and not config['production_enabled']:
        raise ValueError('Production writes are disabled. Sandbox does not spend real money.')
    for attempt in range(2):
        headers={'Authorization':'Bearer '+access_token(force=bool(attempt)),'Content-Language':'en-US','Accept':'application/json'}
        if files is None:headers['Content-Type']='application/json'
        try:r=requests.request(method,config['base']+path,json=payload,files=files,headers=headers,timeout=(10,60))
        except requests.RequestException:raise RuntimeError('eBay request timed out or lost its connection. Check status before retrying publication.') from None
        if r.status_code==401 and attempt==0 and method=='GET':continue
        try:data=r.json() if r.content else {}
        except ValueError:data={}
        if not r.ok:
            errors=data.get('errors',[])
            message='; '.join(str(e.get('message','Request rejected')) for e in errors)[:700]
            raise APIError('eBay: '+(message or f'HTTP {r.status_code}'),r.status_code)
        if r.headers.get('Location'):data['_location']=r.headers['Location']
        return data


def options():
    result={}
    for name in ['fulfillment','payment','return']:
        data=api('GET',f'/sell/account/v1/{name}_policy?marketplace_id=EBAY_US')
        result[name]=data.get(name+'Policies',[])
    result['locations']=api('GET','/sell/inventory/v1/location?limit=100').get('locations',[])
    return result


def category_metadata(category_id):
    if not str(category_id).isdigit():raise ValueError('Enter a numeric eBay leaf category ID.')
    tree=api('GET','/commerce/taxonomy/v1/get_default_category_tree_id?marketplace_id=EBAY_US')['categoryTreeId']
    root=api('GET',f'/commerce/taxonomy/v1/category_tree/{quote(str(tree),safe="")}/get_category_subtree?category_id={category_id}')['categorySubtreeNode']
    if not root.get('leafCategoryTreeNode'):raise ValueError('Select a leaf category, not a parent category.')
    aspects=api('GET',f'/commerce/taxonomy/v1/category_tree/{quote(str(tree),safe="")}/get_item_aspects_for_category?category_id={category_id}').get('aspects',[])
    policies=api('GET','/sell/metadata/v1/marketplace/EBAY_US/get_item_condition_policies?'+urlencode({'filter':'categoryIds:{'+str(category_id)+'}'})).get('itemConditionPolicies',[])
    conditions=next((p.get('itemConditions',[]) for p in policies if str(p.get('categoryId'))==str(category_id)),[])
    return {'category':root['category'],'aspects':aspects,'conditions':conditions}


def save_settings(data):
    allowed={'merchantLocationKey','fulfillmentPolicyId','paymentPolicyId','returnPolicyId'}
    value={k:str(data.get(k,'')).strip()[:200] for k in allowed}
    store.put('actions',{'id':'ebay-settings-'+settings()['environment'],'type':'ebay_settings','settings':value})
    return value


def listing_for(item_id):
    env=settings()['environment']
    return next((a for a in channels.tracked(item_id,'ebay') if a.get('source')=='ebay_api' and a.get('environment')==env),None)


def save_listing(row):return store.put('actions',row)


def listing_id(item_id):return 'ebay-'+settings()['environment']+'-'+item_id


def attach_sku(item_id,sku):
    with LOCK:
        item=store.get('items',item_id)
        if not item or item['status'] in ['sold','sale_pending']:raise ValueError('Choose an unsold item.')
        if not item.get('confirmed'):raise ValueError('Review product facts and confirm that the eBay SKU belongs to this item.')
        if listing_for(item_id):raise ValueError('This item already has an eBay API record.')
        if not isinstance(sku,str) or not 1<=len(sku)<=50:raise ValueError('Enter an existing eBay Inventory API SKU (up to 50 characters).')
        rows=api('GET','/sell/inventory/v1/offer?'+urlencode({'sku':sku,'marketplace_id':'EBAY_US','format':'FIXED_PRICE'})).get('offers',[])
        if len(rows)!=1:raise ValueError('Expected one fixed-price eBay US offer for this SKU.')
        offer=rows[0]
        if offer.get('marketplaceId')!='EBAY_US' or offer.get('format')!='FIXED_PRICE' or offer.get('availableQuantity',0)>1:raise ValueError('This version manages single-unit fixed-price eBay US offers only.')
        inventory=api('GET','/sell/inventory/v1/inventory_item/'+quote(sku,safe=''))
        if inventory.get('groupIds') or inventory.get('availability',{}).get('shipToLocationAvailability',{}).get('quantity',0)>1:raise ValueError('Multiple-variation or multi-unit inventory is not supported.')
        if any(a.get('source')=='ebay_api' and a.get('environment')==settings()['environment'] and a.get('sku')==sku for a in store.all_rows('actions')):raise ValueError('This SKU is already linked to another local item.')
        policies=offer.get('listingPolicies',{})
        config={'categoryId':offer.get('categoryId'),'condition':inventory.get('condition'),'aspects':inventory.get('product',{}).get('aspects',{}),'imageUrls':inventory.get('product',{}).get('imageUrls',[]),'merchantLocationKey':offer.get('merchantLocationKey'),**{k:policies.get(k) for k in ['fulfillmentPolicyId','paymentPolicyId','returnPolicyId']}}
        row={'id':listing_id(item_id),'type':'external_listing','item_id':item_id,'platform':'ebay','source':'ebay_api','environment':settings()['environment'],'sku':sku,'offer_id':offer['offerId'],'status':'linked','publish_settings':config,'created_at':store.now()}
        # Imported remote content may differ: keep it visibly dirty until explicitly reviewed and updated.
        return apply_remote(row,offer)


def read_offer(row):
    if not row.get('offer_id'):raise ValueError('No eBay offer has been created for this item.')
    return api('GET','/sell/inventory/v1/offer/'+quote(row['offer_id'],safe=''))


def apply_remote(row,remote):
    listing=remote.get('listing',{});sold=int(listing.get('soldQuantity',0))
    remote_status=listing.get('listingStatus','UNKNOWN')
    row.update(remote_status=remote_status,offer_status=remote.get('status'),sold_quantity=sold,last_checked_at=store.now(),last_error=None)
    if listing.get('listingId'):
        row['listing_id']=listing['listingId']
        host='www.sandbox.ebay.com' if row['environment']=='sandbox' else 'www.ebay.com'
        row['url']=f'https://{host}/itm/{listing["listingId"]}'
    if sold>0:
        row['status']='sale_detected' if row.get('status')!='sold' else 'sold'
        item=store.get('items',row['item_id'])
        if item and item['status']!='sold':
            item.update(status='sale_pending',sale_detected_at=store.now());store.put('items',item)
        for other in store.all_rows('actions'):
            if other.get('type')=='external_listing' and other.get('item_id')==row['item_id'] and other['id']!=row['id'] and other.get('status')=='posted':
                other['status']='needs_removal';store.put('actions',other)
    elif remote.get('status')=='UNPUBLISHED' or remote_status=='ENDED':row['status']='removed'
    elif listing.get('listingOnHold'):row['status']='on_hold'
    elif remote_status=='ACTIVE':
        # Do not clear a queued removal after a sale on another marketplace.
        if row.get('status') not in ['sold','needs_removal']:row['status']='posted'
    else:row['status']='remote_unknown'
    save_listing(row)
    if row['status'] in ['removed','on_hold','remote_unknown']:
        import outcomes
        outcomes.invalidate(row['item_id'],'eBay availability changed during the observation window.')
    channels.reconcile_item(row['item_id'])
    return row


def check(item_id):
    with LOCK:
        row=listing_for(item_id)
        if not row:raise ValueError('This item has no API-connected eBay listing. A manually pasted URL is not an Inventory API offer.')
        return apply_remote(row,read_offer(row))


def payloads(item,data):
    if not isinstance(data,dict):raise ValueError('eBay settings must be an object.')
    kit,photo=channels.prepare(item,'ebay')
    if item['status'] in ['sold','sale_pending']:raise ValueError('This item has sold or has an eBay sale awaiting confirmation.')
    if not item.get('confirmed'):raise ValueError('Review product facts before publishing or updating eBay.')
    if kit['price_usd'] is None or kit['price_usd']<=0:raise ValueError('Set an asking price or obtain a supported recommendation.')
    if kit['price_usd']<max(item['reserve'],item['cost']/(1-item['fee_rate'])):raise ValueError('Price is below the recorded minimum or acquisition cost after fees.')
    config={**status()['settings'],**data}
    for field in ['merchantLocationKey','fulfillmentPolicyId','paymentPolicyId','returnPolicyId','categoryId','condition']:
        if not config.get(field):raise ValueError('Missing eBay field: '+field)
    if config['condition'] not in CONDITIONS:raise ValueError('Choose a supported eBay condition enumeration.')
    metadata=category_metadata(config['categoryId'])
    condition=next((c for c in metadata['conditions'] if str(c.get('conditionId'))==str(CONDITIONS[config['condition']])),None)
    if not condition:raise ValueError('This condition is not supported for the category or seller account.')
    if condition.get('conditionDescriptors'):raise ValueError('This category requires condition descriptors; select a supported category without grading descriptors for this version.')
    aspects=config.get('aspects',{})
    if not isinstance(aspects,dict) or len(aspects)>80 or any(not isinstance(k,str) or not isinstance(v,list) or not v or any(not isinstance(x,str) or not x.strip() for x in v) for k,v in aspects.items()):raise ValueError('Aspects must map eBay names to nonempty lists of text values.')
    for aspect in metadata['aspects']:
        constraint=aspect.get('aspectConstraint',{});name=aspect['localizedAspectName'];values=aspects.get(name,[])
        if constraint.get('aspectRequired') and not values:raise ValueError('Required eBay aspect: '+name)
        if constraint.get('aspectMode')=='SELECTION_ONLY':
            allowed={v['localizedValue'] for v in aspect.get('aspectValues',[])}
            if any(v not in allowed for v in values):raise ValueError('Choose a listed value for eBay aspect: '+name)
    urls=config.get('imageUrls',[])
    if not isinstance(urls,list) or len(urls)>24 or any(not isinstance(u,str) or urlsplit(u).scheme!='https' or not urlsplit(u).hostname or urlsplit(u).username or urlsplit(u).password for u in urls):raise ValueError('Provide up to 24 public HTTPS product photo URLs.')
    if not urls:
        if not photo:raise ValueError('Add a real product photo or public HTTPS product photo URLs.')
        if settings()['environment']=='sandbox':raise ValueError('Sandbox requires a public HTTPS product photo URL. Localhost photos cannot be fetched by eBay. Production supports direct EPS upload.')
        with photo.open('rb') as stream:
            uploaded=api('POST','/commerce/media/v1_beta/image/create_image_from_file',files={'image':(photo.name,stream,'image/jpeg')})
        if uploaded.get('imageUrl'):urls=[uploaded['imageUrl']]
        else:
            image_id=urlsplit(uploaded.get('_location','')).path.rsplit('/',1)[-1]
            if not image_id:raise RuntimeError('eBay did not return an uploaded image ID.')
            urls=[api('GET','/commerce/media/v1_beta/image/'+quote(image_id,safe=''))['imageUrl']]
    inventory={'availability':{'shipToLocationAvailability':{'quantity':1}},'condition':config['condition'],'conditionDescription':item['description'],
               'product':{'title':kit['title'],'description':kit['description'],'aspects':aspects,'imageUrls':urls}}
    offer={'sku':'snapsell-'+item['id'],'marketplaceId':'EBAY_US','format':'FIXED_PRICE','availableQuantity':1,'categoryId':str(config['categoryId']),
           'listingDescription':'<p>'+__import__('html').escape(kit['description']).replace('\n','<br>')+'</p>','listingDuration':'GTC','merchantLocationKey':str(config['merchantLocationKey']),
           'listingPolicies':{k:str(config[k]) for k in ['fulfillmentPolicyId','paymentPolicyId','returnPolicyId']},'pricingSummary':{'price':{'value':f'{kit["price_usd"]:.2f}','currency':'USD'}}}
    return inventory,offer,{k:config[k] for k in ['categoryId','condition','aspects','merchantLocationKey','fulfillmentPolicyId','paymentPolicyId','returnPolicyId']}|{'imageUrls':urls},kit['price_usd']


def publish(item_id,data):
    with LOCK:
        item=store.get('items',item_id)
        if not item:raise ValueError('Item not found.')
        old=listing_for(item_id)
        if not old and any(a.get('status')=='posted' for a in channels.tracked(item_id,'ebay')):
            raise ValueError('A manually recorded eBay listing is active. Link its existing Inventory SKU or confirm its removal before creating another listing.')
        if old and old.get('offer_id'):
            old=apply_remote(old,read_offer(old))
            if old['status'] in ['posted','on_hold','needs_removal','sale_detected','sold','remote_unknown']:raise ValueError('An eBay listing already exists. Use Check status, Update or Withdraw.')
        inventory,offer,config,price=payloads(item,data)
        row=old or {'id':listing_id(item_id),'type':'external_listing','item_id':item_id,'platform':'ebay','source':'ebay_api','environment':settings()['environment'],'created_at':store.now()}
        row.update(status='publishing',sku=offer['sku'],publish_settings=config)
        save_listing(row)
        try:
            if not row.get('offer_id'):
                # Recover an offer created before a timeout/restart; never blindly create a second offer.
                try:offers=api('GET','/sell/inventory/v1/offer?'+urlencode({'sku':offer['sku'],'marketplace_id':'EBAY_US','format':'FIXED_PRICE'})).get('offers',[])
                except APIError as exc:
                    if exc.status_code!=404:raise
                    offers=[]
                if offers:
                    if len(offers)!=1:raise ValueError('Multiple eBay offers exist for this SKU; resolve them in eBay first.')
                    row['offer_id']=offers[0]['offerId'];save_listing(row)
                    if offers[0].get('status')=='PUBLISHED':return apply_remote(row,offers[0])
                else:
                    api('PUT','/sell/inventory/v1/inventory_item/'+quote(offer['sku'],safe=''),inventory)
                    row['offer_id']=api('POST','/sell/inventory/v1/offer',offer)['offerId'];save_listing(row)
            api('PUT','/sell/inventory/v1/inventory_item/'+quote(offer['sku'],safe=''),inventory)
            api('PUT','/sell/inventory/v1/offer/'+quote(row['offer_id'],safe=''),{k:v for k,v in offer.items() if k in OFFER_FIELDS})
            result=api('POST','/sell/inventory/v1/offer/'+quote(row['offer_id'],safe='')+'/publish')
            row['listing_id']=result['listingId']
            acknowledge(row,item,price)
            row.update(published_at=store.now())
            save_listing(row)
            return apply_remote(row,read_offer(row))
        except (ValueError,RuntimeError) as exc:
            row.update(last_error=str(exc),status='publish_uncertain' if row.get('offer_id') else 'publish_failed');save_listing(row)
            raise


def update(item_id,data=None):
    if data is not None and not isinstance(data,dict):raise ValueError('eBay settings must be an object.')
    with LOCK:
        row=listing_for(item_id)
        if not row:raise ValueError('No API-connected eBay listing for this item.')
        remote=read_offer(row);row=apply_remote(row,remote)
        if row['status']!='posted':raise ValueError('Only an active unsold eBay listing can be updated.')
        item=store.get('items',item_id)
        if row.get('identity_version')!=identity_version(item) and not data:
            raise ValueError('Product identity, condition, specifications or photo changed. Review the eBay category, condition, aspects and photos below before updating.')
        inventory,offer,config,price=payloads(item,{**row.get('publish_settings',{}),**(data or {})})
        old_inventory=api('GET','/sell/inventory/v1/inventory_item/'+quote(row['sku'],safe=''))
        retained={k:copy.deepcopy(v) for k,v in old_inventory.items() if k in INVENTORY_FIELDS}
        retained.update({k:v for k,v in inventory.items() if k!='availability'})
        # Preserve remote quantity and policy/regulatory fields on full-replacement endpoints.
        retained['product']={**old_inventory.get('product',{}),**inventory['product']}
        revised={k:copy.deepcopy(v) for k,v in remote.items() if k in OFFER_FIELDS}
        revised.update({k:v for k,v in offer.items() if k in ['listingDescription','categoryId','merchantLocationKey']})
        revised['pricingSummary']={**remote.get('pricingSummary',{}),'price':offer['pricingSummary']['price']}
        revised['listingPolicies']={**remote.get('listingPolicies',{}),**offer['listingPolicies']}
        try:
            api('PUT','/sell/inventory/v1/inventory_item/'+quote(row['sku'],safe=''),retained)
            api('PUT','/sell/inventory/v1/offer/'+quote(row['offer_id'],safe=''),revised)
        except RuntimeError as exc:
            row.update(last_error=str(exc),last_sync_failed=True);save_listing(row);raise
        acknowledge(row,item,price)
        row.update(publish_settings=config,last_sync_failed=False,last_error=None,synced_at=store.now());save_listing(row)
        return apply_remote(row,read_offer(row))


def withdraw(item_id):
    with LOCK:
        row=listing_for(item_id)
        if not row:raise ValueError('No API-connected eBay listing for this item.')
        remote=read_offer(row)
        if remote.get('status')=='PUBLISHED':api('POST','/sell/inventory/v1/offer/'+quote(row['offer_id'],safe='')+'/withdraw')
        row=apply_remote(row,read_offer(row))
        if row['status'] not in ['removed','sale_detected','sold']:raise RuntimeError('eBay has not confirmed withdrawal. Check status again.')
        return row


def sync_all():
    results=[]
    for row in store.all_rows('actions'):
        if row.get('source')!='ebay_api' or row.get('environment')!=settings()['environment'] or not row.get('offer_id') or row.get('status') in ['removed','sold']:continue
        try:
            result=withdraw(row['item_id']) if row.get('status')=='needs_removal' else check(row['item_id'])
            results.append({'id':row['id'],'status':result['status']})
        except (ValueError,RuntimeError) as exc:
            current=store.get('actions',row['id']) or row
            current.update(last_error=str(exc));save_listing(current)
            results.append({'id':row['id'],'error':str(exc)})
    return results


def start_worker():
    def run():
        while True:
            try:
                if status()['connected']:sync_all()
            except Exception:pass  # Per-listing errors are persisted and shown in Channels.
            time.sleep(120)
    threading.Thread(target=run,name='ebay-status',daemon=True).start()
