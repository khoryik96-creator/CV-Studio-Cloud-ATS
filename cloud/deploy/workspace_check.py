"""Internal web liveness; deliberately not a production readiness check."""
from cloud.deploy.online_check import main as check_listener
from cloud.deploy.workspace_config import service_connection
from cloud.deploy.workspace_roles import verify_service_role
from cloud.private_storage import PrivateStorage
from cloud.deploy.workspace_admin_install import verify_admin_role

def main():
    for service in ("document","provider"):
        verify_service_role(service_connection(service),service)
    verify_admin_role(service_connection("admin"))
    PrivateStorage("/srv/cvcloud/data")
    check_listener()

if __name__=="__main__":
    try:
        main()
    except Exception:
        raise SystemExit(1) from None
