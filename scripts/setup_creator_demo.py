"""Create a separate clean Git demo project from synthetic bundled templates."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def create(directory):
    directory=Path(directory).expanduser().resolve()
    if directory.exists() and any(directory.iterdir()):
        marker=directory/'.promptaid-demo.json'
        if marker.is_file() and json.loads(marker.read_text()).get('demo')=='creator-inbox-v1':return directory
        raise ValueError('Choose an empty directory; existing files will not be overwritten.')
    directory.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'demo/creator-inbox').iterdir():
        if source.is_file():shutil.copy2(source,directory/source.name)
    (directory/'.promptaid-demo.json').write_text(json.dumps({'demo':'creator-inbox-v1','synthetic':True})+'\n')
    (directory/'.gitignore').write_text('__pycache__/\n*.pyc\n')
    def git(*args):subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(directory),*args],check=True,capture_output=True)
    git('init','-q');git('add','.')
    git('-c','user.name=Prompt Aid Demo','-c','user.email=demo@example.invalid','commit','-qm','Seed fictional creator inbox with deliberately flawed extractor')
    return directory


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,default=ROOT/'.prompt-aid/creator-inbox')
    print(create(parser.parse_args().directory))
