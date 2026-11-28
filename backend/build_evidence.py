"""Evidence-based outcomes; worker statements never count as verification."""
import hashlib
import subprocess
from pathlib import Path


def worktree_stamp(root):
    """Bounded content snapshot; symlinks are hashed as links, never followed."""
    if not root or not Path(root).is_dir():return None
    root=Path(root)
    def git(*args):
        return subprocess.run(['git','-c','core.hooksPath=/dev/null','-C',str(root),*args],capture_output=True,check=True,timeout=3).stdout
    try:
        digest=hashlib.sha256(git('rev-parse','HEAD'))
        names=set(filter(None,(git('diff','--no-ext-diff','--no-textconv','--name-only','-z','HEAD')+git('ls-files','--others','--exclude-standard','-z')).split(b'\0')))
        if len(names)>500:return None
        size=0
        for name in sorted(names):
            if name in (b'.venv',b'node_modules'):continue
            path=root/str(name,'utf-8')
            if any(part=='..' for part in path.relative_to(root).parts):return None
            # A changed directory link must not redirect reads outside the worktree.
            if any(p.is_symlink() for p in path.parents if p!=root and p.is_relative_to(root)):return None
            digest.update(name+b'\0')
            if path.is_symlink():digest.update(b'link:'+str(path.readlink()).encode())
            elif path.is_file():
                length=path.stat().st_size;size+=length
                if length>2_000_000 or size>20_000_000:return None
                digest.update(str(path.stat().st_mode).encode());digest.update(path.read_bytes())
            elif path.exists():return None
            else:digest.update(b'deleted')
        return digest.hexdigest()
    except (OSError,ValueError,subprocess.SubprocessError):return None

def check_status(code, output):
    if code == 0:
        if 'Ran 0 tests' in output:
            return 'failed', 'No tests were discovered.'
        return 'passed', ''
    if any(marker in output.lower() for marker in [
        'blocked by sandbox', 'library not loaded:', 'sandbox-exec:',
        'command not found', 'bad interpreter:', 'no module named pytest',
        'failed to initialize sandbox', 'error loading shared libraries',
    ]) or code in (126, 127):
        return 'blocked', 'The check could not run in this environment. Fix its runtime or permissions before retrying.'
    return 'failed', 'The check ran and did not pass.'


def outcome(job):
    state, payload = job['state'], job['payload']
    checks = payload.get('checks', [])
    blocked = any(c.get('status') == 'blocked' or
                  not c.get('passed') and check_status(1, c.get('details', ''))[0] == 'blocked' for c in checks)
    if state in {'queued', 'preparing', 'preflight', 'working', 'checking', 'correcting', 'stopping'}:
        return {'code': 'working', 'title': 'In progress', 'summary': payload['message']}
    if state == 'stopped':
        return {'code': 'stopped', 'title': 'Stopped', 'summary': payload['message']}
    if state == 'blocked_setup' or blocked:
        return {'code': 'blocked_setup', 'title': 'Blocked by setup',
                'summary': 'Verification could not run. This is an environment issue, not a failing feature test.'}
    if state == 'verified':
        stamp=payload.get('check_stamp')
        if not stamp or stamp!=worktree_stamp(payload.get('worktree')):
            return {'code':'needs_review','title':'Needs review','summary':'The worktree changed after verification. Recheck it and confirm the behavior again.'}
        return {'code': 'verified', 'title': 'Verified against approved criteria',
                'summary': 'Automated checks passed and you confirmed every success criterion. Review the diff before applying changes.'}
    if state == 'failed':
        return {'code': 'needs_review', 'title': 'Needs review', 'summary': payload['message']}
    passed = bool(checks) and all(c['passed'] for c in checks)
    return {'code': 'needs_review', 'title': 'Needs review', 'summary':
            'Automated checks passed. Goal-specific behavior still needs your review.' if passed and ('check_stamp' not in payload or payload['check_stamp']) else payload['message']}
