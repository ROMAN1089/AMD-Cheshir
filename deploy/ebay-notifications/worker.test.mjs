import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {handle} from './worker.mjs';
const pair=await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['encrypt','decrypt']);
const publicKey=JSON.stringify(await crypto.subtle.exportKey('jwk',pair.publicKey));
function environment(){
 const rows=new Map();
 return {rows,VERIFICATION_TOKEN:'a'.repeat(48),ENDPOINT_URL:'https://example.workers.dev/ebay/deletion',POLL_TOKEN:'test-only-poll-token',PUBLIC_KEY_JWK:publicKey,
  DB:{prepare(sql){return {bind(...args){return {
   async first(){return rows.has(args[0])?{id:args[0]}:null;},
   async run(){if(sql.startsWith('DELETE')){rows.delete(args[0]);return {meta:{changes:1}};}if(rows.size>=2000)return {meta:{changes:0}};rows.set(args[0],{id:args[0],sealed:args[1]});return {meta:{changes:1}};},
  };},async all(){return {results:[...rows.values()].slice(0,50)};}};}}};
}
function notification(raw=JSON.stringify({metadata:{topic:'MARKETPLACE_ACCOUNT_DELETION'},notification:{data:{username:'sample-test-user'}}})){
 return new Request('https://example.workers.dev/ebay/deletion',{method:'POST',headers:{'x-ebay-signature':'test-signature','content-type':'application/json'},body:raw});
}
test('challenge is exactly SHA256(code+token+registered endpoint)',async()=>{
 const env=environment();const response=await handle(new Request(env.ENDPOINT_URL+'?challenge_code=test-code'),env);
 assert.equal(response.status,200);assert.equal((await response.json()).challengeResponse,createHash('sha256').update('test-code'+env.VERIFICATION_TOKEN+env.ENDPOINT_URL).digest('hex'));
});
test('queue is encrypted, raw bytes preserved, duplicate delivery is idempotent',async()=>{
 const env=environment();const raw=JSON.stringify({metadata:{topic:'MARKETPLACE_ACCOUNT_DELETION'},notification:{data:{username:'sample-test-user'}}},null,2);
 assert.equal((await handle(notification(raw),env)).status,202);
 assert.equal((await handle(notification(raw),env)).status,202);assert.equal(env.rows.size,1);
 const stored=[...env.rows.values()][0];assert.ok(!stored.sealed.includes('sample-test-user'));
 const sealed=JSON.parse(stored.sealed);
 const keyBytes=await crypto.subtle.decrypt({name:'RSA-OAEP'},pair.privateKey,Buffer.from(sealed.key,'base64'));
 const key=await crypto.subtle.importKey('raw',keyBytes,'AES-GCM',false,['decrypt']);
 const clear=JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:Buffer.from(sealed.iv,'base64')},key,Buffer.from(sealed.ciphertext,'base64'))));
 assert.equal(Buffer.from(clear.body,'base64').toString(),raw);assert.equal(clear.signature,'test-signature');
});
test('pending and ack require correct token',async()=>{
 const env=environment();assert.equal((await handle(new Request('https://example.workers.dev/pending'),env)).status,401);
 await handle(notification(),env);const id=[...env.rows.keys()][0];
 assert.equal((await handle(new Request('https://example.workers.dev/ack',{method:'POST',body:JSON.stringify({id})}),env)).status,401);assert.equal(env.rows.size,1);
 assert.equal((await handle(new Request('https://example.workers.dev/ack',{method:'POST',headers:{Authorization:'Bearer '+env.POLL_TOKEN},body:JSON.stringify({id})}),env)).status,204);assert.equal(env.rows.size,0);
});
test('full inbox returns retryable error, never falsely acknowledges',async()=>{
 const env=environment();for(let i=0;i<2000;i++)env.rows.set(String(i),{});
 assert.equal((await handle(notification(),env)).status,503);
});
test('unsigned and oversize messages cannot enter inbox',async()=>{
 const env=environment();assert.equal((await handle(new Request(env.ENDPOINT_URL,{method:'POST',body:'{}'}),env)).status,412);
 assert.equal((await handle(notification('a'.repeat(17000)),env)).status,413);assert.equal(env.rows.size,0);
});
