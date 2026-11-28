import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {runContext} from '../context-tools.mjs';

test('context bridge requires configured roots and returns hashed source evidence',async()=>{
  await assert.rejects(runContext('search','/tmp',{}, {env:{}}),/Configure/);
  const dir=await mkdtemp(path.join(tmpdir(),'prompt-aid-context-'));
  try {
    const root=path.join(dir,'repo');await mkdir(root);
    execFileSync('git',['init','-q',root]);
    await writeFile(path.join(root,'login.py'),'def authenticate(): return "login session"\n');
    const env={...process.env,PROMPT_AID_PROJECT_ROOTS:JSON.stringify([root]),PROMPT_AID_DATA:path.join(dir,'data')};
    const result=await runContext('search',root,{query:'session'}, {env});
    assert.equal(result.results[0].path,'login.py');
    assert.match(result.results[0].content_hash,/^[0-9a-f]{64}$/);
    await assert.rejects(runContext('search',dir,{query:'session'}, {env}),/configured roots/);
    const excluded=await runContext('search',root,{query:'session',excluded_paths:['login.py']},{env});
    assert.deepEqual(excluded.results,[]);
  } finally {await rm(dir,{recursive:true,force:true});}
});
