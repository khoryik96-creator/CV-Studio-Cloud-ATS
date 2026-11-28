"""Private sandbox OAuth state vault, for a future dedicated broker only.

Linux local filesystem, one shared protected volume, separate AES-GCM key.
No HTTP routes, no network, no live credential acquisition. Filesystem locks
serialize each tenant's transitions across broker processes. Do not place this
volume in the document/web/worker containers.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import stat
import tempfile
from secrets import token_bytes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cloud.documents_jobs import uid

MAX_FILE=128*1024

class VaultError(ValueError):
    pass

class OAuthVault:
    def __init__(self,root,*,keys,active_version):
        self.root=Path(root)
        if not self.root.is_absolute() or self.root.is_symlink() or not self.root.is_dir():
            raise VaultError("Existing private vault directory required")
        info=self.root.stat()
        if info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700:
            raise VaultError("Vault must be service-owned mode 0700")
        self.root=self.root.resolve()
        if (not isinstance(keys,dict) or not 1<=len(keys)<=16 or active_version not in keys
                or any(not isinstance(k,str) or not re.fullmatch("[A-Za-z0-9_-]{1,32}",k)
                    or type(v) is not bytes or len(v)!=32 for k,v in keys.items())):
            raise VaultError("Invalid dedicated vault keyring")
        self._keys=dict(keys)
        self._active=active_version

    def _aad(self,tenant,version):
        return ("cvcloud.crm-oauth.v1:"+tenant+":"+version).encode("ascii")

    def _read(self,path,tenant):
        try:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        except FileNotFoundError:
            return {"revision":0,"state":"disconnected"}
        with os.fdopen(fd,"rb") as source:
            info=os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600:
                raise VaultError("Unsafe vault record")
            data=source.read(MAX_FILE+1)
        try:
            if len(data)>MAX_FILE:
                raise ValueError()
            envelope=json.loads(data)
            if set(envelope)!={"version","nonce","ciphertext"}:
                raise ValueError()
            version=envelope["version"]
            nonce=bytes.fromhex(envelope["nonce"])
            if len(nonce)!=12:
                raise ValueError()
            plain=AESGCM(self._keys[version]).decrypt(nonce,bytes.fromhex(envelope["ciphertext"]),self._aad(tenant,version))
            row=json.loads(plain)
            if (not isinstance(row,dict) or type(row.get("revision")) is not int or row["revision"]<0
                or row.get("state") not in ("disconnected","pending","exchanging","connected","refreshing","reconnect_required")):
                raise ValueError()
            return row
        except Exception:
            raise VaultError("Vault record authentication failed") from None

    def _write(self,path,tenant,row):
        nonce=token_bytes(12)
        version=self._active
        payload=json.dumps(row,ensure_ascii=True,separators=(",",":"),allow_nan=False).encode()
        encrypted=AESGCM(self._keys[version]).encrypt(nonce,payload,self._aad(tenant,version))
        data=json.dumps({"version":version,"nonce":nonce.hex(),"ciphertext":encrypted.hex()},separators=(",",":")).encode()
        if len(data)>MAX_FILE:
            raise VaultError("Vault record exceeds limit")
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root,prefix=".vault-",delete=False) as output:
                temp=output.name
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp,path)
            directory=os.open(self.root,os.O_DIRECTORY|os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temp is not None:
                Path(temp).unlink(missing_ok=True)

    @contextmanager
    def locked(self,tenant):
        import fcntl
        tenant=uid(tenant)
        fd=os.open(self.root/(tenant+".lock"),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600:
                raise VaultError("Unsafe vault lock")
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            path=self.root/(tenant+".json")
            yield self._read(path,tenant),lambda row:self._write(path,tenant,row)
        except BlockingIOError:
            raise VaultError("OAuth transition in progress") from None
        finally:
            os.close(fd)
