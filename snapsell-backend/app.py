"""SnapSell API: refactored from CollinQ/sbhacks2025's Flask application."""
import csv
import io
import json
import math
import os
import secrets
import threading
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
load_dotenv(ROOT.parents[1]/'work'/'amd.env')

from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.exceptions import HTTPException
import store
import pricing
import amd
import commerce
import video
import research
import assessment
import markets
import outcomes
import deals
import google_calendar
import channels
import ebay
from catalog import CATEGORIES

app=Flask(__name__)
store.initialize()
store.purge_samples()
# Repair legacy external records that were saved while their items stayed drafts.
for linked_id in {a.get('item_id') for a in store.all_rows('actions') if a.get('type')=='external_listing'}:
    if linked_id:channels.reconcile_item(linked_id)
for interrupted in store.all_rows('jobs'):
    if interrupted['status'] in ['queued','processing']:
        message='The server restarted during research. Run research again.' if interrupted.get('type')=='market_research' else 'The server restarted during extraction. Your upload is saved; retry extraction.'
        interrupted.update(status='failed',message=message,stage='Interrupted'); store.put('jobs',interrupted)
LOCAL_ACCESS=os.getenv('LOCAL_ACCESS','true').lower()=='true'
# The workspace always starts empty. Sample records are confined to isolated tests.
password=os.getenv('SELLER_PASSWORD') or ('snapsell-local' if LOCAL_ACCESS else '')
if not password: raise RuntimeError('Set SELLER_PASSWORD before starting with LOCAL_ACCESS=false.')
secret_path=store.DATA/'.session-secret'
if not secret_path.exists(): secret_path.write_text(secrets.token_hex(32))
app.secret_key=secret_path.read_text().strip()
app.config.update(MAX_CONTENT_LENGTH=250*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower()=='true',PERMANENT_SESSION_LIFETIME=28800)
_requests=defaultdict(deque)
_request_lock=threading.Lock()
_job_lock=threading.Lock()

class Invalid(ValueError): pass

def number(value,name,low=0,high=100000):
    try: result=float(value)
    except (ValueError,TypeError): raise Invalid(f'{name} must be a number.')
    if not math.isfinite(result) or not low<=result<=high: raise Invalid(f'{name} must be between {low} and {high}.')
    return round(result,2)

def binary(value,name):
    try:result=float(value)
    except (TypeError,ValueError):raise Invalid(name+' must be exactly 0 or 1.')
    if result not in [0,1]:raise Invalid(name+' must be exactly 0 or 1.')
    return int(result)

def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict): raise Invalid('Send a JSON object.')
    return data

def item_or_404(item_id):
    item=store.get('items',item_id)
    if not item: raise Invalid('Item not found.')
    if item.get('created_at'):
        item['age_days']=max(0,(datetime.now().astimezone()-datetime.fromisoformat(item['created_at'])).days)
    return item

@app.before_request
def guard():
    if request.path.startswith('/api/'):
        from time import monotonic
        with _request_lock:
            bucket=(request.remote_addr or 'unknown')+(':login' if request.path=='/api/session' and request.method=='POST' else ':api')
            q=_requests[bucket]; t=monotonic()
            while q and q[0]<t-60: q.popleft()
            limit=15 if request.path=='/api/session' and request.method=='POST' else 240
            if len(q)>=limit: return jsonify(error='Too many requests. Please wait a minute.'),429
            q.append(t)
        if request.method not in ['GET','HEAD','OPTIONS']:
            origin=request.headers.get('Origin')
            allowed={'localhost','127.0.0.1',urlparse(os.getenv('PUBLIC_ORIGIN','')).hostname}
            if origin and urlparse(origin).hostname not in allowed:
                return jsonify(error='Origin is not allowed.'),403
            if origin and urlparse(origin).hostname in allowed and urlparse(origin).scheme not in ['http','https']:
                return jsonify(error='Origin is not allowed.'),403
        public=request.path in ['/api/health','/api/session','/api/store'] or request.path.startswith('/api/buyer/')
        if not public and not session.get('seller'):
            return jsonify(error='Sign in to your seller workspace.'),401

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store' if request.path.startswith('/api/') else 'public, max-age=3600'
    return response

@app.errorhandler(Exception)
def error(exc):
    if isinstance(exc,HTTPException): return jsonify(error=exc.description),exc.code
    if isinstance(exc,(Invalid,ValueError)): return jsonify(error=str(exc)),400
    if isinstance(exc,RuntimeError): return jsonify(error=str(exc)),503
    app.logger.error('Request failed: %s',type(exc).__name__)
    return jsonify(error='The request could not be completed. Your saved data is unchanged.'),500

@app.get('/api/health')
def health():
    return jsonify(status='healthy',amd_configured=amd.configured(),local_login=LOCAL_ACCESS and not os.getenv('SELLER_PASSWORD'),database='SQLite',market='US',currency='USD')

@app.route('/api/session',methods=['GET','POST','DELETE'])
def login():
    if request.method=='POST':
        if not secrets.compare_digest(str(body().get('password','')),password): return jsonify(error='Incorrect seller password.'),401
        session.clear(); session['seller']=True; session.permanent=True
    if request.method=='DELETE': session.clear()
    return jsonify(authenticated=bool(session.get('seller')))

@app.get('/api/workspace')
def workspace():
    items=[item_or_404(i['id']) for i in store.all_rows('items')]
    inference=[a for a in store.all_rows('actions') if a.get('type')=='inference']
    jobs=[{k:v for k,v in j.items() if k!='path'} for j in store.all_rows('jobs')]
    return jsonify(items=items,analytics=commerce.analytics(),actions=commerce.actions(),conversations=store.all_rows('conversations'),orders=store.all_rows('orders'),jobs=jobs,amd=dict(configured=amd.configured(),speech_ready=video.speech.ready(),calls=len(inference),input_tokens=sum(a['input_tokens'] for a in inference),output_tokens=sum(a['output_tokens'] for a in inference),recent=inference[-10:]))

@app.get('/api/google-calendar')
def google_status():return jsonify(google_calendar.status())

@app.post('/api/google-calendar/connect')
def google_connect():
    import time
    config=google_calendar.settings()
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
    url=google_calendar.authorize_url(state,verifier)
    session['google_oauth']={'state':state,'verifier':verifier,'expires_at':time.time()+600,'client_id':config['client_id'],'redirect_uri':config['redirect_uri']}
    return jsonify(url=url)

@app.get('/api/google-calendar/callback')
def google_callback():
    import time
    from flask import redirect
    pending=session.pop('google_oauth',{})
    c=google_calendar.settings()
    if not pending or not secrets.compare_digest(request.args.get('state',''),pending['state']) or time.time()>pending['expires_at'] or pending['client_id']!=c['client_id'] or pending['redirect_uri']!=c['redirect_uri']:
        raise Invalid('Google authorization expired or did not match this session. Connect again.')
    if request.args.get('error') or not request.args.get('code'):raise Invalid('Google authorization was declined. Return to Deals to reconnect.')
    google_calendar.exchange(request.args['code'],pending['verifier'])
    return redirect('/?google=connected')

@app.post('/api/google-calendar/disconnect')
def google_disconnect():
    session.pop('google_oauth',None)
    return jsonify(google_calendar.disconnect())

@app.post('/api/google-calendar/check/<slot_id>')
def google_check(slot_id):
    slot=store.get('availability',slot_id)
    if not slot:raise Invalid('Interval not found.')
    return jsonify(available=not bool(google_calendar.busy(slot['start'],slot['end'])),checked_at=store.now())

@app.post('/api/google-calendar/sync/<appointment_id>')
def google_sync(appointment_id):
    if body().get('confirm') is not True:raise Invalid('Confirm copying meeting details to your Google Calendar.')
    return jsonify(google_calendar.sync(appointment_id,enable=True))

@app.get('/api/deals')
def deal_workspace(): return jsonify(deals.workspace())

@app.post('/api/deals/availability')
def deal_availability(): return jsonify(deals.add_slot(body()))

@app.delete('/api/deals/availability/<slot_id>')
def deal_close_slot(slot_id): return jsonify(deals.close_slot(slot_id))

@app.post('/api/deals/appointments')
def deal_book(): return jsonify(deals.book(body()))

@app.post('/api/deals/appointments/<appointment_id>')
def deal_update(appointment_id): return jsonify(deals.update(appointment_id,body()))

@app.get('/api/deals/appointments/<appointment_id>/calendar')
def deal_calendar(appointment_id):
    from flask import Response
    return Response(deals.calendar(appointment_id),mimetype='text/calendar',headers={'Content-Disposition':'attachment; filename="pickup.ics"'})

@app.get('/api/items/<item_id>/pricing')
def pricing_route(item_id): return jsonify(pricing.evaluate(item_or_404(item_id),request.args.get('market','US'),request.args.get('mode','exact'),request.args.get('basis','item')))

@app.route('/api/items/<item_id>/outcome',methods=['GET','POST'])
@ebay.serialized
def observed_outcome(item_id):
    item=item_or_404(item_id)
    if request.method=='GET':return jsonify(window=outcomes.current(item_id))
    data=body()
    if data.get('action')=='begin':return jsonify(window=outcomes.begin(item))
    if data.get('action')=='confirm_unsold' and data.get('confirm') is True:return jsonify(window=outcomes.confirm_unsold(item))
    raise Invalid('Choose begin, or explicitly confirm that the item was unsold throughout its seven-day window.')

@app.route('/api/items/<item_id>/research',methods=['GET','POST'])
@ebay.serialized
def research_item(item_id):
    item=item_or_404(item_id)
    if request.method=='GET':
        market=request.args.get('market','US');mode=request.args.get('mode','exact');basis=request.args.get('basis','item')
        return jsonify(questions=assessment.questions(item),item=item,job=research.latest(item_id,market,mode),pricing=pricing.evaluate(item,market,mode,basis),schedule=research.schedule(item_id,market,mode),outcome_window=outcomes.current(item_id))
    d=body(); urls=d.get('source_urls',[])
    markets.get(d.get('market','US'))
    if d.get('mode','exact') not in ['exact','similar']:raise Invalid('Choose exact or similar product comparison.')
    if not isinstance(urls,list) or len(urls)>5 or any(not isinstance(u,str) for u in urls): raise Invalid('Provide at most five direct product URLs.')
    for u in urls: research.canonical(u)
    if 'fill_draft_price' in d and not isinstance(d['fill_draft_price'],bool):raise Invalid('Draft price option must be true or false.')
    if 'answers' in d:item=assessment.save_answers(item,d['answers'])
    if 'auto_refresh' in d:research.schedule(item_id,d.get('market','US'),d.get('mode','exact'),d['auto_refresh'],urls)
    return jsonify(job=research.start(item_id,urls,d.get('market','US'),d.get('mode','exact'),fill_draft_price=d.get('fill_draft_price',False))),202

@app.post('/api/items/<item_id>/research/schedule')
def research_schedule(item_id):
    item_or_404(item_id);data=body();urls=data.get('source_urls',[])
    if not isinstance(urls,list) or len(urls)>5 or any(not isinstance(u,str) for u in urls):raise Invalid('Provide at most five direct product URLs.')
    for url in urls:research.canonical(url)
    if not isinstance(data.get('enabled'),bool):raise Invalid('Specify whether daily refresh is enabled using true or false.')
    return jsonify(schedule=research.schedule(item_id,data.get('market','US'),data.get('mode','exact'),data['enabled'],urls))

@app.post('/api/items/<item_id>/identity/confirm')
@ebay.serialized
def confirm_identity(item_id):
    import identity
    item_or_404(item_id);data=body()
    if data.get('confirm_match') is not True:raise Invalid('Confirm that the candidate matches your physical item.')
    return jsonify(identity.confirm(item_id,str(data.get('candidate_id',''))))

@app.post('/api/research')
def research_inventory():
    ids=body().get('item_ids',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=10: raise Invalid('Select between 1 and 10 items.')
    selected=[item_or_404(str(i)) for i in ids]
    return jsonify(jobs=[research.start(i['id']) for i in selected]),202

@app.route('/api/items',methods=['POST'])
def create_item():
    d=body()
    item=dict(id=str(uuid4()),title='New item',brand='Unknown',category='Other',model_key='unknown',condition='Not verified',specs={},subtitle='Seller inventory',description='',image='/assets/product.svg',price=0,cost=0,reserve=0,fee_rate=0,holding_cost=0,status='draft',confirmed=False,source='manual',created_at=store.now(),age_days=0,use_case='Everyday use')
    item.update(validate_item(d))
    if item['category']=='Monitor': item['image']='/assets/monitor.svg'
    elif item['category']=='Laptop':item['image']='/assets/laptop-silver.svg'
    item=store.put('items',item)
    if not research.unknown(item['model_key']): research.start(item['id'])
    return jsonify(item),201

def validate_item(d):
    out={}
    for k in ['title','brand','model_key','subtitle','description','use_case']:
        if k in d:
            if not isinstance(d[k],str): raise Invalid(f'{k} must be text.')
            out[k]=d[k].strip()[:2000 if k=='description' else 180]
    if 'title' in out and not out['title']: raise Invalid('Title is required.')
    if 'model_key' in out: out['model_key']=pricing.key(out['model_key'])
    for k in ['price','cost','reserve','holding_cost','fee_rate']:
        if k in d: out[k]=number(d[k],k,0,.4 if k=='fee_rate' else 100000)
    if 'category' in d:
        if d['category'] not in CATEGORIES: raise Invalid('Choose a supported category, or Other for any additional product type.')
        out['category']=d['category']
    if 'condition' in d:
        if d['condition'] not in pricing.CONDITION: raise Invalid('Unsupported condition.')
        out['condition']=d['condition']
    if 'specs' in d:
        if not isinstance(d['specs'],dict) or len(d['specs'])>20: raise Invalid('Specifications must be an object with at most 20 fields.')
        out['specs']={str(k)[:50]:str(v)[:250] for k,v in d['specs'].items()}
    return out

@app.patch('/api/items/<item_id>')
@ebay.serialized
def update_item(item_id):
    item=item_or_404(item_id)
    if item['status']=='sold': raise Invalid('Completed sales cannot be edited.')
    previous=research.fingerprint(item)
    changes=validate_item(body())
    if any(k in changes and changes[k]!=item.get(k) for k in ['title','brand','category','model_key','condition','specs','description','price']):outcomes.invalidate(item_id)
    if any(k in changes and changes[k]!=item.get(k) for k in ['title','brand','category','model_key','condition','specs','description']):
        item['confirmed']=False
    item.update(changes)
    if item.get('image','').startswith('/assets/'):
        item['image']='/assets/monitor.svg' if item['category']=='Monitor' else '/assets/laptop-silver.svg' if item['category']=='Laptop' else '/assets/product.svg'
    item=store.put('items',item)
    if research.fingerprint(item)!=previous and not research.unknown(item['model_key']) and item['category']!='Phone': research.start(item_id)
    return jsonify(item)

@app.post('/api/items/<item_id>/publish')
@ebay.serialized
def publish(item_id):
    item=item_or_404(item_id); d=body()
    if item['status'] in ['sold','sale_pending']: raise Invalid('Completed or detected sales cannot be relisted.')
    if d.get('confirm_facts') is not True: raise Invalid('Review and confirm the product facts first.')
    floor=max(item['reserve'],item['cost']/(1-item['fee_rate']))
    if item['price']<=0 or item['price']<floor: raise Invalid('Set a positive price covering your cost, fees and minimum price.')
    item.update(status='listed',confirmed=True)
    store.put('items',item); store.event(item_id,'publish')
    return jsonify(item)

@app.get('/api/channels')
def channels_workspace():return jsonify(channels.workspace())

@app.get('/api/ebay')
def ebay_connection():return jsonify(ebay.status())

@app.post('/api/ebay/connect')
def ebay_connect():
    state=secrets.token_urlsafe(32)
    session['ebay_oauth']={'state':state,'expires_at':__import__('time').time()+600,'environment':ebay.settings()['environment']}
    return jsonify(url=ebay.authorize_url(state))

@app.get('/api/ebay/callback')
def ebay_callback():
    pending=session.pop('ebay_oauth',{})
    supplied=request.args.get('state','')
    if not pending or not secrets.compare_digest(supplied,pending['state']) or __import__('time').time()>pending['expires_at'] or pending['environment']!=ebay.settings()['environment']:
        raise Invalid('eBay authorization expired or state did not match. Connect again.')
    if request.args.get('error') or not request.args.get('code'):raise Invalid('eBay authorization was declined. Connect again when ready.')
    ebay.exchange(request.args['code'])
    from flask import redirect
    return redirect('/?ebay=connected')

@app.post('/api/ebay/disconnect')
def ebay_disconnect():
    if ebay.settings()['refresh_token']:raise Invalid('Remove EBAY_REFRESH_TOKEN from .env to disconnect environment-based authorization.')
    with ebay.LOCK:ebay.token_path().unlink(missing_ok=True)
    session.pop('ebay_oauth',None)
    return jsonify(connected=False)

@app.get('/api/ebay/options')
def ebay_options():return jsonify(ebay.options())

@app.get('/api/ebay/categories/<category_id>')
def ebay_category(category_id):return jsonify(ebay.category_metadata(category_id))

@app.post('/api/ebay/settings')
def ebay_save_settings():return jsonify(ebay.save_settings(body()))

@app.post('/api/ebay/sync')
def ebay_sync():return jsonify(results=ebay.sync_all())

@app.post('/api/items/<item_id>/ebay/<operation>')
def ebay_item_action(item_id,operation):
    item_or_404(item_id);data=body()
    if operation=='check':return jsonify(ebay.check(item_id))
    if operation=='attach':
        if data.get('confirm') is not True:raise Invalid('Confirm that this eBay SKU belongs to this physical item.')
        return jsonify(ebay.attach_sku(item_id,data.get('sku','')))
    if operation not in ['publish','update','withdraw']:raise Invalid('Choose publish, update, withdraw or check.')
    if data.get('confirm') is not True:raise Invalid('Confirm the eBay action before continuing.')
    if operation=='publish':return jsonify(ebay.publish(item_id,data.get('settings',{})))
    if operation=='update':return jsonify(ebay.update(item_id,data.get('settings') or None))
    return jsonify(ebay.withdraw(item_id))

@app.get('/api/items/<item_id>/channels/<name>')
def listing_kit(item_id,name):return jsonify(channels.prepare(item_or_404(item_id),name)[0])

@app.get('/api/items/<item_id>/channels/<name>/download')
def download_listing_kit(item_id,name):
    data,kit=channels.bundle(item_or_404(item_id),name)
    return app.response_class(data,mimetype='application/zip',headers={'Content-Disposition':f'attachment; filename=snapsell-{name}-{item_id}.zip'})

@app.post('/api/items/<item_id>/channels/<name>/link')
@ebay.serialized
def save_external_listing(item_id,name):
    d=body()
    if d.get('confirm_posted') is not True:raise Invalid('Confirm that you posted this listing on the external marketplace.')
    return jsonify(channels.record_listing(item_or_404(item_id),name,str(d.get('url','')).strip()))

@app.post('/api/items/<item_id>/channels/sale')
@ebay.serialized
def record_external_sale(item_id):
    d=body();item_or_404(item_id)
    if d.get('confirm_completed') is not True:raise Invalid('Confirm the external transaction is complete.')
    return jsonify(channels.complete_sale(item_id,str(d.get('listing_id','')),number(d.get('amount'),'Sale price',.01),number(d.get('fee'),'Actual fee paid',0),number(d.get('cost'),'Acquisition cost',0)))

@app.post('/api/channels/listings/<listing_id>/removed')
def confirm_external_removal(listing_id):
    d=body();listing=store.get('actions',listing_id)
    if not listing or listing.get('type')!='external_listing' or listing.get('status') not in ['posted','needs_removal']:raise Invalid('Choose an active external listing.')
    if d.get('confirm_removed') is not True:raise Invalid('Confirm that you removed the listing on the marketplace.')
    if listing.get('source')=='ebay_api':raise Invalid('Use Withdraw on eBay to end an API-connected listing.')
    outcomes.invalidate(listing['item_id'],'The listing was removed during the observation window.')
    listing.update(status='removed',removed_at=store.now(),source='seller_reported');store.put('actions',listing)
    channels.reconcile_item(listing['item_id'])
    return jsonify(listing)

@app.post('/api/items/<item_id>/channels/<name>/reply')
def marketplace_reply(item_id,name):
    d=body();message=str(d.get('message','')).strip()
    if not 1<=len(message)<=2000:raise Invalid('Paste a buyer message up to 2,000 characters.')
    return jsonify(channels.draft_reply(item_or_404(item_id),amd.redact(message),name))

@app.post('/api/items/<item_id>/review')
@ebay.serialized
def confirm_listing_facts(item_id):
    item=item_or_404(item_id)
    if body().get('confirm_facts') is not True:raise Invalid('Confirm that you reviewed the product facts.')
    item.update(confirmed=True);return jsonify(store.put('items',item))

@app.post('/api/items/<item_id>/strategy')
@ebay.serialized
def strategy(item_id):
    item=item_or_404(item_id)
    if item['status']=='sold': raise Invalid('This item has already sold.')
    selected=next((s for s in pricing.evaluate(item)['strategies'] if s['id']==body().get('strategy')),None)
    if not selected: raise Invalid('No supported recommendation. Import exact-model comparables first.')
    before=item['price']; item.update(price=selected['price'],strategy=selected['id'])
    if before!=item['price']:outcomes.invalidate(item_id)
    model=pricing.fit_model()
    store.put('items',item); store.event(item_id,'price_change',before=before,after=item['price'],model_source=model[2]['source'] if model else 'observed_asking_prices')
    return jsonify(item)

@app.post('/api/actions/<action_id>/apply')
@ebay.serialized
def apply_action(action_id):
    action=next((a for a in commerce.actions() if a['id']==action_id),None)
    if not action: raise Invalid('This action is no longer available.')
    item=item_or_404(action['item_id'])
    before=item['description'] if action['kind']=='description' else item['price']
    if action['kind']=='description': item['description']+=' Includes: '+item['specs']['included']+'.'
    else: item['price']=action['price']
    if action['kind']=='description':item['confirmed']=False
    outcomes.invalidate(item['id'])
    store.put('items',item); store.put('actions',dict(id=action_id,type='applied',at=store.now(),item_id=item['id'],before=before,action=action))
    store.event(item['id'],'action',kind_applied=action['kind'],evidence_source=action['evidence_source'])
    return jsonify(item)

@app.post('/api/process_video')
def process_video():
    f=request.files.get('video')
    if not f or not f.filename: raise Invalid('Choose a video file.')
    ext=Path(f.filename).suffix.lower()
    if ext not in ['.mp4','.mov','.webm','.m4v']: raise Invalid('Supported formats: MP4, MOV, WebM, M4V.')
    job_id=str(uuid4()); directory=store.DATA/'uploads'; directory.mkdir(exist_ok=True)
    path=directory/(job_id+ext); f.save(path)
    # Decode validation applies even before a key is configured.
    try: video.frames(path,job_id)
    except Exception:
        path.unlink(missing_ok=True); raise
    job=store.put('jobs',dict(id=job_id,filename=Path(f.filename).name[:180],path=str(path),notes=request.form.get('notes','')[:4000],status='queued',stage='Queued',message='Video saved',created_at=store.now()))
    video.executor.submit(video.run,job_id)
    return jsonify({k:v for k,v in job.items() if k!='path'}),202

@app.get('/api/jobs/<job_id>')
def get_job(job_id):
    job=store.get('jobs',job_id)
    if not job: raise Invalid('Upload not found.')
    return jsonify({k:v for k,v in job.items() if k!='path'})

@app.post('/api/jobs/<job_id>/retry')
def retry(job_id):
    with _job_lock:
        job=store.get('jobs',job_id)
        if not job: raise Invalid('Upload not found.')
        if job['status'] not in ['failed','awaiting_key']: raise Invalid('Only failed or pending-key uploads can be retried.')
        if not amd.configured(): raise Invalid('Add your AMD key before retrying.')
        job.update(status='queued',message='Queued for another extraction'); store.put('jobs',job)
        video.executor.submit(video.run,job_id)
    return jsonify(status='queued')

@app.get('/api/store')
def storefront(): return jsonify(items=[commerce.public_item(i) for i in store.all_rows('items') if i['status']=='listed'],store_name='Second Life Supply',currency='USD')

@app.post('/api/buyer/items/<item_id>/view')
def view(item_id):
    item=item_or_404(item_id)
    if item['status']!='listed': raise Invalid('Item is not available.')
    session.setdefault('buyer_id',str(uuid4()))
    with store.connection() as db:
        prior=db.execute('SELECT body FROM events WHERE item_id=? AND kind=? AND source=?',(item_id,'view','live')).fetchall()
    if not any(json.loads(r['body']).get('visitor')==session['buyer_id'] for r in prior): store.event(item_id,'view',visitor=session['buyer_id'])
    return jsonify(ok=True)

@app.post('/api/buyer/items/<item_id>/chat')
def chat(item_id):
    item=item_or_404(item_id); d=body(); message=str(d.get('message','')).strip()
    if not 1<=len(message)<=1200: raise Invalid('Message must contain 1–1,200 characters.')
    session.setdefault('buyer_id',str(uuid4()))
    cid=f'{session["buyer_id"]}:{item_id}'
    convo=store.get('conversations',cid) or dict(id=cid,item_id=item_id,buyer='Store visitor',source='live',messages=[])
    answer=commerce.reply(item,message)
    safe=amd.redact(message)
    convo['messages'] += [dict(role='user',content=safe,at=store.now()),dict(role='assistant',content=answer['answer'],at=store.now(),provider=answer['provider'])]
    convo['messages']=convo['messages'][-60:]; store.put('conversations',convo)
    store.event(item_id,'inquiry',question=safe,intents=answer['intents'])
    return jsonify(**answer,conversation_id=cid)

@app.get('/api/buyer/items/<item_id>/recommendations')
def recommendations(item_id): return jsonify(items=commerce.recommend(item_or_404(item_id)))

@app.post('/api/buyer/items/<item_id>/offer')
def offer(item_id):
    item=item_or_404(item_id); d=body()
    if item['status']!='listed': raise Invalid('Item is no longer available.')
    amount=number(d.get('amount'),'Offer',1,100000)
    session.setdefault('buyer_id',str(uuid4()))
    order=store.put('orders',dict(id=str(uuid4()),item_id=item_id,amount=amount,status='pending',buyer_id=session['buyer_id'],buyer='Store visitor',note=amd.redact(str(d.get('note',''))[:500]),created_at=store.now()))
    store.event(item_id,'offer',amount=amount)
    return jsonify(id=order['id'],status='pending',message='Offer sent. The seller must approve the price and pickup details.'),201

@app.post('/api/orders/<order_id>/decide')
@ebay.serialized
def decide(order_id):
    order=store.get('orders',order_id); d=body()
    if not order or order['status']!='pending': raise Invalid('Offer is no longer pending.')
    if d.get('decision')=='decline': order['status']='declined'; return jsonify(store.put('orders',order))
    if d.get('decision')!='complete': raise Invalid('Decision must be decline or complete.')
    if d.get('confirm') is not True: raise Invalid('Confirm that the deal was completed with the buyer.')
    item=item_or_404(order['item_id'])
    if order['amount']<max(item['reserve'],item['cost']/(1-item['fee_rate'])): raise Invalid('Offer is below your minimum price or would lose money after fees. Edit your economics explicitly before accepting.')
    return jsonify(store.complete_order(item['id'],order_id,order['amount']))

@app.get('/api/model')
def model_report():
    model=pricing.fit_model()
    rows=[r for r in store.all_rows('history') if r.get('source')!='synthetic' and r.get('market','US')=='US' and r.get('currency','USD')=='USD']
    return jsonify(report=model[2] if model else None,observations=len(rows),requirements='At least 120 US/USD outcomes, both classes in chronological training/calibration/test splits, and held-out Brier score better than the constant baseline. Seller-reported and imported labels are not independently audited.')

@app.route('/api/amd',methods=['GET','POST'])
def amd_status():
    if not amd.configured(): return jsonify(configured=False,models=[],message='Add AMD_API_KEY to enable live inference.')
    if request.method=='GET': return jsonify(configured=True,models=amd.catalog().get('data',[]))
    data,model=amd.json_response('chat','Return JSON {"status":"connected"}.','Connectivity check.',100)
    return jsonify(configured=True,model=model,result=data,usage=amd.request('GET','/usage?include_recent=true'))

@app.post('/api/data/import')
def import_data():
    file=request.files.get('file'); kind=request.form.get('kind')
    if not file or kind not in ['comparables','history']: raise Invalid('Choose a CSV and data type.')
    if file.content_length and file.content_length>5*1024*1024: raise Invalid('CSV limit is 5MB.')
    raw=file.stream.read(5*1024*1024+1)
    if len(raw)>5*1024*1024: raise Invalid('CSV limit is 5MB.')
    try: rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    except (UnicodeError,csv.Error): raise Invalid('Use a UTF-8 CSV file.')
    if not 1<=len(rows)<=10000: raise Invalid('Import between 1 and 10,000 rows.')
    prepared=[]
    for idx,row in enumerate(rows):
        try:
            if kind=='comparables':
                if not row.get('model_key') or row.get('kind') not in ['sold','asking'] or row.get('condition') not in pricing.CONDITION: raise Invalid('Required: model_key, price, condition, kind (sold/asking).')
                market=markets.get(row.get('market') or 'US')
                if (row.get('currency') or market['currency'])!=market['currency']:raise Invalid('Imported currency must match its research country.')
                if research.unknown(row['model_key']):raise Invalid('Imported exact-model comparables need a known model key.')
                prepared.append(dict(id=str(uuid4()),model_key=pricing.key(row['model_key']),title=row.get('title',row['model_key'])[:180],price=number(row['price'],'price',.01,1_000_000_000),currency=market['currency'],market=market['code'],condition=row['condition'],kind=row['kind'],age_days=number(row.get('age_days',0),'age_days',0,365),source='imported',source_name=row.get('source_name','Seller import')[:100],url=row.get('url','')[:500],observed_at=store.now()))
            else:
                if (row.get('market') or 'US')!='US' or (row.get('currency') or 'USD')!='USD':raise Invalid('Outcome history currently supports US/USD only.')
                ts=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
                if ts.tzinfo is None or ts>datetime.now().astimezone():raise Invalid('History needs a past timestamp with timezone.')
                prepared.append(dict(id=str(uuid4()),price_ratio=number(row['price_ratio'],'price_ratio',.65,1.4),age_days=number(row['age_days'],'age_days',0,60),excellent=binary(row['excellent'],'excellent'),monitor=binary(row['monitor'],'monitor'),completeness=number(row['completeness'],'completeness',.4,1),sold_within_7_days=binary(row['sold_within_7_days'],'sold_within_7_days'),observed_at=ts.isoformat(),source='imported'))
        except (Invalid,KeyError,ValueError): raise Invalid(f'Invalid CSV row {idx+2}. Check the documented columns and value ranges.')
    # All-or-nothing import; schema validated before the transaction.
    if kind=='history':
        import hashlib
        for row in prepared:row['id']='csv-history:'+hashlib.sha256(json.dumps({k:v for k,v in row.items() if k!='id'},sort_keys=True).encode()).hexdigest()
    with store.connection() as db:
        before=db.total_changes
        db.executemany(f'INSERT INTO {kind}(id,body) VALUES(?,?) ON CONFLICT(id) DO NOTHING',[(r['id'],json.dumps(r)) for r in prepared])
        imported=db.total_changes-before
    return jsonify(imported=imported,skipped_duplicates=len(prepared)-imported,kind=kind)

@app.get('/api/export')
def export():
    buf=io.StringIO(); fields=['id','title','category','condition','price','status','model_key','description','source']; writer=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
    for item in store.all_rows('items'):
        row={k:('\''+str(v) if isinstance(v,str) and v[:1] in ['=','+','-','@'] else v) for k,v in item.items()}; writer.writerow(row)
    return app.response_class(buf.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=snapsell-listings.csv'})

@app.get('/media/<path:filename>')
def media(filename):
    published=any(i.get('image')=='/media/'+filename and i['status'] in ['listed','sold'] for i in store.all_rows('items'))
    if not published and not session.get('seller'): return jsonify(error='Sign in to view unreviewed capture frames.'),401
    return send_from_directory(store.DATA/'media',filename)

if __name__=='__main__':
    from waitress import serve
    ebay.start_worker()
    research.start_worker()
    google_calendar.start_worker()
    serve(app,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','5000')),threads=6)
