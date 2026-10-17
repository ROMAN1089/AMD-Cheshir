"""Observed AMD execution, never synthetic performance or estimated API spending."""
from statistics import median
import store,amd

def snapshot():
    actions=store.all_rows('actions')
    calls=[a for a in actions if a.get('type')=='inference']
    reuses=[a for a in actions if a.get('type')=='inference_cache']
    failures=[a for a in actions if a.get('type')=='inference_failure']
    recent=calls[-100:]
    roles=[]
    for role in sorted({a['role'] for a in recent}):
        rows=[a for a in recent if a['role']==role]
        roles.append({'role':role,'models':sorted({a['model'] for a in rows}),'calls':len(rows),'median_ms':round(median([a['latency_ms'] for a in rows])),'input_tokens':sum(a.get('input_tokens',0) for a in rows),'output_tokens':sum(a.get('output_tokens',0) for a in rows)})
    videos=[j for j in store.all_rows('jobs') if j.get('vision_model') and j.get('timings')]
    identity=amd._account_identity()
    verified=[a for a in calls if a.get('account_id')==identity and a.get('valid',True)]
    current_failures=[a for a in failures if a.get('account_id')==identity]
    last_success=verified[-1].get('at') if verified else None
    last_failure=current_failures[-1].get('at') if current_failures else None
    state='not_configured' if not amd.configured() else 'needs_attention' if last_failure and (not last_success or last_failure>last_success) else 'verified' if last_success else 'configured'
    return {'configured':amd.configured(),'connection':state,'last_success_at':last_success,'last_failure_at':last_failure,
            'requests':len(calls),'failures':len(failures),'cache_reuses':len(reuses),
            'input_tokens':sum(a.get('input_tokens',0) for a in calls),'output_tokens':sum(a.get('output_tokens',0) for a in calls),
            'reasoning_tokens':sum(a.get('reasoning_tokens',0) for a in calls),
            'median_ms':round(median([a['latency_ms'] for a in recent])) if recent else None,
            'roles':roles,'recent':[{key:a.get(key) for key in ['id','role','model','at','latency_ms','queue_ms','service_ms','retries','input_tokens','output_tokens','reasoning_tokens','payload_bytes','valid']} for a in calls[-12:]],
            'policy':{'max_in_flight':2,'max_vision_in_flight':1,'start_spacing_seconds':3.2,'intent_cache_seconds':900,'intent_output_budget':256,'intent_read_timeout_seconds':8},
            'videos':[{'id':j['id'],'filename':j.get('filename'),'sampled_frames':j.get('sampled_frames'),'vision_frames':j.get('vision_frames'),'vision_image_count':j.get('vision_image_count'),'vision_input_mode':j.get('vision_input_mode'),'vision_payload_bytes':j.get('vision_payload_bytes'),'timings':j['timings'],'vision_model':j['vision_model']} for j in videos[-5:]],
            'note':'Metrics are observed calls from this workspace. Tokens are reported by AMD. Cache reuse is local; source prices are never cached by the intent classifier. Latency includes queue time and is not an isolated GPU benchmark.'}
