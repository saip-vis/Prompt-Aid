"""Small, hand-labeled fixture evaluation; not a measure of production quality."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from context import scan,bm25_search

def evaluate(search, cases):
    rankings=[]
    for case in cases:
        hits=search(case)
        paths=[]
        for hit in hits:
            path=hit[0].path
            if path not in paths:paths.append(path)
        relevant=set(case['relevant'])
        first=next((i+1 for i,p in enumerate(paths) if p in relevant),None)
        rankings.append({'id':case['id'],'project':case['project'],'expected':case['relevant'],'top':paths[:3],'reciprocal_rank':1/first if first else 0.0,'hit_at_1':bool(first==1),'hit_at_3':bool(first and first<=3),'abstained':not paths})
    positives=[r for r in rankings if r['expected']]
    empty=[r for r in rankings if not r['expected']]
    return {'queries':len(rankings),'positive_queries':len(positives),'recall_at_1':round(sum(r['hit_at_1'] for r in positives)/len(positives),4) if positives else None,'recall_at_3':round(sum(r['hit_at_3'] for r in positives)/len(positives),4) if positives else None,'mrr':round(sum(r['reciprocal_rank'] for r in positives)/len(positives),4) if positives else None,'no_match_queries':len(empty),'no_match_abstention':round(sum(r['abstained'] for r in empty)/len(empty),4) if empty else None,'results':rankings}

def main():
    p=argparse.ArgumentParser();p.add_argument('--method',choices=['bm25','qdrant'],default='bm25');p.add_argument('--project',choices=['cedar','harbor']);args=p.parse_args()
    cases=json.loads((ROOT/'evaluation/queries.json').read_text())
    if args.project:cases=[x for x in cases if x['project']==args.project]
    indexes={name:scan(ROOT/'evaluation/fixtures'/name)[0] for name in {c['project'] for c in cases}}
    if args.method=='qdrant':
        from vector import vector_search
        search=lambda case:vector_search(indexes[case['project']],case['query'],10)
    else:search=lambda case:bm25_search(indexes[case['project']],case['query'],10)
    report=evaluate(search,cases)
    print(json.dumps({'method':args.method,'dataset':'hand-authored synthetic fixtures','report':report},indent=2))
if __name__=='__main__':main()
