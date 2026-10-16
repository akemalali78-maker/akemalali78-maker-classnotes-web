# -*- coding: utf-8 -*-
"""实时问答检测：判断新增转写文字中是否出现"老师提问"或"对之前提问的回答"。

成本控制：用便宜模型（环境变量 QWEN_DETECT_MODEL，默认 qwen-flash 级别）。
每次只把"新增文字 + 最近上下文 + 未解答问题列表"发给模型，与讲课内容无关
的文字直接忽略，不打扰用户。

模块可替换：上层只依赖 detect(new_text, context, open_questions) 的返回结构。
MOCK_AI=1 时用启发式规则代替真实调用（演示"提问→蓝卡→答案回填"全链路）。
"""
import json
import os
import re

import requests

DASHSCOPE_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

DETECT_SYSTEM_PROMPT = (
    "你是大学课堂上的提问检测器。输入包含三部分：\n"
    "1. 最近的课堂文字（上下文）\n"
    "2. 刚刚新增的一段转写文字\n"
    "3. 当前未解答的提问列表\n\n"
    "你只做两件事，其余一律忽略：\n"
    "a) 判断新增文字中老师是否刚提出了一个提问（面向全班的提问，不是自问自答的修辞）。\n"
    "b) 判断新增文字是否在回答未解答提问列表中的某个问题。\n\n"
    "只输出 JSON，不要任何解释：\n"
    '{"new_questions": ["问题1"], "answers": [{"question": "列表中的原问题", "answer": "答案文本"}]}\n'
    "没有发现就输出：{\"new_questions\": [], \"answers\": []}\n"
)


class DetectError(Exception):
    """问答检测失败时抛出。"""


class AnswerError(Exception):
    """AI 作答失败时抛出（调用方可忽略，卡片照常展示）。"""


ANSWER_SYSTEM_PROMPT = (
    "你是大学课堂上的助教。老师刚向全班提了一个问题，请你根据"
    "【本节课已讲内容】给出参考答案，帮助学生即时理解。\n\n"
    "铁律：\n"
    "1. 只能基于【本节课已讲内容】作答，绝不引入课外知识、不编造。\n"
    "2. 如果已讲内容不足以回答这个问题，直接说：本节课还没讲到这部分，请等老师讲解。\n"
    "3. 回答简洁，3-5 句话，口语化，像助教在耳边提示。\n\n"
    "只输出答案正文，不要任何前缀解释。"
)


def answer_from_taught(question, taught_text):
    """根据本节课已讲内容先行作答。返回答案字符串；失败抛 AnswerError。"""
    if not question or not question.strip():
        raise AnswerError("问题为空")
    if os.environ.get("MOCK_AI") == "1":
        return "【演示】结合本节课已讲内容，参考答案是：先抓住老师刚讲的核心概念作答，具体等老师讲解确认。"

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise AnswerError("未配置 DASHSCOPE_API_KEY，无法作答。")
    model = os.environ.get("QWEN_DETECT_MODEL", "qwen-flash").strip() or "qwen-flash"

    user_msg = (
        "【本节课已讲内容】\n" + (taught_text or "（暂无）") + "\n\n"
        "【老师的提问】\n" + question.strip()
    )
    try:
        resp = requests.post(
            DASHSCOPE_CHAT_URL,
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.3,
            },
            timeout=60,
        )
    except requests.RequestException as e:
        raise AnswerError("AI 作答网络失败：%s" % e)
    if resp.status_code != 200:
        raise AnswerError("AI 作答接口返回 %s" % resp.status_code)
    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError):
        raise AnswerError("AI 作答返回格式异常")


def _mock_detect(new_text, context, open_questions):
    """演示用启发式：疑问句视为提问；有未解答问题且出现回答信号词时回填答案。"""
    new_questions = []
    answers = []
    candidates = []
    for sent in re.split(r"(?<=[？?])", new_text):
        s = sent.strip()
        if len(s) < 6:
            continue
        if "？" in s or "?" in s:  # 演示启发式：带问号的句子即视为提问候选
            q = re.sub(r"^[我问大家一个问题：:，,]+", "", s).strip("：:,，")
            if q and not any(q == o for o in open_questions):
                candidates.append(q)
    # 多个疑问句时取最长的一句（通常是实质问题，而非"谁能回答一下"这类套话）
    if candidates:
        new_questions.append(max(candidates, key=len))
    if open_questions and not new_questions:
        if re.search(r"回答|答案是|正确|这位同学说", new_text):
            ans = new_text.strip()
            m = re.search(r"(?:回答|答案是|说)[：:，,]?(.{4,120})", ans)
            answers.append({
                "question": open_questions[0],
                "answer": (m.group(1) if m else ans)[:200],
            })
    return {"new_questions": new_questions, "answers": answers}


def detect(new_text, context, open_questions):
    """返回 {"new_questions": [...], "answers": [{"question":..., "answer":...}]}。"""
    if not new_text or not new_text.strip():
        return {"new_questions": [], "answers": []}
    if os.environ.get("MOCK_AI") == "1":
        return _mock_detect(new_text, context, open_questions)

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise DetectError("未配置 DASHSCOPE_API_KEY，无法做问答检测。")
    model = os.environ.get("QWEN_DETECT_MODEL", "qwen-flash").strip() or "qwen-flash"

    lines = ["【最近的课堂文字】", context or "（无）", "", "【新增文字】", new_text, "",
             "【未解答的提问列表】"]
    if open_questions:
        lines.extend("- " + q for q in open_questions)
    else:
        lines.append("（无）")
    user_msg = "\n".join(lines)

    try:
        resp = requests.post(
            DASHSCOPE_CHAT_URL,
            headers={"Authorization": "Bearer " + api_key,
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": DETECT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
    except requests.RequestException as e:
        raise DetectError("问答检测网络失败：%s" % e)
    if resp.status_code != 200:
        raise DetectError("问答检测接口返回 %s" % resp.status_code)

    try:
        data = json.loads(resp.json()["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, AttributeError):
        return {"new_questions": [], "answers": []}
    return {
        "new_questions": list(data.get("new_questions") or []),
        "answers": list(data.get("answers") or []),
    }
