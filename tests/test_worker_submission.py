import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from render_worker.db import JobStore
from render_worker.drive import DriveMailbox
from render_worker.worker import RenderWorker


@pytest.fixture
def worker(tmp_path):
    worker = RenderWorker.__new__(RenderWorker)
    worker.settings = SimpleNamespace(max_jobs_per_poll=1)
    worker.folders = {name: name for name in ("inbox", "processing", "failed")}
    worker.store = JobStore(tmp_path / "jobs.sqlite3")
    worker.drive = Mock()
    worker._process_job = Mock()
    return worker


def test_uploading_folder_does_not_block_ready_job_and_is_accepted_later(worker):
    uploading = {"id": "uploading", "name": "Upload in progress"}
    ready = {"id": "ready", "name": "Complete upload"}
    worker.drive.list_inbox_folders.return_value = [uploading, ready]
    worker.drive.read_json_child.side_effect = [
        FileNotFoundError("Missing job.json"),
        {"job_id": "ready-job", "input": {"source_video": "source.mp4"}},
    ]

    assert worker._run_once() == 1
    worker.drive.move_folder.assert_called_once_with("ready", "processing")
    worker._process_job.assert_called_once_with("ready-job", "ready")
    for state in (
        "DOWNLOADING", "VALIDATING", "PREPROCESSING", "RENDERING",
        "QA", "UPLOADING", "SUCCEEDED",
    ):
        worker.store.transition("ready-job", state)

    worker.drive.list_inbox_folders.return_value = [uploading]
    worker.drive.read_json_child.side_effect = None
    worker.drive.read_json_child.return_value = {
        "job_id": "later-job", "input": {"source_video": "source.mp4"}
    }

    assert worker._run_once() == 1
    worker._process_job.assert_called_with("later-job", "uploading")
    assert worker.store.get_job("later-job") is not None


def test_missing_manifest_does_not_count_as_processed_or_move_folder(worker):
    worker.drive.list_inbox_folders.return_value = [{"id": "uploading"}]
    worker.drive.read_json_child.side_effect = FileNotFoundError("Missing job.json")

    assert worker._run_once() == 0
    worker.drive.move_folder.assert_not_called()
    worker._process_job.assert_not_called()


@pytest.mark.parametrize("invalid", [None, {"job_id": "invalid"}])
def test_invalid_manifest_is_still_rejected(worker, invalid):
    worker.drive.read_json_child.return_value = invalid

    assert worker._accept_and_process({"id": "bad"}) is True
    worker.drive.move_folder.assert_called_once_with("bad", "failed")
    worker._process_job.assert_not_called()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_drive_json_accepts_optional_utf8_bom(encoding):
    drive = DriveMailbox.__new__(DriveMailbox)
    drive.find_child = Mock(return_value={"id": "manifest"})
    payload = {"job_id": "bom-test", "title": "Thử nghiệm"}
    drive.download_bytes = Mock(return_value=json.dumps(payload).encode(encoding))

    assert drive.read_json_child("folder", "job.json") == payload
