"""Local CLI paths: walk directory descriptors without following symlinks.

Trusted output parents are an operator prerequisite, not same-UID containment.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat


@contextmanager
def parent_directory(value, *, create=False, trusted=False):
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('Parent traversal (..) is not accepted; use an explicit path')
    path = path.absolute()
    if not path.name:
        raise ValueError('A file or new directory name is required')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in (*path.parts[1:-1], None):
            if trusted:
                info = os.fstat(fd)
                if info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid()):
                    raise PermissionError('Use a trusted, non-shared parent for the control demo')
            if component is None:
                break
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, mode=0o700, dir_fd=fd)
                next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, path.name, path
    finally:
        os.close(fd)


def read_json_bytes(value, *, limit=2_000_000):
    with parent_directory(value) as (parent, name, _):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('JSON input must be a regular file, without symlinks')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                raise ValueError('JSON input must be a regular file')
            if opened.st_size > limit:
                raise ValueError('JSON input exceeds 2000000 bytes')
            content = stream.read(limit + 1)
            if len(content) > limit:
                raise ValueError('JSON input exceeds 2000000 bytes')
            return content
