"""Experimental Qdrant local-mode retrieval with corpus-fitted TF-IDF vectors.

This uses lexical vectors, not a pretrained semantic model. The in-memory
collection stores only vectors and numeric ids; source chunks stay in-process.
"""
from collections import Counter
import math
from context import tokenize

MAX_VOCAB=4096
MAX_VECTOR_CELLS=1_000_000

def tfidf_vectors(chunks, query):
    docs=[tokenize((c.path+' ')*2+c.text) for c in chunks]
    if not docs:return [],[]
    df=Counter(term for doc in docs for term in set(doc))
    vocab=sorted(df,key=lambda t:(-df[t],t))[:MAX_VOCAB]
    if len(docs)*len(vocab)>MAX_VECTOR_CELLS:
        raise ValueError('Project is too large for the in-memory vector experiment; use bm25.')
    idf={term:math.log((1+len(docs))/(1+df[term]))+1 for term in vocab}
    def encode(tokens):
        freq=Counter(tokens)
        return [(1+math.log(freq[t]))*idf[t] if freq[t] else 0.0 for t in vocab]
    return [encode(doc) for doc in docs],encode(tokenize(query))

def vector_search(chunks, query, limit=5):
    from qdrant_client import QdrantClient, models
    if not chunks or not tokenize(query):return []
    vectors,q=tfidf_vectors(chunks,query)
    if not q or not any(q):return []
    client=QdrantClient(':memory:')
    try:
        client.create_collection('context',vectors_config=models.VectorParams(size=len(q),distance=models.Distance.COSINE))
        points=[models.PointStruct(id=i,vector=v) for i,v in enumerate(vectors) if any(v)]
        if not points:return []
        client.upsert('context',points=points,wait=True)
        found=client.query_points('context',query=q,limit=max(1,min(limit,10)),with_payload=False).points
        return [(chunks[p.id],float(p.score)) for p in found if p.score>0.000001]
    finally:client.close()
