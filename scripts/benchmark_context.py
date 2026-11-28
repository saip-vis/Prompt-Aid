"""Measure native-style context preparation on one frozen, filtered source snapshot.

No host model call is made. Legacy mode reproduces the old index/search/verify
round trips; fast mode uses a single root-scoped search and its fresh source data.
"""
import argparse,json,os,statistics,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
import store as storage
from semantic import LocalSemantic,LocalReranker

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--mode',choices=['legacy','fast'],required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if not a.fixture.exists():
  from context import scan
  chunks,_=scan(ROOT);a.fixture.mkdir(mode=0o700,parents=True)
  for relative in {c.path for c in chunks}:
   dest=a.fixture/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/relative).read_bytes())
  subprocess.run(['git','init','-q',str(a.fixture)],check=True)
 metrics=[];original_scan=storage.scan
 def measured_scan(root):
  start=time.perf_counter();result=original_scan(root);metrics.append((time.perf_counter()-start)*1000);return result
 storage.scan=measured_scan
 queries=['saved review history project isolation','native window startup pending review','source hash excerpt freshness verification','persistent vectors unchanged chunks','authentication user account isolation','backend search model configuration']
 with tempfile.TemporaryDirectory(prefix='prompt-aid-context-bench-') as tmp:
  semantic=LocalSemantic(Path(tmp)/'vectors',ROOT/'.models/embeddings');reranker=LocalReranker(ROOT/'.models/reranker')
  store=storage.Store(Path(tmp)/'data',[a.fixture],semantic,reranker)
  rows=[]
  try:
   for method in ['bm25','hybrid']:
    for i,query in enumerate(queries+queries[:3]):
     metrics.clear();start=time.perf_counter()
     if a.mode=='legacy':
      project=store.index(a.fixture)['project_id'];result=store.search(project,query,method=method)
      store.verify(project,result['results'])
     else:result=store.search(query=query,root=str(a.fixture),method=method)
     rows.append({'method':method,'query':query,'wall_ms':round((time.perf_counter()-start)*1000,2),'scan_count':len(metrics),'scan_ms':round(sum(metrics),2),'timings':result['timings'],'sources':[(x['path'],x['line_start'],x['line_end']) for x in result['results']]})
  finally:store.close()
  summary={}
  for method in ['bm25','hybrid']:
   samples=[row['wall_ms'] for row in rows if row['method']==method]
   summary[method]={'first_ms':samples[0],'warm_median_ms':round(statistics.median(samples[1:]),2)}
  report={'mode':a.mode,'fixture':str(a.fixture),'summary':summary,'rows':rows,'host_model_latency':'Not included; caller/provider-controlled'}
  a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(summary))
if __name__=='__main__':main()
