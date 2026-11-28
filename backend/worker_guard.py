"""Own a process group; stop it if its controller exits, cancels or times out."""
import argparse,os,signal,subprocess,sys,time

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=int,required=True);p.add_argument('--seconds',type=float,required=True);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    command=a.command[1:] if a.command[:1]==['--'] else a.command
    if not command:raise SystemExit('Missing worker command.')
    stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    process=subprocess.Popen(command,stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr,start_new_session=True)
    deadline=time.monotonic()+a.seconds
    while process.poll() is None and not stopped and os.getppid()==a.parent and time.monotonic()<deadline:time.sleep(.05)
    if process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=1)
        return 130 if stopped else 124
    return process.returncode
if __name__=='__main__':raise SystemExit(main())
