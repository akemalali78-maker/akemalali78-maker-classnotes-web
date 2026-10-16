#!/usr/bin/env python3
"""Opt-in production smoke test. Never print credentials or model responses.

Run on the server after deployment:
  /opt/classnotes/current/.venv/bin/python deployment/acceptance.py --run-real
This makes one short ASR/summary call and, if supplied, one vision call.
The test account and its exact owned records are removed in a transaction.
"""
import argparse
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import secrets
import shlex
import sqlite3
import tempfile
from urllib.parse import urlsplit
import uuid

ENV_PATH = Path("/etc/classnotes.env")
DB_PATH = Path("/var/lib/classnotes/app.db")
DATA_PATH = DB_PATH.parent
AUDIO_PATH = Path("/root/classnotes-staging/test-lesson.wav")
IMAGE_PATH = Path("/root/classnotes-staging/test-timetable.png")
API_BASE = "http://127.0.0.1:8000"


class CheckFailed(Exception):
    """Only fixed, non-sensitive messages may be passed to this exception."""


def check(condition, message):
    if not condition:
        raise CheckFailed(message)


def read_public_config(path):
    # Do not read or return DASHSCOPE_API_KEY. No shell sourcing/evaluation.
    values = {}
    with path.open(encoding="utf-8") as source:
        for line in source:
            key, separator, raw = line.strip().partition("=")
            if separator and key in {"REGISTRATION_CODE", "PUBLIC_BASE_URL", "MOCK_AI", "KEEP_AUDIO"}:
                try:
                    parts = shlex.split(raw, comments=True, posix=True)
                except ValueError:
                    raise CheckFailed("environment_value_format_invalid") from None
                check(len(parts) <= 1, "environment_value_format_invalid")
                values[key] = parts[0] if parts else ""
    return values


def connect_existing(path):
    # mode=rw refuses to create a DB accidentally at the wrong location.
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def cleanup_account(connection, username, expected_uid, course_name):
    """Delete only this random account; refuse unexpected ownership/state."""
    check(username.startswith("codex_qa_") and len(username) == 41, "cleanup_username_guard_failed")
    connection.execute("BEGIN IMMEDIATE")
    try:
        user = connection.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user is None:
            connection.rollback()
            return False
        uid = user["id"]
        check(expected_uid is None or uid == expected_uid, "cleanup_uid_guard_failed")
        courses = connection.execute("SELECT id, name FROM courses WHERE user_id=?", (uid,)).fetchall()
        check(all(c["name"] == course_name for c in courses), "cleanup_course_guard_failed")
        cids = [c["id"] for c in courses]
        notes = connection.execute("SELECT course_id FROM notes WHERE user_id=?", (uid,)).fetchall()
        live = connection.execute("SELECT id, course_id FROM live_sessions WHERE user_id=?", (uid,)).fetchall()
        check(all(n["course_id"] in cids for n in notes), "cleanup_note_guard_failed")
        check(all(s["course_id"] in cids for s in live), "cleanup_live_guard_failed")
        for session in live:
            connection.execute("DELETE FROM live_chunks WHERE session_id=?", (session["id"],))
            connection.execute("DELETE FROM live_questions WHERE session_id=?", (session["id"],))
            connection.execute("DELETE FROM live_sessions WHERE id=? AND user_id=?", (session["id"], uid))
        for cid in cids:
            connection.execute("DELETE FROM notes WHERE user_id=? AND course_id=?", (uid, cid))
            connection.execute("DELETE FROM courses WHERE user_id=? AND id=? AND name=?", (uid, cid, course_name))
        connection.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        connection.execute("DELETE FROM users WHERE id=? AND username=?", (uid, username))
        connection.commit()
        check(connection.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone() is None,
              "cleanup_verification_failed")
        return True
    except BaseException:
        connection.rollback()
        raise


def media_files():
    # Read only. Do not delete unknown audio that might belong to other users.
    return {p.resolve() for directory in (DATA_PATH / "uploads", DATA_PATH / "live_chunks")
            if directory.exists() for p in directory.rglob("*") if p.is_file()}


def request_json(session, method, path, label, in_flight=None, **kwargs):
    if in_flight is not None:
        in_flight["pending"] = True
    response = session.request(method, API_BASE + path, timeout=(10, 900),
                               allow_redirects=False, **kwargs)
    if in_flight is not None:
        in_flight["pending"] = False
    check(response.status_code == 200, label + "_http_" + str(response.status_code))
    try:
        return response.json()
    except ValueError:
        raise CheckFailed(label + "_invalid_json") from None


def run_real():
    import requests

    username = "codex_qa_" + uuid.uuid4().hex
    course_name = "部署验收_" + uuid.uuid4().hex
    uid = None
    registration_attempted = False
    recording_state = {"pending": False}
    report = {"ok": False, "checks": [], "cleanup": "not_needed"}
    connection = None
    try:
        configuration = read_public_config(ENV_PATH)
        check(configuration.get("MOCK_AI") != "1", "mock_mode_not_allowed")
        check(configuration.get("KEEP_AUDIO") != "1", "keep_audio_not_allowed")
        check(bool(configuration.get("REGISTRATION_CODE")), "registration_code_missing")
        public_base = configuration.get("PUBLIC_BASE_URL", "").rstrip("/")
        parsed = urlsplit(public_base)
        check(parsed.scheme == "https" and parsed.hostname and not parsed.username
              and not parsed.password and not parsed.query and not parsed.fragment,
              "public_https_url_invalid")
        check(AUDIO_PATH.is_file() and 0 < AUDIO_PATH.stat().st_size <= 18 * 1024 * 1024,
              "test_audio_missing_or_oversize")
        connection = connect_existing(DB_PATH)
        check(connection.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone() is None,
              "random_username_already_exists")
        before = media_files()
        with requests.Session() as session:
            session.trust_env = False
            cfg = request_json(session, "GET", "/api/config", "config")
            check(cfg.get("mock") is False and cfg.get("asr_configured") is True
                  and cfg.get("registration_code_required") is True, "production_configuration_failed")
            report["checks"].append("real_ai_configured_and_invite_required")
            registration_attempted = True
            registration = request_json(session, "POST", "/api/auth/register", "register", json={
                "username": username, "password": secrets.token_urlsafe(24),
                "registration_code": configuration["REGISTRATION_CODE"],
            })
            token = registration.get("token")
            check(isinstance(token, str) and bool(token), "register_token_missing")
            session.headers["Authorization"] = "Bearer " + token
            user = request_json(session, "GET", "/api/auth/me", "identity")
            check(user.get("username") == username and isinstance(user.get("id"), int), "identity_failed")
            uid = user["id"]
            report["checks"].append("temporary_account_registered")
            course = request_json(session, "POST", "/api/courses", "course", json={
                "name": course_name, "mode": "考试", "weekday": date.today().weekday(),
                "start_time": "08:30", "end_time": "10:05", "start_date": date.today().isoformat(),
            })
            cid = course.get("id")
            check(isinstance(cid, int) and course.get("user_id") == uid, "course_ownership_failed")
            report["checks"].append("course_created")
            with AUDIO_PATH.open("rb") as audio:
                note = request_json(session, "POST", f"/api/courses/{cid}/recordings", "recording",
                                    in_flight=recording_state,
                                    files={"audio": ("test-lesson.wav", audio, "audio/wav")})
            check(note.get("user_id") == uid and note.get("course_id") == cid, "note_ownership_failed")
            transcript = note.get("transcript", "")
            content = note.get("content", "")
            check(isinstance(transcript, str) and "光合作用" in transcript, "real_transcript_content_failed")
            check(isinstance(content, str) and "光合作用" in content, "real_summary_content_failed")
            report["checks"].extend(["real_asr_photosynthesis", "real_summary_photosynthesis"])
            response = session.get(API_BASE + f"/api/notes/{note['id']}/audio", timeout=(10, 30),
                                   allow_redirects=False)
            check(not note.get("audio_path") and response.status_code == 404, "note_audio_not_removed")
            check(not (media_files() - before), "new_audio_files_remain_after_transcription")
            # The actual UUID URLs are intentionally not returned to the client.
            # Successful real ASR proves the model could fetch the temporary URL;
            # the completed note + absent files verifies it is no longer stored.
            public = requests.Session()
            public.trust_env = False
            try:
                response = public.get(public_base + "/media/uploads/" + uuid.uuid4().hex + ".mp3",
                                      timeout=(10, 30), allow_redirects=False)
                check(response.status_code == 404, "public_media_route_not_404_for_unknown_audio")
            finally:
                public.close()
            report["checks"].append("audio_removed_and_unknown_public_url_404")
            if IMAGE_PATH.is_file():
                with IMAGE_PATH.open("rb") as image:
                    preview = request_json(session, "POST", "/api/courses/import-image", "timetable",
                                           files={"image": ("test-timetable.png", image, "image/png")})
                recognized = preview.get("courses")
                check(isinstance(recognized, list) and len(recognized) > 0, "timetable_preview_empty")
                check(all(isinstance(c, dict) and c.get("name") for c in recognized),
                      "timetable_preview_invalid")
                remaining = request_json(session, "GET", "/api/courses", "courses_after_preview")
                check(len(remaining) == 1 and remaining[0].get("id") == cid,
                      "timetable_preview_unexpected_persistence")
                report["checks"].append("real_timetable_preview_without_persistence")
            else:
                report["checks"].append("timetable_fixture_absent_skipped")
        report["ok"] = True
    except CheckFailed as error:
        report["error"] = str(error)
    except Exception as error:
        # Never output exceptions from HTTP/AI/DB: they might contain credentials,
        # transcripts, local paths or response bodies. Root can inspect locally.
        report["error"] = "unexpected_" + type(error).__name__
    finally:
        if recording_state["pending"]:
            # A dropped connection does NOT cancel the server's AI worker. Never
            # delete its parent rows while it could still insert a note later.
            report["ok"] = False
            report["cleanup"] = "deferred_until_server_recording_worker_finishes"
            report["temporary_test_username"] = username
        elif registration_attempted and connection is not None:
            try:
                cleanup_account(connection, username, uid, course_name)
                report["cleanup"] = "verified_test_account_records_removed"
            except Exception as error:
                report["ok"] = False
                report["cleanup"] = "failed_" + type(error).__name__
        if connection is not None:
            connection.close()
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


def self_test():
    """No HTTP or model calls. Verify SQL scoping with fabricated data only."""
    with tempfile.TemporaryDirectory(prefix="classnotes-acceptance-") as directory:
        path = Path(directory) / "test.db"
        with closing(sqlite3.connect(path)) as db:
            db.executescript("""
                CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT);
                CREATE TABLE sessions(token TEXT, user_id INTEGER);
                CREATE TABLE courses(id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT);
                CREATE TABLE notes(id INTEGER, user_id INTEGER, course_id INTEGER);
                CREATE TABLE live_sessions(id TEXT, user_id INTEGER, course_id INTEGER);
                CREATE TABLE live_chunks(session_id TEXT);
                CREATE TABLE live_questions(session_id TEXT);
            """)
            username = "codex_qa_" + "a" * 32
            db.executemany("INSERT INTO users VALUES (?,?)", [(1, "existing_fake_neighbor"), (2, username)])
            db.executemany("INSERT INTO courses VALUES (?,?,?)", [(11, 1, "neighbor"), (22, 2, "qa")])
            db.executemany("INSERT INTO notes VALUES (?,?,?)", [(111, 1, 11), (222, 2, 22)])
            db.executemany("INSERT INTO sessions VALUES (?,?)", [("neighbor_fake", 1), ("qa_fake", 2)])
            db.executemany("INSERT INTO live_sessions VALUES (?,?,?)", [("neighbor_live", 1, 11), ("qa_live", 2, 22)])
            for table in ("live_chunks", "live_questions"):
                db.executemany(f"INSERT INTO {table} VALUES (?)", [("neighbor_live",), ("qa_live",)])
            db.commit()
        connection = connect_existing(path)
        try:
            try:
                cleanup_account(connection, username, 1, "qa")
            except CheckFailed:
                pass
            else:
                raise AssertionError("mismatched uid not rejected")
            check(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2, "guard_changed_data")
            cleanup_account(connection, username, 2, "qa")
            for table in ("users", "courses", "notes", "sessions", "live_sessions", "live_chunks", "live_questions"):
                check(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1,
                      "neighbor_not_preserved")
        finally:
            connection.close()
    print("self_test_ok: scoped cleanup preserves all fabricated neighbor records; no network calls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-real", action="store_true", help="explicitly permit the short paid production API tests")
    group.add_argument("--self-test", action="store_true", help="synthetic local SQL test; no network calls")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
    else:
        raise SystemExit(run_real())
