import time
import unittest
from pathlib import Path
from unittest.mock import patch
from test_builds import BuildFixture, wait
from backend.builds import BuildController, BuildStore
from backend.build_evidence import check_status, outcome, worktree_stamp
from backend.build_runtime import runtime_probe, runtime_reads


class EvidenceTests(BuildFixture):
    def worker(self, prompt, root, turn, stop):
        (root/'result.txt').write_text('ready')
        return {'status':'completed','summary':'Claims all behavior works.','question':''}

    def test_passing_regressions_do_not_verify_the_goal(self):
        controller=self.controller(self.worker)
        job=controller.start(self.spec(acceptance_criteria=['Copies the saved prompt.','Shows a confirmation.']))
        final=wait(controller,job['id'])
        self.assertEqual(final['state'],'needs_review')
        self.assertEqual(final['outcome']['code'],'needs_review')
        self.assertTrue(all(c['status']=='pending' for c in final['payload']['criteria']))
        with self.assertRaises(ValueError):controller.attest(job['id'],0,' ')
        controller.attest(job['id'],0,'Clicked Copy and compared the clipboard with the saved text.')
        self.assertEqual(self.store.get(job['id'])['state'],'needs_review')
        verified=controller.attest(job['id'],1,'Observed Copied, then the label reset.')
        self.assertEqual(verified['outcome']['code'],'verified')
        self.assertEqual(verified['payload']['criteria'][1]['source'],'user')
        (Path(verified['payload']['worktree'])/'result.txt').write_text('modified after confirmation')
        self.assertEqual(self.store.get(job['id'])['outcome']['code'],'needs_review')
        with self.assertRaises(ValueError):controller.attest(job['id'],1,'Old observation')

    def test_preflight_failure_spends_no_worker_turn(self):
        calls=[]
        controller=BuildController(self.store,worker_factory=lambda *args:calls.append(args),
            preflight_runner=lambda *_:[{'label':'Python tests','status':'blocked','reason':'Runtime missing','details':'Library not loaded'}])
        self.controllers.append(controller)
        job=controller.start(self.spec());final=wait(controller,job['id'])
        self.assertEqual(final['state'],'blocked_setup');self.assertEqual(final['payload']['turn'],0)
        self.assertFalse(calls);self.assertEqual(final['outcome']['title'],'Blocked by setup')
        self.assertEqual(self.store.environment(self.root)['results']['preflight'][0]['status'],'blocked')
        with self.assertRaises(ValueError):controller.attest(job['id'],0,'Claimed success')

    def test_checks_that_change_work_cannot_supply_fresh_verification(self):
        def check(spec,root,stop):
            (root/'result.txt').write_text('changed while testing')
            return 0,'Ran 1 test\nOK'
        controller=self.controller(self.worker,check_runner=check)
        job=controller.start(self.spec(checks=[{'kind':'command','label':'Tests','argv':['python3','-m','unittest']}]))
        final=wait(controller,job['id'])
        self.assertEqual(final['state'],'needs_review');self.assertIsNone(final['payload']['check_stamp'])
        with self.assertRaises(ValueError):controller.attest(job['id'],0,'Looks fine')

    def test_setup_failure_after_worker_does_not_trigger_correction(self):
        calls=[]
        def worker(*args):calls.append(1);return self.worker(*args)
        controller=self.controller(worker,check_runner=lambda *_:(1,'dyld: Library not loaded: Python (blocked by sandbox)'))
        job=controller.start(self.spec(checks=[{'kind':'command','label':'Python tests','argv':['python3','-m','unittest']}]))
        final=wait(controller,job['id'])
        self.assertEqual(final['state'],'blocked_setup');self.assertEqual(calls,[1])
        self.assertEqual(final['payload']['checks'][0]['status'],'blocked')
        # Fixing setup can rerun checks without a second coding/model call.
        controller.check_runner=lambda *_:(0,'Ran 4 tests\nOK')
        time.sleep(.03);controller.recheck(job['id'],30);checked=wait(controller,job['id'])
        self.assertEqual(checked['state'],'needs_review');self.assertEqual(calls,[1])
        self.assertEqual(checked['payload']['worktree'],final['payload']['worktree'])
        self.assertTrue(checked['payload']['checks'][0]['passed'])
        self.assertEqual(self.store.environment(self.root)['results']['checks'][0]['status'],'passed')

    def test_memory_is_project_scoped_and_persistent(self):
        self.store.remember_environment(self.root,'preflight',[{'label':'Python','status':'ready','reason':''}])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM environment_memory').fetchone()[0],1)
        self.assertEqual(self.store.environment(self.root)['results']['preflight'][0]['label'],'Python')
        self.store.close();self.store=BuildStore(self.directory/'data',self.workspace)
        self.assertEqual(self.store.environment(self.root)['results']['preflight'][0]['status'],'ready')
        with self.assertRaises(ValueError):self.store.environment(self.directory)

    def test_legacy_blocked_checks_are_honestly_classified(self):
        legacy={'state':'budget_exhausted','payload':{'message':'Turn budget reached','checks':[{'passed':False,'details':'Library not loaded: Python (blocked by sandbox)'}]}}
        self.assertEqual(outcome(legacy)['code'],'blocked_setup')
        self.assertEqual(check_status(0,'Ran 0 tests\nOK')[0],'failed')
        self.assertEqual(check_status(1,'AssertionError: expected copied text')[0],'failed')
        self.assertEqual(check_status(0,'Ran 5 tests\nOK')[0],'passed')
        self.assertEqual(runtime_probe({'kind':'command','argv':['./custom-check','test']}),None)
        self.assertIn('import pytest',runtime_probe({'kind':'command','argv':['python3','-m','pytest']})[-1])
        with patch('backend.build_runtime.sys.executable','/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14'),patch.object(Path,'is_file',return_value=True),patch.object(Path,'resolve',lambda path:path):
            self.assertEqual(runtime_reads(Path('/project'),[]),['/Library/Frameworks/Python.framework/Versions/3.14'])

    def test_api_requires_explicit_manual_observation_and_recheck_approval(self):
        from backend.app import create_app
        from fastapi.testclient import TestClient
        controller=self.controller(self.worker)
        with TestClient(create_app(self.workspace,'x'*40,controller),base_url='http://127.0.0.1') as client:
            headers={'Authorization':'Bearer '+'x'*40}
            job=controller.start(self.spec());wait(controller,job['id'])
            route='/builds/'+job['id']
            self.assertEqual(client.post(route+'/criteria/0/confirm',json={'approved':True,'evidence':'Observed ready'}).status_code,401)
            for approval in [False,1,'true']:
                self.assertEqual(client.post(route+'/criteria/0/confirm',headers=headers,json={'approved':approval,'evidence':'Observed ready'}).status_code,422)
            verified=client.post(route+'/criteria/0/confirm',headers=headers,json={'approved':True,'evidence':'Opened result.txt and confirmed ready.'})
            self.assertEqual(verified.json()['outcome']['code'],'verified')
            self.assertEqual(client.post(route+'/recheck',headers=headers,json={'approved':False}).status_code,422)
            self.assertEqual(client.post(route+'/recheck',headers=headers,json={'approved':True,'max_seconds':30}).status_code,200)
            wait(controller,job['id'])
            self.assertEqual(self.store.get(job['id'])['payload']['criteria'][0]['status'],'pending')

    def test_stamp_changes_for_tracked_untracked_and_deleted_content(self):
        initial=worktree_stamp(self.root)
        (self.root/'new.txt').write_text('one');added=worktree_stamp(self.root)
        self.assertNotEqual(initial,added)
        (self.root/'new.txt').write_text('two');self.assertNotEqual(added,worktree_stamp(self.root))
        (self.root/'new.txt').unlink();(self.root/'README.md').unlink()
        self.assertNotEqual(initial,worktree_stamp(self.root))
        (self.root/'link').symlink_to(self.directory/'outside')
        self.assertIsNotNone(worktree_stamp(self.root))
