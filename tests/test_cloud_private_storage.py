import io
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
import zipfile
from cloud.private_storage import PrivateStorage, StorageError, validate_payload, DOCX

class TestStorage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.storage=PrivateStorage(self.root)
        self.ids=tuple(str(uuid4()) for _ in range(3))
    def test_roundtrip_and_no_overwrite(self):
        raw=b"Fictional candidate"
        info=self.storage.put(*self.ids,io.BytesIO(raw),"text/plain")
        self.assertEqual(self.storage.read_verified(*self.ids,info),raw)
        with self.assertRaises(FileExistsError):
            self.storage.put(*self.ids,io.BytesIO(b"Different"),"text/plain")
        self.assertEqual(self.storage.read_verified(*self.ids,info),raw)
        with self.assertRaises(FileNotFoundError):
            self.storage.read_verified(str(uuid4()),*self.ids[1:],info)
        if os.name=="posix":
            self.assertEqual(next(self.root.glob("*.blob")).stat().st_mode & 0o777,0o600)
    def test_tamper_and_invalid_path(self):
        info=self.storage.put(*self.ids,io.BytesIO(b"test"),"text/plain")
        next(self.root.glob("*.blob")).write_bytes(b"fake")
        with self.assertRaises(StorageError):
            self.storage.read_verified(*self.ids,info)
        with self.assertRaises(ValueError):
            self.storage.put("../escape",*self.ids[1:],io.BytesIO(b"x"),"text/plain")
    def test_bad_document(self):
        for raw,kind in ((b"not PDF","application/pdf"),(b"\x00","text/plain"),(b"not zip",DOCX)):
            with self.assertRaises(StorageError):
                validate_payload(raw,kind)
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            for name in ("[Content_Types].xml","word/document.xml","_rels/.rels","../escape"):
                z.writestr(name,"x")
        with self.assertRaises(StorageError):
            validate_payload(buf.getvalue(),DOCX)
    @unittest.skipUnless(os.name=="posix","Linux private-volume behavior")
    def test_symlink_rejected(self):
        target=self.root/"external"
        target.write_bytes(b"data")
        path=self.storage._path(*self.ids)
        path.symlink_to(target)
        with self.assertRaises(FileExistsError):
            self.storage.put(*self.ids,io.BytesIO(b"safe"),"text/plain")
        self.assertEqual(target.read_bytes(),b"data")
