# -*- coding: utf-8 -*-
"""纪要生成：调用百炼 DashScope OpenAI 兼容接口的 Qwen 模型。

环境变量：
- DASHSCOPE_API_KEY：必填，绝不硬编码。
- QWEN_MODEL：默认 qwen-plus，可改为 qwen-max / qwen-turbo 等。

模块保持可替换：上层只依赖 generate_notes(...) -> str 这个函数签名。
"""
import os

import requests

from . import prompts

DASHSCOPE_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"


class SummarizeError(Exception):
    pass


def _get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise SummarizeError("未配置 DASHSCOPE_API_KEY，无法生成纪要。")
    return key


def generate_notes(transcript: str, course_name: str, mode: str, session_label: str) -> str:
    """
    transcript: 转写文本；course_name: 课程名；
    mode: "考试" / "论文" / "PRE展示"；session_label: 如"第3次课"。
    返回 Markdown 格式的纪要正文。
    """
    if not transcript or not transcript.strip():
        raise SummarizeError("转写文本为空，无法生成纪要。")

    api_key = _get_api_key()
    model = os.environ.get("QWEN_MODEL", "qwen-plus").strip() or "qwen-plus"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompts.build_system_prompt(mode)},
            {"role": "user",
             "content": prompts.build_user_message(course_name, session_label, transcript)},
        ],
        "temperature": 0.3,
    }

    try:
        resp = requests.post(
            DASHSCOPE_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=300,
        )
    except requests.RequestException as e:
        raise SummarizeError(f"纪要生成请求网络失败：{e}")

    if resp.status_code != 200:
        raise SummarizeError(f"纪要接口返回 {resp.status_code}：{resp.text[:300]}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as e:
        raise SummarizeError(f"纪要结果解析失败：{e}")

    content = (content or "").strip()
    if not content:
        raise SummarizeError("模型返回了空纪要，请重试。")
    return content
