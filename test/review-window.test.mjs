import {test} from 'node:test';
import assert from 'node:assert/strict';
import {startReview} from '../skill/prompt-aid/scripts/review-window.mjs';
const review={original:'Fix my page',improved:'Fix my page while preserving its current behavior.',questions:['What is broken?']};
test('review window requires its token and returns the exact edited prompt once',async()=>{
  const session=await startReview(review);const url=new URL(session.url),base=url.origin,token=url.hash.slice(1);
  const request=(pathname,origin,key,body={})=>fetch(base+pathname,{method:'POST',headers:{origin,'x-review-token':key,'content-type':'application/json'},body:JSON.stringify(body)});
  assert.equal((await request('/review','https://evil.example',token)).status,403);
  assert.equal((await request('/review',base,'bad-token')).status,403);
  const loaded=await request('/review',base,token);assert.deepEqual(await loaded.json(),{...review,changes:[],limitations:[]});
  assert.equal((await request('/decision',base,token,{action:'run',prompt:'   '})).status,400);
  assert.equal((await request('/decision',base,token,{action:'run',prompt:'User edited prompt'})).status,200);
  assert.deepEqual(await session.result,{action:'run',prompt:'User edited prompt'});
});
test('cancellation and expiry do not run a prompt',async()=>{
  const session=await startReview(review,{timeoutMs:25});
  assert.deepEqual(await session.result,{action:'timeout'});
  const cancelled=await startReview(review);cancelled.close();
  assert.deepEqual(await cancelled.result,{action:'cancel'});
});
