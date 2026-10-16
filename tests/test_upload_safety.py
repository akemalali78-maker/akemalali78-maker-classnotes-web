"""Regression tests: no real AI calls or production data; run unittest discover."""
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as module


class UploadSafetyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.upload_dir = os.path.join(self.temp, "uploads")
        self.live_dir = os.path.join(self.temp, "live")
        self.stack.enter_context(patch.object(module.db, "DB_PATH", os.path.join(self.temp, "app.db")))
        self.stack.enter_context(patch.object(module.db, "UPLOAD_DIR", self.upload_dir))
        self.stack.enter_context(patch.object(module, "LIVE_CHUNK_DIR", self.live_dir))
        self.stack.enter_context(patch.object(module, "MOCK", False))
        self.stack.enter_context(patch.object(module, "KEEP_AUDIO", False))
        self.stack.enter_context(patch.dict(os.environ, {"REGISTRATION_CODE": ""}))
        self.stack.enter_context(patch.object(module.audio_segments, "split_audio", self.fake_split))
        module.ACTIVE_AUDIO.clear()
        self.client = self.stack.enter_context(TestClient(module.app, raise_server_exceptions=False))
        result = self.client.post("/api/auth/register", json={"username": "test", "password": "original-pass"})
        self.assertEqual(result.status_code, 200)
        self.headers = {"Authorization": "Bearer " + result.json()["token"]}
        course = self.client.post("/api/courses", headers=self.headers, json={"name": "测试课程"})
        self.assertEqual(course.status_code, 200)
        self.course_id = course.json()["id"]

    @contextmanager
    def fake_split(self, path):
        with tempfile.TemporaryDirectory(dir=self.temp) as temp_dir:
            segment = os.path.join(temp_dir, "segment-000.mp3")
            with open(path, "rb") as source, open(segment, "wb") as target:
                target.write(source.read())
            yield [segment]

    def upload(self, content=b"test audio"):
        return self.client.post(
            f"/api/courses/{self.course_id}/recordings", headers=self.headers,
            files={"audio": ("lecture.webm", content, "audio/webm")})

    def assert_no_audio(self):
        files = []
        for base in (self.upload_dir, self.live_dir):
            for directory, _, names in os.walk(base):
                files.extend(os.path.join(directory, name) for name in names)
        self.assertEqual(files, [])
        self.assertEqual(module.ACTIVE_AUDIO, {})

    def public_fetch(self, path, media_path):
        """A nested HTTP request succeeds only if transcribe leaves event-loop free."""
        self.assertTrue(os.path.isfile(path))
        url = "/media/" + media_path
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"test audio")
        self.assertIn("no-store", response.headers["cache-control"])
        self.seen_path, self.seen_url = path, url
        return "转写文本"

    def test_success_only_exposes_audio_during_transcription(self):
        def summarize(*args):
            self.assertFalse(os.path.exists(self.seen_path))
            self.assertEqual(self.client.get(self.seen_url).status_code, 404)
            return "纪要"

        with patch.object(module.transcriber, "transcribe", side_effect=self.public_fetch), \
                patch.object(module.summarizer, "generate_notes", side_effect=summarize):
            result = self.upload()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["transcript"], "转写文本")
        self.assertEqual(result.json()["audio_path"], "")
        self.assert_no_audio()

    def test_asr_failure_cleans_file_and_public_url(self):
        def fail(path, media_path):
            self.public_fetch(path, media_path)
            raise module.transcriber.TranscriptionError("test failure")

        with patch.object(module.transcriber, "transcribe", side_effect=fail):
            result = self.upload()
        self.assertEqual(result.status_code, 502)
        self.assertEqual(self.client.get(self.seen_url).status_code, 404)
        self.assert_no_audio()

    def test_summary_failure_cleans_file(self):
        with patch.object(module.transcriber, "transcribe", side_effect=self.public_fetch), \
                patch.object(module.summarizer, "generate_notes",
                             side_effect=module.summarizer.SummarizeError("test failure")):
            result = self.upload()
        self.assertEqual(result.status_code, 502)
        self.assert_no_audio()

    def test_database_failure_cleans_file_even_with_keep_audio(self):
        with patch.object(module, "KEEP_AUDIO", True), \
                patch.object(module.transcriber, "transcribe", side_effect=self.public_fetch), \
                patch.object(module.summarizer, "generate_notes", return_value="notes"), \
                patch.object(module.db, "create_note", side_effect=RuntimeError("test failure")):
            result = self.upload()
        self.assertEqual(result.status_code, 500)
        self.assert_no_audio()

    def test_keep_audio_still_requires_auth_after_transcription(self):
        with patch.object(module, "KEEP_AUDIO", True), \
                patch.object(module.transcriber, "transcribe", side_effect=self.public_fetch), \
                patch.object(module.summarizer, "generate_notes", return_value="notes"):
            result = self.upload()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(os.path.exists(self.seen_path))
        self.assertTrue(os.path.isfile(result.json()["audio_path"]))
        self.assertEqual(self.client.get(self.seen_url).status_code, 404)
        note_id = result.json()["id"]
        self.assertEqual(self.client.get(f"/api/notes/{note_id}/audio").status_code, 401)
        self.assertEqual(self.client.get(f"/api/notes/{note_id}/audio", headers=self.headers).content,
                         b"test audio")

    def test_upload_limit_and_empty_audio(self):
        with patch.object(module, "MAX_AUDIO_BYTES", 1024), \
                patch.object(module.transcriber, "transcribe") as transcribe:
            oversized = self.upload(b"x" * 1025)
            empty = self.upload(b"")
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(empty.status_code, 400)
        transcribe.assert_not_called()
        self.assert_no_audio()

    def test_exact_upload_limit_is_accepted(self):
        with patch.object(module, "MAX_AUDIO_BYTES", 1024), \
                patch.object(module, "MOCK", True):
            result = self.upload(b"x" * 1024)
        self.assertEqual(result.status_code, 200, result.text)
        self.assert_no_audio()

    def new_live_session(self):
        result = self.client.post("/api/live/sessions", headers=self.headers,
                                  json={"course_id": self.course_id})
        self.assertEqual(result.status_code, 200)
        return result.json()["id"]

    def upload_live(self, sid, content=b"test audio"):
        return self.client.post("/api/live/chunk", headers=self.headers,
                                data={"session_id": sid, "seq": "0"},
                                files={"audio": ("chunk.webm", content, "audio/webm")})

    def test_live_success_has_random_filename_and_threaded_detection(self):
        sid = self.new_live_session()

        def detect(*args):
            self.assertEqual(self.client.get("/api/config").status_code, 200)
            return {"new_questions": [], "answers": []}

        with patch.object(module.transcriber, "transcribe", side_effect=self.public_fetch), \
                patch.object(module.detector, "detect", side_effect=detect):
            result = self.upload_live(sid)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "ok")
        self.assertNotEqual(os.path.basename(self.seen_path), "0.webm")
        self.assertEqual(self.client.get(self.seen_url).status_code, 404)
        self.assert_no_audio()

    def test_live_asr_failure_skips_and_cleans(self):
        sid = self.new_live_session()
        with patch.object(module, "KEEP_AUDIO", True), \
                patch.object(module.transcriber, "transcribe",
                             side_effect=module.transcriber.TranscriptionError("test failure")):
            result = self.upload_live(sid)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "skipped")
        self.assert_no_audio()

    def test_live_limit_and_unexpected_error_cleans(self):
        sid = self.new_live_session()
        with patch.object(module.audio_segments, "MAX_SEGMENT_BYTES", 1024):
            result = self.upload_live(sid, b"x" * 1025)
        self.assertEqual(result.status_code, 413)
        with patch.object(module.transcriber, "transcribe", side_effect=RuntimeError("test failure")):
            result = self.upload_live(sid)
        self.assertEqual(result.status_code, 500)
        self.assert_no_audio()

    def test_split_failure_cleans_original_and_does_not_transcribe(self):
        with patch.object(module.audio_segments, "split_audio",
                          side_effect=module.audio_segments.AudioSplitError("invalid audio")), \
                patch.object(module.transcriber, "transcribe") as transcribe:
            result = self.upload()
        self.assertEqual(result.status_code, 400)
        transcribe.assert_not_called()
        self.assert_no_audio()

    def test_multiple_segments_are_transcribed_sequentially_with_unique_urls(self):
        segment_paths, urls = [], []

        @contextmanager
        def split(path):
            with tempfile.TemporaryDirectory(dir=self.temp) as temp_dir:
                for index in range(2):
                    segment = os.path.join(temp_dir, f"segment-{index}.mp3")
                    with open(segment, "wb") as f:
                        f.write(b"test audio")
                    segment_paths.append(segment)
                yield segment_paths

        def transcribe(path, media_path):
            if urls:
                self.assertEqual(self.client.get(urls[-1]).status_code, 404)
                self.assertFalse(os.path.exists(segment_paths[0]))
            self.public_fetch(path, media_path)
            urls.append(self.seen_url)
            return "first" if len(urls) == 1 else "second"

        with patch.object(module.audio_segments, "split_audio", split), \
                patch.object(module.transcriber, "transcribe", side_effect=transcribe), \
                patch.object(module.summarizer, "generate_notes", return_value="notes"):
            result = self.upload()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["transcript"], "first\nsecond")
        self.assertNotEqual(urls[0], urls[1])
        self.assertTrue(all(not os.path.exists(path) for path in segment_paths))
        self.assertTrue(all(self.client.get(url).status_code == 404 for url in urls))
        self.assert_no_audio()

    def test_stale_disk_file_is_not_public(self):
        path = os.path.join(self.upload_dir, "old.webm")
        with open(path, "wb") as f:
            f.write(b"private old audio")
        self.assertEqual(self.client.get("/media/uploads/old.webm").status_code, 404)

    def test_registration_invite_checks_without_changing_login_password(self):
        with patch.dict(os.environ, {"REGISTRATION_CODE": "test-invite"}):
            self.assertTrue(self.client.get("/api/config").json()["registration_code_required"])
            for code in (None, "wrong", 123, "🙂"):
                response = self.client.post("/api/auth/register", json={
                    "username": "new", "password": "new-pass", "registration_code": code})
                self.assertEqual(response.status_code, 403, response.text)
            response = self.client.post("/api/auth/register", json={
                "username": "new", "password": "new-pass", "registration_code": "test-invite"})
            self.assertEqual(response.status_code, 200, response.text)
            response = self.client.post("/api/auth/login", json={
                "username": "test", "password": "original-pass"})
            self.assertEqual(response.status_code, 200, response.text)

    def test_manual_question_answer_and_dismiss(self):
        sid = self.new_live_session()
        qid = module.db.create_live_question(sid, "什么是 RSI？")
        saved = self.client.post(f"/api/live/questions/{qid}", headers=self.headers,
                                 json={"answer": "相对强弱", "status": "answered"})
        self.assertEqual(saved.status_code, 200, saved.text)
        feed = self.client.get(f"/api/live/{sid}/feed", headers=self.headers)
        row = feed.json()["questions"][0]
        self.assertEqual(row["answer"], "相对强弱")
        self.assertEqual(row["status"], "answered")
        other = module.db.create_live_question(sid, "另一个问题")
        dismissed = self.client.post(f"/api/live/questions/{other}", headers=self.headers,
                                     json={"status": "dismissed"})
        self.assertEqual(dismissed.status_code, 200, dismissed.text)
        statuses = {q["id"]: q["status"] for q in self.client.get(f"/api/live/{sid}/feed", headers=self.headers).json()["questions"]}
        self.assertEqual(statuses[other], "dismissed")
        missing = self.client.post("/api/live/questions/99999", headers=self.headers, json={"status": "dismissed"})
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
