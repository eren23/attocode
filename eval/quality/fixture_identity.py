"""Source-only fixture inventories; runtime indexes are excluded explicitly."""
import hashlib
import os
import stat
import zlib
from pathlib import Path, PurePosixPath


def source_manifest(root):
    root, result = Path(root), {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        if Path(parent) == root and '.attocode' in dirs:
            dirs.remove('.attocode')
        for name in [*dirs, *files]:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            key = path.relative_to(root).as_posix()
            if stat.S_ISLNK(mode):
                result[key] = {'kind': 'symlink', 'target': os.readlink(path)}
            elif stat.S_ISREG(mode):
                with path.open('rb') as stream:
                    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                result[key] = {'kind': 'file', 'bytes': path.stat().st_size, 'sha256': sha}
            elif not stat.S_ISDIR(mode):
                raise ValueError('unexpected fixture entry: ' + key)
    return result


def pinned_manifest(cache, tree):
    from eval.matrix.run import _blob_file, _stored
    result = {}
    for entry in tree['entries']:
        if not _stored(entry):
            continue
        name, mode, oid, size = entry
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or name in result:
            raise ValueError('invalid committed source path')
        body = zlib.decompress(_blob_file(cache, oid).read_bytes())
        actual = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        if actual != oid or len(body) != size:
            raise ValueError('committed source blob identity mismatch')
        result[name] = ({'kind': 'symlink', 'target': os.fsdecode(body)} if mode == '120000' else
                        {'kind': 'file', 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
    return result



def source_entry(manifest, name):
    """Resolve aliases through captured entries, following filesystem path order.

    Expand each symlink before interpreting a following parent component. Every
    link, directory and final file belongs to this inventory; never read the
    host filesystem or accept a path escaping the fixture.
    """
    if not isinstance(name, str) or not name or len(name) > 4096 or name.startswith('/'):
        raise ValueError('invalid source path')
    if all(part not in ('', '.', '..') for part in name.split('/')):
        direct = manifest.get(name)
        if isinstance(direct, dict) and direct.get('kind') == 'file':
            return direct
    pending, resolved, seen, links = name.split('/'), [], set(), 0
    while pending:
        state = (tuple(resolved), tuple(pending))
        if state in seen:
            raise ValueError('cyclic source alias')
        seen.add(state)
        if len('/'.join([*resolved, *pending])) > 4096:
            raise ValueError('oversized source alias')
        part, pending = pending[0], pending[1:]
        if part in ('', '.'):
            continue
        if part == '..':
            if not resolved:
                raise ValueError('source alias escapes fixture')
            resolved.pop()
            continue
        key = '/'.join([*resolved, part])
        entry = manifest.get(key)
        if isinstance(entry, dict) and entry.get('kind') == 'symlink':
            links += 1
            if links > 40:
                raise ValueError('source alias chain exceeds forty links')
            target = entry.get('target')
            if not isinstance(target, str) or not target or len(target) > 4096 or target.startswith('/'):
                raise ValueError('invalid source alias target')
            pending = [*target.split('/'), *pending]
        elif isinstance(entry, dict) and entry.get('kind') == 'file':
            if pending:
                raise ValueError('source alias traverses a regular file')
            return entry
        elif pending and any(path.startswith(key + '/') for path in manifest):
            resolved.append(part)
        else:
            raise ValueError('source alias target is missing from fixture')
    raise ValueError('source alias does not end at a regular file')
