"""Sealed Cloudflare inbox for the local, read-only eBay price integration.

No payloads, identifiers or credentials are logged. Invalid signatures never delete data.
"""
import base64
import hashlib
import json
import re
import threading
import time
from functools import wraps
from urllib.parse import quote, urlsplit

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import dotenv_values
import store

LOCK=threading.RLock()
_keys={}
_status={'configured':False,'last_sync':None,'error':None,'pending':None}
_thread=None

def serialized(fn):
    @wraps(fn)
    def call(*args,**kwargs):
        with LOCK:return fn(*args,**kwargs)
    return call

def config():
    import os
    values={**os.environ,**{k:v for k,v in dotenv_values(store.ROOT/'.env').items() if v is not None}}
    url=values.get('EBAY_NOTIFICATION_RELAY','').rstrip('/')
    return {'url':url,'token':values.get('EBAY_NOTIFICATION_POLL_TOKEN',''),'client_id':values.get('EBAY_BROWSE_CLIENT_ID',''),'client_secret':values.get('EBAY_BROWSE_CLIENT_SECRET','')}

def status():return dict(_status)

def decode(text):return base64.b64decode(text,validate=True)

def unseal(value):
    private=serialization.load_pem_private_key((store.ROOT/'private'/'ebay-notifications.pem').read_bytes(),password=None)
    secret=private.decrypt(decode(value['key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
    return json.loads(AESGCM(secret).decrypt(decode(value['iv']),decode(value['ciphertext']),None))

def public_key(kid):
    if kid in _keys and _keys[kid][0]>time.time():return _keys[kid][1]
    c=config()
    r=requests.post('https://api.ebay.com/identity/v1/oauth2/token',auth=(c['client_id'],c['client_secret']),data={'grant_type':'client_credentials','scope':'https://api.ebay.com/oauth/api_scope'},timeout=(10,30))
    if not r.ok:raise RuntimeError('Cannot authenticate to verify eBay notifications.')
    token=r.json()['access_token']
    r=requests.get('https://api.ebay.com/commerce/notification/v1/public_key/'+quote(kid,safe=''),headers={'Authorization':'Bearer '+token},timeout=(10,30))
    if not r.ok:raise RuntimeError('Cannot retrieve the eBay notification verification key.')
    result=r.json()
    key=serialization.load_pem_public_key(result['key'].encode())
    if not isinstance(key,ec.EllipticCurvePublicKey):raise RuntimeError('Unexpected eBay verification key type.')
    if len(_keys)>=32:_keys.clear()
    _keys[kid]=(time.time()+3600,key)
    return key

def verify(body,header):
    try:
        data=json.loads(decode(header))
        digest={'SHA1':hashes.SHA1,'SHA256':hashes.SHA256}.get(data.get('digest','').upper())
        if data.get('alg','').lower()!='ecdsa' or digest is None or not re.fullmatch(r'[A-Za-z0-9_=-]{1,256}',data.get('kid','')):raise ValueError('Unsupported signature.')
        signature=decode(data['signature'])
    except (ValueError,KeyError,TypeError):raise InvalidSignature from None
    key=public_key(data['kid'])
    key.verify(signature,body,ec.ECDSA(digest()))
    value=json.loads(body)
    if value.get('metadata',{}).get('topic')!='MARKETPLACE_ACCOUNT_DELETION':raise InvalidSignature
    identifiers=value.get('notification',{}).get('data',{})
    if not isinstance(identifiers,dict) or not any(isinstance(identifiers.get(k),str) and identifiers[k] for k in ['username','userId','eiasToken']):raise InvalidSignature
    return identifiers

def purge_research(identifiers):
    """Invalidate all eBay research caches when IDs cannot be mapped to Browse usernames.

    The deletion feed can contain only immutable userId, whereas Browse exposes username.
    Clearing all eBay-derived evidence is deliberate; seller-entered item prices stay intact.
    """
    import pricing
    def contains_ebay(value):
        if isinstance(value,dict):return any(contains_ebay(k) or contains_ebay(v) for k,v in value.items())
        if isinstance(value,list):return any(contains_ebay(v) for v in value)
        return isinstance(value,str) and ('ebay' in value.casefold())
    def matches(value):
        if isinstance(value,dict):return any(matches(v) for v in value.values())
        if isinstance(value,list):return any(matches(v) for v in value)
        return isinstance(value,str) and any(v and (value==v or value=='ebay:'+v) for v in identifiers.values() if isinstance(v,str))
    with LOCK,store.connection() as db:
        db.execute('PRAGMA secure_delete=ON')
        affected_jobs=set();affected_items=set()
        for table in ['comparables','jobs','history','actions','conversations','orders','appointments']:
            for row in db.execute(f'SELECT id,body FROM {table}').fetchall():
                body=json.loads(row['body'])
                # Keep non-personal relay cursor/tombstones and local marketplace settings.
                if table=='actions' and body.get('type') in ['ebay_notification_state','ebay_deletion_tombstone']:continue
                cached=table in ['comparables','jobs','history'] and contains_ebay(body)
                if cached or matches(body):
                    if table=='jobs':affected_jobs.add(row['id'])
                    if body.get('item_id'):affected_items.add(body['item_id'])
                    db.execute(f'DELETE FROM {table} WHERE id=?',(row['id'],))
        # Remove derived snapshots too, even when they do not carry a seller identifier.
        for table in ['jobs','history','actions']:
            for row in db.execute(f'SELECT id,body FROM {table}').fetchall():
                body=json.loads(row['body'])
                if body.get('research_id') in affected_jobs or (table=='jobs' and body.get('item_id') in affected_items and body.get('type')=='market_research'):
                    db.execute(f'DELETE FROM {table} WHERE id=?',(row['id'],))
        for row in db.execute('SELECT id,body FROM items').fetchall():
            body=json.loads(row['body']);assessment=body.get('price_assessment',{})
            if body['id'] in affected_items or assessment.get('research_id') in affected_jobs:
                body.pop('price_assessment',None)
                db.execute('UPDATE items SET body=? WHERE id=?',(json.dumps(body),row['id']))
        for row in db.execute('SELECT id,body FROM events').fetchall():
            body=json.loads(row['body'])
            if contains_ebay(body) or matches(body):db.execute('DELETE FROM events WHERE id=?',(row['id'],))
        for value in identifiers.values():
            if not isinstance(value,str) or not value:continue
            digest=hashlib.sha256(value.encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO actions(id,body) VALUES(?,?)',('ebay-deleted-'+digest,json.dumps({'id':'ebay-deleted-'+digest,'type':'ebay_deletion_tombstone','digest':digest})))
    pricing._cache.clear()
    # Erase deleted bytes in SQLite WAL, rather than keeping old raw seller snapshots there.
    with store.connection() as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

def allowed_seller(username):
    digest=hashlib.sha256(username.encode()).hexdigest()
    return not store.get('actions','ebay-deleted-'+digest)

def sync():
    c=config()
    if not c['url'] or not c['token']:
        _status.update(configured=False);return True
    p=urlsplit(c['url'])
    if p.scheme!='https' or not p.hostname or not p.hostname.endswith(('.workers.dev','.pages.dev')) or p.path or p.query or p.fragment or p.username or p.port:
        _status.update(configured=True,error='Invalid notification relay URL.');return False
    headers={'Authorization':'Bearer '+c['token']}
    try:
        with LOCK:
            for _ in range(40):
                r=requests.get(c['url']+'/pending',headers=headers,timeout=(10,30),allow_redirects=False)
                if r.status_code!=200:raise RuntimeError('Notification inbox could not be read.')
                rows=r.json()
                if not isinstance(rows,list) or len(rows)>50:raise RuntimeError('Unexpected notification inbox response.')
                _status.update(pending=len(rows))
                if not rows:break
                for row in rows:
                    value=unseal(json.loads(row['sealed']))
                    try:
                        identifiers=verify(decode(value['body']),value['signature'])
                    except InvalidSignature:
                        identifiers=None
                    if identifiers:purge_research(identifiers)
                    # Only acknowledge after verification/deletion or a proven invalid signature.
                    r=requests.post(c['url']+'/ack',json={'id':row['id']},headers=headers,timeout=(10,30),allow_redirects=False)
                    if r.status_code!=204:raise RuntimeError('Notification acknowledgement failed.')
            else:raise RuntimeError('Notification backlog remains; eBay research is paused.')
        _status.update(configured=True,last_sync=store.now(),error=None,pending=0);return True
    except Exception:
        _status.update(configured=True,error='Notification sync failed; eBay research is paused. Check relay settings and Production API access.')
        return False

def start_worker():
    global _thread
    if _thread and _thread.is_alive():return
    def loop():
        while True:
            sync();time.sleep(60)
    _thread=threading.Thread(target=loop,daemon=True,name='ebay-deletion');_thread.start()
