import http from 'node:http';
import {readFile} from 'node:fs/promises';
import {generateReview} from './ai-review.mjs';
const files = {
  '/': ['workspace.html', 'text/html; charset=utf-8'],
  '/index.html': ['workspace.html', 'text/html; charset=utf-8'],
  '/review': ['index.html', 'text/html; charset=utf-8'],
  '/demo-logic.mjs': ['demo-logic.mjs', 'text/javascript; charset=utf-8'],
  '/test-host': ['test-host.html', 'text/html; charset=utf-8']
};
const port=Number(process.env.PORT||4317);
export function createPreviewServer({review=generateReview}={}) {
  const server=http.createServer(async(request,response)=>{
    response.setHeader('X-Content-Type-Options','nosniff');
    response.setHeader('Cache-Control','no-store');
    if(request.url==='/api/review' && request.method==='POST'){
      const allowedHost=`127.0.0.1:${server.address().port}`;
      const allowedOrigin=`http://${allowedHost}`;
      if(request.headers.host!==allowedHost || request.headers.origin!==allowedOrigin || request.headers['content-type']?.split(';')[0].trim().toLowerCase()!=='application/json'){
        response.writeHead(403);return response.end('Forbidden');
      }
      let raw='';
      for await(const chunk of request){ raw+=chunk; if(Buffer.byteLength(raw)>100000){response.writeHead(413);return response.end('Request too large');} }
      let data;try{data=JSON.parse(raw);}catch{response.writeHead(400);return response.end('Invalid JSON');}
      const result=await review(data);response.writeHead(result.status,{'content-type':'application/json; charset=utf-8'});return response.end(JSON.stringify(result));
    }
    const match=files[request.url];
    if(request.method!=='GET'||!match){response.writeHead(404);return response.end('Not found');}
    try {
      const contents=await readFile(new URL(`./public/${match[0]}`,import.meta.url));
      response.writeHead(200,{'content-type':match[1]});response.end(contents);
    }catch{response.writeHead(500);response.end('Preview unavailable');}
  });
  return server;
}
if(process.argv[1] && new URL(import.meta.url).pathname===process.argv[1]) createPreviewServer().listen(port,'127.0.0.1',()=>console.log(`Prompt Aid preview: http://127.0.0.1:${port}`));
