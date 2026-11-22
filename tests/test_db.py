from render_worker.db import JobStore


def test_job_state_machine_and_recovery(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    assert store.create_job("job-1", "drive-folder", {"job_id": "job-1"})
    assert not store.create_job("job-1", "drive-folder", {"job_id": "job-1"})

    store.transition("job-1", "DOWNLOADING")
    store.transition("job-1", "VALIDATING")
    store.transition("job-1", "PREPROCESSING")
    store.transition("job-1", "RENDERING")
    assert store.recover_interrupted() == 1
    assert store.get_job("job-1")["state"] == "QUEUED"


def test_invalid_state_transition_is_rejected(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create_job("job-2", "drive-folder", {"job_id": "job-2"})
    try:
        store.transition("job-2", "SUCCEEDED")
    except ValueError as exc:
        assert "Invalid job transition" in str(exc)
    else:
        raise AssertionError("Expected invalid transition to fail.")
