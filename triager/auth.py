"""Persistent local bootstrap token; explicit deployment credentials take precedence."""

import os
import re
import secrets
import stat
from pathlib import Path


def local_token(filename):
    path = Path(filename)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (os.name == "posix" and info.st_mode & 0o077):
                raise ValueError("Local token file must be a private regular file (mode 0600)")
            token = stream.read(256).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise ValueError("Invalid local token file; restore it or set DESK_TOKEN explicitly")
        return token, False
    token = secrets.token_urlsafe(32)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(token + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return token, True
