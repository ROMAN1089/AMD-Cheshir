import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from test_research import isolated,item,seller
import amd,store,commerce,compute,video,research

@pytest.fixture(autouse=True)
def provider_isolation(monkeypatch):
    monkeypatch.setattr(amd,'settings',lambda:('isolated-test-key','https://provider.invalid'))
    monkeypatch.setattr(amd,'_account_identity',lambda:'isolated-account')
    monkeypatch.setattr(amd,'dotenv_values',lambda *args:{})
    monkeypatch.setattr(amd,'_last',0)
    monkeypatch.setattr(amd,'_cooldown',0)
    amd._intent_cache.clear()
    for role in ['VISION','CHAT','AUDIO','INTENT']:monkeypatch.delenv('AMD_'+role+'_MODEL',raising=False)

class Response:
    def __init__(self,status=200,headers=None,data=None,text=''):
        self.status_code=status;self.ok=status==200;self.headers=headers or {};self.text=text;self.data=data or {'ok':True}
    def json(self):return self.data

def test_long_inference_does_not_own_the_entire_gateway(monkeypatch):
    entered=threading.Event();release=threading.Event()
    monkeypatch.setattr(amd,'_pace',lambda:None)
    def transport(method,url,**kwargs):
        if kwargs['json']['work']=='long':
            entered.set();assert release.wait(3)
        return Response()
    monkeypatch.setattr(amd,'_transport',transport)
    with ThreadPoolExecutor(max_workers=2) as executor:
        slow=executor.submit(amd.request,'POST','/chat/completions',{'work':'long'})
        assert entered.wait(2)
        try:assert executor.submit(amd.request,'POST','/chat/completions',{'work':'short'}).result(timeout=1)=={'ok':True}
        finally:release.set()
        assert slow.result(timeout=2)=={'ok':True}

def test_request_starts_are_paced_and_shared_retry_after_is_honored(monkeypatch):
    clock=[100.0];starts=[]
    monkeypatch.setattr(amd,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    responses=iter([Response(429,{'Retry-After':'10'}),Response(),Response()])
    def transport(*args,**kwargs):starts.append(clock[0]);return next(responses)
    monkeypatch.setattr(amd,'_transport',transport)
    assert amd.request('GET','/models')=={'ok':True}
    assert amd.request('GET','/models')=={'ok':True}
    assert starts[1]-starts[0]>=10 and starts[2]-starts[1]>=3.19

def test_no_retry_for_invalid_key(monkeypatch):
    calls=[];monkeypatch.setattr(amd,'_pace',lambda:None)
    monkeypatch.setattr(amd,'_transport',lambda *args,**kwargs:calls.append(1) or Response(401))
    with pytest.raises(amd.ProviderError):amd.request('GET','/models')
    assert len(calls)==1

def test_interactive_task_does_not_wait_out_a_shared_quota_cooldown(monkeypatch):
    monkeypatch.setattr(amd,'_cooldown',amd.time.monotonic()+60)
    monkeypatch.setattr(amd,'_transport',lambda *args,**kwargs:pytest.fail('No request is allowed during the shared cooldown.'))
    with pytest.raises(RuntimeError,match='busy or rate limited'):amd.request('POST','/chat/completions',{},read_timeout=8)

def test_live_catalog_capabilities_guard_model_routing(monkeypatch):
    monkeypatch.setattr(amd,'catalog',lambda **kwargs:{'data':[{'id':'Qwen3.8-Flash-Next','architecture':{'input_modalities':['text']}},{'id':'MiMo-V2.6-Flash','architecture':{'input_modalities':['text','image']}},{'id':'MiniCPM5-2B','architecture':{'input_modalities':['text']}}]})
    assert amd.select('vision')=='MiMo-V2.6-Flash'
    assert amd.select('intent')=='MiniCPM5-2B'
    with pytest.raises(RuntimeError):amd.select('audio')

@pytest.mark.parametrize('status',[500,504])
def test_vision_timeout_uses_one_image_capable_fallback(monkeypatch,status):
    monkeypatch.setattr(amd,'select',lambda role:'Qwen3.8-Flash-Next')
    monkeypatch.setattr(amd,'catalog',lambda **kwargs:{'data':[{'id':'Qwen3.8-Flash-Next','architecture':{'input_modalities':['text','image']}},{'id':'DeepSeek-V4.1-Flash','architecture':{'input_modalities':['text','image']}}]})
    calls=[]
    def response(method,path,payload,**kwargs):
        calls.append(payload['model'])
        if len(calls)==1:raise amd.ProviderError('Provider failed',status)
        return {'choices':[{'message':{'content':'{"items":[]}'}}],'usage':{'prompt_tokens':10,'completion_tokens':4}}
    monkeypatch.setattr(amd,'request',response)
    value,model=amd.json_response('vision','Extract physical products',[])
    assert value=={'items':[]} and model=='DeepSeek-V4.1-Flash' and len(calls)==2
    assert store.all_rows('actions')[-1]['fallback_from']=='Qwen3.8-Flash-Next'

def test_rate_limits_do_not_trigger_a_model_hopping_retry(monkeypatch):
    monkeypatch.setattr(amd,'select',lambda role:'Qwen3.8-Flash-Next')
    monkeypatch.setattr(amd,'request',lambda *args,**kwargs:(_ for _ in ()).throw(amd.ProviderError('Team quota',429)))
    with pytest.raises(amd.ProviderError):amd.json_response('vision','Extract products',[])
    assert len(store.all_rows('actions'))==1

def test_intent_cache_reuses_classification_but_never_product_facts(item,monkeypatch):
    monkeypatch.setattr(amd,'configured',lambda:True)
    monkeypatch.setattr(amd,'select',lambda role:'small-model')
    calls=[]
    def infer(*args):calls.append(args);return {'intents':['battery']},'small-model'
    monkeypatch.setattr(amd,'json_response',infer)
    first=commerce.reply({**item,'specs':{'battery':'87%'}},'What is the battery health?')
    second=commerce.reply({**item,'specs':{'battery':'93%'}},'What is the battery health?')
    assert '87%' in first['answer'] and '93%' in second['answer']
    assert len(calls)==1 and calls[0][0]=='intent' and calls[0][3]==256
    assert len([a for a in store.all_rows('actions') if a.get('type')=='inference_cache'])==1
    monkeypatch.setattr(amd,'_account_identity',lambda:'other-key')
    amd.classify('What is the battery health?');assert len(calls)==2

def test_invalid_intents_never_enter_cache(monkeypatch):
    monkeypatch.setattr(amd,'select',lambda role:'small-model')
    monkeypatch.setattr(amd,'json_response',lambda *args:({'intents':['send_money']},'small-model'))
    with pytest.raises(RuntimeError):amd.classify('Question')
    assert not amd._intent_cache

def test_no_inference_for_unreviewed_item(item,monkeypatch):
    monkeypatch.setattr(amd,'configured',lambda:True)
    monkeypatch.setattr(amd,'classify',lambda message:pytest.fail('Unreviewed facts should not spend inference quota.'))
    assert 'seller review' in commerce.reply({**item,'confirmed':False},'Battery?')['answer']

def test_small_model_cannot_drop_an_explicit_battery_question(item,monkeypatch):
    monkeypatch.setattr(amd,'configured',lambda:True)
    monkeypatch.setattr(amd,'classify',lambda message:(['included','specs'],'small-model'))
    result=commerce.reply({**item,'specs':{'battery':'87%','included':'Original charger'}},'Is the charger included and is the battery health known?')
    assert 'battery' in result['intents'] and '87%' in result['answer'] and 'Original charger' in result['answer']

def test_invalid_structured_response_still_records_actual_reported_tokens(monkeypatch):
    monkeypatch.setattr(amd,'select',lambda role:'test-model')
    monkeypatch.setattr(amd,'request',lambda *args,**kwargs:{'choices':[{'message':{'content':'[1,2]'}}],'usage':{'prompt_tokens':20,'completion_tokens':8}})
    with pytest.raises(RuntimeError):amd.json_response('chat','System','Text')
    call=store.all_rows('actions')[-1]
    assert call['type']=='inference' and call['valid'] is False and call['input_tokens']==20 and call['output_tokens']==8

def test_compute_never_equates_a_key_with_verified_connectivity(seller,monkeypatch):
    monkeypatch.setattr(amd,'configured',lambda:True)
    assert compute.snapshot()['connection']=='configured'
    store.put('actions',{'type':'inference','role':'chat','model':'test-model','latency_ms':100,'input_tokens':10,'output_tokens':2,'at':store.now(),'account_id':'different-key'})
    assert compute.snapshot()['connection']=='configured'
    store.put('actions',{'type':'inference','role':'chat','model':'test-model','latency_ms':100,'input_tokens':10,'output_tokens':2,'at':store.now(),'account_id':'isolated-account'})
    assert seller.get('/api/compute').json['connection']=='verified'
    assert __import__('app').app.test_client().get('/api/compute').status_code==401

def test_only_identical_frames_are_deduplicated_and_temporal_anchors_stay():
    samples=[{'b64':'same','second':index} for index in range(12)]
    assert [row['second'] for row in video.representative_samples(samples)]==[0,6,11]
    samples[4]['b64']='label-changed'
    assert [row['second'] for row in video.representative_samples(samples)]==[0,4,6,11]


def test_exact_research_starts_from_recorded_facts_without_a_planning_call(item,monkeypatch):
    monkeypatch.setattr(amd,'configured',lambda:True)
    monkeypatch.setattr(amd,'json_response',lambda *args:pytest.fail('An exact model already provides search terms.'))
    queries,model=research.plan({**item,'_research_mode':'exact'})
    assert queries and model is None and any('U2720Q' in query for query in queries)

def test_prepared_frames_cannot_read_outside_the_job(monkeypatch,tmp_path):
    monkeypatch.setattr(store,'DATA',tmp_path)
    outside=tmp_path/'private.jpg';outside.write_bytes(b'private')
    expected=([{'url':'safe','second':0}],2)
    monkeypatch.setattr(video,'frames',lambda *args:expected)
    assert video.prepared_frames({'id':'own-job','path':'video.mp4','duration':2,'media_prepared':True,'frames':[{'url':'/media/../private.jpg','second':0}]})==expected

def test_seller_can_recover_a_failed_capture_without_faking_ai_success(seller,tmp_path,monkeypatch):
    from uuid import uuid4
    monkeypatch.setattr(store,'DATA',tmp_path)
    folder=tmp_path/'media'/'failed-capture';folder.mkdir(parents=True)
    (folder/'frame-0.jpg').write_bytes(b'isolated-test-photo')
    store.put('jobs',{'id':'failed-capture','status':'failed','message':'Provider unavailable'})
    assert seller.get('/api/jobs/failed-capture').json['review_frames'][0]['url']=='/media/failed-capture/frame-0.jpg'
    data={'title':'Portable record player','category':'Audio','frame_index':0,'request_id':str(uuid4())}
    response=seller.post('/api/jobs/failed-capture/items',json=data)
    assert response.status_code==201 and response.json['extraction_method']=='seller_selected_frame'
    assert response.json['confirmed'] is False and response.json['price']==0 and response.json['model_key']=='unknown'
    assert seller.post('/api/jobs/failed-capture/items',json=data).json['id']==response.json['id']
    assert len(store.all_rows('items'))==1
    assert store.get('jobs','failed-capture')['status']=='failed'
    assert seller.post('/api/jobs/failed-capture/retry',json={}).status_code==400

def test_seller_cannot_add_a_duplicate_during_running_extraction(seller):
    store.put('jobs',{'id':'running-capture','status':'processing'})
    assert seller.post('/api/jobs/running-capture/items',json={'title':'Chair'}).status_code==400
    assert not store.all_rows('items')

def test_qwen_flash_uses_supported_non_reasoning_mode(monkeypatch):
    monkeypatch.setattr(amd,'select',lambda role:'Qwen3.8-Flash-Next')
    payloads=[]
    def response(method,path,payload,**kwargs):
        payloads.append(payload)
        return {'choices':[{'message':{'content':'{"items":[]}'}}]}
    monkeypatch.setattr(amd,'request',response)
    amd.json_response('vision','Extract observed products',[])
    assert payloads[0]['reasoning_effort']=='none'
