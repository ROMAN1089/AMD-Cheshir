"""Seller questions and auditable draft prices; never infer facts about a physical unit."""
import re
from uuid import uuid4
import store

UNKNOWN='Not verified'

def questions(item):
    specs=item.get('specs',{})
    def q(key,label,options=None,hint=''):
        value=item.get('condition') if key=='condition' else specs.get(key,'')
        if key=='condition' and item.get('source')=='video' and not item.get('assessment_answers'):value=UNKNOWN
        if options and value not in options:value=UNKNOWN
        if key=='battery' and item.get('category')=='Phone' and not re.fullmatch(r'(?:[1-9]|[1-9][0-9]|100)%?',str(value or '')):value=UNKNOWN
        return dict(key=key,label=label,options=options or [],hint=hint,value=value or UNKNOWN)
    common=[q('condition','Cosmetic condition',['Like new','Excellent','Good','Fair','Refurbished',UNKNOWN]),q('working','Does everything work?',['Yes','No',UNKNOWN]),q('repairs','Repairs or replaced parts',['None','Repaired / parts replaced',UNKNOWN]),q('included','What is included?',hint='For example: phone only, original box, cable. Leave unknown if unchecked.')]
    if item.get('category')=='Phone':
        return [q('storage','Storage capacity',['64GB','128GB','256GB','512GB','1TB',UNKNOWN]),q('battery','Battery health (%)',hint='Maximum capacity from Settings, not the current charge. Enter 1–100% or Not verified.'),q('carrier','Carrier lock',['Unlocked','Carrier locked',UNKNOWN]),q('activation_lock','Activation / account lock',['Removed','Still locked',UNKNOWN])]+common
    fields={'Laptop':['processor','memory','storage','screen','battery'],'Tablet':['storage','battery'],'Computer':['processor','memory','storage'],'Monitor':['screen','resolution','pixel_test'],'Clothing':['size','material'],'Shoes':['size','material'],'Furniture':['dimensions','material'],'Vehicle':['year','mileage']}.get(item.get('category'),['dimensions','material'])
    return [q(k,k.replace('_',' ').capitalize()) for k in fields]+common

def save_answers(item,answers):
    if item.get('status') in ['sold','sale_pending']:raise ValueError('This item cannot be assessed while its sale is completed or pending.')
    if not isinstance(answers,dict):raise ValueError('Answers must be an object.')
    schema={q['key']:q for q in questions(item)}
    if set(answers)-set(schema):raise ValueError('Unsupported assessment question.')
    clean={}
    for key,value in answers.items():
        if not isinstance(value,str) or len(value)>250:raise ValueError('Answers must be text of at most 250 characters.')
        value=value.strip() or UNKNOWN
        if schema[key]['options'] and value not in schema[key]['options']:raise ValueError('Choose a supported answer for '+key+'.')
        if key=='battery' and item.get('category')=='Phone' and value!=UNKNOWN:
            if not re.fullmatch(r'(?:[1-9]|[1-9][0-9]|100)%?',value):raise ValueError('Battery health must be 1–100%, or Not verified.')
            value=value.rstrip('%')+'%'
        clean[key]=value
    specs={**item.get('specs',{})}
    for key,value in clean.items():
        if key!='condition':specs[key]=value
    if 'condition' in clean:
        item['condition']=clean['condition']
        if 'condition' in specs:specs['condition']=clean['condition']
    item.update(specs=specs,confirmed=False,assessment_answers={**item.get('assessment_answers',{}),**clean},assessment_at=store.now())
    # A separate draft uses only recorded facts, with missing checks made explicit.
    facts=[f'{key.replace("_"," ").capitalize()}: {value}' for key,value in specs.items() if value and value!=UNKNOWN and key not in ['condition','camera']]
    item['listing_suggestion']={'description':item['title']+'. '+'. '.join(facts)+'. '+('Cosmetic condition: '+item['condition']+'. ' if item['condition']!=UNKNOWN else '')+('Unverified details: '+', '.join(uncertainties(item))+'. ' if uncertainties(item) else '')+'Please ask about any details still marked as unverified.','created_at':store.now()}
    import outcomes
    outcomes.invalidate(item['id'])
    return store.put('items',item)

def uncertainties(item):
    import research
    fields=['storage','battery','carrier','working','repairs','activation_lock'] if item.get('category')=='Phone' else ['working','repairs']
    missing=[key for key in fields if research.unknown(item.get('specs',{}).get(key))]
    if research.unknown(item.get('condition')):missing.append('condition')
    return missing

def reference(item,report):
    """Describe thin/other-condition evidence without promoting it to verified valuation."""
    from collections import defaultdict
    from statistics import median
    rows=[r for r in report['rows'] if r.get('source') in ['verified_web','verified_api'] and r.get('comparison_price') and (r.get('included') or r.get('exclusion_reason') in ['Refurbished retail and used inventory are separate condition classes.','Source colour differs; reference only.'])]
    pages=defaultdict(list)
    for row in rows:
        # Variant offers from one product page share one vote.
        pages[row['url'].split('?')[0]].append(row)
    if not pages:return None
    observations=[];representative=[]
    for group in pages.values():
        grade=item.get('condition','').casefold()
        same=[r for r in group if grade in str(r.get('source_grade','')).casefold()] if grade not in ['not verified','unknown',''] else []
        chosen=same or group
        observations.extend(chosen);representative.append(median([r['comparison_price'] for r in chosen]))
    if len(representative)>=3 and (item.get('category')!='Phone' or 'storage' not in uncertainties(item)):
        center=median(representative);mad=median([abs(v-center) for v in representative]);width=max(center*.35,3.5*1.4826*mad)
        keep={url for (url,_),value in zip(pages.items(),representative) if abs(value-center)<=width}
        observations=[r for r in observations if r['url'].split('?')[0] in keep]
        pages={url:group for url,group in pages.items() if url in keep}
    values=[r['comparison_price'] for r in observations]
    missing=uncertainties(item)
    sellers={str(r['source_name']).removeprefix('www.') for r in observations}
    other=any(r.get('condition')=='Refurbished' and item.get('condition')!='Refurbished' for r in observations)
    battery=item.get('specs',{}).get('battery','')
    low_battery=bool(re.fullmatch(r'\d+%',battery)) and int(battery.rstrip('%'))<80
    blockers=item.get('specs',{}).get('working')=='No' or item.get('specs',{}).get('activation_lock')=='Still locked' or low_battery
    ready=not blockers and len(pages)>=2 and len(sellers)>=2 and not any(k in missing for k in ['storage','condition','working','carrier','activation_lock','battery','repairs']) and report['match_level']=='exact'
    return dict(low=min(values),high=max(values),median=round(median(values),2),pages=len(pages),sellers=len(sellers),missing=missing,retail_refurbished=other,confidence='Preliminary',suggested_price=round(min(median([r['comparison_price'] for r in observations if str(r['source_name']).removeprefix('www.')==seller]) for seller in sellers),2) if ready else None,label='Current source asking prices; a preliminary reference, not confirmed sale values.',explanation='Draft starts at the lower merchant median. Refurbished retail may include warranty, service and battery guarantees that your item does not have. No invented battery or repair discount is applied.' if other else 'Draft starts at the lower merchant median. No invented battery or repair discount is applied.',blocked_reason='Faults, activation lock or battery health below 80% need suitable source offers or an actual repair quote before suggesting a draft price.' if blockers else None)

def apply_draft_price(item_id,job):
    import ebay,research,pricing,outcomes
    @ebay.serialized
    def apply():
        item=store.get('items',item_id)
        if not item or item.get('price',0)>0 or item.get('status')!='draft' or job.get('market','US')!='US' or job.get('mode','exact')!='exact' or research.fingerprint(item)!=job['item_fingerprint']:return
        report=pricing.comparables(item)
        ref=report.get('preliminary')
        selected=next((s['price'] for s in pricing.evaluate(item)['strategies'] if s['id']=='balanced'),None)
        price=selected or (ref or {}).get('suggested_price')
        if not price:return
        floor=max(item.get('reserve',0),item.get('cost',0)/(1-item.get('fee_rate',0)))
        if price<floor or price>100000:return
        item.update(price=price,price_assessment={'research_id':job['id'],'basis':'Observed market median' if selected else 'Preliminary merchant reference','preliminary':not bool(selected),'missing':uncertainties(item),'created_at':store.now()})
        outcomes.invalidate(item_id);store.put('items',item)
        store.event(item_id,'price_change',before=0,after=price,model_source='verified_sources_preliminary' if not selected else 'observed_asking_prices')
    apply()
