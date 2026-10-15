"""Research markets, independent of the legacy USD inventory accounting."""
MARKETS={
 'US':{'name':'United States','currency':'USD','region':'us-en','country_terms':'United States used pre-owned price USD','suffixes':['.us']},
 'KZ':{'name':'Kazakhstan','currency':'KZT','region':'wt-wt','country_terms':'Казахстан б/у цена тенге','suffixes':['.kz']},
 'JP':{'name':'Japan','currency':'JPY','region':'jp-jp','country_terms':'日本 中古 価格 円','suffixes':['.jp']},
 'CN':{'name':'China','currency':'CNY','region':'cn-zh','country_terms':'中国 二手 价格 人民币','suffixes':['.cn']},
}
def get(code='US'):
 if code not in MARKETS:raise ValueError('Choose US, KZ, JP or CN for price research.')
 return {'code':code,**MARKETS[code]}
def for_item(item):return get(item.get('_research_market','US'))
