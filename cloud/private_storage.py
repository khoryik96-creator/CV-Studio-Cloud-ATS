"""Bounded private document byte store. Linux local volume, never a static directory.

Object names are opaque, server-generated UUIDs; callers must authenticate and
authorize ownership against metadata before using these internal methods.
The storage root and its ancestors must be owned by the service/operator, and
must not be writable by any other account. No request routes are exposed here.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import io
import os
from pathlib import Path
import stat
import tempfile
from uuid import UUID
import zipfile

from cloud.documents_jobs import MAX_BYTES, MEDIA_TYPES

CHUNK = 64 * 1024
MAX_ZIP_ENTRIES = 2048
MAX_EXPANDED = 128 * 1024 * 1024
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

class StorageError(ValueError):
    pass

@dataclass(frozen=True)
class StoredObject:
    size: int
    digest: str
    media_type: str

def canonical_id(value):
    return str(UUID(str(value)))

def validate_payload(raw, media_type):
    """Structural preflight only; not a malware scanner or full document parser."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES or media_type not in MEDIA_TYPES:
        raise StorageError("Invalid file size or media type")
    if media_type == "application/pdf":
        if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
            raise StorageError("Invalid PDF signature")
    elif media_type == "text/plain":
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise StorageError("Invalid UTF-8 text") from exc
        if any(ord(c) < 32 and c not in "\t\r\n\f" for c in text):
            raise StorageError("Unexpected text control character")
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                items = archive.infolist()
                if len(items) > MAX_ZIP_ENTRIES or sum(x.file_size for x in items) > MAX_EXPANDED:
                    raise StorageError("DOCX expansion limit exceeded")
                seen = set()
                for item in items:
                    name = item.filename
                    parts = name.rstrip("/").split("/")
                    if not name or "\\" in name or name.startswith("/") or any(p in ("", ".", "..") for p in parts) or ":" in name or item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16):
                        raise StorageError("Unsafe DOCX archive entry")
                    key = name.casefold()
                    if key in seen or key.endswith("vbaproject.bin") or key.startswith("word/embeddings/"):
                        raise StorageError("Unsupported DOCX content")
                    seen.add(key)
                if not {"[content_types].xml","word/document.xml","_rels/.rels"} <= seen:
                    raise StorageError("Invalid DOCX package")
                if archive.testzip() is not None:
                    raise StorageError("Corrupt DOCX archive entry")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
            raise StorageError("Invalid DOCX archive") from exc
    return StoredObject(len(raw), sha256(raw).hexdigest(), media_type)

class PrivateStorage:
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_absolute() or self.root.is_symlink() or not self.root.is_dir():
            raise StorageError("Private storage must be an existing absolute directory")
        if os.name == "posix" and self.root.stat().st_mode & 0o077:
            raise StorageError("Private storage directory must have mode 0700")
        self.root = self.root.resolve()

    def _path(self, tenant, owner, document):
        # Flat directory avoids user-controlled path components and parent symlinks.
        return self.root / (".".join(canonical_id(x) for x in (tenant,owner,document)) + ".blob")

    def put(self, tenant, owner, document, stream, media_type):
        destination = self._path(tenant, owner, document)
        chunks, total = [], 0
        while True:
            chunk = stream.read(CHUNK)
            if not isinstance(chunk, bytes):
                raise StorageError("Expected a binary stream")
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                raise StorageError("Document exceeds size limit")
            chunks.append(chunk)
        raw = b"".join(chunks)
        info = validate_payload(raw, media_type)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".staging-", delete=False) as f:
                name = f.name
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            # No replacement: a collision or retry can never overwrite another object.
            os.link(name, destination, follow_symlinks=False)
            if os.name == "posix":
                fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        finally:
            if name is not None:
                os.unlink(name)
        return info

    def read_verified(self, tenant, owner, document, expected):
        path = self._path(tenant, owner, document)
        if not isinstance(expected, StoredObject) or not 1 <= expected.size <= MAX_BYTES:
            raise StorageError("Invalid stored metadata")
        if path.is_symlink():
            raise StorageError("Invalid storage object")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_size != expected.size:
                raise StorageError("Stored size mismatch")
            data = f.read(expected.size + 1)
        if len(data) != expected.size or sha256(data).hexdigest() != expected.digest:
            raise StorageError("Stored digest mismatch")
        return data
