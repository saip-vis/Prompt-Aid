"""Authenticated loopback API. Start with python -m backend.app --help."""
import argparse
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
import secrets
import sys

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill/prompt-aid/retrieval'))
from store import Store


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Index(Input):
    root: str = Field(min_length=1, max_length=4096)

class Source(Input):
    path: str = Field(min_length=1, max_length=4096)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    content_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    excerpt: str = Field(max_length=3000)
    excerpt_truncated: bool = False
    score: float | None = None
    status: str | None = None
    claim: str | None = Field(default=None, max_length=1000)

class Search(Input):
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    root: str | None = Field(default=None, min_length=1, max_length=4096)
    query: str = Field(min_length=1, max_length=4000)
    method: str = Field(default='bm25', pattern='^(bm25|semantic|hybrid)$')
    limit: int = Field(default=5, ge=1, le=10)
    rerank: bool = False
    excluded_paths: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def one_project(self):
        if (self.project_id is None) == (self.root is None):
            raise ValueError('Choose exactly one project_id or explicit root.')
        return self

class Verify(Input):
    project_id: str = Field(min_length=1, max_length=64)
    sources: list[Source] = Field(default_factory=list, max_length=10)

class Review(Input):
    project_id: str = Field(min_length=1, max_length=64)
    parent_id: str | None = Field(default=None, max_length=64)
    original: str = Field(min_length=1, max_length=12000)
    improved: str = Field(min_length=1, max_length=16000)
    sources: list[Source] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=20)

class Feedback(Input):
    outcome: str = Field(pattern='^(accepted|edited|rejected)$')
    edited_prompt: str | None = Field(default=None, min_length=1, max_length=16000)


def create_app(store, token):
    if not token or len(token) < 32:
        raise ValueError('Use an authentication token of at least 32 characters.')
    @asynccontextmanager
    async def lifespan(app):
        yield
        store.close()
    app = FastAPI(title='Prompt Aid local service', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store

    @app.middleware('http')
    async def private_local_api(request: Request, call_next):
        # No browser-origin requests. Native/CLI/MCP clients authenticate using
        # a private token. Do not trust Host or DNS aliases for loopback access.
        if request.headers.get('origin') or request.url.hostname not in ('127.0.0.1', 'localhost'):
            return JSONResponse({'error': 'Origin or host not allowed.'}, status_code=403)
        if not hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer ' + token).encode()):
            return JSONResponse({'error': 'Authentication required.'}, status_code=401)
        # Bound actual streamed bytes as well as Content-Length before parsing.
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 128_000:
                return JSONResponse({'error': 'Request too large.'}, status_code=413)
            chunks.append(chunk)
        body = b''.join(chunks)
        # Starlette's cached body is replayed to downstream request parsers.
        request._body = body
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic errors can echo prompt/source input; return field paths only.
        return JSONResponse({'error': 'Invalid request.', 'fields': ['.'.join(map(str, e['loc'])) for e in exc.errors()]}, status_code=422)

    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'error': 'Resource not found.'}, status_code=404)

    @app.exception_handler(OSError)
    async def filesystem_error(request, exc):
        return JSONResponse({'error': 'Local data unavailable. Check project/model paths and permissions.'}, status_code=400)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'schema_version': 1, 'pid': os.getpid(), 'semantic': store.semantic is not None, 'reranker': store.reranker is not None,
                'semantic_loaded': getattr(store.semantic, '_model', None) is not None,
                'reranker_loaded': getattr(store.reranker, '_model', None) is not None}

    @app.get('/projects')
    def projects():
        return {'projects': store.projects()}

    @app.post('/projects/index')
    def index(body: Index):
        return store.index(body.root)

    @app.post('/context/search')
    def search(body: Search):
        return store.search(**body.model_dump())

    @app.post('/sources/verify')
    def verify(body: Verify):
        return {'sources': store.verify(body.project_id, [s.model_dump() for s in body.sources])}

    @app.post('/reviews')
    def save(body: Review):
        payload = body.model_dump(exclude={'project_id', 'parent_id'})
        return store.save_review(body.project_id, payload, body.parent_id)

    @app.get('/reviews')
    def history(project_id: str, limit: int = 30):
        return {'reviews': store.history(project_id, limit)}

    @app.get('/reviews/{review_id}')
    def review(review_id: str):
        return store.review(review_id)

    @app.post('/reviews/{review_id}/feedback')
    def feedback(review_id: str, body: Feedback):
        return store.feedback(review_id, body.outcome, body.edited_prompt)

    return app


def private_token(directory):
    path = directory / 'api-token'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(32))
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('Token file must be a private regular file with mode 0600.')
    return path.read_text().strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', action='append', required=True, help='Explicit Git root; repeat to allow another project')
    p.add_argument('--data', type=Path, default=Path.home()/'.local/share/prompt-aid')
    p.add_argument('--port', type=int, default=4318)
    p.add_argument('--host', choices=['127.0.0.1','0.0.0.0'], default='127.0.0.1', help='Use 0.0.0.0 only inside a container published to host loopback')
    p.add_argument('--embedding-model', type=Path, help='Already-downloaded local SentenceTransformer directory')
    p.add_argument('--reranker-model', type=Path, help='Already-downloaded local CrossEncoder directory')
    p.add_argument('--semantic-threshold', type=float, default=0.25, help='Cosine cutoff; calibrate on your own held-out cases')
    args = p.parse_args()
    semantic = reranker = None
    if not args.data.exists():
        args.data.mkdir(parents=True, mode=0o700)
    if args.embedding_model:
        from semantic import LocalSemantic
        semantic = LocalSemantic(args.data/'vectors', args.embedding_model, args.semantic_threshold)
    if args.reranker_model:
        from semantic import LocalReranker
        reranker = LocalReranker(args.reranker_model)
    store = Store(args.data, args.root, semantic, reranker)
    token = private_token(args.data)
    import uvicorn
    # One process owns Qdrant local storage. Log neither payloads nor tokens.
    uvicorn.run(create_app(store, token), host=args.host, port=args.port, access_log=False)

if __name__ == '__main__':
    main()
