import test from 'node:test';
import assert from 'node:assert/strict';
import { handleRequest } from '../src/index.js';

const hash='a'.repeat(64); const path=`/daily/2026/07/21/${hash}.webp`;
function env(found=true) {
  const calls=[];
  const object={body:new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('webp'));c.close();}}),httpMetadata:{contentType:'image/webp'},customMetadata:{sha256:hash}};
  return { calls, ASSETS:{get:async k=>(calls.push(['get',k]),found?object:null),head:async k=>(calls.push(['head',k]),found?object:null),
    put(){calls.push(['put']);throw Error('write called')},delete(){calls.push(['delete']);throw Error('write called')},list(){calls.push(['list']);throw Error('list called')}}};
}
async function run(method='GET',p=path,e=env(),headers={}) { return [await handleRequest(new Request(`https://assets.example${p}`,{method,headers}),e),e]; }

test('GET streams valid object with safe immutable headers',async()=>{const [r,e]=await run();assert.equal(r.status,200);assert.equal(await r.text(),'webp');assert.equal(r.headers.get('content-type'),'image/webp');assert.equal(r.headers.get('cache-control'),'public, max-age=31536000, immutable');assert.equal(r.headers.get('etag'),`"${hash}"`);assert.equal(r.headers.get('x-content-type-options'),'nosniff');assert.deepEqual(e.calls,[['get',path.slice(1)]]);});
test('HEAD has no body and uses head',async()=>{const [r,e]=await run('HEAD');assert.equal(r.status,200);assert.equal(await r.text(),'');assert.deepEqual(e.calls,[['head',path.slice(1)]]);});
test('missing object is 404',async()=>assert.equal((await run('GET',path,env(false)))[0].status,404));
for (const [name,p] of [['non-WebP','/daily/x.png'],['outside','/other/a.webp'],['traversal','/daily/%2e%2e/x.webp'],['encoded slash','/daily%2f2026/x.webp'],['malformed','/daily/%E0%A4%A.webp']]) test(name+' rejected',async()=>assert.equal((await run('GET',p))[0].status,404));
for (const method of ['POST','PUT','DELETE']) test(method+' rejected without bucket operation',async()=>{const e=env();const [r]=await run(method,path,e);assert.equal(r.status,405);assert.deepEqual(e.calls,[]);});
test('conditional GET returns 304',async()=>{const [r]=await run('GET',path,env(),{'If-None-Match':`"${hash}"`});assert.equal(r.status,304);});
test('never lists or writes bucket',async()=>{const [,e]=await run();assert.equal(e.calls.some(x=>['put','delete','list'].includes(x[0])),false);});
