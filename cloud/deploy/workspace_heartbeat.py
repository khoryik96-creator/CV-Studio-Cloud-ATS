"""Process watchdog for bounded workspace scheduler rounds.

A heartbeat is liveness only, never proof of provider readiness or completed
jobs. The watchdog hard-exits a stuck process after its outer deadline; the
existing database lease fencing handles uncertain work after expiry.
"""
import json
import os
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from uuid import uuid4

PATH=Path("/tmp/cvcloud-worker-heartbeat.json")
INTERVAL=5
MAX_ROUND=660
STALE=20

class Heartbeat:
    def __init__(self,path=PATH,*,clock=monotonic,exit_process=os._exit):
        self.path=Path(path)
        self.clock=clock
        self.exit_process=exit_process
        self._lock=RLock()
        self._stop=Event()
        self._status="starting"
        self._since=self.clock()
        self._thread=None

    def _write(self):
        # Serialize the snapshot and atomic replacement with state transitions.
        with self._lock:
            now=self.clock()
            status,since=self._status,self._since
            if status in ("starting","running") and now-since>MAX_ROUND:
                self.exit_process(1)
                return
            tmp=self.path.with_name(self.path.name+"."+uuid4().hex)
            try:
                with tmp.open("x",encoding="utf-8") as output:
                    json.dump({"state":status,"updated":now,"since":since},output)
                os.chmod(tmp,0o600)
                os.replace(tmp,self.path)
            finally:
                tmp.unlink(missing_ok=True)

    def set(self,status):
        if status not in ("starting","running","idle","degraded","stopping"):
            raise ValueError("Unknown heartbeat status")
        with self._lock:
            self._status,self._since=status,self.clock()
            self._write()

    def _loop(self):
        while not self._stop.wait(INTERVAL):
            try:
                self._write()
            except Exception:
                self.exit_process(1)
                return

    def __enter__(self):
        self.set("starting")
        self._thread=Thread(target=self._loop,daemon=True,name="workspace-watchdog")
        self._thread.start()
        return self

    def __exit__(self,*args):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=INTERVAL+1)
        self.path.unlink(missing_ok=True)
        return False

def healthy(path=PATH,*,clock=monotonic):
    try:
        with Path(path).open("rb") as source:
            raw=source.read(1025)
        if len(raw)>1024:
            return False
        row=json.loads(raw)
        if set(row)!={"state","updated","since"} or row["state"] not in ("idle","running","degraded"):
            return False
        now=clock()
        updated,since=row["updated"],row["since"]
        if type(updated) not in (int,float) or type(since) not in (int,float):
            return False
        return 0<=now-updated<=STALE and 0<=now-since and (row["state"]!="running" or now-since<=MAX_ROUND)
    except (OSError,ValueError,TypeError,KeyError):
        return False

if __name__=="__main__":
    raise SystemExit(0 if healthy() else 1)
