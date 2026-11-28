"""Project-scoped persistent indexing, source verification and review history."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from uuid import uuid4

from context import Chunk, BM25Index, format_result, scan


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def fuse(rankings, limit=10):
    """Reciprocal rank fusion; scores are ranking signals, not confidence."""
    scores, chunks = {}, {}
    for hits in rankings:
        for rank, (chunk, _) in enumerate(hits, 1):
            chunks[chunk.key] = chunk
            scores[chunk.key] = scores.get(chunk.key, 0.0) + 1 / (60 + rank)
    return [(chunks[k], scores[k]) for k in sorted(scores, key=lambda k: (-scores[k], k))[:limit]]


class Store:
    def __init__(self, directory, roots, semantic=None, reranker=None):
        self.directory = Path(directory).expanduser().resolve()
        if not self.directory.exists():
            self.directory.mkdir(parents=True, mode=0o700)
        self.roots = {str(Path(root).resolve(strict=True)) for root in roots}
        if not self.roots:
            raise ValueError('Configure at least one explicit project root.')
        self.semantic, self.reranker = semantic, reranker
        self.lock = threading.RLock()
        self.lexical_cache = {}
        self.db = self.directory / 'prompt-aid.sqlite3'
        fd = os.open(self.db, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('Unsupported database version; use a compatible Prompt Aid release.')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, root TEXT UNIQUE, indexed_at TEXT);
              CREATE TABLE IF NOT EXISTS files(project TEXT, path TEXT, hash TEXT, PRIMARY KEY(project,path));
              CREATE TABLE IF NOT EXISTS chunks(project TEXT,path TEXT,start INTEGER,end INTEGER,text TEXT,hash TEXT,
                PRIMARY KEY(project,path,start));
              CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,project TEXT,parent_id TEXT,created_at TEXT,payload TEXT);
              CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,review_id TEXT,created_at TEXT,payload TEXT);
              PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        with self.lock:
            db = sqlite3.connect(self.db, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def root(self, root):
        resolved = str(Path(root).resolve(strict=True))
        if resolved not in self.roots:
            raise ValueError('Project is not one of the explicitly configured roots.')
        return resolved

    def close(self):
        with self.lock:
            if self.semantic is not None:
                self.semantic.close()

    def project(self, project_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        if row is None:
            raise KeyError('Project not found.')
        self.root(row['root'])
        return dict(row)

    def projects(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY root') if r['root'] in self.roots]

    def index(self, root):
        started = time.perf_counter()
        root = self.root(root)
        project_id = hashlib.sha256(root.encode()).hexdigest()[:24]
        # Rescan to apply CURRENT Git ignore rules and secret filters. Only changed
        # files are rewritten; unchanged chunks/embeddings are reused.
        with self.lock:
            chunks, warnings = scan(root)
            grouped = {}
            for c in chunks:
                grouped.setdefault(c.path, []).append(c)
            with self.connect() as db:
                previous = {r['path']: r['hash'] for r in db.execute('SELECT path,hash FROM files WHERE project=?', (project_id,))}
                changed = {p for p, cs in grouped.items() if previous.get(p) != cs[0].content_hash}
                removed = previous.keys() - grouped.keys()
                for path in changed | removed:
                    db.execute('DELETE FROM chunks WHERE project=? AND path=?', (project_id, path))
                    db.execute('DELETE FROM files WHERE project=? AND path=?', (project_id, path))
                for path in changed:
                    cs = grouped[path]
                    db.execute('INSERT INTO files VALUES(?,?,?)', (project_id, path, cs[0].content_hash))
                    db.executemany('INSERT INTO chunks VALUES(?,?,?,?,?,?)', [(project_id, c.path, c.line_start, c.line_end, c.text, c.content_hash) for c in cs])
                db.execute('INSERT INTO projects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET indexed_at=excluded.indexed_at', (project_id, root, utcnow()))
            return {'project_id': project_id, 'files': len(grouped), 'chunks': len(chunks), 'changed_files': len(changed), 'removed_files': len(removed), 'warnings': warnings, 'duration_ms': round((time.perf_counter()-started)*1000, 2)}

    def search(self, project_id=None, query=None, method='bm25', limit=5, rerank=False, excluded_paths=None, root=None):
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError('Provide a non-empty query up to 4000 characters.')
        if method not in ('bm25', 'semantic', 'hybrid'):
            raise ValueError('Unknown retrieval method.')
        if not 1 <= limit <= 10:
            raise ValueError('Limit must be between 1 and 10.')
        started = time.perf_counter()
        with self.lock:
            # Refresh before searching: deleted, ignored or newly sensitive files
            # must not be returned from a stale persistent cache.
            if (project_id is None) == (root is None):
                raise ValueError('Choose exactly one project_id or explicit root.')
            report = self.index(root if root is not None else self.project(project_id)['root'])
            project_id = report['project_id']
            indexed = time.perf_counter()
            with self.connect() as db:
                chunks = [Chunk(r['path'], r['start'], r['end'], r['text'], r['hash']) for r in db.execute('SELECT * FROM chunks WHERE project=? ORDER BY path,start', (project_id,))]
            excluded = set(excluded_paths or [])
            signature = tuple((c.key,c.content_hash) for c in chunks)
            cached = self.lexical_cache.get(project_id)
            cache_hit = cached is not None and cached[0] == signature
            if not cache_hit:
                self.lexical_cache[project_id] = (signature,BM25Index(chunks))
            lexical = self.lexical_cache[project_id][1].search(query,10,excluded)
            lexical_end = time.perf_counter()
            warnings = list(report['warnings'])
            actual = method
            dense = []
            dense_start = time.perf_counter()
            previous_load = getattr(self.semantic, 'load_ms', 0)
            if method != 'bm25':
                if self.semantic is None:
                    if method == 'semantic':
                        raise ValueError('Semantic search requires a configured local embedding model.')
                    warnings.append('Semantic model unavailable; used BM25 only.')
                    actual = 'bm25'
                else:
                    dense = self.semantic.search(project_id, chunks, query, 10)
            dense_end = time.perf_counter()
            # Synchronize the full vector index, then filter candidate lists. This
            # preserves exclusions without deleting their cached embeddings.
            dense = [(c, s) for c, s in dense if c.path not in excluded]
            hits = lexical if actual == 'bm25' else dense if actual == 'semantic' else fuse([lexical, dense], 20)
            reranked = False
            previous_reranker_load = getattr(self.reranker, 'load_ms', 0)
            if rerank:
                if self.reranker is None:
                    warnings.append('Reranker unavailable; kept retrieval ordering.')
                else:
                    hits = self.reranker.rank(query, hits)
                    reranked = True
            result = format_result(hits[:limit], warnings, actual)
            # These excerpts are assembled from this request's fresh filtered scan.
            # The native app still rechecks them before explicit insertion/restore.
            for source in result['results']: source['status'] = 'verified'
            result.update(project_id=project_id, requested_method=method, reranked=reranked,
                          model=getattr(self.semantic, 'identity', None) if method != 'bm25' else None,
                          reranker=getattr(self.reranker, 'identity', None) if reranked else None,
                          duration_ms=round((time.perf_counter()-started)*1000, 2))
            result['timings'] = {
                'index_ms': round((indexed-started)*1000, 2),
                'lexical_ms': round((lexical_end-indexed)*1000, 2),
                'lexical_cache_hit': cache_hit,
                'dense_ms': round((dense_end-dense_start)*1000, 2),
                'embedding_model_load_ms': max(0, getattr(self.semantic, 'load_ms', 0)-previous_load),
                'reranker_model_load_ms': max(0, getattr(self.reranker, 'load_ms', 0)-previous_reranker_load),
            }
            result['vector_sync'] = dict(getattr(self.semantic, 'last_sync', {})) if actual != 'bm25' else None
            return result

    def verify(self, project_id, sources):
        with self.lock:
            root = self.project(project_id)['root']
            chunks, _ = scan(root)
            lookup = {(c.path, c.line_start, c.line_end): c for c in chunks}
            available_paths = {c.path for c in chunks}
            output = []
            for source in sources:
                chunk = lookup.get((source.get('path'), source.get('line_start'), source.get('line_end')))
                status = 'stale' if source.get('path') in available_paths else 'unavailable'
                if chunk:
                    # A matching hash alone is insufficient: the excerpt must
                    # match too. "Verified" means source text, NOT model claims.
                    status = 'verified' if source.get('content_hash') == chunk.content_hash and source.get('excerpt') == chunk.text[:3000] else 'stale'
                output.append({**source, 'status': status})
            return output

    def save_review(self, project_id, payload, parent_id=None):
        self.project(project_id)
        for field, maximum in [('original',12000), ('improved',16000)]:
            if not isinstance(payload.get(field), str) or not payload[field].strip() or len(payload[field]) > maximum:
                raise ValueError('Invalid review text.')
        # Preserve the claim independently of a mechanically checked status.
        sources = self.verify(project_id, payload.get('sources', []))
        payload = {**payload, 'sources': sources}
        review_id, created = str(uuid4()), utcnow()
        with self.connect() as db:
            if parent_id:
                parent = db.execute('SELECT project FROM reviews WHERE id=?', (parent_id,)).fetchone()
                if parent is None or parent['project'] != project_id:
                    raise ValueError('Parent review must belong to the same project.')
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?)', (review_id, project_id, parent_id, created, json.dumps(payload)))
        return self.review(review_id)

    def review(self, review_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM reviews WHERE id=?', (review_id,)).fetchone()
        if row is None:
            raise KeyError('Review not found.')
        self.project(row['project'])
        return {k: row[k] for k in ('id','project','parent_id','created_at')} | {'payload': json.loads(row['payload'])}

    def history(self, project_id, limit=30):
        self.project(project_id)
        with self.connect() as db:
            rows = db.execute('SELECT * FROM reviews WHERE project=? ORDER BY created_at DESC LIMIT ?', (project_id, max(1,min(limit,100)))).fetchall()
        return [{'id': r['id'], 'parent_id': r['parent_id'], 'created_at': r['created_at'], 'title': json.loads(r['payload'])['original'][:100]} for r in rows]

    def feedback(self, review_id, outcome, edited_prompt=None):
        self.review(review_id)
        if outcome not in ('accepted','edited','rejected'):
            raise ValueError('Invalid feedback outcome.')
        if edited_prompt is not None and (not isinstance(edited_prompt, str) or not edited_prompt.strip() or len(edited_prompt)>16000):
            raise ValueError('Invalid edited prompt.')
        if outcome == 'edited' and edited_prompt is None:
            raise ValueError('Edited feedback requires the edited prompt.')
        feedback_id = str(uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO feedback VALUES(?,?,?,?)', (feedback_id, review_id, utcnow(), json.dumps({'outcome': outcome, 'edited_prompt': edited_prompt})))
        return {'id': feedback_id, 'outcome': outcome}
