"""JSON bridge for persistent local context; no project code is executed."""
import argparse
import json
from pathlib import Path
import sys
from store import Store



def via_service(args, root, body, timeout=55):
    """Reuse the one local Qdrant owner; never silently fall back on a live lock."""
    connection = args.data / 'connection.json'
    if not connection.exists():
        return None
    from connection import read_private, request
    config = read_private(connection)
    if root not in config['settings']['roots']:
        raise ValueError('Project is not configured in the running workspace service.')
    def call(route, payload=None):
        try:return request(config,route,payload,timeout=timeout)
        except OSError as exc:
            raise ValueError('Workspace service is offline. Start / reconnect it before using context tools.') from exc
    if args.action == 'search':
        return call('/context/search', {'root':root, **{k:body[k] for k in ['query','method','limit','rerank','excluded_paths'] if k in body}})
    report = call('/projects/index', {'root':root})
    project = report['project_id']
    if args.action == 'index': return report
    if args.action == 'verify': return call('/sources/verify', {'project_id':project, 'sources':body.get('sources',[])})
    if args.action == 'history': return call('/reviews?project_id='+project)
    if args.action == 'save':
        return call('/reviews', {**body['review'], 'project_id':project, **({'parent_id':body['parent_id']} if body.get('parent_id') else {})})
    review_id = body['review_id']
    # Keep path data bounded to UUIDs, and enforce the caller's selected project.
    from uuid import UUID
    review_id = str(UUID(review_id))
    if call('/reviews/'+review_id)['project'] != project: raise ValueError('Review belongs to another project.')
    return call('/reviews/'+review_id+'/feedback', {k:body[k] for k in ['outcome','edited_prompt'] if k in body})

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--action', choices=['index','search','verify','history','save','feedback'], default='search')
    p.add_argument('--allowed-roots', help='JSON array of explicitly allowed project roots')
    p.add_argument('--embedding-model', type=Path)
    p.add_argument('--reranker-model', type=Path)
    args = p.parse_args()
    try:
        raw = sys.stdin.buffer.read(128001)
        if len(raw) > 128000:
            raise ValueError('Request too large.')
        body = json.loads(raw or '{}')
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object.')
        allowed = {str(Path(r).resolve(strict=True)) for r in json.loads(args.allowed_roots)} if args.allowed_roots else {str(Path(args.root).resolve(strict=True))}
        root = str(Path(args.root).resolve(strict=True))
        if root not in allowed:
            raise ValueError('Project is not one of the explicitly configured roots.')
        result = via_service(args, root, body)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False))
            return 0
        semantic = reranker = None
        if args.embedding_model:
            from semantic import LocalSemantic
            semantic = LocalSemantic(args.data/'vectors', args.embedding_model)
        if args.reranker_model:
            from semantic import LocalReranker
            reranker = LocalReranker(args.reranker_model)
        store = Store(args.data, json.loads(args.allowed_roots) if args.allowed_roots else [args.root], semantic, reranker)
        root = store.root(args.root)
        if args.action == 'index':
            result = store.index(root)
        elif args.action == 'search':
            result = store.search(query=body.get('query'), root=root, method=body.get('method','bm25'), limit=body.get('limit',5), rerank=body.get('rerank',False), excluded_paths=body.get('excluded_paths',[]))
        else:
            report = store.index(root)
            project = report['project_id']
            if args.action == 'verify':
                result = {'sources': store.verify(project, body.get('sources',[]))}
            elif args.action == 'history':
                result = {'reviews': store.history(project)}
            elif args.action == 'save':
                result = store.save_review(project, body['review'], body.get('parent_id'))
            else:
                # Do not permit feedback to leak another configured project's review.
                if store.review(body['review_id'])['project'] != project:
                    raise ValueError('Review belongs to another project.')
                result = store.feedback(body['review_id'], body['outcome'], body.get('edited_prompt'))
        store.close()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
