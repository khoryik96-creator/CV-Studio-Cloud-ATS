import unittest
from unittest.mock import patch
from uuid import uuid4
from cloud.deploy.online_workspace_schema import migration_plan, WORKSPACE_SCRIPTS
from cloud.deploy.workspace_roles import discover_roster, verify_service_role
from cloud.deploy.online_workspace import assemble_workspace, assemble_worker

class Result:
    def __init__(self, value):
        self.value = value
    def fetchone(self):
        return self.value
    def fetchall(self):
        return self.value

class Connection:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.statements = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return Result(next(self.responses))

class WorkspaceTests(unittest.TestCase):
    def test_manifest_contains_ordered_transactional_migrations(self):
        plan=migration_plan()
        self.assertEqual(tuple(p[0] for p in plan),WORKSPACE_SCRIPTS)
        self.assertEqual(len(plan),11)
        for name,signature,statement in plan:
            self.assertRegex(signature,r"^[0-9a-f]{64}$")
            self.assertFalse(statement.rstrip().endswith("COMMIT;"))
        self.assertEqual(list(WORKSPACE_SCRIPTS),sorted(WORKSPACE_SCRIPTS))

    def test_wrong_database_and_role_refused(self):
        for db, role in (("hiringplug","cvcloud_document"),("cvcloud_online","cvcloud_auth")):
            conn=Connection([(db,role,role,True,True,True,True,True,True)])
            with self.assertRaises(RuntimeError):
                verify_service_role(lambda:conn,"document")
            self.assertEqual(len(conn.statements),1)

    def test_privileged_role_refused(self):
        conn=Connection([("cvcloud_online","cvcloud_document","cvcloud_document",False,True,True,True,True,True)])
        with self.assertRaises(RuntimeError):
            verify_service_role(lambda:conn,"document")

    def test_role_with_write_grants_refused(self):
        conn=Connection([("cvcloud_online","cvcloud_document","cvcloud_document",True,True,True,True,True,True),
            (False,False,False,False),(True,False,False,False)])
        with self.assertRaises(RuntimeError):
            verify_service_role(lambda:conn,"document")

    def test_roster_has_no_session_token_and_refuses_overflow(self):
        rows=[(str(uuid4()),str(uuid4()),"owner"),(str(uuid4()),str(uuid4()),"recruiter")]
        with patch("cloud.deploy.workspace_roles.verify_service_role"):
            self.assertEqual([p.csrf for p in discover_roster(lambda:Connection([rows]))],["",""])
            self.assertEqual(discover_roster(lambda:Connection([[]])),())
            with self.assertRaises(RuntimeError):
                discover_roster(lambda:Connection([rows*51]))
            with self.assertRaises(RuntimeError):
                discover_roster(lambda:Connection([[rows[0],rows[0]]]))
            with self.assertRaises(RuntimeError):
                discover_roster(lambda:Connection([[(rows[0][0],rows[0][1],"invalid")]]))

    def test_shared_connection_factory_refused(self):
        connection=lambda:None
        with self.assertRaises(ValueError):
            assemble_workspace(config=None,auth_connect=connection,document_connect=connection,
                admin_connect=connection,provider_connect=connection,storage_root=None,cipher=None,catalogue=None)
        with self.assertRaises(ValueError):
            assemble_worker(worker_connect=connection,provider_connect=connection,storage_root=None,
                cipher=None,catalogue=None,principals=[])

    def test_scheduler_reuses_runtime_and_stops_on_roster_failure(self):
        from unittest.mock import Mock
        from cloud.auth import Principal
        from cloud.deploy.workspace_scheduler import WorkspaceScheduler
        roster=(Principal(str(uuid4()),str(uuid4()),"owner",""),)
        runtime=Mock()
        runtime.tick.return_value=("idle",)
        factory=Mock(return_value=runtime)
        scheduler=WorkspaceScheduler(scheduler_connect=lambda:None,runtime_factory=factory)
        with patch("cloud.deploy.workspace_scheduler.discover_roster",side_effect=[roster,roster,RuntimeError("db unavailable"),()]):
            self.assertEqual(scheduler.tick(),("idle",))
            self.assertEqual(scheduler.tick(),("idle",))
            factory.assert_called_once_with(roster)
            with self.assertRaises(RuntimeError):
                scheduler.tick()
            self.assertEqual(runtime.tick.call_count,2)
            self.assertEqual(scheduler.tick(),())

    def test_scheduler_honors_cooperative_stop(self):
        from threading import Event
        from unittest.mock import Mock
        from cloud.deploy.workspace_scheduler import WorkspaceScheduler
        stop=Event()
        scheduler=WorkspaceScheduler(scheduler_connect=lambda:None,runtime_factory=Mock())
        statuses=[]
        def on_round(status):
            statuses.append(status)
            stop.set()
        with patch("cloud.deploy.workspace_scheduler.discover_roster",return_value=()) as discover:
            scheduler.run(stop,on_round=on_round)
            discover.assert_called_once()
        self.assertEqual(statuses,["ok"])

if __name__=="__main__":
    unittest.main()
