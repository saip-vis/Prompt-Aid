"""Opt-in real Codex Build-mode smoke test on a disposable, retained Git fixture."""
import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from store import Store
from backend.builds import BuildStore,BuildController,TERMINAL
from backend.build_api import StartBuild

def main():
    directory=ROOT/'.prompt-aid/build-smoke';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    root=directory/'project'
    if not root.exists():
        root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
        (root/'math_utils.py').write_text('def add(a, b):\n    return a - b\n')
        (root/'test_math_utils.py').write_text('import unittest\nfrom math_utils import add\nclass Addition(unittest.TestCase):\n    def test_integers(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(-2, 3), 1)\n')
        subprocess.run(['git','-C',str(root),'add','.'],check=True)
        subprocess.run(['git','-C',str(root),'-c','user.name=Prompt Aid Demo','-c','user.email=demo@example.invalid','commit','-qm','Disposable failing-addition fixture'],check=True)
    workspace=Store(directory/'data',[root]);store=BuildStore(directory/'data',workspace);controller=BuildController(store)
    spec=StartBuild.model_validate({'root':str(root),'goal':'Fix add(a, b) to return the sum of its two integer arguments.','constraints':['Preserve the existing test file.','Do not add dependencies.'],'checks':[{'kind':'command','label':'Addition tests','argv':['/usr/bin/python3','-m','unittest','-v']}],'max_turns':2,'max_seconds':180,'approved':True}).model_dump()
    try:
        job=controller.start(spec);print('Build:',job['id'],flush=True)
        while True:
            job=store.get(job['id'])
            if job['state'] in TERMINAL:break
            time.sleep(.5)
        print(json.dumps(job,indent=2),flush=True)
        print('DIFF\n'+controller.diff(job['id']))
        assert job['state']=='checks_passed',store.events(job['id'])
        assert 'a - b' in (root/'math_utils.py').read_text(),'Source project was modified.'
        (directory/'last-result.json').write_text(json.dumps(job,indent=2))
    finally:controller.close();workspace.close()
if __name__=='__main__':main()
