"""Opt-in real-model integration test; never downloads weights during testing."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skill/prompt-aid/retrieval'))
from store import Store

@unittest.skipUnless(os.environ.get('PROMPT_AID_TEST_EMBEDDING_MODEL'), 'Set a local model directory to run offline model integration')
class SemanticIntegration(unittest.TestCase):
    def test_local_embeddings_reranking_persistence_and_removal(self):
        from semantic import LocalSemantic, LocalReranker
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'repo';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
            (root/'auth.py').write_text('def authenticate_user():\n    """Keep the user signed in using a persistent session cookie."""\n    return session\n')
            (root/'cart.py').write_text('def price_cart(items):\n    return sum(item.price for item in items)\n')
            semantic=LocalSemantic(Path(temp)/'vectors',os.environ['PROMPT_AID_TEST_EMBEDDING_MODEL'])
            reranker=LocalReranker(os.environ['PROMPT_AID_TEST_RERANKER_MODEL']) if os.environ.get('PROMPT_AID_TEST_RERANKER_MODEL') else None
            store=Store(Path(temp)/'data',[root],semantic,reranker)
            project=store.index(root)['project_id']
            result=store.search(project,'preserve authentication across visits',method='hybrid',rerank=reranker is not None)
            self.assertEqual(result['results'][0]['path'],'auth.py')
            self.assertEqual(result['method'],'hybrid')
            self.assertEqual(result['reranked'],reranker is not None)
            self.assertEqual(store.verify(project,result['results'])[0]['status'],'verified')
            restart=Store(store.directory,[root],semantic,reranker)
            self.assertEqual(restart.search(project,'persistent session cookie',method='semantic')['results'][0]['path'],'auth.py')
            (root/'auth.py').unlink()
            self.assertNotIn('auth.py',[s['path'] for s in restart.search(project,'persistent session cookie',method='semantic')['results']])
            restart.close()
