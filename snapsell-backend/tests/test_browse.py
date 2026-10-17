"""Fixture offers stay isolated from the owner's workspace and live credentials."""
import copy
import pytest
from test_research import isolated,item
import browse
import ebay_notifications

@pytest.fixture
def details():
    return {'itemId':'v1|123456789012|0','title':'Used Dell UltraSharp U2720Q 27-inch 4K monitor','price':{'value':'249.99','currency':'USD'},'conditionId':'3000','condition':'Used','buyingOptions':['FIXED_PRICE'],'itemWebUrl':'https://www.ebay.com/itm/123456789012?tracking=1','seller':{'username':'fixture-seller'},'itemLocation':{'country':'US'},'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}],'shippingOptions':[{'shippingCost':{'value':'12','currency':'USD'},'shipToLocationUsedForEstimate':{'country':'US'},'quantityUsedForEstimate':1}]}

def test_verified_offer_keeps_item_and_delivery_separate(item,details):
    row,reason=browse.offer(item,details)
    assert row['price']==249.99 and row['shipping_amount']==12
    assert row['transaction_verified'] is False and row['kind']=='asking'
    assert row['url']=='https://www.ebay.com/itm/123456789012'
    assert row['evidence']['conditionId']=='3000' and row['page_sha256']

def test_live_non_lot_zero_is_single_item_not_an_empty_bundle(item,details):
    assert browse.offer(item,{**details,'lotSize':0})[0] is not None

@pytest.mark.parametrize('change',[
    {'conditionId':'1500'}, {'conditionId':'7000','condition':'For parts or not working'},
    {'buyingOptions':['AUCTION']},{'lotSize':2},{'lotSize':'unknown'},
    {'estimatedAvailabilities':[]},{'itemLocation':{'country':'CA'}},
    {'price':{'value':'NaN','currency':'USD'}},{'price':{'value':'240','currency':'CAD'}},
    {'itemEndDate':'2000-01-01T00:00:00Z'},{'itemEndDate':'broken'},
    {'title':'Replacement stand for Dell UltraSharp U2720Q 27-inch 4K monitor'},
    {'itemWebUrl':'https://example.com/itm/123456789012'},
])
def test_non_comparable_offers_cannot_supply_price(item,details,change):
    assert browse.offer(item,{**details,**change})[0] is None

def test_shipping_for_other_destination_or_multiple_units_not_accepted(item,details):
    for change in [{'shipToLocationUsedForEstimate':{'country':'CA'}},{'quantityUsedForEstimate':2}]:
        data=copy.deepcopy(details);data['shippingOptions'][0].update(change)
        row,_=browse.offer(item,data)
        assert row and 'shipping_amount' not in row

def test_query_uses_identity_and_separate_configuration(item):
    product={**item,'title':'Huge marketing title '*20,'specs':{'storage':'512GB','memory':'16GB'}}
    queries=browse.queries(product)
    assert len(queries)==2 and all(len(q)<=100 for q in queries)
    assert 'dell u2720q' in queries[0].lower() and 'marketing' not in queries[0]

def test_failed_notification_sync_blocks_network_and_prices(item,monkeypatch):
    monkeypatch.setattr(ebay_notifications,'sync',lambda:False)
    monkeypatch.setattr(browse,'request',lambda *a,**k:pytest.fail('Must not fetch before sync'))
    rows,sources=browse.collect(item)
    assert not rows and sources[0]['status']=='unavailable'

def test_one_unavailable_offer_does_not_discard_remaining_results(item,details,monkeypatch):
    monkeypatch.setattr(ebay_notifications,'sync',lambda:True)
    calls=[]
    def request(path,params=None):
        calls.append(path)
        if path.endswith('/search'):return {'itemSummaries':[{'itemId':'unavailable'},{'itemId':details['itemId']},{'itemId':details['itemId']}]}
        if path.endswith('/unavailable'):raise RuntimeError('Unavailable')
        return details
    monkeypatch.setattr(browse,'request',request)
    rows,sources=browse.collect(item)
    assert len(rows)==1 and len(sources)==2
    assert [s['status'] for s in sources]==['unavailable','verified']
    assert len(calls)==3

def test_request_budget_is_bounded_and_duplicates_not_refetched(item,details,monkeypatch):
    monkeypatch.setattr(ebay_notifications,'sync',lambda:True)
    calls=[]
    def request(path,params=None):
        calls.append(path)
        if path.endswith('/search'):return {'itemSummaries':[{'itemId':str(i)} for i in range(100)]}
        return {**details,'price':{'value':'0','currency':'USD'}}
    monkeypatch.setattr(browse,'request',request)
    rows,sources=browse.collect(item)
    assert not rows and len(sources)==30 and len(calls)==31
