"""Keep unit faults, repair history and source condition separate."""
import re

FAULT_TYPES=['Screen / display','Back glass / housing','Battery','Does not power on','Water damage','Camera','Charging','Face ID / fingerprint','Activation locked','Tear / stain','Missing pages / damage','Structural damage','Damage / missing parts','Other','Not verified']
PATTERNS={
 'Face ID / fingerprint':r'face id (?:not working|broken|fault|does not work)|(?:broken|faulty) face id|fingerprint (?:not working|broken)|face id не работает',
 'Activation locked':r'icloud locked|activation locked|frp locked|заблокирован.{0,10}icloud|アクティベーションロック|激活锁',
 'Tear / stain':r'\b(?:torn|stained|ripped)\b|пятн|порван',
 'Missing pages / damage':r'missing pages|torn pages|нет страниц|вырваны страницы',
 'Structural damage':r'broken leg|broken frame|structural damage|сломана ножка|сломан каркас',
 'Damage / missing parts':r'missing parts|incomplete unit|не хватает деталей',
 'Screen / display':r'(?:broken|cracked|damaged|bad|dead) (?:screen|display|lcd)|(?:screen|display|lcd) (?:broken|cracked|damaged|not working)|разбит.{0,15}экран|画面割|液晶割|碎屏',
 'Back glass / housing':r'(?:back|rear) (?:glass )?(?:cracked|broken|damaged)|(?:cracked|broken) (?:back|rear|housing)|разбит.{0,15}(?:задн|корпус)',
 'Battery':r'(?:bad|dead|faulty|degraded|swollen) battery|battery (?:fault|issue|dead|swollen|degraded)|battery health.{0,8}(?:[1-6][0-9]|7[0-9])%|батаре.{0,10}(?:взду|не держ)|аккумулятор.{0,10}(?:взду|не держ)',
 'Does not power on':r'does(?:n.t| not) (?:power|turn|switch) on|dead motherboard|motherboard is dead|damaged logic board|won.t (?:power|turn) on|no power|не включа|起動不可|不开机',
 'Water damage':r'water damaged?|liquid damaged?|утоплен|попала вода|水没|进水',
 'Camera':r'(?:broken|faulty|dead) camera|camera (?:fault|not working|broken)|камера не работа',
 'Charging':r'(?:not|won.t|doesn.t) charg|charging (?:fault|issue|port broken)|не заряжа',
}
BROAD=r'for parts|parts only|not working|non[- ]?functional|defective|faulty|broken|damaged|cracked|for repair|as[- ]is|на запчасти|не работает|неисправ|ジャンク|故障|坏了'

def source(name,description=''):
    # Ignore explicitly negated damage claims and repair guides, not seller disclosures.
    text=(str(name)+' '+str(description)[:2000]).casefold()
    text=re.sub(r'\b(?:no|not|without) (?:cracks?|damage|defects?|faults?)\b','',text)
    kinds=[kind for kind,pattern in PATTERNS.items() if re.search(pattern,text)]
    return {'faulty':bool(kinds or re.search(BROAD,text)),'types':kinds}

def profile(item):
    s=item.get('specs',{});kind=s.get('fault_type','Not verified')
    details=s.get('fault_details','')
    extra=' '.join(str(s.get(k,'')) for k in ['physical_damage','damage_description','condition_details'])
    inferred=source('',details+' '+extra)['types'] if kind!='None' else []
    for key,value in s.items():
        value=str(value).casefold()
        if 'face_id' in key and (value=='no' or re.search(r'does not work|not working|broken|faulty',value)):inferred.append('Face ID / fingerprint')
        if 'camera' in key and (value=='no' or re.search(r'only works|no cameras|does not work|not working|broken',value)):inferred.append('Camera')
    if s.get('water_damage_indicators')=='Confirmed':inferred.append('Water damage')
    battery=str(s.get('battery',''))
    low=bool(re.fullmatch(r'\d+%',battery)) and int(battery[:-1])<80
    if kind not in FAULT_TYPES:kind='Not verified'
    types=list(dict.fromkeys(([kind] if kind not in ['Not verified','Other','None'] else [])+inferred))
    if low and 'Battery' not in types:types.append('Battery')
    if s.get('activation_lock')=='Still locked' and 'Activation locked' not in types:types.append('Activation locked')
    faulty=s.get('working')=='No' or bool(types) or (kind!='None' and source('',details)['faulty']) or item.get('condition')=='For parts / not working'
    return {'faulty':faulty,'types':types,'details':details,'working':s.get('working','Not verified'),'repair_history':s.get('repairs','Not verified')}

def match(item,name,description=''):
    target=profile(item);observed=source(name,description)
    if target['faulty']:
        if not observed['faulty']:return False,'A faulty unit requires an explicitly faulty source offer, not a working/refurbished unit.'
        if target['types'] and not set(target['types']).issubset(observed['types']):return False,'The disclosed fault type is not confirmed on the source offer.'
    elif observed['faulty']:return False,'Faulty units are separate from working-unit comparisons.'
    return True,'Disclosed fault profile matched.' if target['faulty'] else 'No source fault disclosed.'

def terms(item,market='US'):
    p=profile(item)
    if not p['faulty']:return ''
    generic={'US':'for parts','KZ':'неисправный','JP':'ジャンク 故障','CN':'故障 维修 二手'}[market]
    localized={
      'US':{'Screen / display':'cracked screen','Back glass / housing':'cracked back glass','Battery':'bad battery','Does not power on':'does not power on','Water damage':'water damaged','Camera':'camera not working','Charging':'charging fault','Face ID / fingerprint':'Face ID not working','Activation locked':'activation locked'},
      'KZ':{'Screen / display':'разбит экран','Battery':'неисправная батарея','Does not power on':'не включается','Water damage':'после воды'},
      'JP':{'Screen / display':'画面割れ','Battery':'バッテリー不良','Does not power on':'起動不可','Water damage':'水没'},
      'CN':{'Screen / display':'碎屏','Battery':'电池故障','Does not power on':'不开机','Water damage':'进水'},
    }
    return generic+' '+' '.join(localized.get(market,{}).get(t,t) for t in p['types'])
