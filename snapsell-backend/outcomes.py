"""Explicit seven-day seller-observed outcomes. Never infers an unsold label from silence."""
import hashlib,json
from datetime import datetime,timedelta,timezone
import pricing,store,research

def signature(item):
    return hashlib.sha256(json.dumps({'identity':research.fingerprint(item),'price':item['price'],'currency':item.get('currency','USD')},sort_keys=True).encode()).hexdigest()

def current(item_id):return store.get('actions','outcome-window:'+item_id)

def invalidate(item_id,reason='Price, facts or listing availability changed during the observation window.'):
    window=current(item_id)
    if window and window['status']=='observing':
        window.update(status='invalidated',reason=reason);store.put('actions',window)

def begin(item):
    if item['category'] not in ['Laptop','Monitor'] or item.get('currency','USD')!='USD':raise ValueError('Outcome forecasting currently supports US/USD laptops and monitors.')
    if not item.get('confirmed') or item['status']!='listed' or item['price']<=0:raise ValueError('Use a reviewed, active item with a positive asking price.')
    if current(item['id']):raise ValueError('An observation window is already recorded for this item.')
    listings=[a for a in store.all_rows('actions') if a.get('type')=='external_listing' and a.get('item_id')==item['id'] and a.get('status')=='posted']
    if listings and all(a.get('environment')=='sandbox' for a in listings):raise ValueError('Sandbox listings cannot supply real sales outcome history.')
    comp=pricing.comparables(item)
    if not comp['available']:raise ValueError('A current exact-model market estimate is needed for the observation baseline.')
    ratio=item['price']/comp['median']
    if not .65<=ratio<=1.4 or item.get('age_days',0)>60:raise ValueError('This observation is outside the forecast model support.')
    stamp=datetime.now(timezone.utc)
    row={'id':'outcome-window:'+item['id'],'type':'outcome_window','item_id':item['id'],'status':'observing','opened_at':stamp.isoformat(),'closes_at':(stamp+timedelta(days=7)).isoformat(),'signature':signature(item),'source':'seller_reported','market':'US','currency':'USD',
         'features':{'price_ratio':ratio,'age_days':item.get('age_days',0),'excellent':int(item['condition'] in ['Excellent','Like new']),'monitor':int(item['category']=='Monitor'),'completeness':pricing.completeness(item)},'baseline_sources':[r['url'] for r in comp['rows'] if r['included'] and r.get('url')]}
    return store.put('actions',row)

def finalize(db,window,sold,observed_at):
    row={**window['features'],'id':'observed:'+window['item_id'],'source':'seller_reported_observed','market':'US','currency':'USD','item_id':window['item_id'],'observed_at':observed_at,'sold_within_7_days':sold,'window_opened_at':window['opened_at'],'window_closed_at':window['closes_at'],'outcome_provenance':'Seller confirmation in SnapSell; not independently audited marketplace transaction data.'}
    db.execute('INSERT INTO history(id,body) VALUES(?,?) ON CONFLICT(id) DO NOTHING',(row['id'],json.dumps(row)))
    window.update(status='completed',sold_within_7_days=sold,observed_at=observed_at)
    db.execute('UPDATE actions SET body=? WHERE id=?',(json.dumps(window),window['id']))

def record_sale(db,item,order):
    if order.get('environment')=='sandbox':return
    record=db.execute('SELECT body FROM actions WHERE id=?',('outcome-window:'+item['id'],)).fetchone()
    if not record:return
    window=json.loads(record['body'])
    if window['status']!='observing':return
    if signature(item)!=window['signature']:
        window['status']='invalidated';db.execute('UPDATE actions SET body=? WHERE id=?',(json.dumps(window),window['id']));return
    completed=datetime.fromisoformat(order['completed_at'])
    if datetime.fromisoformat(window['opened_at'])<=completed<=datetime.fromisoformat(window['closes_at']):finalize(db,window,1,order['completed_at'])

def confirm_unsold(item):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        record=db.execute('SELECT body FROM actions WHERE id=?',('outcome-window:'+item['id'],)).fetchone()
        window=json.loads(record['body']) if record else None
        if not window or window['status']!='observing':raise ValueError('No open observation window for this item.')
        if datetime.now(timezone.utc)<datetime.fromisoformat(window['closes_at']):raise ValueError('The complete seven-day observation window has not elapsed.')
        if signature(item)!=window['signature']:raise ValueError('The price or product facts changed; this window cannot be labeled as a constant-price outcome.')
        if item['status']=='sold':
            sales=[json.loads(r['body']) for r in db.execute('SELECT body FROM orders')]
            if any(r.get('item_id')==item['id'] and r.get('status')=='completed' and datetime.fromisoformat(r['completed_at'])<=datetime.fromisoformat(window['closes_at']) for r in sales):raise ValueError('A completed sale is recorded within this window.')
        if item['status']=='sale_pending':raise ValueError('Confirm the detected sale before labeling the observation.')
        finalize(db,window,0,store.now())
    return window
