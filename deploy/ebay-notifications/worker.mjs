// Stores sealed messages only. The private decryption key stays on the seller's PC.
const json = (value, status=200) => Response.json(value, {status, headers:{'Cache-Control':'no-store'}});
const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes)));
export async function handle(request, env) {
  const url = new URL(request.url);
  if (url.pathname === '/ebay/deletion' && request.method === 'GET') {
    const code = url.searchParams.get('challenge_code');
    if (!code || code.length > 512 || !/^[A-Za-z0-9_-]{32,80}$/.test(env.VERIFICATION_TOKEN || '')) return json({error:'Invalid challenge or configuration'},400);
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(code+env.VERIFICATION_TOKEN+env.ENDPOINT_URL));
    return json({challengeResponse:[...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('')});
  }
  if (url.pathname === '/ebay/deletion' && request.method === 'POST') {
    const header=request.headers.get('x-ebay-signature');
    if (!header || header.length>4096 || Number(request.headers.get('content-length') || 0)>16384) return json({error:'Invalid notification'},412);
    // Bound streamed bodies too; do not trust Content-Length.
    const reader=request.body?.getReader(); if (!reader) return json({error:'Missing body'},400);
    const chunks=[]; let length=0;
    while(true) { const {value,done}=await reader.read(); if(done) break; length+=value.length; if(length>16384) {await reader.cancel();return json({error:'Too large'},413);} chunks.push(value); }
    const raw=new Uint8Array(length); let offset=0; for(const chunk of chunks){raw.set(chunk,offset);offset+=chunk.length;}
    let body; try { body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw)); } catch {return json({error:'Invalid JSON'},400);}
    if(body?.metadata?.topic!=='MARKETPLACE_ACCOUNT_DELETION' || typeof body?.notification?.data!=='object' || !body.notification.data) return json({error:'Unsupported notification'},400);
    // Deduplicate the complete signed content, not an unverified notification ID.
    const payload=JSON.stringify({body:b64(raw),signature:header});
    const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(payload));
    const id=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');
    if(await env.DB.prepare('SELECT id FROM inbox WHERE id=?').bind(id).first()) return new Response(null,{status:202});
    const key=await crypto.subtle.generateKey({name:'AES-GCM',length:256},true,['encrypt']);
    const iv=crypto.getRandomValues(new Uint8Array(12));
    const encrypted=await crypto.subtle.encrypt({name:'AES-GCM',iv},key,new TextEncoder().encode(payload));
    const publicKey=await crypto.subtle.importKey('jwk',JSON.parse(env.PUBLIC_KEY_JWK),{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);
    const wrapped=await crypto.subtle.encrypt({name:'RSA-OAEP'},publicKey,await crypto.subtle.exportKey('raw',key));
    const sealed=JSON.stringify({iv:b64(iv),key:b64(wrapped),ciphertext:b64(encrypted)});
    const result=await env.DB.prepare('INSERT OR IGNORE INTO inbox(id,sealed,created_at) SELECT ?,?,? WHERE (SELECT COUNT(*) FROM inbox)<2000').bind(id,sealed,Date.now()).run();
    if(!result.meta.changes) return json({error:'Inbox full; retry later'},503);
    return new Response(null,{status:202});
  }
  if(url.pathname==='/pending' || url.pathname==='/ack') {
    if(!env.POLL_TOKEN || request.headers.get('Authorization')!=='Bearer '+env.POLL_TOKEN) return json({error:'Unauthorized'},401);
    if(url.pathname==='/pending' && request.method==='GET') return json((await env.DB.prepare('SELECT id,sealed FROM inbox ORDER BY created_at,id LIMIT 50').all()).results);
    if(url.pathname==='/ack' && request.method==='POST') {
      const data=await request.json(); if(!/^[a-f0-9]{64}$/.test(data.id || ''))return json({error:'Invalid ID'},400);
      await env.DB.prepare('DELETE FROM inbox WHERE id=?').bind(data.id).run();return new Response(null,{status:204});
    }
  }
  return json({error:'Not found'},404);
}
export default {async fetch(request,env){try{return await handle(request,env);}catch{return json({error:'Notification service unavailable; retry later'},503);}}};
