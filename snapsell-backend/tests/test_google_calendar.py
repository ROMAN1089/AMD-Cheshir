import json,time
from urllib.parse import urlsplit,parse_qs
import pytest
from test_research import isolated,item,seller,app,store
from test_deals import slot,book
import deals
import google_calendar as google

@pytest.fixture(autouse=True)
def google_isolated(monkeypatch):
    monkeypatch.setattr(google,'dotenv_values',lambda *a,**k:{})
    for name in ['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_OAUTH_CLIENT_FILE','GOOGLE_REDIRECT_URI']:monkeypatch.delenv(name,raising=False)
    google.token_path().unlink(missing_ok=True)
    monkeypatch.setattr(google.requests,'request',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unmocked Google request')))

@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID','test-client');monkeypatch.setenv('GOOGLE_CLIENT_SECRET','test-secret')
    google.save_tokens(dict(refresh_token='secret-refresh',access_token='secret-access',expires_at=time.time()+500,client_id='test-client',account_id='account-a',email='test@example.test'))

def remote_for(a):return {'id':a['google']['event_id'],'etag':'version-1',**google.event_body(a)}

def linked(item,monkeypatch,connected):
    monkeypatch.setattr(google,'busy',lambda *a,**k:[])
    monkeypatch.setattr(google,'after_save',lambda a:a)
    return book(item,slot())

def test_missing_keys_are_truthfully_reported(seller):
    r=seller.get('/api/google-calendar').json
    assert not r['configured'] and not r['connected']
    assert seller.post('/api/google-calendar/connect',json={}).status_code==400

def test_tokens_are_encrypted_and_never_returned(connected,seller):
    assert b'secret-refresh' not in google.token_path().read_bytes()
    assert 'secret-refresh' not in json.dumps(seller.get('/api/google-calendar').json)
    assert 'secret-access' not in json.dumps(seller.get('/api/workspace').json)

def test_oauth_uses_state_pkce_offline_and_narrow_scope(connected,seller):
    d=seller.post('/api/google-calendar/connect',json={}).json
    p=parse_qs(urlsplit(d['url']).query)
    assert p['code_challenge_method']==['S256'] and p['access_type']==['offline']
    assert p['scope']==[google.SCOPE] and len(p['state'][0])>30
    assert 'https://www.googleapis.com/auth/calendar ' not in google.SCOPE

@pytest.mark.parametrize('fault',['state','expired','client','redirect','declined'])
def test_oauth_invalid_callback_never_exchanges(connected,seller,monkeypatch,fault):
    d=seller.post('/api/google-calendar/connect',json={}).json
    state=parse_qs(urlsplit(d['url']).query)['state'][0]
    if fault=='expired':
        with seller.session_transaction() as s:s['google_oauth']={**s['google_oauth'],'expires_at':0}
    if fault=='client':monkeypatch.setenv('GOOGLE_CLIENT_ID','different')
    if fault=='redirect':monkeypatch.setenv('GOOGLE_REDIRECT_URI','http://localhost:3000/api/google-calendar/callback')
    monkeypatch.setattr(google,'exchange',lambda *a:pytest.fail('Invalid OAuth callback exchanged a code'))
    path=f'/api/google-calendar/callback?state={state if fault!="state" else "wrong"}&code=code'
    if fault=='declined':path+='&error=access_denied'
    assert seller.get(path).status_code==400

def test_valid_callback_is_consumed_once(connected,seller,monkeypatch):
    d=seller.post('/api/google-calendar/connect',json={}).json;state=parse_qs(urlsplit(d['url']).query)['state'][0]
    calls=[];monkeypatch.setattr(google,'exchange',lambda *a:calls.append(a))
    path=f'/api/google-calendar/callback?state={state}&code=code'
    assert seller.get(path).status_code==302 and len(calls)==1
    assert seller.get(path).status_code==400 and len(calls)==1

def test_changed_client_never_reuses_old_authorization(connected,monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID','different')
    assert not google.status()['connected'] and google.status()['email']==''

def test_refresh_preserves_account_and_refresh_token(connected,monkeypatch):
    t=google.tokens();t['expires_at']=0;google.save_tokens(t)
    monkeypatch.setattr(google,'oauth',lambda d:{'access_token':'new-token','expires_in':3600})
    assert google.access_token()=='new-token'
    assert google.tokens()['account_id']=='account-a' and google.tokens()['refresh_token']=='secret-refresh'

def test_booking_google_busy_or_unreachable_never_saves(item,connected,monkeypatch):
    s=slot();monkeypatch.setattr(google,'busy',lambda *a,**k:[s])
    with pytest.raises(ValueError):book(item,s)
    monkeypatch.setattr(google,'busy',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Unavailable')))
    with pytest.raises(RuntimeError):book(item,s)
    assert store.all_rows('appointments')==[]

def test_create_private_event_no_invites_and_stable_id(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);calls=[]
    def api(method,path='',payload=None,**kw):
        calls.append((method,path,payload,kw))
        if method=='GET':raise google.APIError(404)
        return payload
    monkeypatch.setattr(google,'api',api)
    result=google.sync(a['id']);assert result['google']['status']=='synced'
    post=next(c for c in calls if c[0]=='POST');assert post[2]['id']==a['google']['event_id']
    assert post[2]['visibility']=='private' and 'attendees' not in post[2]
    assert post[3]['params']=={'sendUpdates':'none'}
    assert len(post[2]['reminders']['overrides'])==2

def test_update_managed_event_excludes_itself_and_uses_etag(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);calls=[];exclusions=[]
    monkeypatch.setattr(google,'busy',lambda s,e,x=None:exclusions.append(x) or [])
    monkeypatch.setattr(google,'api',lambda method,path='',payload=None,**kw:calls.append((method,payload,kw)) or (remote_for(a) if method=='GET' else {}))
    assert google.sync(a['id'])['google']['status']=='synced'
    assert exclusions==[a['google']['event_id']]
    assert calls[-1][2]['etag']=='version-1'

@pytest.mark.parametrize('problem',['foreign','guests','deleted'])
def test_other_events_guests_and_deleted_events_are_not_overwritten(item,connected,monkeypatch,problem):
    a=linked(item,monkeypatch,connected);event=remote_for(a)
    if problem=='foreign':event['extendedProperties']={}
    if problem=='guests':event['attendees']=[{'email':'other@example.test'}]
    if problem=='deleted':event['status']='cancelled'
    calls=[]
    monkeypatch.setattr(google,'api',lambda method,*args,**kw:calls.append(method) or event)
    result=google.sync(a['id']);assert result['google']['status']=='error' and calls==['GET']

def test_uncertain_insert_retry_does_not_create_duplicate(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);calls=[];exists=False
    def api(method,path='',payload=None,**kw):
        nonlocal exists
        calls.append(method)
        if method=='GET':
            if exists:return remote_for(a)
            raise google.APIError(404)
        if method=='POST':exists=True;raise RuntimeError('Timed out after insert')
        return {}
    monkeypatch.setattr(google,'api',api)
    assert google.sync(a['id'])['google']['status']=='error'
    assert google.sync(a['id'])['google']['status']=='synced'
    assert calls.count('POST')==1 and calls.count('PATCH')==1

def test_reschedule_and_cancel_keep_local_change_when_google_fails(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected)
    monkeypatch.setattr(google,'after_save',google_after_save)
    monkeypatch.setattr(google,'api',lambda *args,**kw:(_ for _ in ()).throw(google.APIError(503)))
    new=slot(8);moved=deals.update(a['id'],{'action':'reschedule','slot_id':new['id']})
    assert moved['start']==new['start'] and moved['google']['status']=='error'
    result=deals.update(a['id'],{'action':'cancel','confirm':True})
    assert result['status']=='cancelled' and result['google']['status']=='error'
    assert result['google']['next_retry_at']>time.time()

google_after_save=google.after_save

def test_cancel_only_patches_managed_event(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);remote=remote_for(a)
    a['status']='cancelled';a['revision']+=1;store.put('appointments',a);calls=[]
    monkeypatch.setattr(google,'api',lambda method,path='',payload=None,**kw:calls.append((method,payload,kw)) or (remote if method=='GET' else {}))
    assert google.sync(a['id'])['google']['status']=='synced'
    assert calls[-1][1]=={'status':'cancelled'} and calls[-1][2]['params']['sendUpdates']=='none'

def test_account_switch_cannot_move_or_create_linked_meeting(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);t=google.tokens();t['account_id']='account-b';google.save_tokens(t)
    monkeypatch.setattr(google,'api',lambda *a,**kw:pytest.fail('Account switch made an event request'))
    with pytest.raises(ValueError):google.sync(a['id'])

def test_disconnect_keeps_local_records_and_does_not_write_google(item,connected,seller,monkeypatch):
    a=linked(item,monkeypatch,connected)
    assert seller.post('/api/google-calendar/disconnect',json={}).status_code==200
    assert not google.status()['connected'] and store.get('appointments',a['id'])['google']['event_id']==a['google']['event_id']

def test_old_meeting_requires_explicit_copy_confirmation(item,seller,connected,monkeypatch):
    monkeypatch.setattr(google,'status',lambda:{'connected':False})
    a=book(item,slot())
    assert not a.get('google')
    assert seller.post('/api/google-calendar/sync/'+a['id'],json={}).status_code==400

def test_busy_pagination_all_day_declined_and_transparent(connected,monkeypatch):
    s=slot();calls=[]
    e={'id':'event','start':{'dateTime':s['start']},'end':{'dateTime':s['end']}}
    def api(*args,**kw):
        calls.append(kw['params'])
        if len(calls)==1:return {'items':[{**e,'transparency':'transparent'},{**e,'attendees':[{'self':True,'responseStatus':'declined'}]}],'nextPageToken':'page2'}
        return {'items':[{'id':'all-day','start':{'date':'2026-10-16'},'end':{'date':'2026-10-17'}}]}
    monkeypatch.setattr(google,'api',api)
    assert google.busy(s['start'],s['end'])==[{'start':s['start'],'end':s['end']}]
    assert calls[-1]['pageToken']=='page2' and calls[0]['timeZone']=='UTC'

def test_retry_worker_respects_backoff_and_recovers(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);a['google'].update(status='error',next_retry_at=time.time()+60);store.put('appointments',a)
    calls=[];monkeypatch.setattr(google,'sync',lambda key:calls.append(key))
    google.retry_pending();assert calls==[]
    a['google']['next_retry_at']=0;store.put('appointments',a);google.retry_pending();assert calls==[a['id']]

def test_google_endpoints_are_private(connected):
    guest=app.app.test_client()
    assert guest.get('/api/google-calendar').status_code==401
    assert guest.post('/api/google-calendar/connect',json={}).status_code==401

def test_busy_reschedule_keeps_original_meeting(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);new=slot(8)
    monkeypatch.setattr(google,'busy',lambda *args:[new])
    with pytest.raises(ValueError):deals.update(a['id'],{'action':'reschedule','slot_id':new['id']})
    assert store.get('appointments',a['id'])['start']==a['start']

def test_local_cancellation_survives_account_mismatch(item,connected,monkeypatch):
    a=linked(item,monkeypatch,connected);t=google.tokens();t['account_id']='account-b';google.save_tokens(t)
    monkeypatch.setattr(google,'after_save',google_after_save)
    cancelled=deals.update(a['id'],{'action':'cancel','confirm':True})
    assert cancelled['status']=='cancelled' and cancelled['google']['status']=='error'

def test_incomplete_google_permission_does_not_replace_existing_token(connected,monkeypatch):
    old=google.tokens()
    monkeypatch.setattr(google,'oauth',lambda d:{'access_token':'new','refresh_token':'refresh','scope':'openid email','expires_in':3600})
    with pytest.raises(ValueError):google.exchange('code','verifier')
    assert google.tokens()==old

def test_successful_exchange_verifies_google_account_and_omits_id_token(connected,monkeypatch):
    class Response:
        ok=True
        def json(self):return {'sub':'verified-account','email':'verified@example.test'}
    monkeypatch.setattr(google,'oauth',lambda d:{'access_token':'new','refresh_token':'refresh','scope':google.SCOPE,'expires_in':3600,'id_token':'do-not-store'})
    calls=[];monkeypatch.setattr(google,'network',lambda *a,**kw:calls.append((a,kw)) or Response())
    google.exchange('code','verifier')
    assert google.tokens()['account_id']=='verified-account' and 'id_token' not in google.tokens()
    assert calls[0][0][1]=='https://openidconnect.googleapis.com/v1/userinfo'

def test_api_refreshes_once_after_401(connected,monkeypatch):
    class Response:
        def __init__(self,code):self.status_code=code;self.ok=code==200
        def json(self):return {'items':[]}
    calls=[];monkeypatch.setattr(google,'access_token',lambda force=False:calls.append(force) or 'token')
    replies=iter([Response(401),Response(200)]);monkeypatch.setattr(google,'network',lambda *a,**kw:next(replies))
    assert google.api('GET')=={'items':[]} and calls==[False,True]

def test_broken_optional_client_file_does_not_disable_builtin_booking(item,monkeypatch):
    monkeypatch.setenv('GOOGLE_OAUTH_CLIENT_FILE','missing-file.json')
    assert book(item,slot())['status']=='scheduled'
