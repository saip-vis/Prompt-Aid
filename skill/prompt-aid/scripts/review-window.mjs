import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {randomBytes, timingSafeEqual} from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

// One review per process. JSON input contains only content explicitly supplied by the assistant.
export async function startReview(input, {timeoutMs=600000}={}) {
  if (!input || typeof input.original!=='string' || !input.original.trim() || typeof input.improved!=='string' || !input.improved.trim() || input.original.length>12000 || input.improved.length>16000) throw Error('Provide non-empty original and improved prompts within size limits.');
  for(const key of ['changes','questions','limitations']) if(input[key]!==undefined && (!Array.isArray(input[key]) || input[key].length>6 || input[key].some(x=>typeof x!=='string'||x.length>500))) throw Error('Invalid review notes.');
  const review={original:input.original,improved:input.improved,changes:input.changes||[],questions:input.questions||[],limitations:input.limitations||[]};
  const token=randomBytes(32).toString('hex');
  const html=await readFile(new URL('./review-window.html',import.meta.url));
  let finish;
  const result=new Promise(resolve=>{finish=resolve;});
  let settled=false;
  function settle(decision){if(settled)return;settled=true;clearTimeout(timer);finish(decision);server.close();}
  const server=http.createServer(async(req,res)=>{
    const host=`127.0.0.1:${server.address().port}`;
    res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');
    res.setHeader('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");
    if(req.headers.host!==host){res.writeHead(403);return res.end();}
    if(req.method==='GET' && req.url==='/'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});return res.end(html);}
    const given=Buffer.from(req.headers['x-review-token']||'');const expected=Buffer.from(token);
    if(req.headers.origin!==`http://${host}` || given.length!==expected.length || !timingSafeEqual(given,expected)){res.writeHead(403);return res.end();}
    if(req.method==='POST' && req.url==='/review') {res.writeHead(200,{'Content-Type':'application/json'});return res.end(JSON.stringify(review));}
    if(req.method==='POST' && req.url==='/decision') {
      if(req.headers['content-type']?.split(';')[0].trim()!=='application/json'){res.writeHead(415);return res.end();}
      let raw='';for await(const chunk of req){raw+=chunk;if(Buffer.byteLength(raw)>50000){res.writeHead(413);return res.end();}}
      let data;try{data=JSON.parse(raw);}catch{res.writeHead(400);return res.end();}
      if(!data || !['run','cancel'].includes(data.action) || (data.action==='run' && (typeof data.prompt!=='string'||!data.prompt.trim()||data.prompt.length>16000))){res.writeHead(400);return res.end();}
      res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({ok:true}));settle(data.action==='run'?{action:'run',prompt:data.prompt}:{action:'cancel'});return;
    }
    res.writeHead(404);res.end();
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const timer=setTimeout(()=>settle({action:'timeout'}),timeoutMs);
  return {url:`http://127.0.0.1:${server.address().port}/#${token}`,result,close:()=>settle({action:'cancel'})};
}
async function main(){
  const inputPath=process.argv[2];if(!inputPath)throw Error('Usage: node review-window.mjs <review.json> [--no-open]');
  const input=JSON.parse(await readFile(inputPath,'utf8'));
  const session=await startReview(input);
  if(process.argv.includes('--no-open')) process.stderr.write(`Review URL: ${session.url}\n`);
  else {
    if(process.platform!=='darwin'){session.close();throw Error('Automatic window launching currently supports macOS only.');}
    const opener=spawn('/usr/bin/open',['-na','Google Chrome','--args',`--app=${session.url}`],{stdio:'ignore'});
    await new Promise((resolve,reject)=>{opener.once('error',reject);opener.once('exit',code=>code===0?resolve():reject(Error('Could not open the review window. Google Chrome is required.')));}).catch(error=>{session.close();throw error;});
  }
  process.stdout.write(`${JSON.stringify(await session.result)}\n`);
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) main().catch(error=>{process.stderr.write(`${error.message}\n`);process.exitCode=1;});
