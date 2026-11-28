"""Offline operator-only owner provisioning; no HTTP or default accounts."""
import argparse
import getpass
import os
from pathlib import Path
import sys
import warnings
from uuid import uuid4

from cloud.auth import TENANT, password_hash

def normalize_owner(tenant, email, password):
    if not isinstance(tenant,str) or not TENANT.fullmatch(tenant):
        raise ValueError("Invalid organisation slug")
    if not isinstance(email,str):
        raise ValueError("Invalid email")
    email=email.strip().casefold()
    if (not 3<=len(email)<=254 or email.count("@")!=1
            or not all(email.split("@")) or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in email)):
        raise ValueError("Invalid email")
    try:
        email.encode("utf-8")
        if not isinstance(password,str) or not 16<=len(password)<=256 or any(ord(c)<32 or ord(c)==127 for c in password):
            raise ValueError()
        password.encode("utf-8")
    except (UnicodeError,ValueError):
        raise ValueError("Owner password must contain 16 to 256 characters without control characters") from None
    return tenant,email

def verify_owner_database(conn):
    row=conn.execute("""SELECT current_database(),current_user::text,
        (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='cvcloud'),
        to_regclass('public.cvcloud_fixture_marker') IS NULL,
        to_regprocedure('cvcloud.lock_auth_account(uuid,uuid,text,bigint,bigint)') IS NOT NULL,
        NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication)
        FROM pg_roles WHERE rolname=current_user""").fetchone()
    if (not row or row[0]!="cvcloud_online" or row[1]!="cvcloud_schema_owner"
            or row[1]!=row[2] or row[3:]!=(True,True,True)):
        raise RuntimeError("Refusing provisioning outside dedicated online schema owner")

def provision_owner(connect, *, tenant, email, password):
    tenant,email=normalize_owner(tenant,email,password)
    hashed=password_hash(password)
    with connect() as conn:
        verify_owner_database(conn)
        conn.execute("SELECT pg_advisory_xact_lock(20261128, 48)")
        # Existing organisations are never mutated by this bootstrap operation.
        tenant_id,user_id=str(uuid4()),str(uuid4())
        row=conn.execute("""INSERT INTO cvcloud.tenants (id,slug) VALUES (%s,%s)
            ON CONFLICT (slug) DO NOTHING RETURNING id""",(tenant_id,tenant)).fetchone()
        if not row:
            raise ValueError("Organisation already exists; bootstrap does not reset credentials")
        conn.execute("""INSERT INTO cvcloud.users (tenant_id,id,email_normalized,password_hash,role)
            VALUES (%s,%s,%s,%s,'owner')""",(tenant_id,user_id,email,hashed))
    return tenant_id,user_id

def operator_connection():
    import psycopg
    path=os.environ.get("CVCLOUD_SCHEMA_PASSWORD_FILE","")
    if not path or not Path(path).is_absolute():
        raise ValueError("Absolute mounted schema owner password file required")
    password=Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    if not 24<=len(password)<=256 or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in password):
        raise ValueError("Strong schema owner database password required")
    return psycopg.connect(host="online-db",port=5432,dbname="cvcloud_online",
        user="cvcloud_schema_owner",password=password,connect_timeout=5,
        options="-c statement_timeout=5000 -c lock_timeout=3000")

def main():
    parser=argparse.ArgumentParser(description="Create the first owner of a new online organisation")
    parser.add_argument("--tenant",required=True)
    parser.add_argument("--email",required=True)
    args=parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(2,"Interactive terminal required; password is never accepted as an argument.\n")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error",getpass.GetPassWarning)
            password=getpass.getpass("New owner password: ")
            confirmation=getpass.getpass("Confirm owner password: ")
        if password!=confirmation:
            raise ValueError("Passwords do not match")
        provision_owner(operator_connection,tenant=args.tenant,email=args.email,password=password)
    except (Exception,KeyboardInterrupt):
        # Driver errors may contain sensitive data; never print them here.
        parser.exit(1,"Owner provisioning failed. Verify input, dedicated schema and credentials.\n")
    print("Owner created. No password or session token was written to output.")

if __name__=="__main__":
    main()
