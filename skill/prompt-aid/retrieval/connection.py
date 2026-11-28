"""Private local service descriptors shared by CLI and MCP clients."""
import json,os,http.client
from pathlib import Path

def write_private(path, value):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os,'O_NOFOLLOW',0), 0o600)
    with os.fdopen(fd,'w') as stream:
        os.fchmod(stream.fileno(),0o600);json.dump(value,stream)
    os.replace(temp,path)

def read_private(path):
    info=path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError('Workspace configuration must be an owned, private regular file (0600).')
    if info.st_size>16000:raise ValueError('Workspace configuration is too large.')
    return json.loads(path.read_text())

def request(config, route, payload=None, timeout=3):
    url=config['url']
    from urllib.parse import urlparse
    parsed=urlparse(url)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path not in ('','/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Workspace address must be loopback HTTP.')
    token_file=Path(config['token_file']);info=token_file.lstat()
    if token_file.is_symlink() or not token_file.is_file() or info.st_uid!=os.getuid() or info.st_mode & 0o077 or info.st_size>4096:
        raise ValueError('Invalid private token file.')
    if not isinstance(route,str) or not route.startswith('/') or route.startswith('//'):
        raise ValueError('Invalid local route.')
    token=token_file.read_text().strip()
    if len(token)<32 or len(token)>4096:raise ValueError('Invalid private token.')
    # HTTPConnection has no proxy discovery, TLS setup or redirect following.
    # Only the validated literal loopback host receives the token.
    client=http.client.HTTPConnection('127.0.0.1',parsed.port or 80,timeout=timeout)
    try:
        body=json.dumps(payload).encode() if payload is not None else None
        client.request('POST' if payload is not None else 'GET',route,body=body,
                       headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        response=client.getresponse();raw=response.read(256001)
        if len(raw)>256000:raise ValueError('Context response exceeded its size limit.')
        if response.status!=200:raise ValueError('Local workspace rejected the operation (HTTP '+str(response.status)+').')
        return json.loads(raw)
    finally:client.close()

def health(config):
    return request(config,'/health',timeout=1)
