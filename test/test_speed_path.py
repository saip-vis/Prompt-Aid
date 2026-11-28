"""Behavior checks for fast paths: quality/freshness must survive caching."""
from pathlib import Path
import importlib.util,json,subprocess,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from context import BM25Index,bm25_search,scan
from store import Store

spec=importlib.util.spec_from_file_location('review_launcher',ROOT/'skill/prompt-aid/review.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

class FastPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'repo';self.root.mkdir()
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        (self.root/'auth.py').write_text('authentication session cookie\n')
        (self.root/'cart.py').write_text('cart checkout session\n')
        self.store=Store(Path(self.tmp.name)/'data',[self.root])
    def tearDown(self):self.store.close();self.tmp.cleanup()

    def test_root_search_scans_once_and_reuses_lexical_statistics(self):
        with patch('store.scan',wraps=scan) as scanner:
            first=self.store.search(query='authentication',root=str(self.root))
            self.assertEqual(scanner.call_count,1)
        self.assertTrue(all(x['status']=='verified' for x in first['results']))
        with patch('store.BM25Index',side_effect=AssertionError('unchanged corpus rebuilt')):
            second=self.store.search(query='session',root=str(self.root))
            self.assertTrue(second['timings']['lexical_cache_hit'])
        (self.root/'auth.py').write_text('new unrelated implementation\n')
        changed=self.store.search(query='authentication',root=str(self.root))
        self.assertEqual(changed['results'],[]);self.assertFalse(changed['timings']['lexical_cache_hit'])
        self.assertEqual(self.store.verify(first['project_id'],first['results'])[0]['status'],'stale')

    def test_cache_exclusions_match_a_fresh_index(self):
        chunks,_=scan(self.root);index=BM25Index(chunks)
        self.assertEqual(index.search('session',excluded_paths=['auth.py']),bm25_search([c for c in chunks if c.path!='auth.py'],'session'))
        self.assertEqual(index.search('authentication',excluded_paths=['auth.py']),[])

    def test_root_and_project_id_are_exclusive_and_allowlisted(self):
        project=self.store.index(self.root)['project_id']
        with self.assertRaises(ValueError):self.store.search(project,'session',root=str(self.root))
        with self.assertRaises(ValueError):self.store.search(query='session',root=str(self.root.parent))
        from backend.app import create_app
        from fastapi.testclient import TestClient
        with TestClient(create_app(self.store,'x'*40),base_url='http://127.0.0.1') as client:
            headers={'Authorization':'Bearer '+'x'*40}
            for body in [{'query':'session'},{'project_id':project,'root':str(self.root),'query':'session'}]:
                self.assertEqual(client.post('/context/search',headers=headers,json=body).status_code,422)
            self.assertEqual(client.post('/context/search',headers=headers,json={'root':str(self.root),'query':'session'}).status_code,200)

    def test_atomic_publish_keeps_request_and_project_unchanged(self):
        file=Path(self.tmp.name)/'review.json';initial={'original':'Fix login','improved':'','pending':True,'projectRoot':str(self.root)}
        file.write_text(json.dumps(initial));file.chmod(0o600)
        final={**initial,'improved':'Fix session persistence.'}
        with self.assertRaises(ValueError):launcher.publish(file,{**final,'original':'Other work'})
        launcher.publish(file,final);result=json.loads(file.read_text())
        self.assertFalse(result['pending']);self.assertEqual(result['improved'],final['improved'])
        self.assertEqual(file.stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError):launcher.publish(file,final)

    def test_launcher_closes_and_cleans_up_after_cancel(self):
        seen=[]
        def fake_run(command,**kwargs):
            payload=Path(command[-1]);self.assertTrue(json.loads(payload.read_text())['pending'])
            self.assertEqual(payload.stat().st_mode & 0o777,0o600);seen.append(payload)
            return subprocess.CompletedProcess(command,0)
        with patch.object(launcher.subprocess,'run',side_effect=fake_run):launcher.open_review({'original':'Fix login'})
        self.assertFalse(seen[0].exists())

    def test_context_helper_falls_back_to_fresh_lexical_scan(self):
        with patch('workspace.via_service',side_effect=ValueError('offline')):
            result=launcher.context({'root':str(self.root),'query':'authentication'},limit=1,workspace=True)
        self.assertEqual(result['results'][0]['path'],'auth.py')
        self.assertEqual(result['method'],'bm25')
        self.assertTrue(result['warnings'])
