"""Restricted online data repository using database-side account locks."""
from cloud.documents_jobs import DocumentJobs

class OnlineDocumentJobs(DocumentJobs):
    def lock_active_account(self, conn, tenant, user, *, exclusive=False):
        if type(exclusive) is not bool:
            raise ValueError("Invalid lock mode")
        # Verify the explicit principal agrees with the transaction-local scope.
        row=conn.execute("""SELECT cvcloud.lock_workspace_account(%s)
            WHERE current_setting('cvcloud.tenant_id',true)=%s
              AND current_setting('cvcloud.user_id',true)=%s""",
            (exclusive,tenant,user)).fetchone()
        return row[0] if row else None
