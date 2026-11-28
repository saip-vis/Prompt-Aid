"""Read an explicit project and JSON query file; output bounded retrieval evidence."""
import argparse
import json
import sys
from pathlib import Path
from context import bm25_search, format_result, scan

def main():
    p=argparse.ArgumentParser(description='Retrieve project context locally without making changes.')
    p.add_argument('--root',required=True,help='Explicit Git project directory to inspect')
    p.add_argument('--input',required=True,help='Private JSON query file, or - to read JSON from stdin')
    p.add_argument('--limit',type=int,default=5)
    p.add_argument('--method',choices=['bm25','qdrant'],default='bm25',help='qdrant is an optional experimental local vector search')
    args=p.parse_args()
    try:
        data=sys.stdin.buffer.read(24001) if args.input=='-' else Path(args.input).read_bytes()
        if len(data)>24000: raise ValueError('Query file is too large.')
        request=json.loads(data)
        if not isinstance(request,dict) or not isinstance(request.get('query'),str) or not request['query'].strip() or len(request['query'])>4000: raise ValueError('Provide a non-empty query up to 4000 characters.')
        chunks,warnings=scan(args.root)
        if args.method=='qdrant':
            try: from vector import vector_search
            except ImportError as exc: raise ValueError('Qdrant is not installed; use the default bm25 method.') from exc
            try: results=vector_search(chunks,request['query'],args.limit)
            except ImportError as exc: raise ValueError('Qdrant is not installed; use the default bm25 method.') from exc
        else: results=bm25_search(chunks,request['query'],args.limit)
        print(json.dumps(format_result(results,warnings,args.method),ensure_ascii=False))
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr);return 1
    return 0
if __name__=='__main__': sys.exit(main())
