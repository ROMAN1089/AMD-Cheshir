"""Questionnaire and source reference behavior; all numeric fixtures stay isolated."""
import json
import pytest
from test_research import isolated,item,seller,store,research,pricing,app
import assessment

@pytest.fixture
def phone(item):
    return store.put('items',{**item,'category':'Phone','title':'Apple iPhone 16 (blue)','brand':'Apple','model_key':'iphone-16','condition':'Not verified','specs':{'color':'Blue'},'status':'draft','price':0})

def complete(phone):
    return assessment.save_answers(phone,{'storage':'128GB','condition':'Good','battery':'87','working':'Yes','repairs':'None','carrier':'Unlocked','activation_lock':'Removed','included':'Phone only'})

def offers(phone,prices=(500,520),differences=False):
    for index,price in enumerate(prices):
        row=dict(id='offer-'+str(index),model_key=phone['model_key'],item_id=phone['id'],item_fingerprint=research.fingerprint(phone),source='verified_web',price=price,currency='USD',market='US',match_level='exact',kind='asking',condition='Refurbished',url=f'https://merchant{index}.example/products/iphone-16',source_name=f'merchant{index}.example',observed_at=store.now(),page_sha256='real-page-fixture',evidence={'product_title':'iPhone 16 128GB'},title='iPhone 16 128GB Unlocked',source_grade='Good')
        if differences:row['comparison_differences']=['Different colour']
        store.put('comparables',row)

def test_questions_prefilled_and_battery_not_charge(phone,seller):
    data=seller.get('/api/items/actual-item/research').json
    q={q['key']:q for q in data['questions']}
    assert q['storage']['value']=='Not verified' and 'current charge' in q['battery']['hint']
    assert q['condition']['value']=='Not verified'

@pytest.mark.parametrize('value',['101','-1','85% full','0',85])
def test_invalid_battery_does_not_mutate_item(phone,value):
    before=store.get('items',phone['id'])
    with pytest.raises(ValueError):assessment.save_answers(phone,{'battery':value})
    assert store.get('items',phone['id'])==before

def test_answers_are_saved_without_confirming_unknown_facts(phone):
    p=complete(phone)
    assert p['specs']['battery']=='87%' and p['specs']['storage']=='128GB'
    assert not p['confirmed'] and not assessment.uncertainties(p)
    assert '128GB' in p['listing_suggestion']['description']
    assert 'screen' not in p['specs']

def test_unknowns_show_range_but_no_single_draft_price(phone):
    offers(phone)
    r=pricing.comparables(phone)
    assert not r['available'] and r['preliminary']['low']==500
    assert r['preliminary']['suggested_price'] is None and 'storage' in r['preliminary']['missing']

def test_refurbished_reference_not_promoted_to_verified_valuation(phone):
    phone=complete(phone);offers(phone)
    r=pricing.comparables(phone)
    assert not r['available'] and r['preliminary']['retail_refurbished']
    assert r['preliminary']['suggested_price']==500
    assert not pricing.evaluate(phone)['strategies']

def test_one_merchant_with_many_variants_not_enough_for_draft(phone):
    phone=complete(phone);offers(phone,prices=[500])
    row=store.all_rows('comparables')[0]
    store.put('comparables',{**row,'id':'variant2','price':530,'url':row['url']+'?variant=2'})
    assert pricing.comparables(phone)['preliminary']['suggested_price'] is None

@pytest.mark.parametrize('changes',[{'working':'No'},{'activation_lock':'Still locked'},{'battery':'72'}])
def test_faults_locks_and_low_battery_block_working_device_price(phone,changes):
    phone=complete(phone);phone=assessment.save_answers(phone,changes);offers(phone)
    r=pricing.comparables(phone)['preliminary']
    assert r['suggested_price'] is None and r['blocked_reason']

def test_draft_fill_respects_existing_price_and_fingerprint(phone):
    phone=complete(phone);offers(phone)
    job={'id':'research-1','item_fingerprint':research.fingerprint(phone),'market':'US','mode':'exact'}
    assessment.apply_draft_price(phone['id'],job)
    saved=store.get('items',phone['id']);assert saved['price']==500 and saved['price_assessment']['preliminary']
    saved['price']=400;store.put('items',saved);assessment.apply_draft_price(phone['id'],job)
    assert store.get('items',phone['id'])['price']==400
    saved.update(price=0,specs={**saved['specs'],'storage':'256GB'});store.put('items',saved)
    assessment.apply_draft_price(phone['id'],job);assert store.get('items',phone['id'])['price']==0

def test_other_model_variant_and_capacity_rejected(phone):
    phone=complete(phone)
    assert not research.model_match(phone,'Apple iPhone 16 Pro 128GB Unlocked','Blue')[0]
    assert not research.model_match(phone,'Apple iPhone 16 Plus 128GB Unlocked','Blue')[0]
    assert not research.model_match(phone,'Apple iPhone 16 256GB Unlocked','Blue')[0]
    assert not research.model_match(phone,'Apple iPhone 16 128GB AT&T','Blue')[0]

def test_category_links_are_same_origin_and_never_become_prices(phone):
    d={'url':'https://store.example/collections/phones','text':'<a href="/products/apple-iphone-16-ultramarine-unlocked">iPhone 16</a><a href="/products/iphone-16-pro">iPhone 16 Pro</a><a href="http://127.0.0.1/products/iphone-16">iPhone 16</a><p>$1</p>'}
    links=research.product_links(d,phone)
    assert links==['https://store.example/products/apple-iphone-16-ultramarine-unlocked']

def test_colour_references_remain_labelled(phone):
    phone=complete(phone);offers(phone,differences=True)
    report=pricing.comparables(phone)
    assert not report['available'] and report['preliminary']['suggested_price']==500
    assert all(r['comparison_differences'] for r in report['rows'])

def test_expired_sources_cannot_supply_preliminary_prices(phone):
    from datetime import datetime,timedelta,timezone
    offers(phone)
    for r in store.all_rows('comparables'):
        store.put('comparables',{**r,'observed_at':(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()})
    assert pricing.comparables(phone)['preliminary'] is None

def test_invalid_fill_option_does_not_save_answers(phone,seller):
    r=seller.post('/api/items/actual-item/research',json={'answers':{'storage':'128GB'},'fill_draft_price':'true'})
    assert r.status_code==400 and 'storage' not in store.get('items',phone['id'])['specs']

def test_shopify_brand_checked_on_product_capacity_checked_on_variant(phone):
    import merchant
    phone=complete(phone)
    doc={'url':'https://shop.example/products/iphone-16','text':'<meta property="product:price:currency" content="USD">Shopify.currency','sha256':'page'}
    product={'title':'iPhone 16','vendor':'Apple','description':'Refurbished Apple iPhone, blue; also offered in 128GB and 256GB. Unlocked.','variants':[{'id':1,'title':'Blue / 256GB / Good','available':True,'price':60000},{'id':2,'title':'Blue / 128GB / Good','available':True,'price':50000}]}
    response={'text':json.dumps(product),'sha256':'api','fetched_at':store.now()}
    rows,_=merchant.shopify_evidence(doc,phone,lambda url:response,lambda url:None,research.model_match,research.condition_from)
    assert len(rows)==1 and rows[0]['price']==500 and rows[0]['evidence']['variant_id']==2

def test_unknown_storage_range_keeps_legitimate_capacity_spread(phone):
    offers(phone,prices=[500,520,900])
    assert pricing.comparables(phone)['preliminary']['high']==900

def test_obvious_outlier_in_known_configuration_does_not_set_draft(phone):
    phone=complete(phone);offers(phone,prices=[500,520,50])
    r=pricing.comparables(phone)['preliminary']
    assert r['low']==500 and r['suggested_price']==500 and r['pages']==2

def test_imports_do_not_skip_phone_questions(phone):
    offers(phone,prices=[500,520,540])
    for row in store.all_rows('comparables'):
        store.put('comparables',{**row,'source':'imported','condition':'Good'})
    assert not pricing.evaluate(phone)['strategies']
