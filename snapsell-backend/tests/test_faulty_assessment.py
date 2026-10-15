import json
import pytest
from test_research import isolated,item,seller,store,research,pricing,app,document
import assessment,assessment_questions,faults,channels,commerce

def phone(item,**specs):
 return store.put('items',{**item,'category':'Phone','title':'Apple iPhone 16','brand':'Apple','model_key':'iphone-16','status':'draft','confirmed':False,'price':0,'condition':'Good','specs':{'storage':'256GB','working':'No','fault_type':'Screen / display','fault_details':'Screen cracked but turns on','carrier':'Unlocked','activation_lock':'Removed',**specs}})

def put_fault_offer(unit,index=0,price=220,fault='Cracked screen',seller_id=None):
 name='Apple iPhone 16 256GB Unlocked '+fault
 product={'@type':'Product','name':name,'brand':{'name':'Apple'},'description':'Whole phone sold for repair. '+fault,'offers':{'@type':'Offer','price':price,'priceCurrency':'USD','availability':'https://schema.org/InStock','itemCondition':'https://schema.org/DamagedCondition'}}
 doc={'url':f'https://merchant{index}.example/products/phone','text':'<script type="application/ld+json">'+json.dumps(product)+'</script>','sha256':'fixture-proof','fetched_at':store.now()}
 rows,_=research.parse_offers(doc,unit)
 assert rows
 row={**rows[0],'id':'offer'+str(index),'item_id':unit['id'],'item_fingerprint':research.fingerprint(unit)}
 if seller_id:row.update(source='verified_api',source_name='eBay',seller_id=seller_id)
 store.put('comparables',row)
 return row

def test_faulty_whole_unit_prices_can_fill_a_listing(item,seller):
 unit=phone(item)
 for n,p in enumerate([200,220,240]):put_fault_offer(unit,n,p)
 report=pricing.comparables(unit)
 assert report['available'] and report['preliminary']['suggested_price'] is not None
 job=store.put('jobs',{'id':'fault-job','type':'market_research','item_id':unit['id'],'market':'US','mode':'exact','status':'completed','item_fingerprint':research.fingerprint(unit)})
 reply=seller.post('/api/items/'+unit['id']+'/assessment/price',json={'research_id':job['id']})
 assert reply.status_code==200 and reply.json['price']>0 and reply.json['specs']['working']=='No'
 assert not reply.json['confirmed']

def test_fault_profile_is_not_a_blanket_sales_ban(item):
 unit=phone(item);put_fault_offer(unit);put_fault_offer(unit,1,230)
 ref=pricing.comparables(unit)['preliminary']
 assert ref['suggested_price'] is not None and not ref['blocked_reason']
 assert 'battery' in ref['missing']

def test_repaired_and_working_is_not_still_broken(item):
 unit=phone(item,working='Yes',repairs='Repaired / parts replaced',repair_details='Display replaced',fault_type='None',fault_details='None')
 assert not faults.profile(unit)['faulty']
 assert research.model_match(unit,'Used Apple iPhone 16 256GB Unlocked','Good')[0]
 assert not research.model_match(unit,'Apple iPhone 16 256GB Unlocked Cracked screen')[0]
 q={q['key']:q for q in assessment.questions(unit)}
 assert 'after repair' in q['working']['option_labels']['Yes'] and q['repair_details']['visible_if']

@pytest.mark.parametrize('name',['Apple iPhone 16 256GB Unlocked water damaged','Apple iPhone 16 256GB Unlocked does not power on','Apple iPhone 16 replacement screen','Apple iPhone 16 screen replacement repair service'])
def test_different_fault_or_part_cannot_value_cracked_whole_phone(item,name):
 assert not research.model_match(phone(item),name)[0]

@pytest.mark.parametrize('market,term',[('US','for parts'),('KZ','неисправный'),('JP','ジャンク'),('CN','故障')])
def test_fault_queries_include_disclosed_problem_and_country(item,market,term):
 unit=phone(item);unit['_research_market']=market
 queries,_=research.plan(unit)
 assert term in queries[0] and '256GB' in queries[0]
 assert not any('refurbished inurl' in q for q in queries)

def test_unknown_fault_can_collect_references_but_needs_diagnosis_for_single_price(item):
 unit=phone(item,fault_type='Not verified',fault_details='Not verified')
 put_fault_offer(unit);put_fault_offer(unit,1,230)
 ref=pricing.comparables(unit)['preliminary']
 assert ref and ref['suggested_price'] is None and ref['blocked_reason']

def test_api_sellers_count_independently(item):
 unit=phone(item);put_fault_offer(unit,seller_id='ebay:a');put_fault_offer(unit,1,230,seller_id='ebay:b')
 assert pricing.comparables(unit)['preliminary']['sellers']==2
 assert pricing.comparables(unit)['preliminary']['suggested_price'] is not None

def test_faulty_listing_kit_discloses_damage_and_is_exportable(item):
 unit=phone(item);unit.update(confirmed=True,price=200)
 kit,_=channels.prepare(unit,'facebook')
 assert kit['price_usd']==200 and 'For repair:' in kit['title'] and 'FAULTY' in kit['description']
 assert kit['fault_profile']['faulty']
 assert commerce.public_item(unit)['condition']=='For parts / not working'
 assert not any('fault' in m.lower() for m in kit['missing'])

def test_clothes_and_books_do_not_get_phone_questions(item):
 for category in ['Clothing','Books','Furniture']:
  unit={**item,'category':category}
  keys={q['key'] for q in assessment.questions(unit)}
  assert not keys & {'battery','carrier','working','activation_lock'}
  assert 'fault_details' in keys

def test_question_tool_only_prefills_existing_recorded_fact(item):
 unit={**item,'specs':{'material':'Oak'}}
 args={'questions':[{'key':'material','label':'What wood is it?','source_field':'specs.material','value':'Gold','hint':'Check label'}]}
 prepared=assessment_questions.set_assessment_questions(unit,args)
 store.put('actions',{'id':'assessment-questions:'+assessment_questions.version(unit),'status':'completed','questions':prepared})
 q=next(q for q in assessment.questions(unit) if q['key']=='material')
 assert q['value']=='Oak' and 'Gold' not in str(q)

@pytest.mark.parametrize('row',[{'key':'price','label':'Set a price'},{'key':'test','label':'A question','source_field':'specs.storage'},{'key':'__proto__','label':'A question'},{'key':'email','label':'Seller email'}])
def test_question_tool_rejects_unsafe_fields_and_cross_field_answers(item,row):
 with pytest.raises(ValueError):assessment_questions.set_assessment_questions(item,{'questions':[row]})

def test_ai_tool_generates_different_questions_and_records_model(item,monkeypatch):
 monkeypatch.setattr(assessment_questions.amd,'configured',lambda:True)
 for category,key,label in [('Books','printing','Which printing is this?'),('Furniture','wood_finish','What is the finish?')]:
  unit=store.put('items',{**item,'category':category,'specs':{key:'Recorded only'}})
  record=store.put('actions',{'id':'assessment-questions:'+assessment_questions.version(unit),'version':assessment_questions.version(unit),'status':'processing'})
  def generated(role,system,content,budget):
   assert 'set_assessment_questions' in system and category in content
   return {'tool':'set_assessment_questions','arguments':{'questions':[{'key':key,'label':label,'source_field':'specs.'+key}]}},'mock-amd-model'
  monkeypatch.setattr(assessment_questions.amd,'json_response',generated)
  assessment_questions.run(unit['id'],record['id'])
  saved=assessment_questions.current(unit)
  assert saved['status']=='completed' and saved['model']=='mock-amd-model'
  assert next(q for q in assessment.questions(unit) if q['key']==key)['value']=='Recorded only'

def test_provider_failure_leaves_category_questions_usable(item,monkeypatch):
 record=store.put('actions',{'id':'assessment-questions:'+assessment_questions.version(item),'version':assessment_questions.version(item),'status':'processing'})
 monkeypatch.setattr(assessment_questions.amd,'json_response',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Provider unavailable')))
 assessment_questions.run(item['id'],record['id'])
 assert assessment_questions.current(item)['status']=='fallback'
 assert assessment.questions(item)

def test_apply_price_rejects_stale_research_and_keeps_existing_price(item,seller):
 unit=phone(item);put_fault_offer(unit);put_fault_offer(unit,1,230)
 job=store.put('jobs',{'id':'old-result','type':'market_research','item_id':unit['id'],'status':'completed','market':'US','mode':'exact','item_fingerprint':'stale'})
 reply=seller.post('/api/items/'+unit['id']+'/assessment/price',json={'research_id':job['id']})
 assert reply.status_code==400 and store.get('items',unit['id'])['price']==0
 unit['price']=190;store.put('items',unit)
 reply=seller.post('/api/items/'+unit['id']+'/assessment/price',json={'research_id':job['id']})
 assert reply.status_code==400 and store.get('items',unit['id'])['price']==190

def test_browse_requests_non_working_inventory_and_matches_fault(item,monkeypatch):
 import browse
 unit=phone(item)
 calls=[]
 def request(path,params=None):
  calls.append((path,params))
  if path.endswith('search'):return {'itemSummaries':[{'itemId':'123'}]}
  return {'title':'Apple iPhone 16 256GB Unlocked Cracked screen','condition':'For parts or not working','shortDescription':'Whole handset, cracked screen','itemWebUrl':'https://www.ebay.com/itm/1234567890','estimatedAvailabilities':[{'estimatedAvailabilityStatus':'IN_STOCK'}],'itemLocation':{'country':'US'},'price':{'currency':'USD','value':'200'},'seller':{'username':'seller-a'}}
 monkeypatch.setattr(browse,'request',request)
 rows,_=browse.collect(unit)
 assert 'conditionIds:{7000}' in calls[0][1]['filter'] and 'screen' in calls[0][1]['q'].casefold()
 assert rows and rows[0]['price']==200 and rows[0]['condition']=='Damaged / faulty'

def test_specific_ai_test_answer_can_reveal_fault(item):
 unit=phone(item,working='Yes',fault_type='None',fault_details='None',face_id_status='Does not work')
 assert 'Face ID / fingerprint' in faults.profile(unit)['types']
 assert not research.model_match(unit,'Used Apple iPhone 16 256GB Unlocked','Fully working')[0]

def test_ai_wrong_phone_generation_is_discarded(item):
 unit=phone(item)
 wrong={'key':'exact_model_variant','label':'Which iPhone 13 model?','options':['iPhone 13','iPhone 13 Pro']}
 good={'key':'face_id_status','label':'Does Face ID work?','options':['Yes','No']}
 result=assessment_questions.set_assessment_questions(unit,{'questions':[wrong,good]})
 assert [q['key'] for q in result]==['face_id_status']
 with pytest.raises(ValueError):assessment_questions.set_assessment_questions(unit,{'questions':[wrong]})

def test_ai_hint_is_not_a_diagnostic_claim(item):
 unit=phone(item)
 result=assessment_questions.set_assessment_questions(unit,{'questions':[{'key':'screen_original','label':'Is the display original?','hint':'If missing, it is likely replaced'}]})
 assert 'likely' not in result[0]['hint'] and 'Not verified' in result[0]['hint']


def test_whole_phone_needing_repair_is_not_rejected_as_a_service(item):
 unit=phone(item)
 assert research.model_match(unit,'Apple iPhone 16 256GB Unlocked needs screen replacement','Whole phone, cracked screen')[0]
 assert not research.model_match(unit,'Apple iPhone 16 256GB Unlocked cracked screen mail in repair service')[0]


def test_ai_does_not_repeat_core_questions_under_aliases(item):
 unit=phone(item)
 rows=[{'key':'fault_description','label':'Describe the current fault'}, {'key':'accessories_included','label':'What accessories are included?'}, {'key':'repair_history','label':'Has it ever been repaired?'}, {'key':'model_variant','label':'Which exact iPhone 16 variant is this?'}, {'key':'face_id_status','label':'Does Face ID work?','options':['Yes','No']}]
 result=assessment_questions.set_assessment_questions(unit,{'questions':rows})
 assert [r['key'] for r in result]==['face_id_status']
