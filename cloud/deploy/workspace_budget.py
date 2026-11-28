"""Offline operator-only cumulative AI budget management.

Never resets spending or outstanding reservations. No HTTP budget mutation,
provider call or recurring top-up. Run only in the marked workspace.
"""
import argparse
import re
import sys
from cloud.auth import TENANT
from cloud.ai_budget import amount
from cloud.deploy.online_owner import operator_connection, verify_owner_database

def change_limit(connect, *, tenant, expected, new_limit):
    if not isinstance(tenant,str) or not TENANT.fullmatch(tenant):
        raise ValueError("Invalid organisation slug")
    new_limit=amount(new_limit,allow_zero=True)
    if expected is not None:
        expected=amount(expected,allow_zero=True)
    with connect() as conn:
        verify_owner_database(conn)
        if conn.execute("SELECT to_regclass('cvcloud.online_admin_grants') IS NOT NULL").fetchone()!=(True,):
            raise RuntimeError("Marked workspace required")
        row=conn.execute("SELECT id::text FROM cvcloud.tenants WHERE slug=%s AND active FOR UPDATE",(tenant,)).fetchone()
        if row is None:
            raise ValueError("Unknown or inactive organisation")
        tenant_id=row[0]
        conn.execute("SELECT set_config('cvcloud.tenant_id',%s,true)",(tenant_id,))
        current=conn.execute("""SELECT limit_microusd,reserved_microusd,spent_microusd
            FROM cvcloud.ai_budgets WHERE tenant_id=%s FOR UPDATE""",(tenant_id,)).fetchone()
        if current is None:
            if expected is not None:
                raise ValueError("Budget changed; review current limit")
            conn.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,%s)",(tenant_id,new_limit))
            return new_limit,0,0
        if expected is None or current[0]!=expected:
            raise ValueError("Budget changed; review current limit")
        # Lowering below committed costs intentionally stops new reservations.
        # Never erase the amount already committed or settled.
        conn.execute("UPDATE cvcloud.ai_budgets SET limit_microusd=%s WHERE tenant_id=%s",(new_limit,tenant_id))
        return new_limit,current[1],current[2]

def parse_microusd(value):
    if not isinstance(value,str) or not re.fullmatch(r"(0|[1-9][0-9]{0,12})",value):
        raise argparse.ArgumentTypeError("Use whole micro-USD, without separators")
    try:
        return amount(int(value),allow_zero=True)
    except ValueError:
        raise argparse.ArgumentTypeError("Budget outside permitted range") from None

def main():
    parser=argparse.ArgumentParser(description="Explicitly configure cumulative tenant AI spending limit (micro-USD)")
    parser.add_argument("--tenant",required=True)
    expected=parser.add_mutually_exclusive_group(required=True)
    expected.add_argument("--new",action="store_true")
    expected.add_argument("--expected-limit",type=parse_microusd)
    parser.add_argument("--limit",required=True,type=parse_microusd)
    parser.add_argument("--confirm",action="store_true",required=True)
    args=parser.parse_args()
    try:
        limit,reserved,spent=change_limit(operator_connection,tenant=args.tenant,
            expected=None if args.new else args.expected_limit,new_limit=args.limit)
    except Exception:
        parser.exit(1,"Budget change refused. Verify dedicated workspace, tenant and expected limit.\n")
    print(f"Limit={limit} reserved={reserved} spent={spent} (micro-USD). No provider request made.")

if __name__=="__main__":
    main()
