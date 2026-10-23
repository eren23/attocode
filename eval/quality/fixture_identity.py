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
