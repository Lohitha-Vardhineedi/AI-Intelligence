from pathlib import Path

from fastapi.testclient import TestClient

from app.storage.local import LocalStorage


def _upload(client: TestClient, path: Path, name: str | None = None):
    with path.open("rb") as fh:
        return client.post("/api/v1/videos/upload", files={"file": (name or path.name, fh)})


def test_upload_stores_the_file_and_reads_its_properties(client, sample_video, storage):
    response = _upload(client, sample_video)

    assert response.status_code == 201
    video = response.json()["data"]
    assert video["filename"] == "clip.avi"
    assert (video["width"], video["height"], video["frame_count"]) == (64, 48, 20)
    assert video["duration_seconds"] == 2.0
    assert video["latest_job"] is None
    assert storage.path(f"videos/{video['id']}/original.avi").stat().st_size == video["size_bytes"]


def test_unsupported_extension_is_rejected(client, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("not a video")

    response = _upload(client, notes)

    assert response.status_code == 422
    assert response.json() == {
        "success": False,
        "error": {
            "code": "VIDEO_FORMAT_UNSUPPORTED",
            "message": "Unsupported file type. Upload an MP4, AVI, MOV or MKV video.",
        },
    }


def test_file_that_is_not_really_a_video_is_rejected_and_removed(
    client, tmp_path, storage: LocalStorage
):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"\x00" * 2048)

    response = _upload(client, fake)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VIDEO_FORMAT_UNSUPPORTED"
    assert not any(storage.path("videos").iterdir())


def test_process_queues_one_job_at_a_time(client, sample_video, dispatched):
    video_id = _upload(client, sample_video).json()["data"]["id"]

    response = client.post(f"/api/v1/videos/{video_id}/process")
    again = client.post(f"/api/v1/videos/{video_id}/process")

    assert response.status_code == 202
    job = response.json()["data"]
    assert job["status"] == "QUEUED"
    assert dispatched == [job["id"]]
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "JOB_ALREADY_RUNNING"
    latest = client.get(f"/api/v1/videos/{video_id}").json()["data"]["latest_job"]
    assert latest["id"] == job["id"]


def test_list_is_paginated_newest_first(client, sample_video):
    ids = [_upload(client, sample_video).json()["data"]["id"] for _ in range(3)]

    body = client.get("/api/v1/videos", params={"page_size": 2}).json()

    assert [v["id"] for v in body["data"]] == ids[::-1][:2]
    assert body["pagination"] == {"page": 1, "page_size": 2, "total": 3, "pages": 2}


def test_cancel_a_queued_job(client, sample_video):
    video_id = _upload(client, sample_video).json()["data"]["id"]
    job_id = client.post(f"/api/v1/videos/{video_id}/process").json()["data"]["id"]

    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel")
    again = client.post(f"/api/v1/jobs/{job_id}/cancel")

    assert cancelled.json()["data"]["status"] == "CANCELLED"
    assert again.status_code == 409


def test_delete_needs_processing_stopped_and_removes_files(
    client, sample_video, storage: LocalStorage
):
    video_id = _upload(client, sample_video).json()["data"]["id"]
    job_id = client.post(f"/api/v1/videos/{video_id}/process").json()["data"]["id"]

    blocked = client.delete(f"/api/v1/videos/{video_id}")
    client.post(f"/api/v1/jobs/{job_id}/cancel")
    deleted = client.delete(f"/api/v1/videos/{video_id}")

    assert blocked.status_code == 409
    assert deleted.json() == {"success": True, "data": None}
    assert not storage.path(f"videos/{video_id}").exists()
    missing = client.get(f"/api/v1/videos/{video_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_annotated_video_is_404_before_processing(client, sample_video):
    video_id = _upload(client, sample_video).json()["data"]["id"]

    response = client.get(f"/api/v1/videos/{video_id}/annotated")

    assert response.status_code == 404
