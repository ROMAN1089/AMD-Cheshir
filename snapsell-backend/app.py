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
import channels
from catalog import CATEGORIES

app=Flask(__name__)
store.initialize()
store.purge_samples()
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

@app.get('/api/items/<item_id>/pricing')
def pricing_route(item_id): return jsonify(pricing.evaluate(item_or_404(item_id)))

@app.route('/api/items/<item_id>/research',methods=['GET','POST'])
def research_item(item_id):
    item=item_or_404(item_id)
    if request.method=='GET': return jsonify(item=item,job=research.latest(item_id),pricing=pricing.evaluate(item))
    d=body(); urls=d.get('source_urls',[])
    if not isinstance(urls,list) or len(urls)>5 or any(not isinstance(u,str) for u in urls): raise Invalid('Provide at most five direct product URLs.')
    for u in urls: research.canonical(u)
    return jsonify(job=research.start(item_id,urls)),202

@app.post('/api/items/<item_id>/identity/confirm')
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
    item=dict(id=str(uuid4()),title='New item',brand='Unknown',category='Other',model_key='unknown',condition='Good',specs={},subtitle='Seller inventory',description='',image='/assets/product.svg',price=0,cost=0,reserve=0,fee_rate=0,holding_cost=0,status='draft',confirmed=False,source='manual',created_at=store.now(),age_days=0,use_case='Everyday use')
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
def update_item(item_id):
    item=item_or_404(item_id)
    if item['status']=='sold': raise Invalid('Completed sales cannot be edited.')
    previous=research.fingerprint(item)
    item.update(validate_item(body()))
    if item.get('image','').startswith('/assets/'):
        item['image']='/assets/monitor.svg' if item['category']=='Monitor' else '/assets/laptop-silver.svg' if item['category']=='Laptop' else '/assets/product.svg'
    item=store.put('items',item)
    if research.fingerprint(item)!=previous and not research.unknown(item['model_key']): research.start(item_id)
    return jsonify(item)

@app.post('/api/items/<item_id>/publish')
def publish(item_id):
    item=item_or_404(item_id); d=body()
    if item['status']=='sold': raise Invalid('Completed sales cannot be relisted.')
    if d.get('confirm_facts') is not True: raise Invalid('Review and confirm the product facts first.')
    floor=max(item['reserve'],item['cost']/(1-item['fee_rate']))
    if item['price']<=0 or item['price']<floor: raise Invalid('Set a positive price covering your cost, fees and minimum price.')
    item.update(status='listed',confirmed=True)
    store.put('items',item); store.event(item_id,'publish')
    return jsonify(item)

@app.get('/api/channels')
def channels_workspace():return jsonify(channels.workspace())

@app.get('/api/items/<item_id>/channels/<name>')
def listing_kit(item_id,name):return jsonify(channels.prepare(item_or_404(item_id),name)[0])

@app.get('/api/items/<item_id>/channels/<name>/download')
def download_listing_kit(item_id,name):
    data,kit=channels.bundle(item_or_404(item_id),name)
    return app.response_class(data,mimetype='application/zip',headers={'Content-Disposition':f'attachment; filename=snapsell-{name}-{item_id}.zip'})

@app.post('/api/items/<item_id>/channels/<name>/link')
def save_external_listing(item_id,name):
    d=body()
    if d.get('confirm_posted') is not True:raise Invalid('Confirm that you posted this listing on the external marketplace.')
    return jsonify(channels.record_listing(item_or_404(item_id),name,str(d.get('url','')).strip()))

@app.post('/api/items/<item_id>/channels/sale')
def record_external_sale(item_id):
    d=body();item_or_404(item_id)
    if d.get('confirm_completed') is not True:raise Invalid('Confirm the external transaction is complete.')
    return jsonify(channels.complete_sale(item_id,str(d.get('listing_id','')),number(d.get('amount'),'Sale price',.01),number(d.get('fee'),'Actual fee paid',0),number(d.get('cost'),'Acquisition cost',0)))

@app.post('/api/channels/listings/<listing_id>/removed')
def confirm_external_removal(listing_id):
    d=body();listing=store.get('actions',listing_id)
    if not listing or listing.get('type')!='external_listing' or listing.get('status') not in ['posted','needs_removal']:raise Invalid('Choose an active external listing.')
    if d.get('confirm_removed') is not True:raise Invalid('Confirm that you removed the listing on the marketplace.')
    listing.update(status='removed',removed_at=store.now(),source='seller_reported');return jsonify(store.put('actions',listing))

@app.post('/api/items/<item_id>/channels/<name>/reply')
def marketplace_reply(item_id,name):
    d=body();message=str(d.get('message','')).strip()
    if not 1<=len(message)<=2000:raise Invalid('Paste a buyer message up to 2,000 characters.')
    return jsonify(channels.draft_reply(item_or_404(item_id),amd.redact(message),name))

@app.post('/api/items/<item_id>/review')
def confirm_listing_facts(item_id):
    item=item_or_404(item_id)
    if body().get('confirm_facts') is not True:raise Invalid('Confirm that you reviewed the product facts.')
    item.update(confirmed=True);return jsonify(store.put('items',item))

@app.post('/api/items/<item_id>/strategy')
def strategy(item_id):
    item=item_or_404(item_id)
    if item['status']=='sold': raise Invalid('This item has already sold.')
    selected=next((s for s in pricing.evaluate(item)['strategies'] if s['id']==body().get('strategy')),None)
    if not selected: raise Invalid('No supported recommendation. Import exact-model comparables first.')
    before=item['price']; item.update(price=selected['price'],strategy=selected['id'])
    model=pricing.fit_model()
    store.put('items',item); store.event(item_id,'price_change',before=before,after=item['price'],model_source=model[2]['source'] if model else 'observed_asking_prices')
    return jsonify(item)

@app.post('/api/actions/<action_id>/apply')
def apply_action(action_id):
    action=next((a for a in commerce.actions() if a['id']==action_id),None)
    if not action: raise Invalid('This action is no longer available.')
    item=item_or_404(action['item_id'])
    before=item['description'] if action['kind']=='description' else item['price']
    if action['kind']=='description': item['description']+=' Includes: '+item['specs']['included']+'.'
    else: item['price']=action['price']
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
    return jsonify(report=model[2] if model else None)

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
                prepared.append(dict(id=str(uuid4()),model_key=pricing.key(row['model_key']),title=row.get('title',row['model_key'])[:180],price=number(row['price'],'price',1),condition=row['condition'],kind=row['kind'],age_days=number(row.get('age_days',0),'age_days',0,365),source='imported',source_name=row.get('source_name','Seller import')[:100],url=row.get('url','')[:500],observed_at=store.now()))
            else:
                ts=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
                prepared.append(dict(id=str(uuid4()),price_ratio=number(row['price_ratio'],'price_ratio',.65,1.4),age_days=number(row['age_days'],'age_days',0,60),excellent=int(number(row['excellent'],'excellent',0,1)),monitor=int(number(row['monitor'],'monitor',0,1)),completeness=number(row['completeness'],'completeness',.4,1),sold_within_7_days=int(number(row['sold_within_7_days'],'sold_within_7_days',0,1)),observed_at=ts.isoformat(),source='imported'))
        except (Invalid,KeyError,ValueError): raise Invalid(f'Invalid CSV row {idx+2}. Check the documented columns and value ranges.')
    # All-or-nothing import; schema validated before the transaction.
    with store.connection() as db:
        db.executemany(f'INSERT INTO {kind}(id,body) VALUES(?,?)',[(r['id'],json.dumps(r)) for r in prepared])
    return jsonify(imported=len(prepared),kind=kind)

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
    serve(app,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','5000')),threads=6)
