"""Install this checkout's native app and skill without copying models or credentials."""
from pathlib import Path
import argparse,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,default=Path.home()/'.codex/skills/prompt-aid');p.add_argument('--no-build',action='store_true');a=p.parse_args()
if not a.no_build:subprocess.run([str(ROOT/'native/build.sh')],check=True)
source=ROOT/'skill/prompt-aid';dest=a.destination.expanduser()
if dest.resolve()==source.resolve():raise SystemExit('Choose a separate installation directory.')
if dest.exists():
    backup=Path(tempfile.mkdtemp(prefix='prompt-aid-install-backup-'))
    shutil.copytree(dest,backup/'prompt-aid',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    print('Previous installation backed up to',backup)
dest.mkdir(parents=True,exist_ok=True)
shutil.copytree(source,dest,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
print('Installed Prompt Aid app, skill, and retrieval helpers at',dest)
