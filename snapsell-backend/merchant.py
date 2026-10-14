"""Public merchant product adapters. No checkout actions or private APIs."""
import json
import re
from urllib.parse import urlparse,urlunparse,urlencode,parse_qsl
from bs4 import BeautifulSoup

def shopify_evidence(document,item,fetch,allowed,match,condition_from):
    """Use Shopify's documented public Product Ajax response to resolve variants.

    Prices are integer minor units. Currency must be explicitly established by the
    merchant page. A merchant page's conflicting condition metadata remains visible.
    """
    p=urlparse(document['url']); path=p.path
    if '/products/' not in path: return [],[]
    soup=BeautifulSoup(document['text'],'html.parser')
    if 'cdn.shopify.com' not in document['text'] and 'Shopify.' not in document['text']: return [],[]
    meta={str(t.get('property') or t.get('name') or t.get('itemprop') or '').lower():t.get('content','') for t in soup.find_all('meta')}
    currency=meta.get('og:price:currency') or meta.get('product:price:currency') or meta.get('pricecurrency')
    if not currency:
        m=re.search(r'Shopify\.currency\s*=\s*\{[^}]*["\']active["\']\s*:\s*["\']([A-Z]{3})',document['text'])
        currency=m.group(1) if m else None
    if currency!='USD': return [],['The merchant does not explicitly establish USD presentment currency.']
    product_path=path[:path.find('/products/')]+path[path.find('/products/'):].rstrip('/')
    api_url=urlunparse(('https',p.netloc,product_path+'.js','','',''))
    allowed(api_url)
    response=fetch(api_url)
    try: product=json.loads(response['text'])
    except ValueError:return [],['Public product response was not valid JSON.']
    if not isinstance(product,dict) or not isinstance(product.get('variants'),list):return [],[]
    name=str(product.get('title','')); description=BeautifulSoup(str(product.get('description','')),'html.parser').get_text(' ',strip=True)
    ok,reason=match(item,name,description)
    if not ok:return [],[reason]
    condition=condition_from('',name+' '+description[:2000])
    if condition in ['New','Unknown']:return [],['Pre-owned condition is not explicit in the primary product description.']
    rows=[]
    conflict='NewCondition' in document['text'] and condition=='Refurbished'
    for v in product['variants'][:40]:
        if v.get('available') is not True:continue
        try:amount=int(v['price'])/100
        except (ValueError,TypeError,KeyError):continue
        if not 1<=amount<=100000:continue
        title=name+' · '+str(v.get('title','Default'))
        # Never convert RAM/storage from another variant into this variant's facts.
        if not match(item,title,description)[0]:continue
        offer_query=[(k,val) for k,val in parse_qsl(p.query) if k!='variant']+[('variant',str(v.get('id','')))]
        offer_url=urlunparse((p.scheme,p.netloc,p.path,p.params,urlencode(offer_query),''))
        rows.append(dict(title=title[:250],price=amount,currency='USD',condition=condition,kind='asking',source='verified_web',verification='Public Shopify Product Ajax variant; page currency and product description cross-checked',url=document['url'],offer_url=offer_url,source_name=p.hostname,observed_at=response['fetched_at'],age_days=0,page_sha256=document['sha256'],api_sha256=response['sha256'],evidence={'product_title':name,'description_quote':description[:1600],'variant_title':v.get('title'),'variant_id':v.get('id'),'variant_sku':v.get('sku'),'price_minor_units':v['price'],'priceCurrency':currency,'available':v['available'],'product_api_url':api_url,'condition_basis':'Primary product title/description; cosmetic grade retained without numerical adjustment','metadata_conflict':'The page description says refurbished; a JSON-LD template also contains NewCondition.' if conflict else None},match_reason=reason,availability='InStock',model_key=item['model_key'],shipping='Shipping and taxes not verified',transaction_verified=False,source_grade=str(v.get('title',''))))
    # Multiple grades are independent offers but not independent merchants.
    return rows,[] if rows else ['The public product response has no matching available variants.']
