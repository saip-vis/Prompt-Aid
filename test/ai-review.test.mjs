import {test} from 'node:test';
import assert from 'node:assert/strict';
import {generateReview} from '../ai-review.mjs';
import {createPreviewServer} from '../preview.mjs';

const input={prompt:'Fix the login bug', conversation:'It fails on mobile.',project:'React app',target:'Codex desktop'};
const good={improved_prompt:'Fix the login bug on mobile.',changes:['Included the device.'],questions:['What error appears?'],limitations:['The error has not been provided.']};
const reply=(content,status='completed')=>({ok:true,json:async()=>({status,output:[{type:'message',content}]})});
test('AI request includes only supplied context and validates the result',async()=>{
  let body;
  const result=await generateReview(input,{apiKey:'test',model:'test-model',fetchImpl:async(url,options)=>{
    assert.equal(url,'https://api.openai.com/v1/responses');body=JSON.parse(options.body);
    return reply([{type:'output_text',text:JSON.stringify(good)}]);
  }});
  assert.equal(result.status,200);assert.deepEqual(result.review,good);
  assert.equal(body.store,false);assert.deepEqual(JSON.parse(body.input),input);assert.equal(body.text.format.strict,true);
});
test('missing key, invalid input, refusal and bad provider responses are handled',async()=>{
  assert.equal((await generateReview(input,{apiKey:''})).status,503);
  assert.equal((await generateReview({...input,prompt:'  '},{apiKey:'test'})).status,400);
  assert.equal((await generateReview(input,{apiKey:'test',fetchImpl:async()=>reply([{type:'refusal',refusal:'no'}])})).status,422);
  assert.equal((await generateReview(input,{apiKey:'test',fetchImpl:async()=>reply([{type:'output_text',text:'{}'}])})).status,502);
  assert.equal((await generateReview(input,{apiKey:'test',fetchImpl:async()=>reply([], 'incomplete')})).status,502);
});
test('local endpoint requires same origin and JSON',async t=>{
  const server=createPreviewServer({review:async()=>({status:200,review:good})});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>server.close());
  const url=`http://127.0.0.1:${server.address().port}`;
  const send=(origin,contentType='application/json')=>fetch(`${url}/api/review`,{method:'POST',headers:{origin,'content-type':contentType},body:JSON.stringify(input)});
  assert.equal((await send('https://attacker.example')).status,403);
  assert.equal((await send(url,'text/plain')).status,403);
  const result=await send(url);assert.equal(result.status,200);assert.deepEqual((await result.json()).review,good);
});
