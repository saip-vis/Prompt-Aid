import json,os,signal,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from store import Store
from backend.builds import BuildStore,BuildController,TERMINAL
from backend.build_api import StartBuild

def fixture(path):
    path.mkdir();subprocess.run(['git','init','-q',str(path)],check=True)
    (path/'README.md').write_text('A disposable build fixture.\n')
    subprocess.run(['git','-C',str(path),'add','.'],check=True)
    subprocess.run(['git','-C',str(path),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture'],check=True)

def wait(controller,id):
    deadline=time.monotonic()+6
    while time.monotonic()<deadline:
        job=controller.store.get(id)
        if job['state'] in TERMINAL:return job
        time.sleep(.02)
    raise AssertionError('Controller did not finish: '+str(controller.store.get(id)))

class BuildFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.directory=Path(self.temp.name);self.root=self.directory/'repo';fixture(self.root)
        self.workspace=Store(self.directory/'data',[self.root]);self.store=BuildStore(self.directory/'data',self.workspace);self.controllers=[]
    def tearDown(self):
        for controller in self.controllers:controller.close()
        self.store.close();self.workspace.close();self.temp.cleanup()
    def spec(self,**updates):
        return StartBuild.model_validate({'root':str(self.root),'goal':'Create result.txt containing ready.','constraints':['Preserve README.md.'],'checks':[{'kind':'file_contains','label':'Output text','path':'result.txt','text':'ready'}],'max_turns':3,'max_seconds':30,'approved':True,**updates}).model_dump()
    def controller(self,worker,check_runner=None):
        controller=BuildController(self.store,worker_factory=worker,check_runner=check_runner);self.controllers.append(controller);return controller

class BuildTests(BuildFixture):
    def test_verified_result_retains_worktree_without_touching_source(self):
        def worker(prompt,root,turn,stop):
            self.assertIn('Preserve README.md',prompt);(root/'result.txt').write_text('ready')
            return {'status':'completed','summary':'Created the file.','question':''}
        controller=self.controller(worker);job=controller.start(self.spec());final=wait(controller,job['id'])
        self.assertEqual(final['state'],'checks_passed');self.assertFalse((self.root/'result.txt').exists())
        self.assertIn('ready',controller.diff(job['id']));self.assertTrue(final['payload']['checks'][0]['passed'])
        self.assertEqual(controller.stop(job['id'])['state'],'checks_passed')
    def test_failed_check_causes_targeted_correction_then_pass(self):
        calls=[]
        def worker(prompt,root,turn,stop):
            calls.append(prompt);(root/'result.txt').write_text('wrong' if turn==1 else 'ready')
            return {'status':'completed','summary':'Attempt '+str(turn),'question':''}
        controller=self.controller(worker);job=controller.start(self.spec());final=wait(controller,job['id'])
        self.assertEqual(final['state'],'checks_passed');self.assertEqual(len(calls),2);self.assertIn('Required text missing.',calls[1])
        self.assertTrue(any(e['kind']=='correction' for e in self.store.events(job['id'])))
    def test_stalled_worker_and_turn_budget_stop_the_loop(self):
        def worker(*_):return {'status':'completed','summary':'Done','question':''}
        controller=self.controller(worker);job=controller.start(self.spec(max_turns=5));final=wait(controller,job['id'])
        self.assertEqual(final['state'],'needs_input');self.assertEqual(final['payload']['turn'],2)
        job=controller.start(self.spec(max_turns=1));self.assertEqual(wait(controller,job['id'])['state'],'budget_exhausted')
    def test_question_pauses_without_running_checks(self):
        controller=self.controller(lambda *_:{'status':'needs_input','summary':'Need a decision.','question':'Which output format?'})
        job=controller.start(self.spec());final=wait(controller,job['id']);self.assertEqual(final['state'],'needs_input');self.assertEqual(final['payload']['checks'],[])
    def test_stop_prevents_checks_and_further_worker_turns(self):
        entered=threading.Event();calls=[]
        def worker(prompt,root,turn,stop):
            calls.append(turn);entered.set();stop.wait(3);return {'status':'completed','summary':'Interrupted','question':''}
        controller=self.controller(worker);job=controller.start(self.spec());self.assertTrue(entered.wait(3))
        with self.assertRaises(ValueError):controller.start(self.spec())
        controller.stop(job['id']);final=wait(controller,job['id'])
        self.assertEqual(final['state'],'stopped');self.assertEqual(calls,[1]);self.assertEqual(final['payload']['checks'],[])
    def test_approval_dirty_root_and_path_escape_are_rejected(self):
        controller=self.controller(lambda *_:None)
        bad=self.spec();bad['approved']=False
        with self.assertRaises(ValueError):controller.start(bad)
        (self.root/'uncommitted.txt').write_text('user edits')
        with self.assertRaises(ValueError):controller.start(self.spec())
        for path in ['../outside.txt','/tmp/outside.txt']:
            with self.assertRaises(ValueError):self.spec(checks=[{'kind':'file_exists','label':'Bad','path':path}])
    def test_recovery_does_not_restart_and_project_reads_are_isolated(self):
        job=self.store.create(self.spec());self.store.update(job['id'],'working')
        self.store.close()
        recovered=BuildStore(self.directory/'data',self.workspace)
        self.assertEqual(recovered.get(job['id'])['state'],'needs_input')
        recovered.close()
        other=self.directory/'other';fixture(other);restricted=Store(self.directory/'data',[other])
        try:
            private=BuildStore(self.directory/'data',restricted)
            with self.assertRaises(ValueError):private.get(job['id'])
            self.assertEqual(private.list(),[]);private.close()
        finally:restricted.close()
    def test_symlink_check_does_not_read_outside_worktree(self):
        def worker(prompt,root,turn,stop):
            (root/'result.txt').symlink_to(self.root/'README.md');return {'status':'completed','summary':'Done','question':''}
        controller=self.controller(worker);job=controller.start(self.spec());final=wait(controller,job['id']);self.assertEqual(final['state'],'failed');self.assertIn('symlink',final['payload']['message'])

class WatchdogTests(unittest.TestCase):
    def test_dead_controller_and_timeout_stop_the_child(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'should-not-exist'
            child=[sys.executable,'-c','import time;from pathlib import Path;time.sleep(.5);Path('+repr(str(marker))+').write_text("escaped")']
            guard=[sys.executable,str(ROOT/'backend/worker_guard.py')]
            for parent,seconds in [(os.getpid()+100000,3),(os.getpid(),.05)]:
                result=subprocess.run(guard+['--parent',str(parent),'--seconds',str(seconds),'--',*child],timeout=4)
                self.assertEqual(result.returncode,124);self.assertFalse(marker.exists())

class ResumeBuildTests(BuildFixture):
    def test_user_answer_continues_same_worktree_with_remaining_budget(self):
        def worker(prompt,root,turn,stop):
            if turn==1:
                (root/'partial.txt').write_text('retained')
                return {'status':'needs_input','summary':'Need content.','question':'What content?'}
            self.assertTrue((root/'partial.txt').exists());self.assertIn('Use ready',prompt)
            (root/'result.txt').write_text('ready');return {'status':'completed','summary':'Completed','question':''}
        controller=self.controller(worker);job=controller.start(self.spec());first=wait(controller,job['id'])
        time.sleep(.03)
        controller.resume(job['id'],'Use ready',30);second=wait(controller,job['id'])
        self.assertEqual(second['state'],'checks_passed');self.assertEqual(second['payload']['turn'],2)
        self.assertEqual(second['payload']['worktree'],first['payload']['worktree'])

class BuildAPITests(BuildFixture):
    def test_approval_authentication_and_project_scoped_build_routes(self):
        from backend.app import create_app
        from fastapi.testclient import TestClient
        def worker(prompt,root,turn,stop):
            (root/'result.txt').write_text('ready');return {'status':'completed','summary':'Created output','question':''}
        controller=self.controller(worker)
        with TestClient(create_app(self.workspace,'x'*40,controller),base_url='http://127.0.0.1') as client:
            headers={'Authorization':'Bearer '+'x'*40}
            self.assertEqual(client.get('/builds/config').status_code,401)
            for approval in [False,1,'true']:
                self.assertEqual(client.post('/builds',headers=headers,json={**self.spec(),'approved':approval}).status_code,422)
            self.assertEqual(client.post('/builds',headers=headers,json={**self.spec(),'root':str(self.directory)}).status_code,400)
            response=client.post('/builds',headers=headers,json=self.spec());self.assertEqual(response.status_code,200)
            id=response.json()['id'];wait(controller,id)
            self.assertEqual(client.get('/builds/'+id,headers=headers).json()['state'],'checks_passed')
            self.assertTrue(client.get('/builds/'+id+'/events',headers=headers).json()['events'])
            self.assertIn('ready',client.get('/builds/'+id+'/diff',headers=headers).json()['diff'])
            self.assertEqual(client.post('/builds/'+id+'/resume',headers=headers,json={'answer':'go','approved':False}).status_code,422)

class ProcessCancellationTests(BuildFixture):
    def test_stop_event_terminates_owned_process_group(self):
        controller=self.controller(lambda *_:None);job=self.store.create(self.spec());stop=threading.Event();errors=[]
        (self.directory/'tmp').mkdir();marker=self.root/'child-pid'
        command=[sys.executable,'-c','import os,time;from pathlib import Path;Path('+repr(str(marker))+').write_text(str(os.getpid()));time.sleep(20)']
        def run():
            try:controller._process(job['id'],command,self.root,'',stop,time.monotonic()+10)
            except InterruptedError as exc:errors.append(str(exc))
        thread=threading.Thread(target=run);thread.start();deadline=time.monotonic()+4
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(marker.exists());pid=int(marker.read_text());stop.set();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,['Stopped.'])
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)
