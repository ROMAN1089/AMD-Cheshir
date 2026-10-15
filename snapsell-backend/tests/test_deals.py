from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import pytest
from test_research import item,seller,isolated,app,store
import deals

def slot(hours=4):
    start=datetime.now(timezone.utc)+timedelta(hours=hours)
    return deals.add_slot({'start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat(),'location':'Pickup point, Алматы'})

def book(item,s):
    return deals.book({'item_id':item['id'],'slot_id':s['id'],'buyer':'Buyer alias'})

def travel(monkeypatch,a,minutes=5):
    value=(deals.instant(a['start'])+timedelta(minutes=minutes)).isoformat()
    monkeypatch.setattr(store,'now',lambda:value)

def test_private_schedule_and_calendar(item,seller):
    a=book(item,slot()); guest=app.app.test_client()
    assert guest.get('/api/deals').status_code==401
    assert guest.get(f"/api/deals/appointments/{a['id']}/calendar").status_code==401
    assert seller.get('/api/deals').json['appointments'][0]['buyer']=='Buyer alias'

@pytest.mark.parametrize('offset',[-5,0,5,9])
def test_offsets_are_normalized_without_changing_instant(offset):
    start=datetime.now(timezone(timedelta(hours=offset)))+timedelta(hours=5)
    s=deals.add_slot({'start':start.isoformat(),'end':(start+timedelta(minutes=20)).isoformat(),'location':'Meeting point'})
    assert deals.instant(s['start'])==start

@pytest.mark.parametrize('changes',[{'start':'2026-01-01T10:00:00'},{'end':'invalid'},{'location':''}])
def test_invalid_slots_do_not_write(changes):
    start=datetime.now(timezone.utc)+timedelta(hours=4)
    d={'start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat(),'location':'Point',**changes}
    with pytest.raises(ValueError):deals.add_slot(d)
    assert store.all_rows('availability')==[]

def test_overlapping_slots_rejected_but_adjacent_allowed():
    s=slot()
    with pytest.raises(ValueError):deals.add_slot(s)
    end=deals.instant(s['end'])
    deals.add_slot({'start':end.isoformat(),'end':(end+timedelta(minutes=30)).isoformat(),'location':'Point'})
    assert len(store.all_rows('availability'))==2

def test_atomic_competing_bookings(item):
    s=slot();second=store.put('items',{**item,'id':'second'})
    def attempt(i):
        try:return book(i,s)
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[item,second]))
    assert len([r for r in results if r])==1
    assert len(store.all_rows('appointments'))==1

def test_same_item_cannot_have_two_meetings(item):
    book(item,slot())
    with pytest.raises(ValueError):book(item,slot(6))

def test_unreviewed_item_cannot_book(item):
    item['confirmed']=False;store.put('items',item)
    with pytest.raises(ValueError):book(item,slot())

def test_linked_offer_must_belong_to_item(item):
    store.put('orders',{'id':'bad','item_id':'other','status':'pending'})
    with pytest.raises(ValueError):deals.book({'item_id':item['id'],'slot_id':slot()['id'],'buyer':'Buyer','order_id':'bad'})

def test_reschedule_clears_buyer_confirmation_and_releases_slot(item):
    s=slot();a=book(item,s);new=slot(8)
    with pytest.raises(ValueError):deals.update(a['id'],{'action':'confirm'})
    deals.update(a['id'],{'action':'confirm','buyer_agreed':True})
    a=deals.update(a['id'],{'action':'reschedule','slot_id':new['id']})
    assert a['status']=='scheduled' and 'buyer_confirmed_at' not in a
    assert next(r for r in deals.workspace()['availability'] if r['id']==s['id'])['available']
    assert not next(r for r in deals.workspace()['availability'] if r['id']==new['id'])['available']

def test_cancel_releases_interval_and_cannot_be_repeated(item):
    s=slot();a=book(item,s)
    with pytest.raises(ValueError):deals.close_slot(s['id'])
    deals.update(a['id'],{'action':'cancel','confirm':True})
    assert deals.workspace()['availability'][0]['available']
    with pytest.raises(ValueError):deals.update(a['id'],{'action':'pickup','confirm':True})
    assert deals.close_slot(s['id'])['status']=='closed'

def test_pickup_is_not_revenue_and_cannot_be_repeated(item,monkeypatch):
    a=book(item,slot())
    with pytest.raises(ValueError):deals.update(a['id'],{'action':'pickup','confirm':True})
    deals.update(a['id'],{'action':'confirm','buyer_agreed':True});travel(monkeypatch,a)
    assert deals.update(a['id'],{'action':'pickup','confirm':True})['status']=='picked_up'
    assert store.get('items',item['id'])['status']=='listed'
    assert store.all_rows('orders')==[] and not store.events(item['id'])
    with pytest.raises(ValueError):book(item,slot(7))

def test_no_show_cannot_be_recorded_early(item,monkeypatch):
    a=book(item,slot())
    with pytest.raises(ValueError):deals.update(a['id'],{'action':'no_show','confirm':True})
    travel(monkeypatch,a)
    assert deals.update(a['id'],{'action':'no_show','confirm':True})['status']=='no_show'

def test_sold_item_can_still_be_picked_up(item):
    store.put('items',{**item,'status':'sold'})
    assert book(item,slot())['status']=='scheduled'

def test_reminders_persist_dismissal_and_escalate(item,monkeypatch):
    a=book(item,slot(4));r=deals.workspace()['reminders'][0];assert r['kind']=='day'
    deals.update(a['id'],{'action':'dismiss','revision':r['revision'],'kind':r['kind']})
    assert deals.workspace()['reminders']==[]
    travel(monkeypatch,a,-30);assert deals.workspace()['reminders'][0]['kind']=='hour'
    travel(monkeypatch,a,40);assert deals.workspace()['reminders'][0]['kind']=='overdue'
    deals.update(a['id'],{'action':'cancel','confirm':True});assert deals.workspace()['reminders']==[]

def test_stale_reminder_dismissal_rejected(item):
    a=book(item,slot());old=a['revision']
    deals.update(a['id'],{'action':'reschedule','slot_id':slot(8)['id']})
    with pytest.raises(ValueError):deals.update(a['id'],{'action':'dismiss','revision':old,'kind':'day'})

def test_calendar_utc_escape_fold_and_cancel_status(item,seller):
    s=slot();a=deals.book({'item_id':item['id'],'slot_id':s['id'],'buyer':'Alias','note':'Тест; запятая, '+('Я'*100)+'\r\nBEGIN:VEVENT'})
    r=seller.get(f"/api/deals/appointments/{a['id']}/calendar")
    assert r.status_code==200 and r.mimetype=='text/calendar'
    content=r.data.decode('utf-8');assert all(len(line.encode('utf-8'))<=75 for line in content.split('\r\n'))
    unfolded=content.replace('\r\n ','');assert '\\; запятая\\,' in unfolded and '\\nBEGIN:VEVENT' in unfolded
    assert '\r\nBEGIN:VEVENT\r\n' in content and content.count('\r\nBEGIN:VEVENT\r\n')==1
    assert deals.instant(a['start']).strftime('%Y%m%dT%H%M%SZ') in content
    deals.update(a['id'],{'action':'cancel','confirm':True})
    assert 'STATUS:CANCELLED' in deals.calendar(a['id'])
