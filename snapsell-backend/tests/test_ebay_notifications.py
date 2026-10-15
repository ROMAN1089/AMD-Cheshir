import base64
import hashlib
import json
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from test_research import isolated,app,store,item
import ebay_notifications as notifications

def signed(monkeypatch,digest='SHA256'):
    private=ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(notifications,'public_key',lambda kid:private.public_key())
    body=json.dumps({'metadata':{'topic':'MARKETPLACE_ACCOUNT_DELETION'},'notification':{'data':{'username':'deleted-seller','userId':'immutable-id'}}}).encode()
    signature=private.sign(body,ec.ECDSA({'SHA1':hashes.SHA1,'SHA256':hashes.SHA256}[digest]()))
    header=base64.b64encode(json.dumps({'alg':'ecdsa','digest':digest,'kid':'key-1','signature':base64.b64encode(signature).decode()}).encode()).decode()
    return body,header

@pytest.mark.parametrize('digest',['SHA1','SHA256'])
def test_real_ecdsa_signature_and_tamper(monkeypatch,digest):
    body,header=signed(monkeypatch,digest)
    assert notifications.verify(body,header)['username']=='deleted-seller'
    with pytest.raises(InvalidSignature):notifications.verify(body+b' ',header)

def test_missing_or_malformed_signature_cannot_delete():
    for value in ['', 'not base64',base64.b64encode(b'{}').decode()]:
        with pytest.raises(InvalidSignature):notifications.verify(b'{}',value)

def test_purge_removes_snapshots_but_preserves_own_item_and_other_merchants(item):
    store.put('comparables',{'id':'ebay-1','item_id':item['id'],'source_name':'eBay','seller_id':'ebay:deleted-seller'})
    store.put('comparables',{'id':'other','source_name':'Loop','price':123})
    store.put('jobs',{'id':'research-1','type':'market_research','item_id':item['id'],'sources':[{'url':'https://www.ebay.com/itm/123'}]})
    store.put('items',{**item,'price_assessment':{'research_id':'research-1'}})
    notifications.purge_research({'userId':'immutable-id'})
    assert store.get('comparables','ebay-1') is None
    assert store.get('jobs','research-1') is None
    assert store.get('comparables','other')['price']==123
    assert store.get('items',item['id'])['price']==item['price']
    assert 'price_assessment' not in store.get('items',item['id'])
    assert 'immutable-id' not in json.dumps(store.all_rows('actions'))

def test_tombstone_prevents_reimport(item):
    notifications.purge_research({'username':'deleted-seller'})
    assert not notifications.allowed_seller('deleted-seller')
    assert notifications.allowed_seller('other-seller')

def test_relay_failure_pauses_browse_without_ack(monkeypatch):
    monkeypatch.setattr(notifications,'config',lambda:{'url':'https://test.workers.dev','token':'private'})
    calls=[]
    def fail(*a,**k):calls.append(a);raise RuntimeError('network')
    monkeypatch.setattr(notifications.requests,'get',fail)
    assert not notifications.sync()
    assert len(calls)==1 and notifications.status()['error']

def test_does_not_send_poll_secret_to_unapproved_host(monkeypatch):
    monkeypatch.setattr(notifications,'config',lambda:{'url':'https://attacker.example','token':'private'})
    monkeypatch.setattr(notifications.requests,'get',lambda *a,**k:pytest.fail('secret leaked'))
    assert not notifications.sync()
