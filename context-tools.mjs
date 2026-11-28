import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {homedir} from 'node:os';
import path from 'node:path';

export function runContext(action, root, input, {env=process.env}={}) {
  let roots;
  try { roots=JSON.parse(env.PROMPT_AID_PROJECT_ROOTS||'[]'); }
  catch { return Promise.reject(new Error('PROMPT_AID_PROJECT_ROOTS must be a JSON array.')); }
  if(!Array.isArray(roots)||!roots.length||roots.some(r=>typeof r!=='string'||!path.isAbsolute(r))) return Promise.reject(new Error('Configure PROMPT_AID_PROJECT_ROOTS with explicit absolute Git project roots first.'));
  return new Promise((resolve,reject)=>{
    const child=spawn(env.PROMPT_AID_PYTHON||'python3',[
      fileURLToPath(new URL('./skill/prompt-aid/retrieval/workspace.py',import.meta.url)),
      '--root',root,'--allowed-roots',JSON.stringify(roots),
      '--data',env.PROMPT_AID_DATA||path.join(homedir(),'.local/share/prompt-aid'),
      '--action',action,
      ...(env.PROMPT_AID_EMBEDDING_MODEL?['--embedding-model',env.PROMPT_AID_EMBEDDING_MODEL]:[]),
      ...(env.PROMPT_AID_RERANKER_MODEL?['--reranker-model',env.PROMPT_AID_RERANKER_MODEL]:[])
    ],{stdio:['pipe','pipe','pipe'],env});
    let stdout='',stderr='',settled=false;
    const timer=setTimeout(()=>{child.kill();finish(new Error('Context operation timed out.'));},60000);
    function finish(error,value){if(settled)return;settled=true;clearTimeout(timer);error?reject(error):resolve(value);}
    child.on('error',error=>finish(error));
    child.stdin.on('error',error=>finish(error));
    child.stdout.on('data',chunk=>{stdout+=chunk;if(Buffer.byteLength(stdout)>256000){child.kill();finish(new Error('Context response exceeded its size limit.'));}});
    child.stderr.on('data',chunk=>{stderr+=chunk;if(Buffer.byteLength(stderr)>16000){child.kill();finish(new Error('Context bridge failed.'));}});
    child.on('close',code=>{
      if(code!==0){let message='Context operation failed.';try{message=JSON.parse(stderr).error||message;}catch{}return finish(new Error(message));}
      try{finish(null,JSON.parse(stdout));}catch{finish(new Error('Invalid context response.'));}
    });
    child.stdin.end(JSON.stringify(input));
  });
}
