import json,copy,time
from datetime import datetime,timedelta,timezone
import pytest
from test_research import item,seller,isolated,document,app,store,research,pricing
import browse,markets

@pytest.mark.parametrize('market',['US','KZ','JP','CN'])
@pytest.mark.parametrize('phase',['plan','refine'])
def test_enabled_amd_receives_valid_query_prompt(item,monkeypatch,market,phase):
    """Exercise the enabled-provider branch: disabled AMD hides f-string failures."""
    import re
    monkeypatch.setattr(app.amd,'configured',lambda:True)
    received=[]
    def answer(role,prompt,payload,budget):
        schema=json.loads(re.search(r'Return JSON (\{.*?\})\.',prompt).group(1))
        assert isinstance(schema['queries'],list) and all(isinstance(q,str) for q in schema['queries'])
        assert markets.get(market)['name'] in prompt
        received.append(prompt)
        return {'queries':['Used Dell UltraSharp U2720Q local offers']},'mock-enabled-amd'
    monkeypatch.setattr(app.amd,'json_response',answer)
    target={**item,'_research_market':market}
    if phase=='plan':
        queries,model=research.plan(target)
    else:
        queries,blocked,model=research.refine(target,[])
    assert received and queries and model=='mock-enabled-amd'

@pytest.mark.parametrize('phase',['plan','refine'])
def test_enabled_amd_outage_keeps_default_research_queries(item,monkeypatch,phase):
    monkeypatch.setattr(app.amd,'configured',lambda:True)
    monkeypatch.setattr(app.amd,'json_response',lambda *a:(_ for _ in ()).throw(RuntimeError('Provider unavailable')))
    result=research.plan(item) if phase=='plan' else research.refine(item,[])
    assert result[0] and result[-1] is None

def test_supported_phone_research_can_set_asking_price(item,seller):
    phone=store.put('items',{**item,'title':'Apple iPhone 16','brand':'Apple','model_key':'iphone-16','category':'Phone','price':0,'specs':{'storage':'128GB','battery':'87%','working':'Yes','repairs':'None','carrier':'Unlocked','activation_lock':'Removed'}})
    for index,price in enumerate([400,420,440]):
        product={'@type':'Product','name':'Used Apple iPhone 16 128GB Unlocked','offers':{'@type':'Offer','price':price,'priceCurrency':'USD','availability':'https://schema.org/InStock','itemCondition':'https://schema.org/UsedCondition'}}
        doc={'url':f'https://seller{index}.example/iphone-16','text':'<script type="application/ld+json">'+json.dumps(product)+'</script>','sha256':'fixture','fetched_at':store.now()}
        rows,_=research.parse_offers(doc,phone)
        assert rows
        store.put('comparables',{**rows[0],'id':str(index),'item_id':phone['id'],'item_fingerprint':research.fingerprint(phone)})
    assert pricing.evaluate(phone)['comparables']['available']
    response=seller.post('/api/items/'+phone['id']+'/strategy',json={'strategy':'balanced'})
    assert response.status_code==200 and response.json['price']==420
    assert store.get('items',phone['id'])['price']==420

def test_missing_phone_evidence_cannot_write_a_guessed_price(item,seller):
    phone=store.put('items',{**item,'title':'Apple iPhone 16','brand':'Apple','model_key':'iphone-16','category':'Phone','price':0})
    response=seller.post('/api/items/'+phone['id']+'/strategy',json={'strategy':'balanced'})
    assert response.status_code==400 and store.get('items',phone['id'])['price']==0

def evidence(item,market='US',price=250,index=0,mode='exact',shipping=None):
    currency=markets.get(market)['currency'];suffix={'US':'example','KZ':'kz','JP':'jp','CN':'cn'}[market]
    product={'@type':'Product','name':'Used Dell UltraSharp U2720Q 27-inch monitor','description':'4K monitor','offers':{'@type':'Offer','price':price,'priceCurrency':currency,'availability':'https://schema.org/InStock','itemCondition':'https://schema.org/UsedCondition'}}
    if shipping is not None:product['offers']['shippingDetails']={'shippingDestination':{'addressCountry':market},'shippingRate':{'currency':currency,'value':shipping}}
    doc={'url':f'https://seller{index}.{suffix}/item-{index}','text':'<script type="application/ld+json">'+json.dumps(product)+'</script>','sha256':'test-hash','fetched_at':store.now()}
    rows,_=research.parse_offers(doc,{**item,'_research_market':market,'_research_mode':mode})
    assert rows
    row={**rows[0],'id':f'{market}-{mode}-{index}','item_id':item['id'],'item_fingerprint':research.fingerprint(item)}
    store.put('comparables',row);return row

@pytest.mark.parametrize('market',['US','KZ','JP','CN'])
def test_four_market_prices_are_kept_in_native_currency(item,market):
    for index in range(3):evidence(item,market,1000+index*100,index)
    report=pricing.evaluate(item,market)
    assert report['comparables']['available']
    assert report['comparables']['currency']==markets.get(market)['currency']
    assert report['comparables']['median']==pytest.approx(1100,abs=2)
    if market!='US':assert report['strategies']==[] and report['model'] is None

def test_foreign_prices_cannot_populate_us_listing_kit(item):
    import channels
    for index in range(3):evidence(item,'KZ',100000+index*10000,index)
    assert not pricing.evaluate(item)['comparables']['available']
    assert channels.prepare({**item,'price':0},'ebay')[0]['price_usd'] is None

def test_market_rows_are_excluded_in_audit_and_not_mixed(item):
    for index in range(3):evidence(item,'KZ',100000,index);evidence(item,'US',250,index)
    report=pricing.comparables(item,'KZ')
    assert report['sample_count']==3 and report['median']==pytest.approx(100000)
    assert len([r for r in report['rows'] if not r['included']])==3

def test_shipping_is_source_backed_and_never_silently_invented(item):
    for index in range(3):evidence(item,'US',250,index,shipping=10)
    report=pricing.comparables(item,basis='delivered')
    assert report['median']==pytest.approx(260) and report['shipping_observations']==3
    assert pricing.evaluate(item,basis='delivered')['strategies']==[]
    row=store.get('comparables','US-exact-0');row.pop('shipping_amount');store.put('comparables',row)
    assert not pricing.comparables(item,basis='delivered')['available']
    assert pricing.comparables(item)['available']

def test_shipping_wrong_country_is_not_added_to_estimate(item):
    doc=document();data=json.loads(doc['text'].split('<script type="application/ld+json">')[1].split('</script>')[0])
    data['offers']['shippingDetails']={'shippingDestination':{'addressCountry':'JP'},'shippingRate':{'currency':'USD','value':10}}
    doc['text']='<script type="application/ld+json">'+json.dumps(data)+'</script>'
    assert 'shipping_amount' not in research.parse_offers(doc,item)[0][0]

def test_outlier_removal_rechecks_independent_sellers(item):
    for index in range(4):
        row=evidence(item,'US',100 if index<3 else 9999,index)
        row['source_name']='one-merchant.example' if index<3 else 'outlier.example';store.put('comparables',row)
    report=pricing.comparables(item)
    assert not report['available'] and report['independent_merchants']==1
    assert any('outlier' in (r['exclusion_reason'] or '') for r in report['rows'])

def test_tracking_links_and_variant_prices_do_not_create_independence(item):
    for index in range(4):
        row=evidence(item,'US',200+index*5,index)
        row['url']='https://one.example/product?variant='+str(index);store.put('comparables',row)
    report=pricing.comparables(item)
    assert report['independent_pages']==1 and report['sample_count']==1

def test_unknown_model_reference_is_not_an_automatic_valuation(item):
    unknown={**item,'model_key':'unknown','title':'Dell UltraSharp monitor','_research_mode':'similar'}
    for index in range(3):evidence(unknown,'US',200+index*10,index,mode='similar')
    result=pricing.evaluate(unknown,mode='similar')
    assert not result['comparables']['available'] and result['comparables']['reference_band']
    assert result['strategies']==[] and result['model'] is None
    assert not pricing.evaluate(unknown)['comparables']['available']

def test_brands_and_capacity_substrings_cannot_be_confused(item):
    assert not research.model_match(item,'Used Samsung U2720Q')[0]
    assert not research.model_match(item,'Used Dell U2723QE')[0]
    laptop={**item,'model_key':'dell-5420','category':'Laptop','specs':{'memory':'16GB'}}
    assert not research.model_match(laptop,'Dell 5420 116GB')[0]
    assert research.model_match(laptop,'Dell 5420 16 GB RAM')[0]

def test_multilingual_used_condition_and_unicode_model_keys():
    for text in ['Б/у монитор','中古モニター','二手显示器']:assert research.condition_from('',text)=='Used — grade unspecified'
    assert pricing.key('Стул Москва')=='стул-москва'
    assert research.norm('二手Dell U2720Q显示器')=='二手 dell u2720q 显示器'

def test_currency_alone_cannot_prove_country_for_generic_domain(item):
    doc=document();data=json.loads(doc['text'].split('<script type="application/ld+json">')[1].split('</script>')[0]);data['offers']['priceCurrency']='JPY'
    doc['text']='<script type="application/ld+json">'+json.dumps(data)+'</script>'
    target={**item,'_research_market':'JP'}
    assert not research.parse_offers(doc,target)[0]
    data['offers']['eligibleRegion']='JP';doc['text']='<script type="application/ld+json">'+json.dumps(data)+'</script>'
    assert research.parse_offers(doc,target)[0][0]['currency']=='JPY'

def test_expired_and_future_observations_are_rejected(item):
    for index in range(3):
        row=evidence(item,index=index);row['observed_at']=(datetime.now(timezone.utc)+timedelta(days=1 if index==0 else -8)).isoformat();store.put('comparables',row)
    assert not pricing.comparables(item)['available']

def test_market_refresh_replaces_only_its_own_evidence(item,monkeypatch):
    evidence(item,'KZ');evidence(item,'US')
    monkeypatch.setattr(research,'plan',lambda i:([],None));monkeypatch.setattr(research,'discover',lambda *a,**k:([],[]));monkeypatch.setattr(research,'refine',lambda *a:([],[],None));monkeypatch.setattr(browse,'configured',lambda:False)
    job=store.put('jobs',{'item_id':item['id'],'market':'KZ','mode':'exact','item_fingerprint':research.fingerprint(item),'status':'queued'})
    research.run(job['id'])
    assert len(store.all_rows('comparables'))==1 and store.all_rows('comparables')[0]['market']=='US'

def test_daily_refresh_is_opt_in_persistent_and_skips_sold_items(item,monkeypatch):
    assert not research.schedule(item['id'],'JP')['enabled']
    calls=[];monkeypatch.setattr(research,'start',lambda *a,**k:calls.append(a) or {'id':'queued'})
    research.schedule(item['id'],'JP','exact',True,[])
    key=research.schedule_id(item['id'],'JP','exact');record=store.get('actions',key);record['next_at']=0;store.put('actions',record)
    assert research.refresh_due()==['queued'] and calls[0][2]=='JP'
    assert research.refresh_due()==[]
    record['next_at']=0;store.put('actions',record);store.put('items',{**item,'status':'sold'})
    assert research.refresh_due()==[]

def test_invalid_market_and_modes_are_rejected_by_api(item,seller):
    assert seller.get('/api/items/actual-item/research?market=INVALID').status_code==400
    assert seller.get('/api/items/actual-item/pricing?basis=madeup').status_code==400
    assert seller.post('/api/items/actual-item/research',json={'market':'CN','mode':'madeup'}).status_code==400

def test_official_browse_requires_available_us_offers_and_distinct_sellers(item,monkeypatch):
    def api(path,params=None):
        if path=='/item_summary/search':return {'itemSummaries':[{'itemId':str(i)} for i in range(3)]}
        i=path.rsplit('/',1)[-1]
        return {'buyingOptions':['FIXED_PRICE'],'itemId':i,'title':'Used Dell UltraSharp U2720Q','condition':'Used','localizedAspects':[{'name':'Screen','value':'27 inch 4K'}],'itemWebUrl':f'https://www.ebay.com/itm/{i}','price':{'value':'250','currency':'USD'},'itemLocation':{'country':'US'},'seller':{'username':'seller'+i},'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}]}
    monkeypatch.setattr(browse,'request',api)
    rows,sources=browse.collect(item)
    assert len(rows)==3 and len({r['seller_id'] for r in rows})==3
    assert all(r['source']=='verified_api' and not r['transaction_verified'] for r in rows)
    for index,row in enumerate(rows):store.put('comparables',{**row,'id':str(index),'item_id':item['id'],'item_fingerprint':research.fingerprint(item)})
    assert pricing.comparables(item)['available']

def test_browse_errors_do_not_invent_prices(item,monkeypatch):
    monkeypatch.setattr(browse,'request',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Not authorized')))
    rows,sources=browse.collect(item)
    assert not rows and sources[0]['status']=='unavailable'

def baseline(item):
    for index in range(3):evidence(item,index=index)

def test_observation_freezes_real_features_and_sale_labels_once(item,seller):
    import outcomes,channels
    baseline(item)
    response=seller.post('/api/items/actual-item/outcome',json={'action':'begin'})
    assert response.status_code==200 and response.json['window']['features']['price_ratio']==pytest.approx(1.2)
    listing=channels.record_listing(item,'facebook','https://www.facebook.com/marketplace/item/123')
    channels.complete_sale(item['id'],listing['id'],280,20,100)
    history=store.all_rows('history')
    assert len(history)==1 and history[0]['sold_within_7_days']==1
    assert history[0]['source']=='seller_reported_observed'
    assert outcomes.current(item['id'])['status']=='completed'
    assert pricing.fit_model() is None

def test_unsold_label_requires_seven_days_and_explicit_confirmation(item,seller):
    import outcomes
    baseline(item);outcomes.begin(item)
    assert seller.post('/api/items/actual-item/outcome',json={'action':'confirm_unsold','confirm':True}).status_code==400
    window=outcomes.current(item['id']);window.update(opened_at=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),closes_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat());store.put('actions',window)
    assert not store.all_rows('history')
    assert seller.post('/api/items/actual-item/outcome',json={'action':'confirm_unsold'}).status_code==400
    assert seller.post('/api/items/actual-item/outcome',json={'action':'confirm_unsold','confirm':True}).status_code==200
    assert store.all_rows('history')[0]['sold_within_7_days']==0
    assert seller.post('/api/items/actual-item/outcome',json={'action':'confirm_unsold','confirm':True}).status_code==400

def test_price_change_then_revert_cannot_manufacture_constant_price_outcome(item,seller):
    import outcomes
    baseline(item);outcomes.begin(item)
    assert seller.patch('/api/items/actual-item',json={'price':310}).status_code==200
    seller.patch('/api/items/actual-item',json={'price':300})
    assert outcomes.current(item['id'])['status']=='invalidated' and not store.all_rows('history')

def test_sale_after_window_is_not_automatically_labeled_unsold(item):
    import outcomes,channels
    baseline(item);window=outcomes.begin(item);window.update(opened_at=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),closes_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat());store.put('actions',window)
    listing=channels.record_listing(item,'facebook','https://www.facebook.com/marketplace/item/123')
    channels.complete_sale(item['id'],listing['id'],280,20,100)
    assert not store.all_rows('history') and outcomes.current(item['id'])['status']=='observing'

def test_observation_needs_evidence_and_supported_category(item,seller):
    assert seller.post('/api/items/actual-item/outcome',json={'action':'begin'}).status_code==400
    baseline(item);store.put('items',{**item,'category':'Furniture'})
    assert seller.post('/api/items/actual-item/outcome',json={'action':'begin'}).status_code==400

def test_sandbox_listings_cannot_train_real_sales_history(item):
    import outcomes
    baseline(item)
    store.put('actions',{'type':'external_listing','item_id':item['id'],'status':'posted','environment':'sandbox'})
    with pytest.raises(ValueError,match='Sandbox'):outcomes.begin(item)

def test_fractional_and_future_history_import_is_rejected(seller):
    import io
    columns='price_ratio,age_days,excellent,monitor,completeness,sold_within_7_days,observed_at\n'
    for label,date in [('0.5','2026-01-01T00:00:00+00:00'),('0.004','2026-01-01T00:00:00+00:00'),('1','2099-01-01T00:00:00+00:00')]:
        csv=columns+f'1,2,1,1,0.8,{label},{date}\n'
        result=seller.post('/api/data/import',data={'kind':'history','file':(io.BytesIO(csv.encode()),'history.csv')})
        assert result.status_code==400 and not store.all_rows('history')

def test_forecast_splits_need_both_classes():
    for index in range(140):
        store.put('history',{'id':str(index),'source':'imported','market':'US','currency':'USD','price_ratio':1,'age_days':10,'excellent':0,'monitor':1,'completeness':.8,'sold_within_7_days':index%2 if index<98 else 1,'observed_at':f'2025-01-01T00:{index//60:02}:{index%60:02}+00:00'})
    assert pricing.fit_model() is None

def test_daily_refresh_does_not_mix_latest_jobs_by_country(item):
    for market in ['US','JP','CN']:
        store.put('jobs',{'id':market,'type':'market_research','item_id':item['id'],'market':market,'mode':'exact','status':'completed'})
    assert research.latest(item['id'],'JP')['id']=='JP'
    assert research.latest(item['id'],'US')['id']=='US'

def test_repeated_history_import_does_not_manufacture_new_outcomes(seller):
    import io
    csv='price_ratio,age_days,excellent,monitor,completeness,sold_within_7_days,observed_at\n1,2,1,1,0.8,1,2026-01-01T00:00:00+00:00\n'
    first=seller.post('/api/data/import',data={'kind':'history','file':(io.BytesIO(csv.encode()),'history.csv')})
    second=seller.post('/api/data/import',data={'kind':'history','file':(io.BytesIO(csv.encode()),'history.csv')})
    assert first.json['imported']==1 and second.json['imported']==0 and second.json['skipped_duplicates']==1
    assert len(store.all_rows('history'))==1

def test_daily_refresh_can_be_stopped_without_running_another_search(item,seller):
    response=seller.post('/api/items/actual-item/research/schedule',json={'market':'CN','enabled':True})
    assert response.status_code==200 and response.json['schedule']['enabled']
    assert seller.post('/api/items/actual-item/research/schedule',json={'market':'CN','enabled':False}).status_code==200
    assert not research.schedule(item['id'],'CN')['enabled']
    assert seller.post('/api/items/actual-item/research/schedule',json={'market':'CN','enabled':True,'source_urls':['https://localhost/test']*6}).status_code==400

def test_recorded_screen_gpu_and_refresh_rate_are_not_ignored(item):
    assert not research.model_match(item,'Dell U2720Q 24-inch 1080p')[0]
    target={**item,'specs':{'gpu':'RTX 3060','refresh_rate':'144 Hz'}}
    assert not research.model_match(target,'Dell U2720Q RTX 3050 144 Hz')[0]
    assert research.model_match(target,'Dell U2720Q RTX 3060 144 Hz')[0]

@pytest.mark.parametrize('market,currency',[('US','USD'),('KZ','KZT'),('JP','JPY'),('CN','CNY')])
def test_regional_csv_import_retains_country_and_currency(seller,market,currency):
    import io
    csv=f'model_key,title,price,condition,kind,age_days,source_name,url,market,currency\ndell-u2720q,Dell monitor,250000,Good,asking,0,Seller report,,{market},{currency}\n'
    response=seller.post('/api/data/import',data={'kind':'comparables','file':(io.BytesIO(csv.encode()),'prices.csv')})
    assert response.status_code==200
    row=store.all_rows('comparables')[0]
    assert row['market']==market and row['currency']==currency and row['source']=='imported'

def test_csv_cannot_relabel_dollars_as_tenge_or_unknown_as_exact(seller):
    import io
    for model,currency in [('dell-u2720q','USD'),('unknown','KZT')]:
        csv=f'model_key,price,condition,kind,market,currency\n{model},100000,Good,asking,KZ,{currency}\n'
        response=seller.post('/api/data/import',data={'kind':'comparables','file':(io.BytesIO(csv.encode()),'prices.csv')})
        assert response.status_code==400 and not store.all_rows('comparables')

def test_large_reference_cannot_bypass_inventory_price_limit(item):
    for index in range(3):evidence(item,'US',250000,index)
    assert pricing.evaluate(item)['comparables']['available']
    assert not pricing.evaluate(item)['strategies']
