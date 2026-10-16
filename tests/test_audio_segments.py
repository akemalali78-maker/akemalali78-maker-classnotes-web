import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.audio_segments import AudioSplitError, split_audio


class SegmentTests(unittest.TestCase):
    def test_missing_ffmpeg(self):
        with patch("backend.audio_segments.shutil.which", return_value=None):
            with self.assertRaises(AudioSplitError):
                with split_audio("unused.mp3"):
                    pass

    def test_segments_and_cleanup_after_caller_error(self):
        created = []
        def simulate(command, **kwargs):
            pattern = command[-1]
            for index in range(2):
                path = Path(pattern % index)
                path.write_bytes(b"fake-audio")
                created.append(path)
        with patch("backend.audio_segments.shutil.which", return_value="ffmpeg"), \
             patch("backend.audio_segments.subprocess.run", side_effect=simulate):
            with self.assertRaisesRegex(RuntimeError, "caller"):
                with split_audio("unused.mp3") as segments:
                    self.assertEqual(len(segments), 2)
                    self.assertTrue(all(Path(s).exists() for s in segments))
                    raise RuntimeError("caller")
        self.assertTrue(all(not p.exists() for p in created))

    def test_decoder_failure_cleans_directory(self):
        created = []
        def simulate(command, **kwargs):
            path = Path(command[-1] % 0)
            path.write_bytes(b"partial")
            created.append(path)
            raise OSError("failure")
        with patch("backend.audio_segments.shutil.which", return_value="ffmpeg"), \
             patch("backend.audio_segments.subprocess.run", side_effect=simulate):
            with self.assertRaises(AudioSplitError):
                with split_audio("unused.mp3"):
                    pass
        self.assertTrue(all(not p.exists() for p in created))


if __name__ == "__main__":
    unittest.main()
