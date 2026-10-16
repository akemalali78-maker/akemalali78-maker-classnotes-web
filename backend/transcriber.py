# -*- coding: utf-8 -*-
"""语音转文字：qwen-audio-3.0-asr-flash（DashScope 原生接口）。

实测结论（2026-10-13，真 Key 联调，踩坑记录）：
1. 该 Key 的工作空间未授权 qwen3-asr-flash（/v1/models 列表里没有），
   可用的是 qwen-audio-3.0-asr-flash —— 不要换回 qwen3-asr-flash。
2. 必须走原生接口 POST /api/v1/services/aigc/multimodal-generation/generation，
   兼容模式的 input_audio 对该 Key 始终 400。
3. 音频必须以公网 URL 传入（input_audio.data），base64 / data URI 均不支持。
4. parameters.format 必须显式指定（mp3/wav 等），缺省报 "format is empty"。
5. 返回文本在 output.text。

因此部署时必须配置 PUBLIC_BASE_URL（如 https://xxx.sealos.run），
音频通过 app.py 挂载的 /media 公开路径提供给转写服务。
文件名是 UUID，不可猜解；MVP 阶段可接受无鉴权公开 serving。
本地开发（无公网域名）时转写不可用，会抛 TranscriptionError 明示。

环境变量：
- DASHSCOPE_API_KEY：必填，绝不硬编码。
- ASR_MODEL：默认 qwen-audio-3.0-asr-flash。
- PUBLIC_BASE_URL：必填（如 https://xxx.sealos.run），末尾不带斜杠。

模块保持可替换：上层只依赖 transcribe(audio_path, media_url_path) -> str。
"""
import os

import requests

DASHSCOPE_NATIVE_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)

# 文件后缀 -> parameters.format
FORMAT_MAP = {
    ".wav": "wav",
    ".mp3": "mp3",
    ".m4a": "mp4",
    ".mp4": "mp4",
    ".aac": "aac",
    ".webm": "webm",
    ".ogg": "ogg",
}


class TranscriptionError(Exception):
    pass


def _get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise TranscriptionError("未配置 DASHSCOPE_API_KEY，无法调用语音转写服务。")
    return key


def transcribe(audio_path: str, media_url_path: str | None = None) -> str:
    """把本地音频文件转写成文本。

    audio_path: 本地文件路径（用于校验存在性和格式）。
    media_url_path: 该文件在 /media 下的公开路径，如 "uploads/abc.mp3"；
        不传则默认为 "uploads/<文件名>"。
    """
    api_key = _get_api_key()
    model = os.environ.get("ASR_MODEL", "qwen-audio-3.0-asr-flash").strip() \
        or "qwen-audio-3.0-asr-flash"

    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise TranscriptionError(
            "未配置 PUBLIC_BASE_URL：转写服务需要通过公网 URL 拉取音频，"
            "请在部署时设置（如 https://xxx.sealos.run）。"
        )
    if not os.path.exists(audio_path):
        raise TranscriptionError(f"音频文件不存在：{audio_path}")

    ext = os.path.splitext(audio_path)[1].lower()
    audio_format = FORMAT_MAP.get(ext)
    if not audio_format:
        raise TranscriptionError(f"不支持的音频格式：{ext}，请上传 wav / mp3 / m4a / webm。")

    if not media_url_path:
        media_url_path = "uploads/" + os.path.basename(audio_path)
    public_url = base + "/media/" + media_url_path.lstrip("/")

    body = {
        "model": model,
        "input": {
            "messages": [
                {"role": "user",
                 "content": [{"type": "input_text",
                              "text": "请把这段课堂录音完整转写成中文文字，保留说话内容，不要总结。"}]},
                {"role": "user",
                 "content": [{"type": "input_audio",
                              "input_audio": {"data": public_url}}]},
            ]
        },
        "parameters": {"format": audio_format},
    }

    try:
        resp = requests.post(
            DASHSCOPE_NATIVE_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json",
                     "X-DashScope-SSE": "disable"},
            json=body,
            timeout=300,
        )
    except requests.RequestException as e:
        raise TranscriptionError(f"转写请求网络失败：{e}")

    if resp.status_code != 200:
        raise TranscriptionError(f"转写接口返回 {resp.status_code}：{resp.text[:300]}")

    try:
        text = resp.json()["output"]["text"]
    except (KeyError, ValueError) as e:
        raise TranscriptionError(f"转写结果解析失败：{e}，原始返回：{resp.text[:300]}")

    text = (text or "").strip()
    if not text:
        raise TranscriptionError("转写结果为空，可能是音频无有效人声。")
    return text
