"""Legacy fixtures for isolated tests only. Never imported by the application."""
import math
import random
from datetime import datetime, timedelta, timezone
import store

PRODUCTS = [
    ('macbook-air-m1','Apple MacBook Air M1','Apple','Laptop',499,340,449,'Excellent','8GB RAM · 256GB SSD · 13.3-inch', 'An everyday favorite. Lightweight, quiet, and ready for work.', 9, 'laptop-silver','Student & remote work', {'processor':'Apple M1','memory':'8GB','storage':'256GB SSD','screen':'13.3-inch','battery':'87% health, seller verified','included':'Original charger'}),
    ('thinkpad-t14','Lenovo ThinkPad T14 Gen 2','Lenovo','Laptop',429,260,335,'Good','16GB RAM · 512GB SSD · Ryzen 5', 'A dependable workhorse with a great keyboard. Light wear on the lid.', 28,'laptop-dark','Business & productivity', {'processor':'AMD Ryzen 5 PRO 5650U','memory':'16GB','storage':'512GB SSD','screen':'14-inch FHD','battery':'Not tested','included':'65W USB-C charger'}),
    ('dell-u2720q','Dell UltraSharp U2720Q','Dell','Monitor',289,165,249,'Excellent','27-inch · 4K IPS · USB-C', 'More room for your best work. Crisp 4K detail with USB-C connectivity.', 13,'monitor','Creative & productivity', {'screen':'27-inch 4K IPS','ports':'USB-C, DisplayPort, HDMI','included':'Stand and power cable','pixel_test':'No dead pixels, seller verified'}),
    ('lg-27gl83a','LG UltraGear 27GL83A-B','LG','Monitor',219,105,179,'Good','27-inch · QHD IPS · 144Hz', 'Smooth motion and vivid color. A capable gaming display with minor stand wear.', 35,'monitor-gaming','Gaming', {'screen':'27-inch 2560×1440 IPS','refresh_rate':'144Hz','ports':'DisplayPort, HDMI','included':'Stand and power cable','pixel_test':'Not tested'}),
    ('dell-xps-13','Dell XPS 13 9310','Dell','Laptop',579,355,499,'Excellent','16GB RAM · 512GB SSD · Intel i7', 'A compact premium laptop for work on the move.', 5,'laptop-silver','Business & travel', {'processor':'Intel Core i7-1165G7','memory':'16GB','storage':'512GB SSD','screen':'13.4-inch FHD+','battery':'Not tested','included':'USB-C charger'}),
    ('samsung-m7','Samsung Smart Monitor M7','Samsung','Monitor',239,135,195,'Good','32-inch · 4K · Smart apps', 'A generous workspace that doubles as an entertainment screen.', 17,'monitor','Remote work & entertainment', {'screen':'32-inch 4K','ports':'USB-C, HDMI','included':'Stand, remote and power cable','pixel_test':'Not tested'}),
]

def seed():
    if store.all_rows('items'):
        return
    rng = random.Random(73)
    for pid,title,brand,cat,price,cost,base,cond,spec,desc,age,image,use,specs in PRODUCTS:
        if cat=='Laptop': specs['display_output']='USB-C, DisplayPort' if brand=='Apple' else 'USB-C, HDMI'
        item = store.put('items', dict(id=pid,title=title,brand=brand,category=cat,model_key=pid,price=price,cost=cost,reserve=round(cost*1.15),fee_rate=.08,holding_cost=.35,condition=cond,specs=specs,subtitle=spec,description=desc,status='listed',age_days=age,created_at=(datetime.now(timezone.utc)-timedelta(days=age)).isoformat(),image=f'/assets/{image}.svg',use_case=use,source='synthetic',confirmed=True,questions=[],strategy='balanced'))
        for j in range(14):
            store.put('comparables',dict(id=f'{pid}-comp-{j}',model_key=pid,title=title,price=round(base*rng.uniform(.80,1.20)),condition=rng.choice(['Good','Excellent']),age_days=rng.randint(1,40),kind='sold' if j<10 else 'asking',source='synthetic',source_name='Demo US resale dataset',observed_at=store.now(),url=''))
        for j in range(rng.randint(50,140)):
            store.event(pid,'view',source='synthetic')
        for j in range(rng.randint(4,17)):
            store.event(pid,'inquiry',source='synthetic',question='Is the charger included?' if j%3 == 0 else 'Is this still available?')
    for i in range(1800):
        ratio=rng.uniform(.65,1.40); age=rng.uniform(0,60); excellent=int(rng.random()>.45); monitor=int(rng.random()>.5); complete=rng.uniform(.4,1)
        logit=1.0-5.0*(ratio-1)-.011*age+.35*excellent-.20*monitor+.75*(complete-.7)
        sold=int(rng.random()<1/(1+math.exp(-logit)))
        store.put('history',dict(id=f'demo-history-{i}',price_ratio=ratio,age_days=age,excellent=excellent,monitor=monitor,completeness=complete,sold_within_7_days=sold,source='synthetic',observed_at=(datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=i//10)).isoformat()))
    store.put('conversations',dict(id='demo-conversation',item_id='thinkpad-t14',buyer='Demo buyer',source='synthetic',messages=[{'role':'user','content':'Does it come with a charger? I need a setup for working from home.','at':store.now()},{'role':'assistant','content':'Yes, the seller lists a 65W USB-C charger. The ThinkPad has 16GB RAM and a 512GB SSD. Battery life has not been tested. A USB-C monitor could complete your workspace.','at':store.now(),'provider':'Demo fixture'}]))
