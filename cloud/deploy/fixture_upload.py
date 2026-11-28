"""Interactive fixture admission: never persist arbitrary candidate documents."""
from io import BytesIO
from cloud.private_storage import StorageError

class FixtureUpload:
    def __init__(self, delegate, source):
        self.delegate = delegate
        self.expected = source.strip()
        self.limit = len(source.encode("utf-8")) + 16

    def upload(self, principal, stream, *, media_type, byte_size):
        if media_type != "text/plain" or type(byte_size) is not int or not 1 <= byte_size <= self.limit:
            raise StorageError("Only the supplied fictional text fixture is accepted")
        raw = stream.read(byte_size + 1)
        try:
            valid = len(raw) == byte_size and raw.decode("utf-8").strip() == self.expected
        except (UnicodeError, AttributeError, TypeError):
            valid = False
        if not valid:
            raise StorageError("Only the supplied fictional text fixture is accepted")
        return self.delegate.upload(principal, BytesIO(raw), media_type=media_type, byte_size=byte_size)
