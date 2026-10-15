"""Behavioral tests against a deterministic Inventory API double, no live writes."""
import copy
import json
import time
import pytest
from test_research import item, seller, isolated, app, store
import channels
import ebay


class Server:
    def __init__(self):
        self.calls=[];self.inventory={};self.offer=None;self.timeout_publish=False;self.fail_update=False

    def __call__(self,method,path,payload=None,files=None):
        self.calls.append((method,path,copy.deepcopy(payload)))
        if path.startswith('/sell/inventory/v1/inventory_item/'):
            if method=='GET':return copy.deepcopy(self.inventory)
            self.inventory=copy.deepcopy(payload);return {}
        if path.startswith('/sell/inventory/v1/offer?'):
            return {'offers':[copy.deepcopy(self.offer)] if self.offer else []}
        if path=='/sell/inventory/v1/offer' and method=='POST':
            assert not self.offer,'duplicate offer'
            self.offer={**copy.deepcopy(payload),'offerId':'offer-1','status':'UNPUBLISHED'};return {'offerId':'offer-1'}
        if path=='/sell/inventory/v1/offer/offer-1/publish':
            self.offer.update(status='PUBLISHED',listing={'listingId':'listing-1','listingStatus':'ACTIVE','soldQuantity':0})
            if self.timeout_publish:raise RuntimeError('Connection lost after publish')
            return {'listingId':'listing-1'}
        if path=='/sell/inventory/v1/offer/offer-1/withdraw':
            self.offer.update(status='UNPUBLISHED');self.offer.pop('listing',None);return {}
        if path=='/sell/inventory/v1/offer/offer-1':
            if method=='GET':return copy.deepcopy(self.offer)
            if self.fail_update:raise ebay.APIError('eBay rejected update',400)
            self.offer={**self.offer,**copy.deepcopy(payload)};return {}
        raise AssertionError((method,path))


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv('EBAY_ENVIRONMENT','sandbox')
    monkeypatch.setenv('EBAY_CLIENT_ID','test-client')
    monkeypatch.setenv('EBAY_CLIENT_SECRET','test-secret')
    monkeypatch.setenv('EBAY_RUNAME','test-runame')
    monkeypatch.delenv('EBAY_REFRESH_TOKEN',raising=False)
    ebay.token_path().unlink(missing_ok=True)
    result=Server()
    monkeypatch.setattr(ebay,'api',result)
    monkeypatch.setattr(ebay,'category_metadata',lambda c:{'category':{'categoryId':str(c)},'conditions':[{'conditionId':'3000'}],'aspects':[{'localizedAspectName':'Brand','aspectConstraint':{'aspectRequired':True}}]})
    return result


@pytest.fixture
def publish_settings():
    return {'merchantLocationKey':'warehouse','fulfillmentPolicyId':'shipping','paymentPolicyId':'payment','returnPolicyId':'returns','categoryId':'123','condition':'USED_EXCELLENT','aspects':{'Brand':['Dell']},'imageUrls':['https://photos.example/actual-monitor.jpg']}


def published(item,server,publish_settings):return ebay.publish(item['id'],publish_settings)


def test_publish_only_marks_listing_after_remote_confirmation(item,server,publish_settings):
    store.put('items',{**item,'status':'draft'})
    row=published(item,server,publish_settings)
    assert row['status']=='posted' and row['source']=='ebay_api' and row['environment']=='sandbox'
    assert row['url']=='https://www.sandbox.ebay.com/itm/listing-1'
    assert store.get('items',item['id'])['status']=='listed'
    assert server.inventory['availability']['shipToLocationAvailability']['quantity']==1
    assert server.offer['listingDuration']=='GTC'
    assert server.offer['pricingSummary']['price']['value']=='300.00'
    assert store.all_rows('orders')==[]


def test_repeat_publish_cannot_create_a_duplicate(item,server,publish_settings):
    published(item,server,publish_settings)
    with pytest.raises(ValueError,match='already exists'):published(item,server,publish_settings)
    assert len([c for c in server.calls if c[0]=='POST' and c[1]=='/sell/inventory/v1/offer'])==1


def test_publish_timeout_is_recovered_without_duplicate(item,server,publish_settings):
    server.timeout_publish=True
    with pytest.raises(RuntimeError):published(item,server,publish_settings)
    assert ebay.listing_for(item['id'])['status']=='publish_uncertain'
    assert ebay.check(item['id'])['status']=='posted'
    with pytest.raises(ValueError):published(item,server,publish_settings)
    assert len([c for c in server.calls if c[1].endswith('/publish')])==1


def test_offer_creation_response_loss_is_recovered_before_inventory_replacement(item,server,publish_settings,monkeypatch):
    published(item,server,publish_settings)
    row=ebay.listing_for(item['id']);row.pop('offer_id');row['status']='publish_failed';store.put('actions',row)
    writes_before=len([c for c in server.calls if c[0]=='PUT'])
    result=published(item,server,publish_settings)
    assert result['status']=='posted'
    assert len([c for c in server.calls if c[0]=='PUT'])==writes_before


def test_update_preserves_quantity_regulatory_and_shipping_fields(item,server,publish_settings):
    published(item,server,publish_settings)
    server.inventory['packageWeightAndSize']={'weight':{'value':4,'unit':'POUND'}}
    server.inventory['availability']['shipToLocationAvailability']['quantity']=0
    server.offer['availableQuantity']=0
    server.offer['regulatory']={'productSafety':{'statements':['test']}}
    server.offer['listingPolicies']['bestOfferTerms']={'bestOfferEnabled':False}
    store.put('items',{**store.get('items',item['id']),'price':325,'description':'Reviewed new description'})
    ebay.update(item['id'])
    assert server.inventory['availability']['shipToLocationAvailability']['quantity']==0
    assert server.inventory['packageWeightAndSize']['weight']['value']==4
    assert server.offer['availableQuantity']==0 and server.offer['regulatory']
    assert server.offer['listingPolicies']['bestOfferTerms']=={'bestOfferEnabled':False}
    assert server.offer['pricingSummary']['price']['value']=='325.00'
    assert 'Reviewed new description' in server.offer['listingDescription']
    assert not channels.workspace()['listings'][0]['needs_sync']


def test_partial_failed_update_stays_dirty_and_retriable(item,server,publish_settings):
    published(item,server,publish_settings)
    store.put('items',{**store.get('items',item['id']),'price':325})
    server.fail_update=True
    with pytest.raises(ebay.APIError):ebay.update(item['id'])
    assert channels.workspace()['listings'][0]['needs_sync']
    server.fail_update=False;ebay.update(item['id'])
    assert not channels.workspace()['listings'][0]['needs_sync']


def test_identity_changes_need_explicit_review_of_ebay_fields(item,server,publish_settings):
    published(item,server,publish_settings)
    store.put('items',{**store.get('items',item['id']),'specs':{'included':'New checked cable'}})
    with pytest.raises(ValueError,match='Product identity'):ebay.update(item['id'])
    ebay.update(item['id'],publish_settings)


def test_withdraw_checks_remote_before_marking_removed(item,server,publish_settings):
    published(item,server,publish_settings)
    row=ebay.withdraw(item['id'])
    assert row['status']=='removed' and store.get('items',item['id'])['status']=='draft'
    ebay.withdraw(item['id'])
    assert len([c for c in server.calls if c[1].endswith('/withdraw')])==1


def test_detected_sale_blocks_relisting_without_inventing_financials(item,server,publish_settings,seller):
    row=published(item,server,publish_settings)
    other=channels.record_listing(store.get('items',item['id']),'facebook','https://www.facebook.com/marketplace/item/123')
    server.offer['listing']['soldQuantity']=1
    assert ebay.check(item['id'])['status']=='sale_detected'
    assert store.get('items',item['id'])['status']=='sale_pending'
    assert store.get('actions',other['id'])['status']=='needs_removal'
    assert not store.all_rows('orders')
    assert seller.post('/api/items/actual-item/publish',json={'confirm_facts':True}).status_code==400
    with pytest.raises(ValueError):published(item,server,publish_settings)
    channels.complete_sale(item['id'],row['id'],280,20,100)
    assert ebay.check(item['id'])['status']=='sold'
    assert len(store.all_rows('orders'))==1


def test_external_sale_queues_and_automatically_withdraws_ebay_copy(item,server,publish_settings):
    row=published(item,server,publish_settings)
    other=channels.record_listing(store.get('items',item['id']),'facebook','https://www.facebook.com/marketplace/item/123')
    channels.complete_sale(item['id'],other['id'],280,20,100)
    assert store.get('actions',row['id'])['status']=='needs_removal'
    ebay.sync_all()
    assert store.get('actions',row['id'])['status']=='removed'
    assert store.get('items',item['id'])['status']=='sold'


def test_on_hold_and_unknown_status_are_not_active_inventory(item,server,publish_settings):
    published(item,server,publish_settings)
    server.offer['listing']['listingOnHold']=True
    assert ebay.check(item['id'])['status']=='on_hold'
    assert store.get('items',item['id'])['status']=='draft'
    server.offer['listing'].pop('listingOnHold');server.offer['listing']['listingStatus']='NOT_LISTED'
    assert ebay.check(item['id'])['status']=='remote_unknown'


@pytest.mark.parametrize('missing',['merchantLocationKey','fulfillmentPolicyId','paymentPolicyId','returnPolicyId','categoryId','condition'])
def test_missing_publish_fields_fail_before_remote_writes(item,server,publish_settings,missing):
    publish_settings.pop(missing)
    with pytest.raises(ValueError):published(item,server,publish_settings)
    assert not server.calls


def test_unreviewed_facts_and_category_requirements_prevent_publication(item,server,publish_settings):
    store.put('items',{**item,'confirmed':False})
    with pytest.raises(ValueError,match='Review'):published(item,server,publish_settings)
    store.put('items',item);publish_settings['aspects']={}
    with pytest.raises(ValueError,match='Required eBay aspect'):published(item,server,publish_settings)
    publish_settings['aspects']={'Brand':['Dell']};publish_settings['condition']='USED_GOOD'
    with pytest.raises(ValueError,match='not supported'):published(item,server,publish_settings)
    assert not server.calls


def test_manual_url_cannot_be_updated_or_withdrawn(item,server):
    channels.record_listing(item,'ebay','https://www.ebay.com/itm/123')
    with pytest.raises(ValueError):ebay.update(item['id'])
    with pytest.raises(ValueError):ebay.withdraw(item['id'])
    assert not server.calls


def test_api_listing_cannot_be_overwritten_by_manual_confirmation(item,server,publish_settings,seller):
    row=published(item,server,publish_settings)
    assert seller.post(f'/api/channels/listings/{row["id"]}/removed',json={'confirm_removed':True}).status_code==400
    assert seller.post('/api/items/actual-item/channels/ebay/link',json={'url':'https://www.ebay.com/itm/123','confirm_posted':True}).status_code==400


def test_oauth_state_expiry_and_replay_are_rejected(item,server,seller,monkeypatch):
    calls=[];monkeypatch.setattr(ebay,'exchange',lambda code:calls.append(code))
    response=seller.post('/api/ebay/connect',json={})
    assert response.status_code==200 and 'auth.sandbox.ebay.com' in response.json['url']
    with seller.session_transaction() as session:state=session['ebay_oauth']['state']
    assert seller.get('/api/ebay/callback?code=abc&state=wrong').status_code==400
    assert not calls
    seller.post('/api/ebay/connect',json={})
    with seller.session_transaction() as session:state=session['ebay_oauth']['state']
    assert seller.get('/api/ebay/callback?code=abc&state='+state).status_code==302
    assert calls==['abc']
    assert seller.get('/api/ebay/callback?code=abc&state='+state).status_code==400
    seller.post('/api/ebay/connect',json={})
    with seller.session_transaction() as session:session['ebay_oauth']={**session['ebay_oauth'],'expires_at':0};state=session['ebay_oauth']['state']
    assert seller.get('/api/ebay/callback?code=abc&state='+state).status_code==400


def test_tokens_are_encrypted_and_excluded_from_workspace(server,monkeypatch):
    ebay.save_tokens({'access_token':'private-access','refresh_token':'private-refresh','expires_in':3600})
    assert b'private-access' not in ebay.token_path().read_bytes()
    assert ebay.read_tokens()['refresh_token']=='private-refresh'
    assert 'private-' not in json.dumps(ebay.status())
    monkeypatch.setenv('EBAY_ENVIRONMENT','production')
    assert not ebay.status()['connected']
    monkeypatch.setenv('EBAY_ENVIRONMENT','sandbox')
    ebay.token_path().unlink()


def test_api_production_write_gate_and_network_failure(monkeypatch):
    monkeypatch.setenv('EBAY_ENVIRONMENT','production');monkeypatch.setenv('EBAY_ENABLE_PRODUCTION','false')
    with pytest.raises(ValueError,match='disabled'):ebay.api('POST','/sell/inventory/v1/offer',{})
    monkeypatch.setenv('EBAY_ENVIRONMENT','sandbox');monkeypatch.setattr(ebay,'access_token',lambda **k:'private-access')
    def fail(*a,**k):raise ebay.requests.Timeout('secret request internals')
    monkeypatch.setattr(ebay.requests,'request',fail)
    with pytest.raises(RuntimeError,match='Check status'):ebay.api('POST','/sell/inventory/v1/offer',{})


def test_ebay_routes_require_seller_and_explicit_action_confirmation(item,server,seller):
    buyer=app.app.test_client()
    assert buyer.get('/api/ebay').status_code==401
    assert buyer.post('/api/ebay/sync',json={}).status_code==401
    assert seller.post('/api/items/actual-item/ebay/publish',json={}).status_code==400
    assert not server.calls

def test_existing_inventory_sku_can_be_linked_without_remote_writes(item,server,publish_settings):
    published(item,server,publish_settings)
    row=ebay.listing_for(item['id'])
    with store.connection() as db:db.execute('DELETE FROM actions WHERE id=?',(row['id'],))
    before=len([c for c in server.calls if c[0]!='GET'])
    attached=ebay.attach_sku(item['id'],row['sku'])
    assert attached['offer_id']=='offer-1' and attached['status']=='posted'
    assert len([c for c in server.calls if c[0]!='GET'])==before
    assert channels.workspace()['listings'][0]['needs_sync']
    ebay.update(item['id'],publish_settings)

def test_multi_unit_sku_and_duplicate_sku_are_rejected(item,server,publish_settings):
    published(item,server,publish_settings)
    other=store.put('items',{**item,'id':'other'})
    server.offer['availableQuantity']=2
    with pytest.raises(ValueError,match='single-unit'):ebay.attach_sku(other['id'],'snapsell-actual-item')
    server.offer['availableQuantity']=1
    with pytest.raises(ValueError,match='already linked'):ebay.attach_sku(other['id'],'snapsell-actual-item')

def test_manual_active_listing_prevents_duplicate_publication(item,server,publish_settings):
    channels.record_listing(item,'ebay','https://www.ebay.com/itm/123')
    with pytest.raises(ValueError,match='manually recorded'):published(item,server,publish_settings)
    assert not server.calls

def test_expired_access_token_refresh_preserves_refresh_token(server,monkeypatch):
    ebay.save_tokens({'access_token':'old','refresh_token':'refresh-secret','expires_in':0})
    grants=[]
    def token(data):grants.append(data);return {'access_token':'new','expires_in':3600}
    monkeypatch.setattr(ebay,'oauth',token)
    assert ebay.access_token()=='new'
    assert ebay.read_tokens()['refresh_token']=='refresh-secret'
    assert len(grants)==1 and grants[0]['grant_type']=='refresh_token'
    assert ebay.access_token()=='new' and len(grants)==1
    ebay.token_path().unlink()

def test_category_metadata_requires_leaf_and_returns_conditions(monkeypatch):
    calls=[]
    def request(method,path,*a,**k):
        calls.append(path)
        if 'default_category' in path:return {'categoryTreeId':'0'}
        if 'subtree' in path:return {'categorySubtreeNode':{'leafCategoryTreeNode':True,'category':{'categoryId':'123'}}}
        if 'aspects' in path:return {'aspects':[{'localizedAspectName':'Brand'}]}
        if 'condition' in path:return {'itemConditionPolicies':[{'categoryId':'123','itemConditions':[{'conditionId':'3000'}]}]}
        raise AssertionError(path)
    monkeypatch.setattr(ebay,'api',request)
    assert ebay.category_metadata('123')['conditions'][0]['conditionId']=='3000'
    assert len(calls)==4
    with pytest.raises(ValueError):ebay.category_metadata('invalid')

def test_remote_error_does_not_mark_a_listing_removed(item,server,publish_settings,monkeypatch):
    published(item,server,publish_settings)
    original=server.__call__
    def request(method,path,payload=None,**kwargs):
        if path.endswith('/withdraw'):raise ebay.APIError('eBay withdrawal rejected',400)
        return original(method,path,payload)
    monkeypatch.setattr(ebay,'api',request)
    with pytest.raises(ebay.APIError):ebay.withdraw(item['id'])
    assert ebay.listing_for(item['id'])['status']=='posted'
