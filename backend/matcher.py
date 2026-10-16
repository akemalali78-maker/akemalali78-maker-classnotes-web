# -*- coding: utf-8 -*-
"""按当前时间自动匹配课程。

匹配规则（用户确认的口径）：
1. 某课程的上课时间为 [start, end]，若当前时间落在
   [start 前 30 分钟, end 后 30 分钟] 内，则命中；
2. 同时命中多门（如连堂）时，选上课开始时间离当前时间最近的那门；
3. 一门都没命中时，默认选中今日最近的一门课（今天没课则选接下来最近的一门）；
4. 用户可在录音页一键手动切换。

输入的 courses 是 db 里的课程 dict，需含 weekday(0=周一..6=周日)、
start_time / end_time("HH:MM")。缺少结构化时间的课程不参与匹配。
"""
from datetime import datetime

WINDOW_BEFORE_MIN = 30  # 开课前 30 分钟
WINDOW_AFTER_MIN = 30   # 下课后 30 分钟


def _to_minutes(tstr: str):
    """'HH:MM' -> 当天分钟数，格式非法返回 None。"""
    try:
        h, m = tstr.strip().split(":")
        h, m = int(h), int(m)
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


def _matchable(c):
    return (c.get("weekday") is not None
            and _to_minutes(c.get("start_time") or "") is not None
            and _to_minutes(c.get("end_time") or "") is not None)


def _next_occurrence_delta(c, now: datetime) -> int:
    """距该课程下一次上课还有多少分钟（含今天还没上的）。"""
    s = _to_minutes(c["start_time"])
    days_ahead = (c["weekday"] - now.weekday()) % 7
    delta = days_ahead * 1440 + (s - (now.hour * 60 + now.minute))
    if delta < -WINDOW_AFTER_MIN:
        delta += 7 * 1440
    return delta


def match_course(courses, now: datetime) -> dict:
    """
    返回 {"selected": course|None, "candidates": [...], "mode": ..., "label": ...}。
    mode: "window"（命中时间窗口）/ "nearest"（兜底最近）/ "none"（无课可选）。
    label: 给前端/小程序直接展示的一句话，如"已自动识别为《教育心理学》"。
    """
    pool = [c for c in courses if _matchable(c)]
    if not pool:
        return {"selected": None, "candidates": [], "mode": "none",
                "label": "还没有设置上课时间的课程"}

    now_min = now.hour * 60 + now.minute
    wd = now.weekday()
    hits = []
    for c in pool:
        if c["weekday"] != wd:
            continue
        s = _to_minutes(c["start_time"])
        e = _to_minutes(c["end_time"])
        if s - WINDOW_BEFORE_MIN <= now_min <= e + WINDOW_AFTER_MIN:
            hits.append((abs(s - now_min), c))  # 按离上课开始时间的距离排序
    if hits:
        hits.sort(key=lambda x: x[0])
        selected = hits[0][1]
        return {"selected": selected,
                "candidates": [c for _, c in hits],
                "mode": "window",
                "label": f"已自动识别为《{selected['name']}》"}

    # 兜底：今日最近的一门；今天没课则选接下来最近的一门
    pool.sort(key=lambda c: _next_occurrence_delta(c, now))
    selected = pool[0]
    return {"selected": selected,
            "candidates": pool[:3],
            "mode": "nearest",
            "label": f"当前不在上课时间，为你选中了最近的《{selected['name']}》"}
