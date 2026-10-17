"""Explain which physical-unit attributes source text actually establishes."""
import re

UNKNOWN={'','unknown','not verified','not tested','none','n/a'}
MATCHED_ELSEWHERE={'processor','memory','storage','screen','resolution','refresh_rate','gpu','carrier','size','color','material','working','fault_type','fault_details','condition'}

def audit(item,row):
    evidence=row.get('evidence',{})
    text=' '.join(str(v) for v in [row.get('title',''),evidence.get('description',''),evidence.get('description_quote','')]).casefold()
    normalize=lambda value:re.sub(r'[^\w]+',' ',str(value).casefold()).strip()
    matched,unverified,conflicts=[],[],[]
    for key,value in item.get('specs',{}).items():
        if key in MATCHED_ELSEWHERE or (str(value).strip().casefold() in UNKNOWN and not (key=='repairs' and str(value)=='None')):continue
        if key=='battery' and item.get('category')=='Phone':
            expected=re.fullmatch(r'(\d{1,3})%?',str(value).strip())
            actual=re.search(r'battery\s*(?:health|capacity|maximum capacity)?\s*[:=\-]?\s*(\d{1,3})\s*%',text)
            if actual and expected:
                (matched if int(actual[1])==int(expected[1]) else conflicts).append(key)
            else:unverified.append(key)
        elif key=='repairs':
            if str(value)=='None' and re.search(r'\b(?:never repaired|no repairs|no repair history|all original parts)\b',text):matched.append(key)
            elif str(value)=='None' and re.search(r'\b(?:has been repaired|was repaired|replaced screen|screen replaced)\b',text):conflicts.append(key)
            else:unverified.append(key)
        elif normalize(value) not in {'yes','no'} and len(normalize(value))>=3 and normalize(value) in normalize(text):matched.append(key)
        else:unverified.append(key)
    return {'confirmed':matched,'unverified':unverified,'conflicts':conflicts,'note':'Only source-stated attributes are confirmed. Missing battery, repair or other unit facts do not receive invented numerical adjustments.'}
