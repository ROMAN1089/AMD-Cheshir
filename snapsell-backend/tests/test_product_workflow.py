import io
import json
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from test_research import isolated,item,seller
import app,store,channels,photos,backups,attribute_evidence
import maintenance

def image_bytes(color='green',size=(120,80)):
    data=io.BytesIO();Image.new('RGB',size,color).save(data,'PNG');return data.getvalue()

def test_manual_item_photo_crop_gallery_and_export(item,seller):
    response=seller.post('/api/items/actual-item/photos',data={'photo':(io.BytesIO(image_bytes()),'my-photo.png')})
    assert response.status_code==200
    first=response.json['image'];assert first.endswith('.jpg') and response.json['confirmed'] is False
    with Image.open(photos.path_for(first)) as image:assert not image.getexif()
    cropped=seller.patch('/api/items/actual-item/photos',json={'action':'crop','url':first,'crop':[.25,0,.5,1]})
    assert cropped.status_code==200
    with Image.open(photos.path_for(cropped.json['image'])) as image:assert image.size==(60,80)
    archive=zipfile.ZipFile(io.BytesIO(channels.bundle(store.get('items',item['id']),'facebook')[0]))
    assert 'photo.jpg' in archive.namelist() and 'photo-2.jpg' in archive.namelist()
    assert len(json.loads(archive.read('listing.json'))['photos'])==2
    assert seller.patch('/api/items/actual-item/photos',json={'action':'primary','url':first}).json['image']==first
    assert seller.patch('/api/items/actual-item/photos',json={'action':'remove','url':first}).json['image']!=first

@pytest.mark.parametrize('data',[{'action':'crop','url':'/media/../../.session-secret','crop':[0,0,1,1]},{'action':'primary','url':'https://evil.invalid/image.jpg'}])
def test_photos_reject_unowned_sources(item,seller,data):
    assert seller.patch('/api/items/actual-item/photos',json=data).status_code==400

@pytest.mark.parametrize('crop',[[0,0,0,1],[-.1,0,1,1],[.5,0,1,1],[0,0,'bad',1],[0,0,True,1]])
def test_crop_validation(item,seller,crop):
    first=seller.post('/api/items/actual-item/photos',data={'photo':(io.BytesIO(image_bytes()),'photo.png')}).json['image']
    assert seller.patch('/api/items/actual-item/photos',json={'action':'crop','url':first,'crop':crop}).status_code==400

def test_corrupt_photo_and_unauthenticated_upload(item,seller):
    assert seller.post('/api/items/actual-item/photos',data={'photo':(io.BytesIO(b'<svg/>'),'pretend.jpg')}).status_code==400
    assert app.app.test_client().post('/api/items/actual-item/photos').status_code==401

def test_archive_and_restore_preserve_item_and_block_posting(item,seller):
    assert seller.post('/api/items/actual-item/archive',json={}).json['archived_at']
    assert seller.post('/api/items/actual-item/channels/facebook/link',json={'confirm_posted':True,'url':'https://www.facebook.com/marketplace/item/12345/'}).status_code==400
    assert 'archived_at' not in seller.post('/api/items/actual-item/archive',json={'restore':True}).json
    listing=channels.record_listing(store.get('items',item['id']),'facebook','https://www.facebook.com/marketplace/item/12345/')
    assert seller.post('/api/items/actual-item/archive',json={}).status_code==400
    assert store.get('actions',listing['id'])['status']=='posted'

def test_real_expenses_and_duplicate_sale(item,seller):
    listing=channels.record_listing(item,'facebook','https://www.facebook.com/marketplace/item/12345/')
    data={'listing_id':listing['id'],'amount':300,'fee':20,'cost':100,'shipping':15,'packaging':3,'repairs':30,'taxes':4,'labor':10,'refunds':2,'confirm_completed':True}
    response=seller.post('/api/items/actual-item/channels/sale',json=data)
    assert response.status_code==200 and response.json['economics']['net_contribution']==116
    assert seller.post('/api/items/actual-item/channels/sale',json=data).status_code==400
    assert channels.workspace()['net_contribution']==116

def test_attribute_audit_never_assumes_missing_unit_facts():
    product={'category':'Phone','specs':{'battery':'87%','repairs':'None','ai_face_id':'Yes'}}
    report=attribute_evidence.audit(product,{'title':'Used iPhone','evidence':{'description':'Battery health: 75%. Screen replaced.'}})
    assert report['conflicts']==['battery','repairs'] and report['unverified']==['ai_face_id']
    assert attribute_evidence.audit(product,{'title':'Used phone'})['unverified']==['battery','repairs','ai_face_id']

def test_recovery_includes_encryption_key_and_media(item,tmp_path,monkeypatch):
    # Do not copy actual seller credentials or private files into an isolated test.
    monkeypatch.setattr(store,'ROOT',tmp_path/'project')
    source=store.DATA/'media'/'recovery-test.jpg';source.parent.mkdir(parents=True,exist_ok=True);source.write_bytes(image_bytes())
    import base64,hashlib
    from cryptography.fernet import Fernet
    encryption_key=base64.urlsafe_b64encode(hashlib.sha256((store.DATA/'.session-secret').read_bytes()).digest())
    (store.DATA/'.ebay-sandbox.token').write_bytes(Fernet(encryption_key).encrypt(b'isolated-recovery-token'))
    archive=backups.create(tmp_path/'archives')
    (store.DATA/'.ebay-sandbox.token').unlink()
    assert backups.verify(archive)['files']
    destination=backups.restore(archive,tmp_path/'restored')
    assert (destination/'data/media/recovery-test.jpg').read_bytes()==source.read_bytes()
    assert (destination/'data/.session-secret').read_bytes()==(store.DATA/'.session-secret').read_bytes()
    recovered_key=base64.urlsafe_b64encode(hashlib.sha256((destination/'data/.session-secret').read_bytes()).digest())
    assert Fernet(recovered_key).decrypt((destination/'data/.ebay-sandbox.token').read_bytes())==b'isolated-recovery-token'
    import sqlite3
    with sqlite3.connect(destination/'data/snapsell.sqlite3') as db:assert db.execute('SELECT id FROM items').fetchone()[0]==item['id']
    with pytest.raises(ValueError):backups.restore(archive,destination)

def test_backup_tampering_is_rejected(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as archive:archive.writestr('manifest.json',json.dumps({'format':1,'files':[{'path':'../outside','sha256':'bad'}]}))
    with pytest.raises(ValueError):backups.verify(path)

def test_cleanup_preserves_product_photos_and_active_jobs(item,tmp_path,monkeypatch):
    data=tmp_path/'data';data.mkdir();monkeypatch.setattr(store,'DATA',data)
    monkeypatch.setattr(store,'DB',data/'snapsell.sqlite3');store.initialize()
    item=store.put('items',{**item,'source':'video','job_id':'finished','image':'/media/finished/frame-0.jpg'})
    for name in ['media/finished/frame-0.jpg','media/finished/frame-1.jpg','media/orphan.jpg','media/active/frame-0.jpg','uploads/finished.mp4','uploads/active.mp4']:
        path=data/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'owned-test-file')
    store.put('jobs',{'id':'finished','status':'completed','path':str(data/'uploads/finished.mp4')})
    store.put('jobs',{'id':'active','status':'processing','path':str(data/'uploads/active.mp4')})
    import os,time
    os.utime(data/'media/orphan.jpg',(time.time()-7200,time.time()-7200))
    candidates=maintenance.disposable()
    assert set(candidates)=={data/'media/orphan.jpg',data/'uploads/finished.mp4'}
    assert maintenance.cleanup()['removed_files']==2
    assert (data/'media/finished/frame-1.jpg').exists() and (data/'uploads/active.mp4').exists()
    assert store.get('jobs','finished')['upload_removed'] is True

def test_complete_manual_marketplace_workflow_and_persisted_price(seller):
    created=seller.post('/api/items',json={'title':'Used wooden chair','category':'Furniture','condition':'Good','price':60,'cost':15}).json
    key=created['id']
    assert seller.post(f'/api/items/{key}/photos',data={'photo':(io.BytesIO(image_bytes()),'chair.png')}).status_code==200
    # Simulate a newer supported price arriving while an older editor is open.
    seller.patch(f'/api/items/{key}',json={'price':75})
    assert seller.patch(f'/api/items/{key}',json={'description':'Seller checked the joints.'}).json['price']==75
    assert seller.post(f'/api/items/{key}/review',json={'confirm_facts':True}).json['confirmed']
    kit=seller.get(f'/api/items/{key}/channels/facebook').json
    assert kit['ready_for_manual_posting'] and kit['price_usd']==75
    assert not store.all_rows('actions')
    linked=seller.post(f'/api/items/{key}/channels/facebook/link',json={'url':'https://www.facebook.com/marketplace/item/54321/','confirm_posted':True}).json
    sale=seller.post(f'/api/items/{key}/channels/sale',json={'listing_id':linked['id'],'amount':70,'fee':0,'cost':15,'packaging':2,'confirm_completed':True})
    assert sale.status_code==200 and sale.json['economics']['net_contribution']==53
    assert seller.get('/api/workspace').json['analytics']['net_contribution']==53

def test_archived_item_cannot_hide_scheduled_pickup(item,seller):
    store.put('appointments',{'id':'pickup','item_id':item['id'],'status':'scheduled'})
    assert seller.post('/api/items/actual-item/archive',json={}).status_code==400
