"""User-clicked reconnect using only previously configured, explicitly allowed roots."""
import argparse,json,os
from pathlib import Path
import subprocess,sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);a=p.parse_args()
    path=Path.home()/'.local/share/prompt-aid/runtime.json'
    try:
        info=path.lstat()
        if path.is_symlink() or not path.is_file() or info.st_uid!=os.getuid() or info.st_mode & 0o077 or info.st_size>16000:raise ValueError('Invalid private runtime configuration.')
        config=json.loads(path.read_text());settings=config['settings']
        if str(Path(a.project).resolve(strict=True)) not in settings['roots']:raise ValueError('Project is not configured for local context.')
        command=[config['python'],'-m','backend.manage','start','--data',config['data'],'--port',str(settings['port'])]
        for root in settings['roots']:command+=['--root',root]
        for name in ['embedding_model','reranker_model']:
            if settings.get(name):command+=['--'+name.replace('_','-'),settings[name]]
        return subprocess.run(command,cwd=config['repository'],timeout=20).returncode
    except FileNotFoundError:
        print('Set up local context once with: .venv/bin/python -m backend.manage start --root /your/project',file=sys.stderr);return 1
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        print(str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
