"""Train a tiny pairwise reranker on one synthetic project, evaluate another.

Research/demo only: small hand-authored labels are not production training data.
"""
from __future__ import annotations
import argparse,json,random,sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from context import scan,bm25_search,tokenize
from evaluate import evaluate
import torch
from torch import nn


def features(query,chunk,score):
    q=set(tokenize(query)); terms=tokenize(chunk.text); doc=set(terms); path=set(tokenize(chunk.path))
    overlap=len(q & doc); n=max(1,len(q))
    return [score/(1+score),overlap/n,len(q & path)/n,overlap/max(1,len(doc))]

def candidates(index,query):
    return bm25_search(index,query,10)

def train(cases,index,epochs=100):
    torch.manual_seed(7);random.seed(7);torch.set_num_threads(1)
    model=nn.Sequential(nn.Linear(4,8),nn.Tanh(),nn.Linear(8,1))
    opt=torch.optim.Adam(model.parameters(),lr=0.02)
    pairs=[];uncovered=[]
    for case in cases:
        hits=candidates(index,case['query']); positives=[features(case['query'],c,s) for c,s in hits if c.path in case['relevant']];negatives=[features(case['query'],c,s) for c,s in hits if c.path not in case['relevant']]
        if not positives and case['relevant']: uncovered.append(case['id'])
        for pos in positives:
            for neg in negatives:pairs.append((pos,neg))
    if not pairs:raise ValueError('No positive/negative training pairs available.')
    x_pos=torch.tensor([p for p,_ in pairs],dtype=torch.float32);x_neg=torch.tensor([n for _,n in pairs],dtype=torch.float32)
    for _ in range(epochs):
        opt.zero_grad(); loss=torch.nn.functional.softplus(-(model(x_pos)-model(x_neg))).mean(); loss.backward();opt.step()
    model.eval()
    return model,{'pairs':len(pairs),'train_queries':len(cases),'uncovered_train_queries':uncovered,'epochs':epochs,'seed':7}

def rerank(model, index, query):
    hits=candidates(index,query)
    if not hits:return []
    x=torch.tensor([features(query,c,s) for c,s in hits],dtype=torch.float32)
    with torch.no_grad():scores=model(x).reshape(-1).tolist()
    return [(c,float(value)) for (c,_),value in sorted(zip(hits,scores),key=lambda x:(-x[1],x[0][0].path,x[0][0].line_start))]

def main():
    p=argparse.ArgumentParser();p.add_argument('--train-project',choices=['cedar','harbor'],default='cedar');p.add_argument('--test-project',choices=['cedar','harbor'],default='harbor');p.add_argument('--output',type=Path,help='Optional path for experiment report JSON');args=p.parse_args()
    if args.train_project==args.test_project:p.error('Train and test projects must differ.')
    cases=json.loads((ROOT/'evaluation/queries.json').read_text()); train_cases=[c for c in cases if c['project']==args.train_project];test_cases=[c for c in cases if c['project']==args.test_project]
    train_index=scan(ROOT/'evaluation/fixtures'/args.train_project)[0];test_index=scan(ROOT/'evaluation/fixtures'/args.test_project)[0]
    model,training=train(train_cases,train_index)
    baseline=evaluate(lambda c:candidates(test_index,c['query']),test_cases)
    experiment=evaluate(lambda c:rerank(model,test_index,c['query']),test_cases)
    payload={'dataset':'hand-authored synthetic fixtures; no external training data','train_project':args.train_project,'held_out_project':args.test_project,'training':training,'torch_version':torch.__version__,'baseline_bm25':baseline,'torch_reranker':experiment,'limitations':['Small synthetic benchmark; not evidence of real-world improvement.','Reranker can only reorder lexical candidates and cannot recover documents missed by candidate retrieval.','Experimental model is not used by the skill by default.']}
    data=json.dumps(payload,indent=2)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(data+'\n')
    print(data)
if __name__=='__main__':main()
