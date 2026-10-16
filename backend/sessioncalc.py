# -*- coding: utf-8 -*-
"""根据课程的上课星期 + 学期开始日期 + 录音日期，推算这是"第几次课"。

算法（用户确认的口径）：
    从学期开始日期起，每到该课程的上课 weekday 记一次，到录音当天为止是第几次。
    即：数 [start_date, record_date] 区间内共有多少个"课程的上课星期几"。

简化假设（README 中已说明，不做处理）：
1. 每门课每周固定星期几上一次；
2. 节假日调课/停课不考虑——放假那周会计入一次，介意的话可手动删除多余纪要。

weekday 为 None（老数据或未填写）或 start_date 为空时，
退化为"该课程已有纪要数 + 1"。
"""
from datetime import date, timedelta


def compute_session_no(weekday, start_date_str: str,
                       record_date: date, existing_count: int) -> int:
    """weekday: 0=周一..6=周日；返回第几次课（>=1）。"""
    if weekday is not None and start_date_str:
        try:
            start = date.fromisoformat(start_date_str)
            if record_date >= start:
                # start 之后（含当天）的第一个上课日
                first = start + timedelta(days=(weekday - start.weekday()) % 7)
                if first <= record_date:
                    return (record_date - first).days // 7 + 1
                return 1
        except ValueError:
            pass
    # 兜底：按已有纪要数量顺延
    return existing_count + 1


def format_title(session_no: int, course_name: str, record_date: date) -> str:
    """标题格式：第N次《课程名》· M月d日"""
    return f"第{session_no}次《{course_name}》· {record_date.month}月{record_date.day}日"
