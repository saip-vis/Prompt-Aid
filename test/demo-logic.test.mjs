import {test} from 'node:test';
import assert from 'node:assert/strict';
import {questionsFor,buildDraft} from '../public/demo-logic.mjs';

test('questions adapt to the request without inventing information',()=>{
  assert.equal(questionsFor('Make my website better')[0].id,'focus');
  assert.equal(questionsFor('Fix the broken login page')[0].id,'behavior');
  assert.equal(questionsFor('Optimize slow queries')[0].id,'bottleneck');
  assert.equal(questionsFor('Add an export button')[0].id,'outcome');
  assert.equal(buildDraft('Make my website better',{}),'Make my website better');
  assert.equal(buildDraft('   ',{focus:'something'}),'');
});
test('draft contains only the original request and provided answers',()=>{
  const result=buildDraft('Make my website better.',{focus:'Improve the dashboard.',direction:'Keep it dark.',constraints:'',behavior:'not relevant'});
  assert.match(result,/^Make my website better\./);
  assert.match(result,/Improve the dashboard\./);
  assert.match(result,/Keep it dark\./);
  assert.doesNotMatch(result,/not relevant/);
  assert.doesNotMatch(result,/What should stay unchanged/);
});
