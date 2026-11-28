"""Real Qdrant persistence with deterministic, instrumented embeddings."""
import json
from pathlib import Path
import subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from semantic import LocalSemantic,LocalReranker
from store import Store

class TinyModel:
    def get_sentence_embedding_dimension(self):return 3
    def encode_document(self,texts,**kwargs):
        import numpy as np
        return np.array([[1.,0.,0.] for t in texts])
    def encode_query(self,texts,**kwargs):
        import numpy as np
        return np.array([[1.,0.,0.] for t in texts])

def fixture_vectors(directory):
    model=LocalSemantic(directory,ROOT,threshold=0)
    model.identity='deterministic-test';model._model=TinyModel()
    return model

class PersistentVectorTests(unittest.TestCase):
    def test_edit_in_one_block_reuses_other_blocks_in_same_file(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);root=temp/'repo';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            lines=['unchanged authentication line '+str(i) for i in range(30)]+['old session behavior']
            file=root/'auth.py';file.write_text('\n'.join(lines)+'\n')
            store=Store(temp/'data',[root],fixture_vectors(temp/'vectors'))
            try:
                project=store.index(root)['project_id']
                first=store.search(project,'authentication',method='semantic')
                self.assertEqual(first['vector_sync']['embedded_chunks'],2)
                source=next(s for s in first['results'] if s['line_start']==1)
                lines[-1]='new session behavior';file.write_text('\n'.join(lines)+'\n')
                result=store.search(project,'authentication',method='semantic')
                self.assertEqual(result['vector_sync']['embedded_chunks'],1)
                self.assertEqual(result['vector_sync']['reused_chunks'],1)
                self.assertEqual(result['vector_sync']['removed_chunks'],1)
                # Cached vector reuse must never preserve an obsolete file hash.
                self.assertEqual(store.verify(project,[source])[0]['status'],'stale')
                self.assertTrue(all(s['status']=='verified' for s in store.verify(project,result['results'])))
            finally:store.close()

    def test_lazy_models_do_not_import_or_fingerprint_until_requested(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp,patch('semantic.model_identity',side_effect=AssertionError('eager fingerprint')):
            semantic=LocalSemantic(Path(temp)/'vectors',temp)
            reranker=LocalReranker(temp)
            self.assertIsNone(semantic._model);self.assertIsNone(reranker._model)
            self.assertFalse((Path(temp)/'vectors').exists())

    def test_restarts_change_delete_ignore_and_project_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);roots=[temp/'a',temp/'b']
            for root in roots:
                root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            (roots[0]/'auth.py').write_text('authentication session cookie\n')
            (roots[0]/'cart.py').write_text('cart checkout total\n')
            (roots[1]/'private.py').write_text('other project authentication\n')
            semantic=fixture_vectors(temp/'vectors');store=Store(temp/'data',roots,semantic)
            project=store.index(roots[0])['project_id'];other=store.index(roots[1])['project_id']
            result=store.search(project,'authentication',method='semantic')
            self.assertEqual(result['vector_sync']['embedded_chunks'],2)
            self.assertEqual(store.search(project,'authentication',method='semantic')['vector_sync']['reused_chunks'],2)
            self.assertEqual(store.search(other,'authentication',method='semantic')['vector_sync']['embedded_chunks'],1)
            store.close()
            # New process opens the on-disk vectors and must embed zero documents.
            script='''import sys,json;sys.path.insert(0,sys.argv[1]);from test_persistent_vectors import fixture_vectors;from store import Store;from pathlib import Path
s=Store(Path(sys.argv[2])/'data',[Path(sys.argv[2])/'a',Path(sys.argv[2])/'b'],fixture_vectors(Path(sys.argv[2])/'vectors'))
r=s.search(sys.argv[3],'authentication',method='semantic');s.close();print(json.dumps(r))'''
            child=subprocess.run([sys.executable,'-c',script,str(ROOT/'test'),str(temp),project],text=True,capture_output=True,check=True)
            restarted=json.loads(child.stdout);self.assertEqual(restarted['vector_sync']['embedded_chunks'],0);self.assertEqual(restarted['vector_sync']['reused_chunks'],2)
            store=Store(temp/'data',roots,fixture_vectors(temp/'vectors'))
            try:
                (roots[0]/'auth.py').write_text('updated authentication\n')
                changed=store.search(project,'authentication',method='semantic')
                self.assertEqual(changed['vector_sync']['embedded_chunks'],1)
                self.assertEqual(changed['vector_sync']['removed_chunks'],1)
                (roots[0]/'cart.py').unlink()
                (roots[0]/'.gitignore').write_text('auth.py\n')
                cleared=store.search(project,'authentication',method='semantic')
                self.assertEqual(cleared['results'],[]);self.assertEqual(cleared['vector_sync']['removed_chunks'],2)
                self.assertEqual([s['path'] for s in store.search(other,'authentication',method='semantic')['results']],['private.py'])
            finally:store.close()

    def test_vector_id_cache_skips_scroll_and_recovers_after_partial_failure(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);root=temp/'repo';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            file=root/'auth.py';file.write_text('authentication session\n')
            semantic=fixture_vectors(temp/'vectors');store=Store(temp/'data',[root],semantic)
            try:
                project=store.index(root)['project_id'];store.search(project,'session',method='semantic')
                with patch.object(semantic._client,'scroll',side_effect=AssertionError('warm query reread all IDs')):
                    result=store.search(project,'session',method='semantic')
                    self.assertTrue(result['vector_sync']['id_cache_hit'])
                file.write_text('changed authentication\n')
                with patch.object(semantic._client,'upsert',side_effect=ValueError('simulated interrupted sync')):
                    with self.assertRaises(ValueError):store.search(project,'authentication',method='semantic')
                result=store.search(project,'authentication',method='semantic')
                self.assertFalse(result['vector_sync']['id_cache_hit'])
                self.assertEqual(result['vector_sync']['embedded_chunks'],1)
                self.assertEqual(store.verify(project,result['results'])[0]['status'],'verified')
            finally:store.close()
