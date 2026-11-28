"""Local-only service readiness, first-search and persistent restart measurements."""
import argparse,json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();runs=[]
 with tempfile.TemporaryDirectory(prefix='prompt-aid-service-bench-') as temp:
  temp=Path(temp);repo=temp/'repo';repo.mkdir();subprocess.run(['git','init','-q',str(repo)],check=True)
  (repo/'auth.py').write_text('def authenticate_user():\n    """Keep the user signed in using a persistent session cookie."""\n    return session\n')
  (repo/'cart.py').write_text('def price_cart(items):\n    return sum(item.price for item in items)\n')
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  data=temp/'data'
  for run in range(2):
   env={**os.environ,'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false'}
   cmd=[sys.executable,'-m','backend.app','--root',str(repo),'--data',str(data),'--port',str(port),'--embedding-model',str(ROOT/'.models/embeddings'),'--reranker-model',str(ROOT/'.models/reranker')]
   start=time.perf_counter();proc=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
   def request(route,body=None):
    token=(data/'api-token').read_text().strip()
    req=urllib.request.Request(f'http://127.0.0.1:{port}'+route,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=45))
   try:
    while True:
     try:health=request('/health');break
     except (OSError,ValueError):
      if proc.poll() is not None:raise RuntimeError('Service exited before ready')
      if time.perf_counter()-start>60:raise TimeoutError('Service readiness timeout')
      time.sleep(.025)
    ready=round((time.perf_counter()-start)*1000,2)
    index=request('/projects/index',{'root':str(repo)})
    results=[]
    for i in range(2):
     search_start=time.perf_counter();result=request('/context/search',{'project_id':index['project_id'],'query':'persistent authentication session','method':'hybrid','rerank':True})
     results.append({'wall_ms':round((time.perf_counter()-search_start)*1000,2),'reported_ms':result['duration_ms'],'timings':result.get('timings'),'vector_sync':result.get('vector_sync'),'first_path':result['results'][0]['path']})
    runs.append({'process':'first' if run==0 else 'restart','ready_ms':ready,'health':health,'searches':results})
   finally:
    proc.terminate()
    try:proc.wait(timeout=10)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
  a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(runs,indent=2)+'\n');print(json.dumps(runs))
if __name__=='__main__':main()
