"""External marketplace listing kits and seller-reported outcomes.

Export is never publication. Marketplace links and completed sales are explicitly
reported by the seller; they do not masquerade as API-synchronized events.
"""
import io,json,zipfile,hashlib,html,re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import store,pricing,commerce,amd,faults,photos

PLATFORMS={
 'ebay':{'name':'eBay','url':'https://www.ebay.com/sl/sell','mode':'listing_kit','integration':'Seller API authorization and listing policies required for direct publishing.','hosts':['ebay.com'],'title_limit':80},
 'facebook':{'name':'Facebook Marketplace','url':'https://www.facebook.com/marketplace/create/item','mode':'manual_transfer','integration':'Copy the prepared listing and upload the included photo in your Facebook account.','hosts':['facebook.com'],'title_limit':80},
 'craigslist':{'name':'Craigslist','url':'https://post.craigslist.org/','mode':'manual_transfer','integration':'Select your city and category in Craigslist, then use the prepared listing.','hosts':['craigslist.org'],'title_limit':70},
}

def platform(name):
 if name not in PLATFORMS:raise ValueError('Choose eBay, Facebook Marketplace or Craigslist.')
 return PLATFORMS[name]

def version(item):
 return hashlib.sha256(json.dumps({k:item.get(k) for k in ['title','description','category','condition','specs','price','image','photos','confirmed']},sort_keys=True).encode()).hexdigest()

def prepare(item,name):
 destination=platform(name);report=pricing.evaluate(item)
 recommendation=next((s for s in report.get('strategies',[]) if s['id']=='balanced'),None)
 price=item['price'] if item['price']>0 else recommendation['price'] if recommendation else None
 price_source='Seller price' if item['price']>0 else ('Verified market median' if report['comparables']['source']=='verified_web' else 'Seller-provided comparable median') if recommendation else 'More matching price evidence needed'
 fault_profile=faults.profile(item)
 title=('For repair: ' if fault_profile['faulty'] else '')+item['title']
 if len(title)>destination['title_limit']:
  title=title[:destination['title_limit']]
  if ' ' in title:title=title.rsplit(' ',1)[0]
 title=title.rstrip(' ,;·-')
 facts=['Condition: '+item['condition']] if item.get('confirmed') else ['Condition: seller review pending']
 for k,v in item.get('specs',{}).items():
  if v and not any(w in str(v).lower() for w in ['not verified','unknown','not tested']):facts.append(k.replace('_',' ').title()+': '+str(v))
 description=item.get('description','').strip()
 if fault_profile['faulty']:facts.insert(0,'FAULTY / FOR REPAIR: '+(', '.join(fault_profile['types']) or 'Fault not yet diagnosed')+'. '+str(fault_profile['details']))
 text=description+'\n\n'+'\n'.join(facts)
 image=item.get('image','');photo=None
 if image.startswith('/media/'):
  path=(store.DATA/'media'/image.removeprefix('/media/')).resolve()
  if path.is_relative_to((store.DATA/'media').resolve()) and path.is_file():photo=path
 missing=[]
 if item.get('archived_at'):missing.append('Restore this archived item before preparing a new listing.')
 if item['status'] in ['sold','sale_pending']:missing.append('This item has sold or has an eBay sale awaiting confirmation; do not post another listing.')
 if not item.get('confirmed'):missing.append('Review and confirm product facts.')
 if price is None:missing.append('Choose a price or gather enough matching market evidence.')
 elif price<max(item['reserve'],item['cost']/(1-item['fee_rate'])):missing.append('The asking price is below your recorded minimum or fee-adjusted acquisition cost.')
 if photo is None:missing.append('Add a real product photo on the marketplace; the placeholder is not exported.')
 kit={'item_id':item['id'],'platform':name,'platform_name':destination['name'],'title':title,'description':text.strip(),'price_usd':price,'price_source':price_source,'condition':'For parts / not working' if fault_profile['faulty'] else item['condition'],'fault_profile':fault_profile,'category_hint':item['category'],'photo_available':photo is not None,'ready_for_manual_posting':not missing,'missing':missing,'open_url':destination['url'],'integration':destination['integration'],'listing_version':version(item),'publication_status':'not_published'}
 kit['price_evidence']={'basis':report['comparables']['basis'],'confidence':report['comparables'].get('confidence'),'sources':[{k:r.get(k) for k in ['title','price','condition','url','source_name','observed_at','included','exclusion_reason']} for r in report['comparables'].get('rows',[])]}
 kit['photos']=photos.gallery(item)
 if name=='ebay':
  aspects={k.replace('_',' ').title():[str(v)] for k,v in item.get('specs',{}).items() if v and 'not verified' not in str(v).lower()}
  kit['ebay_draft']={'sku':'snapsell-'+item['id'],'inventory_item':{'availability':{'shipToLocationAvailability':{'quantity':1}},'product':{'title':title,'description':text.strip(),'aspects':aspects,'imageUrls':[]}},'offer':{'marketplaceId':'EBAY_US','format':'FIXED_PRICE','availableQuantity':1,'listingDescription':'<p>'+html.escape(text.strip()).replace('\n','<br>')+'</p>',**({'pricingSummary':{'price':{'value':f'{price:.2f}','currency':'USD'}}} if price is not None else {})},'required_before_api_publish':['Seller OAuth authorization','eBay leaf category ID and category-specific item aspects','Category-supported inventory condition','Public product photo URL','Inventory location','Fulfillment, payment and return business policy IDs']}
 return kit,photo

def bundle(item,name):
 kit,photo=prepare(item,name);data=io.BytesIO()
 with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
  archive.writestr('listing.json',json.dumps(kit,indent=2))
  archive.writestr('title.txt',kit['title']);archive.writestr('description.txt',kit['description'])
  if kit['price_usd'] is not None:archive.writestr('price.txt',f'{kit["price_usd"]:.2f} USD')
  if photo:archive.write(photo,'photo'+photo.suffix.lower())
  for index,url in enumerate(photos.gallery(item)[1:],2):
   try:archive.write(photos.path_for(url),f'photo-{index}.jpg')
   except ValueError:continue
  archive.writestr('POSTING_GUIDE.txt',f'{kit["platform_name"]} listing kit\n\nOpen: {kit["open_url"]}\n\n{kit["integration"]}\nReview the title, description, price, photos and platform-specific required fields before posting. Downloading this kit does not publish anything.\n\n'+('\n'.join(kit['missing']) or 'Prepared for manual transfer.')+'\n\nAfter posting, save the live listing URL in SnapSell. Mark a sale only after the external transaction is complete.\n')
 return data.getvalue(),kit

def tracked(item_id,name):
 return [a for a in store.all_rows('actions') if a.get('type')=='external_listing' and a.get('item_id')==item_id and a.get('platform')==name]

def reconcile_item(item_id):
 item=store.get('items',item_id)
 if not item or item['status'] in ['sold','sale_pending']:return
 active=any(a.get('type')=='external_listing' and a.get('item_id')==item_id and a.get('status')=='posted' for a in store.all_rows('actions'))
 item['status']='listed' if active else 'draft'
 store.put('items',item)

def record_listing(item,name,url):
 destination=platform(name);p=urlsplit(url)
 if p.scheme!='https' or p.username or p.password or (p.port and p.port!=443) or not any(p.hostname==h or (p.hostname or '').endswith('.'+h) for h in destination['hosts']):raise ValueError('Use an HTTPS listing URL from the selected marketplace.')
 patterns={'ebay':r'^/itm/(?:[^/]+/)?\d+(?:/|$)','facebook':r'^/marketplace/item/\d+(?:/|$)','craigslist':r'/\d+\.html$'}
 if not re.search(patterns[name],p.path):raise ValueError('Use the actual item listing URL, not a marketplace homepage or profile.')
 if item['status'] in ['sold','sale_pending']:raise ValueError('This item is sold or has a sale awaiting confirmation.')
 if item.get('archived_at'):raise ValueError('Restore this item before recording a listing.')
 if not item.get('confirmed'):raise ValueError('Review the product facts before recording its listing.')
 kit,_=prepare(item,name)
 if kit['price_usd'] is not None and item['price']<=0:item['price']=kit['price_usd']
 existing=tracked(item['id'],name);row=existing[-1] if existing else {'id':str(uuid4()),'type':'external_listing','item_id':item['id'],'platform':name,'created_at':store.now()}
 if row.get('source')=='ebay_api':raise ValueError('Manage the API-connected eBay listing using its sync and withdraw controls.')
 row.update(url=url[:2000],status='posted',source='seller_reported',listing_version=version(item),updated_at=store.now())
 item['status']='listed'
 with store.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  current=json.loads(db.execute('SELECT body FROM items WHERE id=?',(item['id'],)).fetchone()['body'])
  if current['status'] in ['sold','sale_pending']:raise ValueError('This item is sold or has a sale awaiting confirmation.')
  db.execute('UPDATE items SET body=? WHERE id=?',(json.dumps(item),item['id']))
  db.execute('INSERT INTO actions(id,body) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(row['id'],json.dumps(row)))
 return row

def complete_sale(item_id,listing_id,amount,fee,cost,expenses=None):
 expenses=expenses or {}
 with store.connection() as db:
  db.execute('BEGIN IMMEDIATE')
  row=db.execute('SELECT body FROM items WHERE id=?',(item_id,)).fetchone();item=json.loads(row['body']) if row else None
  row=db.execute('SELECT body FROM actions WHERE id=?',(listing_id,)).fetchone();listing=json.loads(row['body']) if row else None
  if not item or item['status']=='sold' or not listing or listing.get('type')!='external_listing' or listing['item_id']!=item_id or listing.get('status') not in ['posted','sale_detected']:raise ValueError('Record an active external listing or detected eBay sale before recording its completed sale.')
  economics={'cost':cost,'fee_amount':fee,**expenses,'net_contribution':round(amount-fee-cost-sum(expenses.values()),2)}
  order={'id':str(uuid4()),'item_id':item_id,'status':'completed','amount':amount,'platform':listing['platform'],'listing_url':listing['url'],'source':'seller_reported','economics':economics,'completed_at':store.now()}
  if listing.get('environment'):order['environment']=listing['environment']
  item.update(status='sold',sold_price=amount,sold_at=store.now());listing.update(status='sold',sold_at=store.now())
  db.execute('UPDATE items SET body=? WHERE id=?',(json.dumps(item),item_id));db.execute('UPDATE actions SET body=? WHERE id=?',(json.dumps(listing),listing_id))
  # Other copies require removal on the external site. Do not pretend they were ended.
  for other in db.execute('SELECT id,body FROM actions').fetchall():
   value=json.loads(other['body'])
   if value.get('type')=='external_listing' and value.get('item_id')==item_id and value['id']!=listing_id and value.get('status')=='posted':
    value.update(status='needs_removal');db.execute('UPDATE actions SET body=? WHERE id=?',(json.dumps(value),value['id']))
  db.execute('INSERT INTO orders(id,body) VALUES(?,?)',(order['id'],json.dumps(order)))
  import outcomes
  outcomes.record_sale(db,item,order)
  db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(str(uuid4()),item_id,'sale','seller_reported',store.now(),json.dumps({'amount':amount,'order_id':order['id'],'platform':listing['platform']})))
 return order

def workspace():
 listings=[a for a in store.all_rows('actions') if a.get('type')=='external_listing']
 for listing in listings:
  item=store.get('items',listing['item_id'])
  listing['needs_sync']=bool(item and listing.get('status')=='posted' and (listing.get('listing_version')!=version(item) or listing.get('last_sync_failed')))
 sales=[o for o in store.all_rows('orders') if o.get('source')=='seller_reported' and o.get('platform') in PLATFORMS]
 return {'platforms':[{'id':name,**value} for name,value in PLATFORMS.items()],'listings':listings,'sales':sales,'revenue':round(sum(o['amount'] for o in sales),2),'net_contribution':round(sum(o['economics']['net_contribution'] for o in sales),2),'note':'External links and completed sales are seller-reported. Marketplace activity is not automatically synchronized.'}

def draft_reply(item,message,name):
 platform(name)
 if item['status']=='sold':return {'answer':'This item has sold. Thank you for your interest.','provider':'Recorded inventory','intents':['availability'],'mode':'draft_only','sent':False,'platform':name}
 if item['status']=='sale_pending':return {'answer':'A sale has been reported for this item and is awaiting seller confirmation. Please do not make another offer yet.','provider':'eBay inventory status','intents':['availability'],'mode':'draft_only','sent':False,'platform':name}
 posted=any(a.get('status')=='posted' for a in tracked(item['id'],name))
 kit,_=prepare(item,name)
 result=commerce.reply({**item,'status':'listed','price':kit['price_usd'] or 0},message)
 result['answer']=result['answer'].replace('Use Make an offer to send a price to the seller.','Please send your proposed price in this conversation.').replace('Suggested items appear below when compatibility is recorded.','I can check compatible items from the seller’s inventory.')
 if not posted and 'availability' in result['intents']:result['answer']='Availability needs seller confirmation before sending this reply.'
 result.update(mode='draft_only',sent=False,platform=name)
 store.put('actions',{'type':'reply_draft','item_id':item['id'],'platform':name,'question':amd.redact(message),'answer':result['answer'],'intents':result['intents'],'source':'seller_reported','at':store.now()})
 return result
