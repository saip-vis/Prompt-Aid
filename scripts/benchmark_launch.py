"""Compare native invocation-to-window times using the current code or a saved baseline.

Runs a throwaway instrumented build; never invokes the reviewed task. UI timing
ends after window display and one main-queue turn, not a hardware frame callback.
"""
import argparse,json,os,statistics,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--baseline',action='store_true');p.add_argument('--runs',type=int,default=5);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 with tempfile.TemporaryDirectory(prefix='prompt-aid-launch-') as tmp:
  tmp=Path(tmp);source=(ROOT/'native/PromptAid.swift').read_text()
  # A fixed instrumentation point in the same window presentation path.
  target='self.window = window'
  source=source.replace(target,target+'''\n        window.displayIfNeeded()
        DispatchQueue.main.async {
            if let path = ProcessInfo.processInfo.environment["PROMPT_AID_BENCH_READY"] {
                try? Data("ready".utf8).write(to: URL(fileURLWithPath:path), options:.atomic)
                self.session.finish("cancel")
            }
        }''')
  (tmp/'PromptAid.swift').write_text(source)
  files=[str(x) for x in (ROOT/'native').glob('*.swift') if x.name!='PromptAid.swift']+[str(tmp/'PromptAid.swift')]
  cmd=['xcrun','swiftc','-target',os.uname().machine+'-apple-macos13.0']+([] if a.baseline else ['-O'])+files+['-o',str(tmp/'PromptAid'),'-framework','AppKit','-framework','SwiftUI']
  subprocess.run(cmd,check=True)
  payload=tmp/'review.json';payload.write_text(json.dumps({'original':'Add a search filter to saved designs.','improved':'Add a search filter to saved designs while preserving account isolation.','evidence':[],'changes':[],'questions':[],'limitations':[]}));payload.chmod(0o600)
  times=[]
  for i in range(a.runs):
   ready=tmp/'ready';ready.unlink(missing_ok=True)
   env={k:v for k,v in os.environ.items() if not k.startswith('PROMPT_AID_')};env['PROMPT_AID_BENCH_READY']=str(ready)
   started=time.perf_counter();proc=subprocess.Popen([str(tmp/'PromptAid'),str(payload)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
   while not ready.exists() and proc.poll() is None and time.perf_counter()-started<15:time.sleep(.005)
   elapsed=(time.perf_counter()-started)*1000
   if not ready.exists():
    proc.kill();out,err=proc.communicate();raise RuntimeError(f'Native window failed ({proc.returncode}): {err.decode()[:300]}')
   out,err=proc.communicate(timeout=5);assert json.loads(out)['action']=='cancel';times.append(round(elapsed,2))
  result={'mode':'baseline' if a.baseline else 'optimized','runs_ms':times,'first_ms':times[0],'warm_median_ms':statistics.median(times[1:] or times),'endpoint':'window.displayIfNeeded plus next main queue turn; polling resolution 5ms','review_preparation':'Fixture JSON already prepared; excludes host model/tool latency'}
  a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
