"""Bounded, local-only retrieval over explicitly chosen Git projects."""
from __future__ import annotations
import math
import hashlib
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Retrieval is deliberately restricted to small, human-readable project files.
ALLOWED_SUFFIXES = {'.md', '.txt', '.html', '.css', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.py', '.swift', '.json', '.toml', '.yaml', '.yml', '.sql', '.sh', '.go', '.rs'}
SKIP_DIRS = {'.git', '.agents', '.codex', '.aws', '.ssh', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', 'coverage', '.next', '.cache', 'vendor'}
SKIP_NAMES = {'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'poetry.lock', 'cargo.lock', 'credentials', 'id_rsa', 'id_ed25519'}
STOP = set('a an and are as at be but by can do for from how i in is it its make me my of on or our should that the their this to update want we what which with would you your website site project please'.split())
MAX_FILE = 256_000
MAX_FILES = 1500
MAX_CHUNKS = 6000
CHUNK_LINES = 30
SECRET_MARKERS = re.compile(r'(?i)(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)\s*[:=]\s*[\"\'][^\"\']{8,}|\bgh[opusr]_[A-Za-z0-9]{30,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{30,})')

@dataclass(frozen=True)
class Chunk:
    path: str
    line_start: int
    line_end: int
    text: str
    content_hash: str = ''
    @property
    def key(self): return f'{self.path}:{self.line_start}-{self.line_end}'

def tokenize(text: str) -> list[str]:
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    return [t for t in re.findall(r'[a-z0-9]+', text.lower()) if len(t)>1 and t not in STOP]

def safe_path(rel: str) -> bool:
    parts = Path(rel).parts
    if not parts or any(p in {'..','.'} for p in parts) or Path(rel).is_absolute(): return False
    lower = [p.lower() for p in parts]
    if any(p in SKIP_DIRS or p.startswith('.') for p in lower): return False
    name=lower[-1]
    if name in SKIP_NAMES or any(x in name for x in ('credential','secret','private_key','api_key','id_rsa')): return False
    if name.endswith(('.min.js','.min.css','.map','.lock')): return False
    return Path(name).suffix in ALLOWED_SUFFIXES

def scan(root: str|Path) -> tuple[list[Chunk], list[str]]:
    root = Path(root).resolve(strict=True)
    if not root.is_dir(): raise ValueError('Project root must be a directory.')
    # --exclude-standard honors ignore rules for untracked files. Require a Git
    # project rather than silently scanning an arbitrary directory such as $HOME.
    proc=subprocess.run(['git','-c',f'safe.directory={root}','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'],capture_output=True,check=False)
    if proc.returncode: raise ValueError('Choose a Git project directory; context retrieval did not scan this path.')
    paths=sorted(set(os.fsdecode(x) for x in proc.stdout.split(b'\0') if x))
    # Include tracked paths in the ignore check: ls-files normally ignores
    # ignore rules for files that have already been added to Git.
    ignored=subprocess.run(['git','-c',f'safe.directory={root}','-C',str(root),'check-ignore','--no-index','-z','--stdin'],input=proc.stdout,capture_output=True,check=False)
    if ignored.returncode not in (0,1): raise ValueError('Could not apply project ignore rules; retrieval stopped.')
    ignored_paths={os.fsdecode(x) for x in ignored.stdout.split(b'\0') if x}
    paths=[p for p in paths if p not in ignored_paths]
    chunks=[]; warnings=[]; skipped=0; accepted=0
    for rel in paths:
        if not safe_path(rel): continue
        p=root/rel
        try:
            # Do not follow file or directory symlinks, including those pointing
            # inside the root. Never use content from outside the chosen tree.
            cur=root
            for part in Path(rel).parts:
                cur=cur/part
                if cur.is_symlink(): raise OSError('symlink')
            if not p.is_file() or p.stat().st_size>MAX_FILE: skipped+=1; continue
            if accepted>=MAX_FILES: warnings.append(f'File limit reached ({MAX_FILES}); results are incomplete.'); break
            data=p.read_bytes()
            if b'\0' in data: skipped+=1; continue
            text=data.decode('utf-8')
            if SECRET_MARKERS.search(text): skipped+=1; continue
        except (OSError, UnicodeError): skipped+=1; continue
        accepted+=1
        digest=hashlib.sha256(data).hexdigest()
        lines=text.splitlines()
        for start in range(0,len(lines),CHUNK_LINES):
            body='\n'.join(lines[start:start+CHUNK_LINES])
            if not body.strip(): continue
            chunks.append(Chunk(rel,start+1,min(start+CHUNK_LINES,len(lines)),body,digest))
            if len(chunks)>=MAX_CHUNKS: warnings.append(f'Chunk limit reached ({MAX_CHUNKS}); results are incomplete.'); break
        if len(chunks)>=MAX_CHUNKS: break
    if skipped: warnings.append(f'{skipped} unreadable, sensitive-looking, binary, oversized, or symlinked file(s) skipped.')
    return chunks,warnings

class BM25Index:
    """Reusable token statistics; scoring/order match the original BM25 function."""
    def __init__(self, chunks):
        self.chunks = chunks
        self.frequencies = [Counter(tokenize((c.path+' ')*2+c.text)) for c in chunks]
        self.lengths = [sum(f.values()) for f in self.frequencies]
        self.df = Counter(term for f in self.frequencies for term in f)
        self.average = sum(self.lengths)/len(chunks) if chunks else 1

    def search(self, query, limit=5, excluded_paths=None):
        words=set(tokenize(query))
        if not words or not self.chunks:return []
        excluded=set(excluded_paths or [])
        selected=[i for i,c in enumerate(self.chunks) if c.path not in excluded]
        if not selected:return []
        df=self.df if not excluded else Counter(term for i in selected for term in self.frequencies[i])
        average=self.average if not excluded else sum(self.lengths[i] for i in selected)/len(selected)
        average=average or 1
        scores=[]
        for i in selected:
            freq=self.frequencies[i];length=self.lengths[i];score=0.0
            for term in words:
                n=df[term]
                if not n:continue
                f=freq[term]
                if f:score+=math.log(1+(len(selected)-n+0.5)/(n+0.5))*f*2.2/(f+1.2*(0.25+0.75*length/average))
            if score>0:scores.append((self.chunks[i],score))
        return sorted(scores,key=lambda x:(-x[1],x[0].path,x[0].line_start))[:max(0,min(limit,10))]

def bm25_search(chunks: list[Chunk], query: str, limit: int=5) -> list[tuple[Chunk,float]]:
    return BM25Index(chunks).search(query,limit)

def format_result(results, warnings, method='bm25'):
    return {'method':method,'local_only':True,'warnings':warnings,'results':[{'path':c.path,'line_start':c.line_start,'line_end':c.line_end,'content_hash':c.content_hash,'score':round(float(score),6),'excerpt':c.text[:3000],'excerpt_truncated':len(c.text)>3000} for c,score in results]}
