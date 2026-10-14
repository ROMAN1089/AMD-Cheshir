"""Durable single-store SQLite repository. Original Supabase schema retained upstream.

SQLite is the portable hackathon runtime; there is no browser service-role key.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'snapsell.sqlite3'

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize():
    with connection() as db:
        for name in ['items', 'comparables', 'conversations', 'jobs', 'history', 'actions', 'orders']:
            db.execute(f'CREATE TABLE IF NOT EXISTS {name} (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, item_id TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS event_item ON events(item_id, kind)')

TABLES = {'items','comparables','conversations','jobs','history','actions','orders'}

def all_rows(table):
    if table not in TABLES:
        raise ValueError('Unknown table')
    with connection() as db:
        return [present(table,json.loads(r['body'])) for r in db.execute(f'SELECT body FROM {table} ORDER BY rowid')]

def present(table,row):
    if table=='items' and row.get('created_at'):
        try:
            created=datetime.fromisoformat(row['created_at'])
            if created.tzinfo is None:created=created.replace(tzinfo=timezone.utc)
            row['age_days']=max(0,(datetime.now(timezone.utc)-created).days)
        except (ValueError,TypeError):pass
    return row

def get(table, key):
    if table not in TABLES:
        raise ValueError('Unknown table')
    with connection() as db:
        row = db.execute(f'SELECT body FROM {table} WHERE id=?', (key,)).fetchone()
        return present(table,json.loads(row['body'])) if row else None

def put(table, body):
    if table not in TABLES:
        raise ValueError('Unknown table')
    body = dict(body)
    body.setdefault('id', str(uuid4()))
    with connection() as db:
        db.execute(f'INSERT INTO {table}(id,body) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body', (body['id'], json.dumps(body)))
    return body

def event(item_id, kind, source='live', **body):
    with connection() as db:
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)', (str(uuid4()), item_id, kind, source, now(), json.dumps(body)))

def purge_samples():
    """Remove only explicitly synthetic fixtures and their dependent records."""
    removed={}
    with connection() as db:
        ids={r['id'] for r in db.execute('SELECT id,body FROM items') if json.loads(r['body']).get('source')=='synthetic'}
        for table in TABLES:
            count=0
            for r in db.execute(f'SELECT id,body FROM {table}').fetchall():
                body=json.loads(r['body'])
                if body.get('source')=='synthetic' or body.get('item_id') in ids or (table=='items' and r['id'] in ids):
                    db.execute(f'DELETE FROM {table} WHERE id=?',(r['id'],)); count+=1
            removed[table]=count
        removed['events']=db.execute("DELETE FROM events WHERE source='synthetic'").rowcount
        for item_id in ids:
            removed['events']+=db.execute('DELETE FROM events WHERE item_id=?',(item_id,)).rowcount
    return removed

def events(item_id=None):
    with connection() as db:
        rows = db.execute('SELECT * FROM events WHERE item_id=? ORDER BY created_at', (item_id,)) if item_id else db.execute('SELECT * FROM events ORDER BY created_at')
        return [{**dict(r), 'body':json.loads(r['body'])} for r in rows]

def complete_order(item_id, offer_id, amount):
    """One atomic transition prevents duplicate revenue or selling the same item twice."""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT body FROM items WHERE id=?', (item_id,)).fetchone()
        item = json.loads(row['body']) if row else None
        if not item or item['status'] != 'listed':
            raise ValueError('This item is no longer available.')
        offer = db.execute('SELECT body FROM orders WHERE id=?', (offer_id,)).fetchone()
        order = json.loads(offer['body']) if offer else None
        if not order or order['status'] != 'pending' or order['item_id'] != item_id:
            raise ValueError('This offer is no longer pending.')
        item.update(status='sold', sold_price=amount, sold_at=now())
        order.update(status='completed', completed_at=now(),economics={'cost':item['cost'],'fee_rate':item['fee_rate'],'net_contribution':round(amount*(1-item['fee_rate'])-item['cost'],2)})
        db.execute('UPDATE items SET body=? WHERE id=?', (json.dumps(item), item_id))
        db.execute('UPDATE orders SET body=? WHERE id=?', (json.dumps(order), offer_id))
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)', (str(uuid4()),item_id,'sale','live',now(),json.dumps({'amount':amount,'offer_id':offer_id})))
    return order
