"""Optional offline embeddings, persistent Qdrant and pretrained reranking.

Models must already exist in explicitly configured local directories. This module
never downloads weights or enables model-supplied Python code.
"""
import hashlib
import json
import math
import threading
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def model_identity(path):
    path = Path(path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError('Choose a local model directory.')
    manifest = []
    for p in sorted(path.rglob('*')):
        relative = p.relative_to(path)
        if p.is_file() and not any(part.startswith('.') for part in relative.parts):
            digest = hashlib.sha256()
            with p.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            manifest.append((str(relative), digest.hexdigest()))
    return str(path), hashlib.sha256(json.dumps(manifest).encode()).hexdigest()[:24]


class LocalSemantic:
    def __init__(self, directory, model_path, threshold=0.25):
        self.path = str(Path(model_path).resolve(strict=True))
        if not Path(self.path).is_dir():
            raise ValueError('Choose a local model directory.')
        self.identity = None
        self._model = None
        self._client = None
        self._known_ids = {}
        self.lock = threading.RLock()
        self.load_ms = 0
        self.last_sync = {}
        self.directory = Path(directory)
        self.threshold = threshold

    @property
    def model(self):
        with self.lock:
            if self._model is None:
                started = time.perf_counter()
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as exc:
                    raise ValueError("Install requirements-semantic.txt to enable local semantic retrieval.") from exc
                self.path, self.identity = model_identity(self.path)
                self._model = SentenceTransformer(self.path, local_files_only=True, trust_remote_code=False, device='cpu')
                self.load_ms = round((time.perf_counter()-started)*1000, 2)
            return self._model

    def close(self):
        with self.lock:
            if self._client is not None:
                self._client.close()
                self._client = None
            self._known_ids.clear()

    def search(self, project_id, chunks, query, limit=10):
        with self.lock:
            return self._search(project_id, chunks, query, limit)

    def _search(self, project_id, chunks, query, limit):
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise ValueError("Install requirements-semantic.txt to enable persistent vectors.") from exc
        model = self.model
        self.directory.mkdir(parents=True, exist_ok=True)
        collection = 'p_' + project_id + '_' + self.identity
        if self._client is None:
            self._client = QdrantClient(path=str(self.directory))
        client = self._client
        try:
            dimension = model.get_embedding_dimension() if hasattr(model, 'get_embedding_dimension') else model.get_sentence_embedding_dimension()
            cache_hit = collection in self._known_ids
            if not cache_hit and not client.collection_exists(collection):
                client.create_collection(collection, vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE))
            # Embeddings depend on path/text, not the whole-file freshness hash.
            # Editing another block in the same file must not re-embed this one.
            expected = {str(uuid5(NAMESPACE_URL, project_id + ':' + c.key + ':' + hashlib.sha256(c.text.encode()).hexdigest())): c for c in chunks}
            # This instance exclusively owns local Qdrant storage. Reconcile from
            # disk once after opening; subsequent syncs reuse committed IDs.
            existing = self._known_ids.get(collection)
            if existing is None:
                existing = set()
                offset = None
                while True:
                    points, offset = client.scroll(collection, limit=256, offset=offset, with_payload=False, with_vectors=False)
                    existing.update(str(p.id) for p in points)
                    if offset is None:
                        break
            obsolete = existing - expected.keys()
            if obsolete:
                client.delete(collection, points_selector=models.PointIdsList(points=list(obsolete)), wait=True)
            missing = sorted(expected.keys() - existing)
            self.last_sync = {'embedded_chunks': len(missing), 'reused_chunks': len(expected.keys() & existing), 'removed_chunks': len(obsolete), 'collection': collection, 'id_cache_hit': cache_hit}
            for start in range(0, len(missing), 32):
                ids = missing[start:start+32]
                vectors = model.encode_document([expected[i].path + '\n' + expected[i].text for i in ids], normalize_embeddings=True, convert_to_numpy=True)
                if not all(math.isfinite(float(v)) for row in vectors for v in row):
                    raise ValueError('Embedding model returned non-finite vectors.')
                client.upsert(collection, points=[models.PointStruct(id=i, vector=v.tolist()) for i, v in zip(ids, vectors)], wait=True)
            self._known_ids[collection] = set(expected)
            if not expected:
                return []
            vector = model.encode_query([query], normalize_embeddings=True, convert_to_numpy=True)[0].tolist()
            found = client.query_points(collection, query=vector, limit=limit, score_threshold=self.threshold, with_payload=False).points
            return [(expected[str(p.id)], float(p.score)) for p in found if str(p.id) in expected]
        except Exception:
            # A failed sync is retried from actual on-disk IDs next time.
            self.last_sync = {}
            self._known_ids.pop(collection, None)
            raise


class LocalReranker:
    def __init__(self, model_path):
        self.path = str(Path(model_path).resolve(strict=True))
        if not Path(self.path).is_dir():
            raise ValueError('Choose a local model directory.')
        self.identity = None
        self._model = None
        self.lock = threading.RLock()
        self.load_ms = 0

    @property
    def model(self):
        with self.lock:
            if self._model is None:
                started = time.perf_counter()
                try:
                    from sentence_transformers import CrossEncoder
                except ImportError as exc:
                    raise ValueError("Install requirements-semantic.txt to enable local reranking.") from exc
                self.path, self.identity = model_identity(self.path)
                self._model = CrossEncoder(self.path, local_files_only=True, trust_remote_code=False, device='cpu')
                self.load_ms = round((time.perf_counter()-started)*1000, 2)
            return self._model

    def rank(self, query, hits):
        if not hits:
            return []
        scores = self.model.predict([(query, c.path + '\n' + c.text) for c, _ in hits], show_progress_bar=False)
        values = [float(s) for s in scores]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Reranker returned non-finite scores.')
        return sorted(zip([c for c, _ in hits], values), key=lambda hit: (-hit[1], hit[0].key))
