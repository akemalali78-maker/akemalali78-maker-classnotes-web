# -*- coding: utf-8 -*-
"""课表截图导入：识别截图中的全部课程，返回结构化课程列表。

调用阿里云百炼 DashScope 的视觉模型（默认 qwen3-vl-plus），图片以 base64 data URL
直接传入 OpenAI 兼容接口（chat/completions），一次 HTTP 请求即可。

环境变量：
- DASHSCOPE_API_KEY：必填，绝不硬编码。
- QWEN_VL_MODEL：默认 qwen3-vl-plus。

MOCK_AI=1 时返回 3 门演示课程（含不同星期和时间），用于无 Key 联调。

模块保持可替换：上层只依赖 extract_courses(image_bytes) -> list[dict] 这个函数签名，
每项为 {"name": str, "weekday": 1-7（1=周一）, "start_time": "HH:MM", "end_time": "HH:MM"}。

作息说明：prompt 内置了用户学校的固定作息（第1-2节 8:30-10:05 等，见 VL_SYSTEM_PROMPT
第3条），因课表截图通常只标第几节不标具体时刻。换学校需改此处。
"""
import base64
import json
import os
import re

import requests

DASHSCOPE_CHAT_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 截图大小上限：10MB（base64 后约 13MB，兼容接口可承受）
MAX_IMAGE_BYTES = 10 * 1024 * 1024

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MIME_MAP = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

VL_SYSTEM_PROMPT = (
    "你是一个大学课表识别助手。用户会给你一张课表截图，请识别出其中的全部课程。\n"
    "只输出一个 JSON 数组，不要任何解释、不要 markdown 代码块标记。\n"
    "数组每项格式：{\"name\": \"课程名\", \"weekday\": 1-7的数字（1=周一，7=周日）, "
    "\"start_time\": \"HH:MM\"24小时制, \"end_time\": \"HH:MM\"24小时制}。\n"
    "注意：\n"
    "1. 一张课表通常有 8-12 门课。仔细数，不要漏掉下午和晚上的课；竖排文字也要识别。\n"
    "2. 同一门课在不同星期出现多次时（例如周二和周四都有），拆成多项，每项一个上课时段。\n"
    "   判断星期几的方法（必须遵守）：先读出该课程所在列顶部的日期数字（如 10/06），\n"
    "   再用公历换算成星期几。参考锚点：2026年10月13日是星期二。\n"
    "   关键：上午/下午/晚上各时段的方块列位置可能错开，不要数第几列！\n"
    "   对每门课，比较其方块中心与顶部7个日期标签（从左到右依次为周一到周日）\n"
    "   的水平位置，取正上方最近的那个日期标签，再换算星期。\n"
    "   注意最左侧的方块可能只露出一半，它属于最左边的日期。\n"
    "3. 截图里一般不写几点几分，只写第几节。按这张作息表换算（用户学校的固定作息）：\n"
    "   第1-2节 8:30-10:05；第3-4节 10:25-12:00；第5-6节 13:30-15:05；\n"
    "   第7-8节 15:25-17:00；晚上矮块 18:30-20:55，晚上高块（纵贯到页面底部附近）18:30-21:45。\n"
    "4. 若截图中有 LUNCH BREAK / DINNER BREAK 这类分隔线：分隔线上方是上午的课，\n"
    "   上下午分隔线之间是下午的课，晚分隔线下方是晚上的课；再结合课程块的高度\n"
    "   （矮块=2节，横跨整个半天的长块=4节）确定对应上面第3条的哪个时段。\n"
    "5. 课程名只取课程名称，不要带老师名、教室、周次（如\"33-17\"教室号不要）。\n"
    "6. 例外（牢记）：教育社会学（申超老师）的课时长不规则，是 08:30-11:10，\n"
    "   看到这门课直接用这个时间，不要按第3条换算。\n"
    "7. 若截图上某门课直接写了具体时刻（如详情页显示 08:30-10:05），优先采用截图上的时刻。\n"
    "8. 标注\"自主安排\"、没有固定上课时间的课程（如技术创新与产品研发管理实践）也要列出，\n"
    "   start_time 和 end_time 填 \"待定\"，用户会手动补。\n"
    "9. 识别不到任何课程时输出空数组 []。"
)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ImportError(Exception):
    """课表识别失败时抛出（上层转为 400 中文错误）。"""


def _get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise ImportError("未配置 DASHSCOPE_API_KEY，无法识别课表截图。")
    return key


def _mock_courses():
    """演示数据：3 门课，覆盖不同星期和时间。"""
    return [
        {"name": "教育心理学", "weekday": 2, "start_time": "15:30", "end_time": "17:05"},
        {"name": "课程与教学论", "weekday": 4, "start_time": "10:00", "end_time": "11:35"},
        {"name": "教育研究方法", "weekday": 5, "start_time": "19:00", "end_time": "20:35"},
    ]


def _validate_courses(raw) -> list:
    """清洗模型输出：只要合法项，非法项丢弃。"""
    if not isinstance(raw, list):
        raise ImportError("识别结果格式异常，请换一张更清晰的课表截图重试。")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        try:
            weekday = int(item.get("weekday"))
        except (TypeError, ValueError):
            continue
        start = str(item.get("start_time") or "").strip()
        end = str(item.get("end_time") or "").strip()
        if not name or not 1 <= weekday <= 7:
            continue
        # "待定" 表示自主安排、无固定时间的课程：保留，时间置空由用户手动补
        if start == "待定" or end == "待定":
            start, end = "", ""
        elif not TIME_RE.match(start) or not TIME_RE.match(end):
            continue
        out.append({"name": name, "weekday": weekday,
                    "start_time": start, "end_time": end})
    return out


def extract_courses(image_bytes: bytes, ext: str = ".png") -> list:
    """识别课表截图，返回课程列表。失败抛 ImportError。"""
    if not image_bytes:
        raise ImportError("没有收到图片数据。")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImportError(
            f"截图过大（{len(image_bytes) / 1024 / 1024:.1f}MB），请压缩到 10MB 以内再上传。"
        )
    if os.environ.get("MOCK_AI") == "1":
        return _mock_courses()

    api_key = _get_api_key()
    model = os.environ.get("QWEN_VL_MODEL", "qwen3-vl-plus").strip() or "qwen3-vl-plus"
    mime = MIME_MAP.get(ext.lower(), "image/png")
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": VL_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                {"type": "text", "text": "请识别这张课表截图中的全部课程，只输出 JSON 数组。"},
            ]},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(
            DASHSCOPE_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=300,  # 大课表截图识别较慢，放宽到 300s
        )
    except requests.RequestException as e:
        raise ImportError(f"识别请求网络失败：{e}")

    if resp.status_code != 200:
        raise ImportError(f"识别接口返回 {resp.status_code}：{resp.text[:300]}")

    try:
        content = resp.json()["choices"][0]["message"]["content"] or ""
        # 兼容模型偶发包一层 {"courses": [...]}
        data = json.loads(content.strip())
        if isinstance(data, dict):
            for key in ("courses", "data", "result"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
    except (ValueError, KeyError, IndexError, AttributeError) as e:
        raise ImportError(f"识别结果解析失败：{e}，请换一张更清晰的截图重试。")

    courses = _validate_courses(data)
    return courses
