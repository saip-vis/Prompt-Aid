"""Compare the actual old CLI and new skill helper on the same frozen project."""
import argparse,json,os,socket,statistics,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 with tempfile.TemporaryDirectory(prefix='prompt-aid-helper-bench-') as temp:
  data=Path(temp)/'data'
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  manager=[sys.executable,'-m','backend.manage']
  subprocess.run(manager+['start','--root',str(a.fixture),'--data',str(data),'--port',str(port)],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
  rows={};sources={}
  try:
   for mode in ['old_cli','new_helper']:
    rows[mode]=[];sources[mode]=[]
    command=[sys.executable,str(a.fixture/'skill/prompt-aid/retrieval/cli.py'),'--root',str(a.fixture),'--input','-'] if mode=='old_cli' else [sys.executable,str(ROOT/'skill/prompt-aid/review.py'),'context']
    for i in range(7):
     body={'query':'saved review history project isolation'}
     if mode=='new_helper':body['root']=str(a.fixture)
     start=time.perf_counter();result=subprocess.run(command,input=json.dumps(body),text=True,capture_output=True,env={**os.environ,'PROMPT_AID_DATA':str(data)},check=True)
     elapsed=(time.perf_counter()-start)*1000;r=json.loads(result.stdout)
     rows[mode].append(round(elapsed,2));sources[mode].append([(s['path'],s['line_start'],s['line_end']) for s in r['results'][:3]])
   assert all(x==sources['old_cli'][0] for group in sources.values() for x in group)
   report={'samples_ms':rows,'median_ms':{k:round(statistics.median(v[1:]),2) for k,v in rows.items()},'same_top_three':True,'provider_time_included':False,'new_helper_default_limit':3,'old_cli_default_limit':5}
   a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
  finally:subprocess.run(manager+['stop','--data',str(data)],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
if __name__=='__main__':main()
