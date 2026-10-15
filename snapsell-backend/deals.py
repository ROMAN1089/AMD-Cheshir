"""Seller-managed pickup appointments. No outbound messages or payment processing."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import store
import google_calendar as google

ACTIVE = {'scheduled', 'confirmed'}

def instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError('Provide a date and time with its UTC offset.')

def text(value, name, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name} is required (maximum {limit} characters).')
    return value.strip()

def rows(db, table):
    return [json.loads(r['body']) for r in db.execute(f'SELECT body FROM {table}')]

def save(db, table, row):
    db.execute(f'INSERT INTO {table} VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (row['id'], json.dumps(row)))
    return row

def find(db, table, key):
    row = db.execute(f'SELECT body FROM {table} WHERE id=?', (key,)).fetchone()
    if not row: raise ValueError('Record not found.')
    return json.loads(row['body'])

def add_slot(data):
    start, end = instant(data.get('start')), instant(data.get('end'))
    if start <= instant(store.now()) or not timedelta(minutes=15) <= end-start <= timedelta(hours=4):
        raise ValueError('Choose a future interval lasting 15 minutes to 4 hours.')
    location = text(data.get('location'), 'Meeting location')
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for slot in rows(db, 'availability'):
            if slot['status']=='open' and start < instant(slot['end']) and end > instant(slot['start']):
                raise ValueError('This interval overlaps another availability interval.')
        return save(db, 'availability', dict(id=str(uuid4()), start=start.isoformat(), end=end.isoformat(), location=location, status='open', created_at=store.now()))

def close_slot(key):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        slot = find(db, 'availability', key)
        if any(a['slot_id']==key and a['status'] in ACTIVE for a in rows(db,'appointments')):
            raise ValueError('Cancel or reschedule the meeting before closing its interval.')
        slot['status']='closed'
        return save(db,'availability',slot)

def available_slot(db, key, excluding=None):
    slot = find(db,'availability',key)
    if slot['status']!='open' or instant(slot['start'])<=instant(store.now()):
        raise ValueError('This interval is no longer available.')
    for a in rows(db,'appointments'):
        if a['id']!=excluding and a['status'] in ACTIVE and instant(a['start'])<instant(slot['end']) and instant(a['end'])>instant(slot['start']):
            raise ValueError('Another meeting already occupies this interval.')
    return slot

@google.serialized
def book(data):
    buyer = text(data.get('buyer'), 'Buyer name or marketplace alias', 120)
    note = data.get('note','')
    if not isinstance(note,str) or len(note)>1000: raise ValueError('Notes must be at most 1000 characters.')
    candidate=store.get('availability',str(data.get('slot_id','')))
    if candidate:google.ensure_free(candidate)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        item = find(db,'items',str(data.get('item_id','')))
        if not item.get('confirmed'): raise ValueError('Review the item facts before arranging pickup.')
        if any(a['item_id']==item['id'] and a['status'] in ACTIVE | {'picked_up'} for a in rows(db,'appointments')):
            raise ValueError('This item already has a meeting or a recorded pickup.')
        slot = available_slot(db,str(data.get('slot_id','')))
        order_id=data.get('order_id') or None
        if order_id:
            order=find(db,'orders',str(order_id))
            if order.get('item_id')!=item['id'] or order.get('status') not in {'pending','completed'}:
                raise ValueError('Choose a pending or completed offer for this item.')
        appointment=dict(id=str(uuid4()), item_id=item['id'], title=item['title'], buyer=buyer, note=note, order_id=order_id, slot_id=slot['id'], start=slot['start'], end=slot['end'], location=slot['location'], status='scheduled', revision=1, dismissed=[], created_at=store.now(), updated_at=store.now())
        if google.connected():appointment['google']=google.association(appointment)
        save(db,'appointments',appointment)
    return google.after_save(appointment)

@google.serialized
def update(key,data):
    if data.get('action')=='reschedule':
        candidate=store.get('availability',str(data.get('slot_id','')))
        if candidate:google.ensure_free(candidate,store.get('appointments',key))
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        a=find(db,'appointments',key)
        action=data.get('action')
        if action=='dismiss':
            if data.get('revision')!=a['revision']: raise ValueError('The meeting changed. Refresh its reminders.')
            kind=data.get('kind')
            if kind not in {'day','hour','overdue'}: raise ValueError('Unknown reminder.')
            a['dismissed']=list(set(a['dismissed']+[kind]))
        else:
            if a['status'] not in ACTIVE: raise ValueError('This meeting is already closed.')
            if action=='confirm':
                if data.get('buyer_agreed') is not True: raise ValueError('Confirm that the buyer agreed to this time and place.')
                if instant(a['end'])<=instant(store.now()): raise ValueError('Reschedule this expired meeting first.')
                a.update(status='confirmed', buyer_confirmed_at=store.now(), confirmation_source='seller_reported')
            elif action=='reschedule':
                slot=available_slot(db,str(data.get('slot_id','')),excluding=key)
                a.update(slot_id=slot['id'],start=slot['start'],end=slot['end'],location=slot['location'],status='scheduled',revision=a['revision']+1,dismissed=[])
                a.pop('buyer_confirmed_at',None); a.pop('confirmation_source',None)
            elif action in {'cancel','no_show','pickup'}:
                if data.get('confirm') is not True: raise ValueError('Confirm this meeting outcome.')
                if action in {'pickup','no_show'} and instant(a['start'])>instant(store.now()): raise ValueError('The meeting has not started yet.')
                if action=='pickup' and a['status']!='confirmed': raise ValueError('Record the buyer agreement before confirming pickup.')
                a.update(status={'cancel':'cancelled','no_show':'no_show','pickup':'picked_up'}[action], closed_at=store.now(), outcome_source='seller_reported')
            else: raise ValueError('Unknown meeting action.')
        if action not in {'dismiss','reschedule'}: a['revision']+=1
        a['updated_at']=store.now()
        if action!='dismiss' and a.get('google',{}).get('enabled'):a['google']['status']='pending'
        save(db,'appointments',a)
    return google.after_save(a) if action!='dismiss' else a

def workspace():
    with store.connection() as db:
        appointments=rows(db,'appointments'); slots=rows(db,'availability')
    now=instant(store.now()); reminders=[]
    for a in appointments:
        if a['status'] not in ACTIVE: continue
        start,end=instant(a['start']),instant(a['end'])
        kind='overdue' if now>=end else 'hour' if now>=start-timedelta(hours=1) else 'day' if now>=start-timedelta(days=1) else None
        if kind and kind not in a['dismissed']:
            reminders.append(dict(id=f"{a['id']}:{a['revision']}:{kind}", appointment_id=a['id'],revision=a['revision'],kind=kind,title=a['title'],start=a['start']))
    for slot in slots:
        slot['available']=slot['status']=='open' and instant(slot['start'])>now and not any(a['status'] in ACTIVE and instant(a['start'])<instant(slot['end']) and instant(a['end'])>instant(slot['start']) for a in appointments)
    return dict(appointments=sorted(appointments,key=lambda a:a['start']), availability=sorted(slots,key=lambda s:s['start']),reminders=reminders,server_time=now.isoformat())

def calendar(key):
    a=store.get('appointments',key)
    if not a: raise ValueError('Meeting not found.')
    def escape(v): return str(v).replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    def dt(v): return instant(v).strftime('%Y%m%dT%H%M%SZ')
    status='CANCELLED' if a['status'] in {'cancelled','no_show'} else 'CONFIRMED' if a['status'] in {'confirmed','picked_up'} else 'TENTATIVE'
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//SnapSell//Pickup//EN','BEGIN:VEVENT',f"UID:{a['id']}@snapsell.local",f"SEQUENCE:{a['revision']}",'DTSTAMP:'+dt(a['updated_at']),'DTSTART:'+dt(a['start']),'DTEND:'+dt(a['end']),'SUMMARY:'+escape('Pickup: '+a['title']),'LOCATION:'+escape(a['location']),'DESCRIPTION:'+escape('Buyer: '+a['buyer']+'\n'+a['note']), 'STATUS:'+status,'BEGIN:VALARM','TRIGGER:-PT1H','ACTION:DISPLAY','DESCRIPTION:Pickup reminder','END:VALARM','END:VEVENT','END:VCALENDAR']
    # RFC 5545 folding, counting UTF-8 octets without splitting a character.
    folded=[]
    for line in lines:
        part=''
        for char in line:
            if len((part+char).encode('utf-8'))>75: folded.append(part); part=' '
            part+=char
        folded.append(part)
    return '\r\n'.join(folded)+'\r\n'
