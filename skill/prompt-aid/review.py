"""Small stdlib-only launcher, atomic publisher, and bounded context helper."""
import argparse,json,os,subprocess,sys,tempfile,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def read_input():
    raw=sys.stdin.buffer.read(128001)
    if len(raw)>128000:raise ValueError('Review input is too large.')
    data=json.loads(raw)
    if not isinstance(data,dict):raise ValueError('Expected a JSON object.')
    return data

def validate(data,pending=False):
    original=data.get('original');improved=data.get('improved','')
    if not isinstance(original,str) or not original.strip() or len(original)>12000:raise ValueError('Invalid original request.')
    if not isinstance(improved,str) or len(improved)>16000 or (not pending and not improved.strip()):raise ValueError('Invalid suggested prompt.')
    if data.get('projectRoot') is not None and (not isinstance(data['projectRoot'],str) or not Path(data['projectRoot']).is_absolute()):raise ValueError('Choose an explicit absolute project root.')
    for field in ['changes','questions','limitations','evidence','assumptions']:
        if field in data and (not isinstance(data[field],list) or any(not isinstance(x,str) for x in data[field])):raise ValueError('Invalid review notes.')

def publish(path,data):
    info=path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_uid!=os.getuid() or info.st_mode & 0o077:raise ValueError('Use the private review_file returned by open.')
    previous=json.loads(path.read_text());validate(data)
    if not previous.get('pending') or previous['original']!=data['original'] or previous.get('projectRoot')!=data.get('projectRoot'):raise ValueError('Final review must retain the original request and project.')
    data={**data,'pending':False}
    raw=json.dumps(data,ensure_ascii=False).encode()
    if len(raw)>128000:raise ValueError('Review input is too large.')
    fd,name=tempfile.mkstemp(prefix='ready-',suffix='.json',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
        os.replace(name,path)
    finally:Path(name).unlink(missing_ok=True)

def open_review(data,metrics=None):
    validate(data,pending=True)
    payload={'original':data['original'],'improved':'','pending':True,**{k:[] for k in ['changes','questions','limitations','evidence']}}
    if data.get('projectRoot') is not None:payload['projectRoot']=data['projectRoot']
    with tempfile.TemporaryDirectory(prefix='prompt-aid-review-') as directory:
        path=Path(directory)/'review.json';path.write_text(json.dumps(payload));path.chmod(0o600)
        print(json.dumps({'event':'review_starting','review_file':str(path)}),flush=True)
        env=dict(os.environ)
        if metrics:env['PROMPT_AID_LAUNCH_METRICS']=str(metrics)
        result=subprocess.run([str(HERE/'Prompt Aid.app/Contents/MacOS/PromptAid'),str(path)],env=env)
        if result.returncode:raise ValueError('Native window failed; present the review in chat and wait for the user.')

def context(data,limit,workspace=False):
    root=data.get('root');query=data.get('query')
    if not isinstance(root,str) or not Path(root).is_absolute():raise ValueError('Choose an explicit absolute project root.')
    if not isinstance(query,str) or not query.strip() or len(query)>4000:raise ValueError('Provide a bounded nonempty query.')
    started=time.perf_counter()
    sys.path.insert(0,str(HERE/'retrieval'))
    from context import scan,bm25_search,format_result
    result=None;warning=None
    if workspace:
        from workspace import via_service
        from types import SimpleNamespace
        directory=Path(os.environ.get('PROMPT_AID_DATA',str(Path.home()/'.local/share/prompt-aid')))
        args=SimpleNamespace(data=directory,action='search')
        try:result=via_service(args,str(Path(root).resolve(strict=True)),{'query':query,'method':'bm25','limit':limit},timeout=3)
        except (OSError,ValueError):warning='Configured workspace was unavailable; used a fresh lexical scan.'
    if result is None:
        chunks,warnings=scan(root)
        result=format_result(bm25_search(chunks,query,limit),warnings)
        if warning:result['warnings'].append(warning)
    result.setdefault('timings',{})['context_helper_ms']=round((time.perf_counter()-started)*1000,2)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['open','publish','context']);p.add_argument('--review-file',type=Path);p.add_argument('--metrics',type=Path);p.add_argument('--workspace',action='store_true',help='Use configured service; default avoids service overhead for one-off reviews');p.add_argument('--limit',type=int,choices=range(1,6),default=3);args=p.parse_args()
    try:
        data=read_input()
        if args.action=='open':open_review(data,args.metrics)
        elif args.action=='publish':
            if args.review_file is None:raise ValueError('Provide --review-file from the running window.')
            publish(args.review_file,data);print('{"status":"ready"}')
        else:print(json.dumps(context(data,args.limit,args.workspace),ensure_ascii=False))
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
