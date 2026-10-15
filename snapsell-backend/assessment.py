"""Seller questions and auditable draft prices; never infer facts about a physical unit."""
import re
from uuid import uuid4
import store

UNKNOWN='Not verified'

def questions(item):
    import assessment_questions
    specs=item.get('specs',{})
    def q(key,label,options=None,hint='',**extra):
        value=item.get('condition') if key=='condition' else specs.get(key,'')
        if key=='condition' and item.get('source')=='video' and not item.get('assessment_answers'):value=UNKNOWN
        if options and value not in options:value=UNKNOWN
        if key=='battery' and item.get('category')=='Phone' and not re.fullmatch(r'(?:[1-9]|[1-9][0-9]|100)%?',str(value or '')):value=UNKNOWN
        return dict(key=key,label=label,options=options or [],hint=hint,value=value or UNKNOWN,**extra)
    electronic=item.get('category') in ['Phone','Laptop','Tablet','Computer','Monitor','Audio','Camera','Gaming','Electronics','Appliance','Vehicle','Tools']
    common=[q('condition','Cosmetic condition',['Like new','Excellent','Good','Fair','Refurbished','For parts / not working',UNKNOWN]),q('included','What is included?',hint='List the actual included accessories or parts, or leave unverified.')]
    if electronic:
        common.insert(1,q('working','Current working status',['Yes','No',UNKNOWN],hint='Choose Yes if it works now, including after a successful repair.',option_labels={'Yes':'Yes — works now (also after repair)','No':'No — faulty / not fully working',UNKNOWN:'Not verified — not tested'}))
        common += [q('repairs','Repair history',['None','Repaired / parts replaced',UNKNOWN]),q('repair_details','What was repaired or replaced?',visible_if={'repairs':['Repaired / parts replaced']},multiline=True)]
    import faults
    applicable_faults=[v for v in faults.FAULT_TYPES if v not in ['Tear / stain','Missing pages / damage','Structural damage','Damage / missing parts']] if electronic else {'Clothing':['Tear / stain','Other',UNKNOWN],'Shoes':['Tear / stain','Other',UNKNOWN],'Books':['Missing pages / damage','Other',UNKNOWN],'Furniture':['Structural damage','Other',UNKNOWN]}.get(item.get('category'),['Damage / missing parts','Other',UNKNOWN])
    common += [q('fault_type','Current damage / fault type',['None',*applicable_faults],hint='Choose None if all previous faults were repaired. Cosmetic condition and current function are separate.'),q('fault_details','Describe the current fault or damage',hint='For example: screen cracked but turns on, charging port broken, or does not power on. Do not describe a repaired fault as still present.',multiline=True,visible_if_any={'working':['No'],'fault_type':[v for v in applicable_faults if v!=UNKNOWN]})]
    if item.get('category')=='Phone':
        base=[q('storage','Storage capacity',['64GB','128GB','256GB','512GB','1TB',UNKNOWN]),q('battery','Battery health (%)',hint='Maximum capacity from Settings, not current charge. Unknown is allowed; a faulty phone does not require a working battery to be sold.'),q('carrier','Carrier lock',['Unlocked','Carrier locked',UNKNOWN]),q('activation_lock','Activation / account lock',['Removed','Still locked',UNKNOWN])]+common
    else:
        fields={'Laptop':['processor','memory','storage','screen','battery'],'Tablet':['storage','battery'],'Computer':['processor','memory','storage'],'Monitor':['screen','resolution','pixel_test'],'Clothing':['size','material'],'Shoes':['size','material'],'Furniture':['dimensions','material'],'Books':['isbn','edition','language'],'Vehicle':['year','mileage']}.get(item.get('category'),[])
        base=[q(k,k.replace('_',' ').capitalize()) for k in fields]+common
    record=assessment_questions.current(item)
    if record and record.get('status')=='completed':
        existing={v['key'] for v in base}
        for generated in record.get('questions',[]):
            if generated['key'] in existing:continue
            field={k:v for k,v in generated.items() if k not in ['value','source_field']}
            base.append(q(**field));existing.add(generated['key'])
    return base[:20]

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
    if clean.get('fault_type')=='None':specs['fault_details']='None'
    if len(specs)>30:raise ValueError('At most 30 recorded specifications are supported.')
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
    present={q['key'] for q in questions(item)}
    fields=['storage','battery','carrier','working','repairs','activation_lock'] if item.get('category')=='Phone' else [k for k in ['working','repairs'] if k in present]
    missing=[key for key in fields if research.unknown(item.get('specs',{}).get(key))]
    if research.unknown(item.get('condition')):missing.append('condition')
    return missing

def reference(item,report):
    """Describe thin/other-condition evidence without promoting it to verified valuation."""
    from collections import defaultdict
    from statistics import median
    rows=[r for r in report['rows'] if r.get('source') in ['verified_web','verified_api'] and r.get('comparison_price') and (r.get('included') or r.get('exclusion_reason') in ['Refurbished retail and used inventory are separate condition classes.','Source colour differs; reference only.'])]
    import faults
    rows=[r for r in rows if faults.match(item,r.get('title',''),str(r.get('evidence',{}).get('description',r.get('evidence',{}).get('description_quote',''))))[0]]
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
    def seller(row):return row.get('seller_id') or str(row['source_name']).removeprefix('www.')
    sellers={seller(r) for r in observations}
    other=any(r.get('condition')=='Refurbished' and item.get('condition')!='Refurbished' for r in observations)
    import faults
    profile=faults.profile(item)
    fault_unknown=profile['faulty'] and not profile['types']
    blockers=fault_unknown
    critical=['storage','working'] if item.get('category')=='Phone' else ['condition']
    ready=not blockers and len(pages)>=2 and len(sellers)>=2 and not any(k in missing for k in critical) and report['match_level']=='exact'
    reason='Choose the current fault type or describe the fault to obtain a targeted damaged-item price.' if fault_unknown else None
    return dict(low=min(values),high=max(values),median=round(median(values),2),pages=len(pages),sellers=len(sellers),missing=missing,retail_refurbished=other,confidence='Preliminary',suggested_price=round(min(median([r['comparison_price'] for r in observations if seller(r)==merchant]) for merchant in sellers),2) if ready else None,label='Current source asking prices; a preliminary reference, not confirmed sale values.',explanation='Draft starts at the lower merchant median. Refurbished retail may include warranty, service and battery guarantees that your item does not have. No invented battery or repair discount is applied.' if other else 'Draft starts at the lower merchant median. No invented battery or repair discount is applied.',fault_profile=profile,blocked_reason=reason)

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
        return item
    return apply()
