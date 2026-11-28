import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PromptAidClient} from '../../.build/typescript/client.js';
const token='x'.repeat(40);
test('client constrains destination and rejects implicit approval',()=>{
  for(const address of ['https://example.com','http://localhost:4318','http://127.0.0.1:4318?token=x','http://user@127.0.0.1:4318'])assert.throws(()=>new PromptAidClient(address,token));
  const client=new PromptAidClient('http://127.0.0.1:4318',token);
  assert.throws(()=>client.startBuild({approved:false}));assert.throws(()=>client.getBuild('../secret'));
});
test('client sends private auth headers, uses event cursors and reads comparison',async()=>{
  const requests=[];
  const client=new PromptAidClient('http://127.0.0.1:4318',token,{fetch:async(url,options)=>{
    requests.push([url,options]);return Response.json({events:[],mode:'within_run',replay:[]});}});
  await client.events('job-1',12);await client.comparison('job-1','job-2');
  assert.equal(requests[0][0].search,'?after=12');assert.equal(requests[0][1].headers.Authorization,`Bearer ${token}`);
  assert.equal(requests[0][1].redirect,'error');assert.equal(requests[1][0].search,'?baseline_id=job-2');
  assert.ok(!requests[0][0].href.includes(token));
});
test('client handles service failures and bounded responses without echoing bodies',async()=>{
  for(const response of [new Response('private detail',{status:401}),new Response('not json'),Response.json({value:'x'.repeat(256001)})]) {
    const client=new PromptAidClient('http://127.0.0.1:4318',token,{fetch:async()=>response});
    await assert.rejects(client.listBuilds(),error=>!error.message.includes(token)&&!error.message.includes('private detail'));
  }
});
