"""Private input publication with serialized, per-user admission.

Files are published before metadata commit. A failed/uncertain transaction may
leave an orphan for the future reconciler; never remove it on uncertain commit.
These limits cover registered inputs, not all physical storage.
"""
from uuid import uuid4
from cloud.documents_jobs import MAX_BYTES,MEDIA_TYPES,ScopeError
from cloud.private_storage import StorageError
from cloud.documents_jobs import JobConflict

MAX_INPUT_BYTES_PER_USER=256*1024*1024
MAX_INPUTS_PER_USER=100

class UploadService:
    def __init__(self,repository,storage):
        self.repository=repository
        self.storage=storage

    def upload(self,principal,stream,*,media_type,byte_size):
        if media_type not in MEDIA_TYPES or type(byte_size) is not int or not 1<=byte_size<=MAX_BYTES:
            raise StorageError("Invalid upload")
        with self.repository.scoped(principal) as (conn,tenant,owner):
            active=conn.execute("""SELECT u.id FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active
                FOR UPDATE OF u FOR SHARE OF t""",(tenant,owner)).fetchone()
            if not active:
                raise ScopeError("Account inactive")
            count,total=conn.execute("""SELECT count(*),coalesce(sum(byte_size),0) FROM cvcloud.documents
                WHERE tenant_id=%s AND owner_id=%s""",(tenant,owner)).fetchone()
            if count>=MAX_INPUTS_PER_USER or total+byte_size>MAX_INPUT_BYTES_PER_USER:
                raise JobConflict("Input storage quota reached")
            # Bounded read: content-length is required by the HTTP boundary.
            raw=stream.read(byte_size+1)
            if not isinstance(raw,bytes) or len(raw)!=byte_size:
                raise StorageError("Upload size mismatch")
            from io import BytesIO
            object_id=str(uuid4())
            info=self.storage.put(tenant,owner,object_id,BytesIO(raw),media_type)
            conn.execute("""INSERT INTO cvcloud.documents
                (tenant_id,id,owner_id,media_type,byte_size,sha256) VALUES (%s,%s,%s,%s,%s,%s)""",
                (tenant,object_id,owner,media_type,info.size,info.digest))
        return object_id
