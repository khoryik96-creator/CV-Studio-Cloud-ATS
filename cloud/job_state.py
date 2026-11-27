"""Pure policy for worker recovery; no automatic replay of potentially paid calls."""
from enum import Enum

class State(str, Enum):
    QUEUED="queued"
    RUNNING="running"
    SUCCEEDED="succeeded"
    FAILED="failed"
    NEEDS_REVIEW="needs_review"

_ALLOWED = {
    State.QUEUED: frozenset({State.RUNNING}),
    State.RUNNING: frozenset({State.SUCCEEDED,State.FAILED,State.NEEDS_REVIEW}),
    State.NEEDS_REVIEW: frozenset({State.FAILED}),
    State.SUCCEEDED: frozenset(),
    State.FAILED: frozenset(),
}

def transition(current, target):
    current,target=State(current),State(target)
    if target not in _ALLOWED[current]:
        raise ValueError("Invalid job state transition")
    return target

def expired_lease(current):
    # Cannot know whether an external AI provider already charged for the job.
    # A stale worker must never silently return the task to the queue.
    return transition(current,State.NEEDS_REVIEW)
