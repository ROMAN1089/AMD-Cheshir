import math
import re
from collections import Counter
import amd
import pricing
import store

def recommend(item,budget=None):
    result=[]
    for other in store.all_rows('items'):
        if other.get('archived_at') or other['id']==item['id'] or other['status']!='listed' or other['category']==item['category']: continue
        if {item['category'],other['category']}!={'Laptop','Monitor'}:continue
        if budget and other['price']+item['price']>budget: continue
        laptop=item if item['category']=='Laptop' else other
        monitor=other if item['category']=='Laptop' else item
        output=str(laptop.get('specs',{}).get('display_output','')).lower()
        ports=str(monitor.get('specs',{}).get('ports','')).lower()
        compatible=next((p for p in ['hdmi','displayport'] if p in output and p in ports),None)
        if not compatible and 'usb-c' in output and 'usb-c' in ports and any(s in output for s in ['displayport','alt mode','thunderbolt']) and any(s in ports for s in ['displayport','alt mode','video input','thunderbolt']):compatible='usb-c video'
        if not compatible: continue
        score=2*int(item.get('use_case')==other.get('use_case'))+1/(1+other['price']/300)
        result.append(dict(item=public_item(other),score=round(score,3),reason=f'Complements your {item["category"].lower()} through {compatible.upper()}. Confirm the required cable is included.',combined_price=round(item['price']+other['price'],2)))
    return sorted(result,key=lambda r:r['score'],reverse=True)[:3]

def public_item(item):
    import faults
    if faults.profile(item)['faulty']:item={**item,'condition':'For parts / not working' if item.get('specs',{}).get('working')=='No' else 'Damaged / disclosed faults'}
    return {k:v for k,v in item.items() if k in {'id','title','brand','category','condition','specs','subtitle','description','image','price','status','use_case','source'}}

def offline_intents(message):
    m=message.lower(); intents=[]
    terms={'battery':['battery','charge cycles','last on a charge'],'included':['included','charger','come with','cable','stand'],'specs':['ram','memory','processor','storage','screen','resolution','refresh','ports'],'condition':['condition','scratch','wear','damage'],'pickup':['pick up','pickup','meet','delivery','shipping'],'offer':['offer','take $','accept $','discount','best price'],'bundle':['setup','monitor','bundle','work from home'],'warranty':['warranty','return','guarantee'],'availability':['available','still for sale']}
    for kind,words in terms.items():
        if any(word in m for word in words): intents.append(kind)
    return intents or ['other']

def reply(item,message,allow_unconfirmed=False):
    provider='Local fact-based assistant'; intents=offline_intents(message); warning=None
    if amd.configured():
        try:
            classified,model=amd.classify(message)
            if classified: intents=classified
            provider=f'AMD · {model}'
        except RuntimeError as exc:
            warning=str(exc); provider='Local fallback · AMD unavailable'
    answers=[]; specs=item.get('specs',{})
    if item['status']!='listed':
        return dict(answer='This item is no longer available. Please choose another item from the store.',provider=provider,recommendations=[],intents=['availability'])
    if not item.get('confirmed') and not allow_unconfirmed:
        return dict(answer='Product facts need seller review before I can answer reliably. Please ask the seller to confirm the details.',provider=provider,recommendations=[],intents=intents)
    for intent in intents:
        if intent=='availability': answers.append(f'Yes, the {item["title"]} is available.'+(f' The asking price is ${item["price"]:,.2f}.' if item['price']>0 else ' The asking price needs seller confirmation.'))
        elif intent=='battery': answers.append('Battery: '+str(specs.get('battery','Not verified. The seller needs to check this.'))+'.')
        elif intent=='included': answers.append('The seller lists: '+str(specs.get('included','Included accessories have not been verified.'))+'.')
        elif intent=='specs': answers.append('Seller-confirmed specifications: '+ '; '.join(f'{k.replace("_"," ")}: {v}' for k,v in specs.items() if k not in ['included','battery'])+'.')
        elif intent=='condition': answers.append(f'The seller rates it {item["condition"]}. {item["description"]}')
        elif intent=='pickup': answers.append('You can request local pickup when submitting an offer. The seller will confirm the time and location; no meeting is booked automatically.')
        elif intent=='offer': answers.append('Use Make an offer to send a price to the seller. A discount or sale requires seller approval.')
        elif intent=='bundle': answers.append('I checked the available catalog for a complementary item with a matching display connection. Suggested items appear below when compatibility is recorded.')
        elif intent=='warranty': answers.append('No warranty or return policy is recorded. Please ask the seller before purchasing.')
        elif intent=='other': answers.append(f'The {item["title"]}'+(f' is listed at ${item["price"]:,.2f}.' if item['price']>0 else ' needs a confirmed asking price.')+' I can help with specifications, condition, accessories, or an offer. Unrecorded details require the seller to check.')
    return dict(answer=' '.join(dict.fromkeys(answers)),provider=provider,warning=warning,recommendations=recommend(item) if 'bundle' in intents else [],intents=intents)

def counts(item_id,source=None):
    return Counter(e['kind'] for e in store.events(item_id) if source is None or e['source']==source)

def actions():
    result=[]
    for item in store.all_rows('items'):
        if item.get('archived_at') or item['status']!='listed': continue
        e=store.events(item['id']); stats=counts(item['id']); questions=Counter()
        external_questions=[a for a in store.all_rows('actions') if a.get('type')=='reply_draft' and a.get('item_id')==item['id']]
        for question in external_questions:
            for intent in question.get('intents',[]):questions[intent]+=1
        for event in e:
            if event['kind']=='inquiry':
                for intent in offline_intents(event['body'].get('question','')):
                    questions[intent]+=1
        recorded={a.get('id') for a in store.all_rows('actions') if a.get('type')=='applied'}
        if questions['included']>=3 and 'Includes:' not in item['description'] and item.get('specs',{}).get('included'):
            action_id=f'faq-{item["id"]}'
            if action_id not in recorded: result.append(dict(id=action_id,item_id=item['id'],kind='description',title='Answer the question buyers keep asking',detail=f'{questions["included"]} recorded accessory questions. Update the local description, then synchronize or manually revise your marketplace listings.',evidence_source='seller_reported' if external_questions else 'live',priority=1,item_title=item['title']))
        if item.get('age_days',0)>=21:
            analysis=pricing.evaluate(item)
            best=next((s for s in analysis['strategies'] if s['id']=='balanced'),None)
            if best and best['price']<item['price']:
                action_id=f'price-{item["id"]}-{best["price"]}'
                if action_id not in recorded: result.append(dict(id=action_id,item_id=item['id'],kind='price',price=best['price'],title='Review the price against current evidence',detail=f'Listed for {item["age_days"]} days. Compare ${item["price"]} with ${best["price"]} using the observed market evidence. No sales improvement is assumed.',evidence_source=analysis['comparables']['source'],priority=2,item_title=item['title']))
    return sorted(result,key=lambda a:a['priority'])

def analytics():
    items=store.all_rows('items'); ev=store.events(); live=[e for e in ev if e['source']=='live']; demo=[e for e in ev if e['source']=='synthetic']
    orders=[o for o in store.all_rows('orders') if o['status']=='completed']
    revenue=sum(o['amount'] for o in orders); byid={i['id']:i for i in items}
    contribution=sum(o.get('economics',{}).get('net_contribution',o['amount']*(1-byid[o['item_id']]['fee_rate'])-byid[o['item_id']]['cost']) for o in orders)
    def funnel(events):
        c=Counter(e['kind'] for e in events)
        return dict(views=c['view'],inquiries=c['inquiry'],offers=c['offer'],sales=c['sale'])
    external=[a for a in store.all_rows('actions') if a.get('type')=='reply_draft']
    return dict(revenue=round(revenue,2),net_contribution=round(contribution,2),inventory_value=round(sum(i['price'] for i in items if i['status']=='listed' and not i.get('archived_at')),2),active_count=sum(i['status']=='listed' and not i.get('archived_at') for i in items),draft_count=sum(i['status']=='draft' and not i.get('archived_at') for i in items),recorded_questions=len(external)+len([e for e in live if e['kind']=='inquiry']),completed_sales=len(orders),live=funnel(live),external=funnel([e for e in ev if e['source']=='seller_reported']),synthetic=funnel(demo),items=[dict(id=i['id'],title=i['title'],status=i['status'],price=i['price'],age_days=i.get('age_days',0),live=dict(counts(i['id'],'live')),synthetic=dict(counts(i['id'],'synthetic'))) for i in items],note='Net contribution deducts recorded acquisition cost, fees and any recorded shipping, packaging, repair, tax, labor and refund expenses. Unrecorded costs are excluded. Sales are seller-confirmed deals; no payment is processed.')
