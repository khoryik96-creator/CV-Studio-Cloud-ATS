"""Server-side session policy. No desktop state or external provider credentials."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Protocol
from werkzeug.security import check_password_hash, generate_password_hash

ROLES = frozenset({"owner", "admin", "recruiter"})
TTL = timedelta(hours=8)
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
TENANT = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62})")
PASSWORD_METHOD = "scrypt:32768:8:1"

@dataclass(frozen=True)
class Account:
    tenant_id: str
    user_id: str
    role: str
    password_hash: str
    active: bool = True

@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    role: str
    csrf: str

class AuthStore(Protocol):
    def consume_attempt(self, key: str, now: datetime) -> bool: ...
    def find_account(self, tenant: str, email: str) -> Account | None: ...
    def create_session(self, digest: str, csrf: str, account: Account, expires: datetime) -> bool: ...
    def get_session(self, digest: str, now: datetime) -> Principal | None: ...
    def delete_session(self, digest: str) -> None: ...

def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def password_hash(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    return generate_password_hash(password, method=PASSWORD_METHOD)

class Auth:
    def __init__(self, store: AuthStore, *, clock=lambda: datetime.now(timezone.utc)):
        self.store = store
        self.clock = clock
        self.dummy_hash = password_hash(secrets.token_urlsafe(32))

    def login(self, tenant, email, password, client_key):
        if not all(isinstance(v, str) for v in (tenant, email, password, client_key)):
            return None
        tenant, email = tenant.strip().lower(), email.strip().casefold()
        if not TENANT.fullmatch(tenant) or not 3 <= len(email) <= 254 or "@" not in email or not 1 <= len(password) <= 256 or not client_key or len(client_key) > 128:
            return None
        now = self.clock()
        # Both limits are consumed before lookup, even for nonexistent accounts.
        source_ok = self.store.consume_attempt(digest("source:" + client_key), now)
        if not source_ok:
            return None  # do not create unlimited distinct account buckets from a blocked source
        account_ok = self.store.consume_attempt(digest("account:" + tenant + ":" + email), now)
        if not account_ok:
            return None
        account = self.store.find_account(tenant, email)
        stored = account.password_hash if account and account.active and account.role in ROLES else self.dummy_hash
        try:
            valid = check_password_hash(stored, password)
        except (ValueError, TypeError):
            valid = False
        if not valid or not account or not account.active or account.role not in ROLES:
            return None
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        if not self.store.create_session(digest(raw), csrf, account, now + TTL):
            return None  # account changed while password was being checked
        return raw

    def principal(self, raw):
        if not isinstance(raw, str) or not TOKEN.fullmatch(raw):
            return None
        p = self.store.get_session(digest(raw), self.clock())
        return p if p and p.role in ROLES else None

    def logout(self, raw, csrf):
        p = self.principal(raw)
        if not p or not isinstance(csrf, str) or not TOKEN.fullmatch(csrf) or not hmac.compare_digest(p.csrf, csrf):
            return False
        self.store.delete_session(digest(raw))
        return True
