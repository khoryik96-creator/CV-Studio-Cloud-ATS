"""Internal bounded scheduler; no HTTP worker trigger or public entrypoint."""
from threading import Event, Lock
from cloud.deploy.workspace_roles import discover_roster

class WorkspaceScheduler:
    def __init__(self, *, scheduler_connect, runtime_factory, interval=2):
        if not callable(scheduler_connect) or not callable(runtime_factory):
            raise ValueError("Trusted scheduler and runtime factory required")
        if type(interval) is not int or not 1<=interval<=30:
            raise ValueError("Invalid scheduling interval")
        self._connect=scheduler_connect
        self._factory=runtime_factory
        self._interval=interval
        self._identities=None
        self._runtime=None
        self._lock=Lock()

    def tick(self):
        """Refresh active identities; keep fairness across stable roster rounds.

        A failed roster lookup must never dispatch using stale principals.
        WorkerRuntime remains responsible for lease fencing and budget checks.
        """
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Overlapping scheduling round")
        try:
            roster=discover_roster(self._connect)
            if not roster:
                self._identities=None
                self._runtime=None
                return ()
            if roster!=self._identities:
                self._identities=None
                self._runtime=None
                runtime=self._factory(roster)
                self._runtime=runtime
                self._identities=roster
            return self._runtime.tick()
        except Exception:
            self._identities=None
            self._runtime=None
            raise
        finally:
            self._lock.release()

    def run(self, stop: Event, *, on_round):
        """Run until cooperative stop, never start another round after stop.

        Callback receives sanitized status only. Unexpected failures terminate
        the loop so a future supervisor can back off/restart. In-flight calls
        remain bounded by the worker's transport and lease policy.
        """
        if not isinstance(stop,Event) or not callable(on_round):
            raise ValueError("Stop event and status callback required")
        while not stop.is_set():
            try:
                outcomes=self.tick()
            except Exception:
                on_round("unavailable")
                raise RuntimeError("Workspace scheduling failed") from None
            on_round("degraded" if "unavailable" in outcomes else "ok")
            if stop.wait(self._interval):
                break
