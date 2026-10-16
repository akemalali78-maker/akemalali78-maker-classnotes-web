"""Private, bounded ASR segments. No user audio is printed or left behind."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import tempfile

SEGMENT_SECONDS = 240
MAX_SEGMENT_BYTES = 10 * 1024 * 1024
MAX_SEGMENTS = 45  # Bound a single request to at most three hours.


class AudioSplitError(Exception):
    pass


@contextmanager
def split_audio(audio_path: str):
    """Yield independent mono MP3 paths; remove every segment on any exit.

    The original upload is managed by the caller. Generated paths must only be
    published while the corresponding ASR request is actively reading them.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise AudioSplitError("服务器尚未安装 ffmpeg，暂时无法处理课堂录音。")
    with tempfile.TemporaryDirectory(prefix="classnotes-asr-") as private_dir:
        target = str(Path(private_dir) / "segment-%03d.mp3")
        command = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(audio_path), "-map", "0:a:0", "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k",
            "-t", str(SEGMENT_SECONDS * MAX_SEGMENTS + 1),
            "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
            "-reset_timestamps", "1", target,
        ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=180)
        except subprocess.TimeoutExpired:
            raise AudioSplitError("录音预处理超时，请缩短录音后重试。") from None
        except (OSError, subprocess.CalledProcessError):
            # Do not disclose source paths or ffmpeg diagnostics to the client.
            raise AudioSplitError("无法解码这份录音，请使用有效的 MP3、WAV、M4A 或 WebM 音频。") from None
        segments = sorted(Path(private_dir).glob("segment-*.mp3"))
        if not segments:
            raise AudioSplitError("录音中没有可处理的音频。")
        if len(segments) > MAX_SEGMENTS:
            raise AudioSplitError("单次录音超过三小时，请分次上传。")
        if any(not p.stat().st_size or p.stat().st_size > MAX_SEGMENT_BYTES for p in segments):
            raise AudioSplitError("音频分段大小异常，请缩短录音后重试。")
        yield [str(p) for p in segments]
