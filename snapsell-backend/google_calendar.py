"""Primary-calendar connector, with durable retries and no buyer invitations."""
import base64
import hashlib
import html
import json
import os
import threading
import time
from functools import wraps
from urllib.parse import urlencode, urlsplit
import requests
from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values
import store

SCOPE='openid email https://www.googleapis.com/auth/calendar.events.owned'
LOCK=threading.RLock()
BASE='https://www.googleapis.com/calendar/v3/calendars/primary/events'

def serialized(fn):
    @wraps(fn)
    def run(*args,**kwargs):
        with LOCK:return fn(*args,**kwargs)
    return run

def settings():
    values=dict(os.environ)
    values.update({k:v for k,v in dotenv_values(store.ROOT/'.env').items() if k.startswith('GOOGLE_') and v is not None})
    filename=values.get('GOOGLE_OAUTH_CLIENT_FILE','').strip()
    client={}
    if filename:
        try:client=json.loads(__import__('pathlib').Path(filename).read_text())['web']
        except (OSError,ValueError,KeyError):raise ValueError('Google client file must be a downloaded Web application OAuth JSON.') from None
    return {'client_id':values.get('GOOGLE_CLIENT_ID') or client.get('client_id',''), 'client_secret':values.get('GOOGLE_CLIENT_SECRET') or client.get('client_secret',''), 'redirect_uri':values.get('GOOGLE_REDIRECT_URI') or 'http://127.0.0.1:3000/api/google-calendar/callback'}

def cipher():return Fernet(base64.urlsafe_b64encode(hashlib.sha256((store.DATA/'.session-secret').read_bytes()).digest()))
def token_path():return store.DATA/'.google-calendar.token'
def tokens():
    if not token_path().exists():return {}
    try:return json.loads(cipher().decrypt(token_path().read_bytes()))
    except (InvalidToken,ValueError):raise RuntimeError('Saved Google authorization is unreadable. Reconnect Google Calendar.') from None

def save_tokens(value):
    temp=token_path().with_suffix('.tmp');temp.write_bytes(cipher().encrypt(json.dumps(value).encode()));temp.replace(token_path())

def connected():
    return token_path().exists() and status()['connected']

def status():
    c=settings();t=tokens();missing=[k for k in ['client_id','client_secret'] if not c[k]]
    return dict(configured=not missing,connected=bool(not missing and t.get('refresh_token') and t.get('client_id')==c['client_id']),email=t.get('email','') if t.get('client_id')==c['client_id'] else '',missing=missing,redirect_uri=c['redirect_uri'],calendar='primary')

def network(method,url,**kwargs):
    try:return requests.request(method,url,timeout=(5,15),allow_redirects=False,**kwargs)
    except requests.RequestException:raise RuntimeError('Google Calendar is unavailable. Try again later.') from None

def oauth(payload):
    c=settings();r=network('POST','https://oauth2.googleapis.com/token',data={**payload,'client_id':c['client_id'],'client_secret':c['client_secret']})
    if not r.ok:raise RuntimeError('Google authorization failed. Check the client settings or reconnect your account.')
    try:return r.json()
    except ValueError:raise RuntimeError('Google authorization returned an invalid response.') from None

def authorize_url(state,verifier):
    c=settings();uri=urlsplit(c['redirect_uri'])
    if not status()['configured']:raise ValueError('Configure a Google Web OAuth client before connecting.')
    if uri.path!='/api/google-calendar/callback' or (uri.scheme!='https' and not(uri.scheme=='http' and uri.hostname in {'localhost','127.0.0.1'})):
        raise ValueError('Use HTTPS or localhost for the Google callback ending /api/google-calendar/callback.')
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(dict(client_id=c['client_id'],redirect_uri=c['redirect_uri'],response_type='code',scope=SCOPE,state=state,access_type='offline',prompt='consent select_account',code_challenge=challenge,code_challenge_method='S256'))

@serialized
def exchange(code,verifier):
    c=settings();t=oauth({'grant_type':'authorization_code','code':code,'code_verifier':verifier,'redirect_uri':c['redirect_uri']})
    if not t.get('access_token') or not t.get('refresh_token') or 'https://www.googleapis.com/auth/calendar.events.owned' not in t.get('scope','').split():
        raise ValueError('Google Calendar permission or offline access was not granted. Connect again and grant Calendar access.')
    r=network('GET','https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+t['access_token']})
    if not r.ok:raise RuntimeError('Could not verify the connected Google account.')
    identity=r.json()
    if not identity.get('sub'):raise RuntimeError('Google account identity is missing.')
    save_tokens(dict(access_token=t['access_token'],refresh_token=t['refresh_token'],expires_at=time.time()+int(t.get('expires_in',0))-60,client_id=c['client_id'],account_id=identity['sub'],email=identity.get('email','')))

@serialized
def access_token(force=False):
    if not status()['connected']:raise ValueError('Connect Google Calendar first.')
    t=tokens()
    if force or t.get('expires_at',0)<=time.time():
        updated=oauth({'grant_type':'refresh_token','refresh_token':t['refresh_token']})
        if not updated.get('access_token'):raise RuntimeError('Google access expired. Reconnect Google Calendar.')
        t.update(access_token=updated['access_token'],refresh_token=updated.get('refresh_token',t['refresh_token']),expires_at=time.time()+int(updated.get('expires_in',0))-60);save_tokens(t)
    return t['access_token']

class APIError(RuntimeError):
    def __init__(self,code):super().__init__(f'Google Calendar request failed ({code}). Reconnect for 401/403, or retry later.');self.code=code

def api(method,path='',payload=None,params=None,etag=None):
    for attempt in range(2):
        headers={'Authorization':'Bearer '+access_token(force=attempt==1)}
        if etag:headers['If-Match']=etag
        r=network(method,BASE+path,headers=headers,json=payload,params=params)
        if r.status_code==401 and not attempt:continue
        if not r.ok:raise APIError(r.status_code)
        if r.status_code==204:return {}
        try:return r.json()
        except ValueError:raise RuntimeError('Google Calendar returned an invalid response.') from None

def busy(start,end,exclude=None):
    """Read primary-calendar instances; return only opaque intervals, never titles."""
    import deals
    result=[];page=None
    for _ in range(10):
        d=api('GET',params=dict(timeMin=start,timeMax=end,singleEvents='true',showDeleted='false',timeZone='UTC',maxResults=250,**({'pageToken':page} if page else {})))
        if not isinstance(d.get('items'),list):raise RuntimeError('Google availability could not be checked.')
        for e in d['items']:
            if e.get('id')==exclude or e.get('status')=='cancelled' or e.get('transparency')=='transparent':continue
            me=next((x for x in e.get('attendees',[]) if x.get('self')),None)
            if me and me.get('responseStatus')=='declined':continue
            s=e.get('start',{});t=e.get('end',{})
            # Requesting UTC makes dated all-day entries unambiguous: conservatively
            # occupy the entire queried interval instead of guessing calendar timezone.
            if s.get('date') or t.get('date'):result.append({'start':start,'end':end});continue
            if not s.get('dateTime') or not t.get('dateTime'):raise RuntimeError('Google event time could not be checked.')
            if deals.instant(s['dateTime'])<deals.instant(end) and deals.instant(t['dateTime'])>deals.instant(start):result.append({'start':s['dateTime'],'end':t['dateTime']})
        page=d.get('nextPageToken')
        if not page:return result
    raise RuntimeError('Too many Google events in this interval. Availability remains unverified.')

def ensure_free(slot,appointment=None):
    if not connected():return
    g=(appointment or {}).get('google',{})
    exclude=g.get('event_id') if g.get('account_id')==tokens().get('account_id') else None
    if busy(slot['start'],slot['end'],exclude):raise ValueError('This interval is occupied in your primary Google Calendar. Choose another interval.')

def association(a):
    t=tokens();installation=hashlib.sha256((store.DATA/'.session-secret').read_bytes()).hexdigest()[:16]
    key=hashlib.sha256((installation+a['id']+t['account_id']).encode()).hexdigest()
    return dict(enabled=True,account_id=t['account_id'],event_id=key,status='pending',synced_revision=0,attempts=0,next_retry_at=0)

def owned(event,a):
    tag=event.get('extendedProperties',{}).get('private',{})
    if tag.get('snapsellAppointment')!=a['id'] or tag.get('snapsellInstance')!=hashlib.sha256((store.DATA/'.session-secret').read_bytes()).hexdigest()[:16]:
        raise ValueError('Google event ownership could not be verified. No external event was changed.')
    if event.get('attendees'):raise ValueError('This Google event has guests. Remove them in Google Calendar before synchronizing it.')

def event_body(a):
    return dict(summary=('Picked up: ' if a['status']=='picked_up' else 'Pickup: ')+a['title'],description=html.escape('Buyer alias: '+a['buyer']+'\n'+a['note']+'\nSnapSell status: '+a['status']),location=a['location'],start={'dateTime':a['start']},end={'dateTime':a['end']},status='confirmed' if a['status'] in {'confirmed','picked_up'} else 'tentative',visibility='private',transparency='opaque',reminders={'useDefault':False,'overrides':[{'method':'popup','minutes':1440},{'method':'popup','minutes':60}]},extendedProperties={'private':{'snapsellAppointment':a['id'],'snapsellInstance':hashlib.sha256((store.DATA/'.session-secret').read_bytes()).hexdigest()[:16]}})

@serialized
def sync(key,enable=False):
    a=store.get('appointments',key)
    if not a:raise ValueError('Meeting not found.')
    if not status()['connected']:raise ValueError('Connect Google Calendar first.')
    g=a.get('google',{})
    if not g.get('enabled'):
        if not enable:return a
        if a['status'] in {'cancelled','no_show'}:raise ValueError('This meeting is cancelled.')
        a['google']=g=association(a);store.put('appointments',a)
    if g['account_id']!=tokens()['account_id']:raise ValueError('Reconnect the Google account originally linked to this meeting.')
    try:
        try:remote=api('GET','/'+g['event_id'])
        except APIError as e:
            if e.code!=404:raise
            remote=None
        cancel=a['status'] in {'cancelled','no_show'}
        if remote:
            if remote.get('status')=='cancelled':
                if not cancel:raise ValueError('The Google event was removed. It will not be recreated automatically.')
            else:
                owned(remote,a)
                if not remote.get('etag'):raise ValueError('Google event version is missing. Retry before updating it.')
                if not cancel and a['status'] in {'scheduled','confirmed'}:ensure_free(a,a)
                api('PATCH','/'+g['event_id'],{'status':'cancelled'} if cancel else event_body(a),params={'sendUpdates':'none'},etag=remote.get('etag'))
        elif not cancel:
            if g.get('synced_revision'):raise ValueError('The Google event is missing. Automatic recreation is disabled.')
            if a['status'] in {'scheduled','confirmed'}:ensure_free(a,a)
            try:api('POST',payload={'id':g['event_id'],**event_body(a)},params={'sendUpdates':'none'})
            except APIError as e:
                if e.code!=409:raise
                # Insert could have succeeded before a timeout. Verify before updating.
                existing=api('GET','/'+g['event_id']);owned(existing,a)
                if existing.get('status')=='cancelled' or not existing.get('etag'):raise ValueError('Google event was removed or its version is missing.')
                api('PATCH','/'+g['event_id'],event_body(a),params={'sendUpdates':'none'},etag=existing.get('etag'))
        g.update(status='synced',synced_revision=a['revision'],synced_at=store.now(),error='',attempts=0,next_retry_at=0)
    except (ValueError,RuntimeError) as e:
        attempts=g.get('attempts',0)+1
        g.update(status='error',error=str(e),attempts=attempts,next_retry_at=time.time()+min(3600,60*2**min(attempts-1,6)))
    a['google']=g;return store.put('appointments',a)

def after_save(a):
    if not a.get('google',{}).get('enabled'):return a
    try:
        if connected():return sync(a['id'])
    except (ValueError,RuntimeError) as e:
        a['google'].update(status='error',error=str(e))
        store.put('appointments',a)
    return a

@serialized
def disconnect():
    # Keep remote events and local bindings so reconnecting the same account can
    # reconcile outstanding changes without creating duplicate events.
    token_path().unlink(missing_ok=True)
    return dict(connected=False)

@serialized
def retry_pending():
    if not connected():return
    for a in store.all_rows('appointments'):
        g=a.get('google',{})
        if g.get('enabled') and g.get('account_id')==tokens().get('account_id') and (g.get('synced_revision')!=a['revision'] or g.get('status')=='error') and time.time()>=g.get('next_retry_at',0):sync(a['id'])

def start_worker():
    def run():
        while True:
            time.sleep(60)
            try:retry_pending()
            except Exception:pass # Persisted per-meeting errors are shown in Deals.
    threading.Thread(target=run,daemon=True,name='google-calendar-sync').start()
