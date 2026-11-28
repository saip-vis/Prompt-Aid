"""Start/reuse/stop the explicitly configured loopback workspace (no login daemon)."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

DATA = Path.home()/'.local/share/prompt-aid'
ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from connection import write_private,read_private,health


def start(args):
    roots=sorted({str(Path(x).expanduser().resolve(strict=True)) for x in args.root})
    for root in roots:
        subprocess.run(['git','-C',root,'rev-parse','--show-toplevel'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    connection=args.data/'connection.json'
    wanted={'roots':roots,'embedding_model':str(args.embedding_model.resolve()) if args.embedding_model else None,'reranker_model':str(args.reranker_model.resolve()) if args.reranker_model else None,'port':args.port}
    for name in ('embedding_model','reranker_model'):
        if wanted[name] and not Path(wanted[name]).is_dir():raise ValueError('Configured local model directory is unavailable.')
    if connection.exists():
        old=read_private(connection)
        try:state=health(old)
        except (OSError,urllib.error.URLError):state=None
        if state:
            if old.get('settings') != wanted:raise ValueError('Workspace is running with different roots/models. Stop it before changing configuration.')
            return {'status':'reused','url':old['url'],'health':state}
    cmd=[sys.executable,'-m','backend.app','--data',str(args.data),'--port',str(args.port)]
    for root in roots:cmd+=['--root',root]
    if wanted['embedding_model']:cmd+=['--embedding-model',wanted['embedding_model']]
    if wanted['reranker_model']:cmd+=['--reranker-model',wanted['reranker_model']]
    log=args.data/'service.log';fd=os.open(log,os.O_CREAT|os.O_APPEND|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        os.fchmod(fd,0o600)
        process=subprocess.Popen(cmd,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=fd,stderr=fd,start_new_session=True,env={**os.environ,'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false'})
    finally:os.close(fd)
    config={'url':f'http://127.0.0.1:{args.port}','token_file':str(args.data/'api-token'),'pid':process.pid,'settings':wanted}
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if process.poll() is not None:raise ValueError('Workspace could not start. See the private service.log (the port may already be in use).')
            try:
                state=health(config)
                # Never attach to another process that happens to use this port.
                if state.get('pid')==process.pid:break
            except (OSError,urllib.error.URLError):pass
            time.sleep(.05)
        else:raise ValueError('Workspace did not become ready in 15 seconds.')
        write_private(connection,config)
        runtime={'python':sys.executable,'repository':str(ROOT),'data':str(args.data),'settings':wanted}
        write_private(args.data/'runtime.json',runtime)
        return {'status':'started','url':config['url'],'health':state}
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','status','stop']);p.add_argument('--root',action='append',default=[]);p.add_argument('--data',type=Path,default=DATA);p.add_argument('--port',type=int,default=4318);p.add_argument('--embedding-model',type=Path);p.add_argument('--reranker-model',type=Path);a=p.parse_args()
    a.data=a.data.expanduser().resolve();a.data.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(a.data/'manager.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if a.action=='start':
                if not a.root:raise ValueError('Choose at least one explicit Git project with --root.')
                result=start(a)
            else:
                c=read_private(a.data/'connection.json');state=health(c)
                if a.action=='stop':
                    if state.get('pid')!=c['pid']:raise ValueError('Workspace process identity changed; no process was stopped.')
                    os.kill(c['pid'],signal.SIGTERM)
                    deadline=time.monotonic()+10
                    while time.monotonic()<deadline:
                        try:health(c)
                        except OSError:
                            # Listener shutdown precedes resource/worker cleanup.
                            # Wait for process exit (or zombie state) before reuse.
                            state=subprocess.run(['ps','-p',str(c['pid']),'-o','stat='],capture_output=True,text=True,timeout=1)
                            if not state.stdout.strip() or state.stdout.strip().startswith('Z'):break
                        time.sleep(.05)
                    else:raise ValueError('Workspace is still shutting down; retry status before restarting.')
                    (a.data/'connection.json').unlink(missing_ok=True);result={'status':'stopped'}
                else:result={'status':'running','health':state,'url':c['url']}
        print(json.dumps(result))
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print('Workspace: '+str(exc),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
