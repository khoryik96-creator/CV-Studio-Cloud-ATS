"""Cooperative lease supervision; caller must enforce an outer process deadline.

No scheduler or production worker wiring. The renewal callable must use its
own DB connection, bounded DB timeouts and the same immutable lease token.
"""
from threading import Event, Thread, Lock
from time import monotonic

class LeaseLost(RuntimeError):
    pass

class LeaseSupervisor:
    def __init__(self, renew, *, interval=20, deadline=600, clock=monotonic):
        if not 0 < interval <= 30 or not interval < deadline <= 3600:
            raise ValueError("invalid supervision limits")
        self.renew=renew
        self.interval=interval
        self.deadline=deadline
        self.clock=clock
        self._stop=Event()
        self._lost=Event()
        self._lock=Lock()
        self._started=False
        self._thread=None
        self._end=None

    def _renew(self):
        try:
            if self.clock()>=self._end or not self.renew():
                self._lost.set()
                return False
            return True
        except Exception:
            self._lost.set()
            return False

    def _loop(self):
        while not self._stop.wait(self.interval):
            if not self._renew():
                return

    def __enter__(self):
        with self._lock:
            if self._started:
                raise RuntimeError("supervisor is single-use")
            self._started=True
        self._end=self.clock()+self.deadline
        if not self._renew():
            raise LeaseLost("lease_unavailable")
        self._thread=Thread(target=self._loop,name="cvcloud-heartbeat",daemon=True)
        self._thread.start()
        return self

    def check(self):
        if not self._started or self._end is None or self._stop.is_set() or self._lost.is_set() or self.clock()>=self._end:
            raise LeaseLost("lease_lost_or_deadline")

    def __exit__(self,exc_type,exc,tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                self._lost.set()
        if exc_type is None and (self._lost.is_set() or self.clock()>=self._end):
            raise LeaseLost("lease_lost_or_deadline")
        return False
