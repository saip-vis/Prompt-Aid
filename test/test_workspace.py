import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skill/prompt-aid/retrieval'))
from store import Store, fuse
from context import Chunk


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'repo'
        self.root.mkdir()
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        (self.root/'login.py').write_text('def authenticate():\n    return "session login"\n')
        (self.root/'cart.py').write_text('def checkout():\n    return "shopping cart"\n')
        self.store = Store(Path(self.temp.name)/'data', [self.root])
        self.project = self.store.index(self.root)['project_id']

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_incremental_changes_deletions_and_restart(self):
        self.assertEqual(self.store.index(self.root)['changed_files'],0)
        (self.root/'login.py').write_text('def login(): return "new session"\n')
        (self.root/'cart.py').unlink()
        result = self.store.index(self.root)
        self.assertEqual((result['changed_files'],result['removed_files']),(1,1))
        restarted = Store(self.store.directory,[self.root])
        self.assertEqual(restarted.search(self.project,'new session')['results'][0]['path'],'login.py')
        self.assertEqual(restarted.search(self.project,'shopping cart')['results'],[])

    def test_stale_evidence_tampering_exclusions_and_current_ignore_rules(self):
        source = self.store.search(self.project,'session login')['results'][0]
        source['claim'] = 'An unverified model assertion'
        self.assertEqual(self.store.verify(self.project,[source])[0]['status'],'verified')
        tampered = {**source,'excerpt':'made up code'}
        self.assertEqual(self.store.verify(self.project,[tampered])[0]['status'],'stale')
        self.assertEqual(self.store.search(self.project,'session',excluded_paths=['login.py'])['results'],[])
        (self.root/'login.py').write_text('different implementation')
        self.assertEqual(self.store.verify(self.project,[source])[0]['status'],'stale')
        (self.root/'.gitignore').write_text('login.py\n')
        self.assertEqual(self.store.search(self.project,'implementation')['results'],[])
        self.assertEqual(self.store.verify(self.project,[source])[0]['status'],'unavailable')
        with sqlite3.connect(self.store.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM chunks WHERE path=?',('login.py',)).fetchone()[0],0)

    def test_sensitive_change_is_not_served_from_cache(self):
        (self.root/'login.py').write_text('password = "secret-password-123"\nlogin session')
        self.assertEqual(self.store.search(self.project,'login session')['results'],[])

    def test_roots_and_symlinks_cannot_escape_allowlist(self):
        with self.assertRaises(ValueError): self.store.index(self.root.parent)
        (self.root/'escape.py').symlink_to(self.root/'login.py')
        self.assertNotIn('escape.py',[s['path'] for s in self.store.search(self.project,'login')['results']])
        with tempfile.TemporaryDirectory() as other:
            restricted = Store(self.store.directory,[other])
            with self.assertRaises(ValueError): restricted.review(self.store.save_review(self.project,{'original':'fix','improved':'fix session'})['id'])

    def test_history_revisions_feedback_and_source_validation(self):
        source = self.store.search(self.project,'login')['results'][0]
        a = self.store.save_review(self.project,{'original':'Fix login','improved':'Fix session handling','sources':[source]})
        b = self.store.save_review(self.project,{'original':'Fix login','improved':'Fix mobile session handling'},a['id'])
        self.assertEqual(self.store.review(a['id'])['payload']['improved'],'Fix session handling')
        self.assertEqual(b['parent_id'],a['id'])
        self.assertEqual(len(self.store.history(self.project)),2)
        self.assertEqual(a['payload']['sources'][0]['status'],'verified')
        self.assertEqual(self.store.feedback(a['id'],'edited','Fix the session bug')['outcome'],'edited')
        with self.assertRaises(ValueError): self.store.feedback(a['id'],'edited')
        with self.assertRaises(ValueError): self.store.save_review(self.project,{'original':' ','improved':'ok'})
        with self.assertRaises(ValueError): self.store.save_review(self.project,{'original':'ok','improved':'ok'},'missing-parent')

    def test_unavailable_models_have_explicit_fallback_and_no_fake_reranking(self):
        result = self.store.search(self.project,'session',method='hybrid',rerank=True)
        self.assertEqual(result['method'],'bm25')
        self.assertEqual(result['requested_method'],'hybrid')
        self.assertFalse(result['reranked'])
        self.assertEqual(len(result['warnings']),2)
        with self.assertRaises(ValueError): self.store.search(self.project,'session',method='semantic')

    def test_rank_fusion_deduplicates_chunks(self):
        a,b = Chunk('a',1,1,'a'),Chunk('b',1,1,'b')
        result = fuse([[(a,10),(b,1)],[(b,8)]])
        self.assertEqual([c.path for c,_ in result],['b','a'])

    def test_bridge_persists_and_rejects_unconfigured_root(self):
        command = [sys.executable,str(ROOT/'skill/prompt-aid/retrieval/workspace.py'),'--root',str(self.root),'--data',str(self.store.directory),'--allowed-roots',json.dumps([str(self.root)]),'--action','search']
        response = subprocess.run(command,input=json.dumps({'query':'login'}),text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(response.stdout)['results'][0]['path'],'login.py')
        command[command.index('--root')+1] = str(self.root.parent)
        self.assertNotEqual(subprocess.run(command,input='{}',text=True,capture_output=True).returncode,0)


class APITests(unittest.TestCase):
    def setUp(self):
        WorkspaceTests.setUp(self)
        from fastapi.testclient import TestClient
        from backend.app import create_app
        self.client = TestClient(create_app(self.store,'x'*40), base_url='http://127.0.0.1')
        self.headers = {'Authorization':'Bearer '+'x'*40}

    def tearDown(self):
        self.client.close()
        WorkspaceTests.tearDown(self)

    def test_api_auth_size_validation_and_origin(self):
        self.assertEqual(self.client.get('/projects').status_code,401)
        self.assertEqual(self.client.get('/projects',headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/context/search',headers=self.headers,json={'project_id':self.project,'query':'session','limit':99}).status_code,422)
        self.assertEqual(self.client.post('/context/search',headers=self.headers,content='x'*128001).status_code,413)
        self.assertEqual(self.client.post('/projects/index',headers=self.headers,json={'root':str(self.root.parent)}).status_code,400)
        response = self.client.post('/reviews',headers=self.headers,json={'project_id':self.project,'original':'secret draft','improved':'ok','unexpected':True})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('secret draft',response.text)

    def test_api_complete_review_lifecycle(self):
        result = self.client.post('/context/search',headers=self.headers,json={'project_id':self.project,'query':'session'}).json()
        source = result['results'][0]
        saved = self.client.post('/reviews',headers=self.headers,json={'project_id':self.project,'original':'Fix login','improved':'Fix the session bug','sources':[source]}).json()
        self.assertEqual(saved['payload']['sources'][0]['status'],'verified')
        history = self.client.get('/reviews',headers=self.headers,params={'project_id':self.project}).json()
        self.assertEqual(history['reviews'][0]['id'],saved['id'])
        self.assertEqual(self.client.get('/reviews/'+saved['id'],headers=self.headers).json()['payload']['original'],'Fix login')
        self.assertEqual(self.client.post('/reviews/'+saved['id']+'/feedback',headers=self.headers,json={'outcome':'accepted'}).status_code,200)
        self.assertEqual(self.client.post('/reviews/'+saved['id']+'/feedback',headers=self.headers,json={'outcome':'edited'}).status_code,400)
        self.assertEqual(self.client.get('/reviews/missing',headers=self.headers).status_code,404)

if __name__ == '__main__': unittest.main()
