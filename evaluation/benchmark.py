"""Compare persistent retrieval methods on labeled cases; no model calls to APIs.

The bundled cases remain small, synthetic and jointly authored with fixtures.
Use --cases/--fixtures for a separately labeled corpus; do not tune on its test split.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from store import Store


def measure(store, projects, cases, method, rerank):
    rows = []
    for case in cases:
        result = store.search(projects[case['project']],case['query'],method,10,rerank)
        paths = list(dict.fromkeys(r['path'] for r in result['results']))
        relevant = set(case['relevant'])
        rank = next((i+1 for i,p in enumerate(paths) if p in relevant),None)
        rows.append({'id':case['id'], 'expected':sorted(relevant), 'top':paths[:3],
                     'recall_at_1':len(relevant & set(paths[:1]))/len(relevant) if relevant else None,
                     'recall_at_3':len(relevant & set(paths[:3]))/len(relevant) if relevant else None,
                     'reciprocal_rank':1/rank if rank else 0, 'abstained':not paths,
                     'method':result['method'], 'reranked':result['reranked'], 'duration_ms':result['duration_ms']})
    positives = [r for r in rows if r['expected']]
    negatives = [r for r in rows if not r['expected']]
    times = sorted(r['duration_ms'] for r in rows)
    return {'queries':len(rows), 'recall_at_1':statistics.mean(r['recall_at_1'] for r in positives) if positives else None,
            'recall_at_3':statistics.mean(r['recall_at_3'] for r in positives) if positives else None,
            'mrr':statistics.mean(r['reciprocal_rank'] for r in positives) if positives else None,
            'no_match_abstention':statistics.mean(r['abstained'] for r in negatives) if negatives else None,
            'p50_ms':statistics.median(times), 'max_ms':max(times), 'results':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases',type=Path,default=ROOT/'evaluation/queries.json')
    p.add_argument('--fixtures',type=Path,default=ROOT/'evaluation/fixtures')
    p.add_argument('--embedding-model',type=Path)
    p.add_argument('--reranker-model',type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    cases=json.loads(args.cases.read_text())
    roots={c['project']:args.fixtures/c['project'] for c in cases}
    with tempfile.TemporaryDirectory(prefix='prompt-aid-eval-') as directory:
        semantic=reranker=None
        if args.embedding_model:
            from semantic import LocalSemantic
            semantic=LocalSemantic(Path(directory)/'vectors',args.embedding_model)
        if args.reranker_model:
            from semantic import LocalReranker
            reranker=LocalReranker(args.reranker_model)
        store=Store(directory,list(roots.values()),semantic,reranker)
        projects={name:store.index(root)['project_id'] for name,root in roots.items()}
        methods=[('bm25',False)]
        if semantic:methods += [('semantic',False),('hybrid',False)]
        if reranker:methods += [('hybrid' if semantic else 'bm25',True)]
        results={method+('+rerank' if rr else ''):measure(store,projects,cases,method,rr) for method,rr in methods}
        report={'dataset':str(args.cases.relative_to(ROOT)) if args.cases.is_relative_to(ROOT) else args.cases.name,
                'embedding_model':getattr(semantic,'identity',None), 'reranker':getattr(reranker,'identity',None),
                'limitations':['Bundled 17 cases are synthetic; these are not production accuracy estimates.',
                  'No training or fine-tuning performed. No claim of learned improvement.',
                  'Model initialization is outside timings; first index embedding work is included.',
                  'Only one no-match case; abstention performance is not established.'], 'methods':results}
    text=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text+'\n')
    print(text)

if __name__=='__main__':main()
