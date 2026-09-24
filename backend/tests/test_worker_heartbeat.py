from types import SimpleNamespace
from unittest.mock import MagicMock

from worker import tasks


def test_worker_heartbeat_refreshes_running_job(monkeypatch):
    waits = iter([False, False, True])
    event = SimpleNamespace(wait=lambda _seconds: next(waits), set=MagicMock())
    update_one = MagicMock(side_effect=[RuntimeError("temporary failure"), None])

    class InlineThread:
        def __init__(self, target, daemon):
            self.target = target
            assert daemon is True

        def start(self):
            self.target()

        def join(self, timeout):
            assert timeout == 1

    monkeypatch.setattr(tasks.threading, "Event", lambda: event)
    monkeypatch.setattr(tasks.threading, "Thread", InlineThread)
    monkeypatch.setattr(
        tasks,
        "database",
        SimpleNamespace(jobs=SimpleNamespace(update_one=update_one)),
    )

    @tasks.with_job_heartbeat
    def sample(job_id):
        return f"done:{job_id}"

    assert sample("job-1") == "done:job-1"
    assert update_one.call_count == 2
    query, update = update_one.call_args.args
    assert query == {"id": "job-1", "state": "running"}
    assert update["$set"]["heartbeat_at"] == update["$set"]["updated_at"]
    event.set.assert_called_once()
