import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skill/prompt-aid/retrieval'))
from context import scan,bm25_search,format_result

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        (self.root/'src').mkdir();(self.root/'src'/'login.js').write_text('// Authenticate login session\nexport const login = true;\n')
        (self.root/'.gitignore').write_text('ignored.js\ntracked-ignored.js\n')
        (self.root/'tracked-ignored.js').write_text('login session should remain excluded')
        subprocess.run(['git','-C',str(self.root),'add','-f','tracked-ignored.js'],check=True)
        (self.root/'ignored.js').write_text('login session ignored')
        (self.root/'.env').write_text('login session SECRET')
        (self.root/'src'/'sensitive.py').write_text('password = "very-secret-password"\nlogin session')
        (self.root/'src'/'huge.py').write_text('login '+ 'x'*260000)
        (self.root/'src'/'outside.js').symlink_to('/etc/hosts')
    def tearDown(self): self.temp.cleanup()
    def test_excludes_ignored_secrets_symlinks_and_large_files(self):
        chunks,warnings=scan(self.root)
        self.assertEqual({c.path for c in chunks},{'src/login.js'})
        result=format_result(bm25_search(chunks,'fix login session'),warnings)
        self.assertEqual(result['results'][0]['path'],'src/login.js')
        self.assertEqual(result['results'][0]['line_start'],1)
        self.assertTrue(warnings)
    def test_unknown_or_generic_query_does_not_invent_context(self):
        chunks,_=scan(self.root)
        self.assertEqual(bm25_search(chunks,'fix websocket kerberos'),[])
        self.assertEqual(bm25_search(chunks,'make it better'),[])
    def test_refuses_non_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): scan(tmp)
    def test_cli_outputs_evidence_and_does_not_execute_query(self):
        query=self.root/'query.json'
        query.write_text(json.dumps({'query':'login session'}))
        proc=subprocess.run([sys.executable,str(ROOT/'skill/prompt-aid/retrieval/cli.py'),'--root',str(self.root),'--input',str(query)],capture_output=True,text=True,check=True)
        result=json.loads(proc.stdout)
        self.assertEqual(result['method'],'bm25')
        self.assertEqual(result['results'][0]['path'],'src/login.js')

    def test_cli_supports_stdin_for_container_use(self):
        proc=subprocess.run(
            [sys.executable,str(ROOT/'skill/prompt-aid/retrieval/cli.py'),'--root',str(self.root),'--input','-'],
            input=json.dumps({'query':'login session'}),capture_output=True,text=True,check=True,
        )
        self.assertEqual(json.loads(proc.stdout)['results'][0]['path'],'src/login.js')


class VectorTests(unittest.TestCase):
    def test_in_memory_qdrant_and_abstention(self):
        try:
            import qdrant_client  # noqa: F401
        except ImportError:
            self.skipTest('Optional qdrant-client is not installed')
        from vector import vector_search
        from context import Chunk
        chunks=[Chunk('login.js',1,1,'authenticate login session'),Chunk('layout.css',1,1,'visual page layout')]
        hits=vector_search(chunks,'fix login authentication')
        self.assertEqual(hits[0][0].path,'login.js')
        self.assertEqual(vector_search(chunks,'websocket kerberos'),[])
    def test_vector_memory_budget_rejects_oversized_indexes(self):
        from unittest.mock import patch
        from vector import tfidf_vectors
        from context import Chunk
        chunks=[Chunk('a.py',1,1,'alpha beta'),Chunk('b.py',1,1,'gamma delta')]
        with patch('vector.MAX_VECTOR_CELLS',2):
            with self.assertRaises(ValueError): tfidf_vectors(chunks,'alpha')

if __name__=='__main__': unittest.main()
