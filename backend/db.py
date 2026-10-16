# -*- coding: utf-8 -*-
"""SQLite 数据层：建表 + 增删改查。全部用标准库 sqlite3，无外部依赖。"""
import os
import sqlite3
import time

# 数据库文件放在 data/ 目录下，避免污染代码目录
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "app.db")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    pw_salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    schedule_text TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '考试',
    start_date TEXT NOT NULL DEFAULT '',
    weekday INTEGER,
    start_time TEXT NOT NULL DEFAULT '',
    end_time TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    session_no INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    transcript TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    audio_path TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
-- 第二期：实时课堂问答模式
CREATE TABLE IF NOT EXISTS live_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    course_id INTEGER NOT NULL,
    session_no INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'live',
    created_at INTEGER NOT NULL,
    ended_at INTEGER
);
CREATE TABLE IF NOT EXISTS live_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    created_at INTEGER NOT NULL,
    UNIQUE(session_id, seq)
);
CREATE TABLE IF NOT EXISTS live_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at INTEGER NOT NULL,
    answered_at INTEGER
);
"""


def _connect():
    """每次操作新建连接（MVP 并发量极小，这样最简单可靠）。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        # 兼容老数据库：补上结构化时间字段（已存在则忽略）
        for col, ddl in (("weekday", "INTEGER"), ("start_time", "TEXT"), ("end_time", "TEXT")):
            try:
                conn.execute(f"ALTER TABLE courses ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        # 实时问答：提问卡片增加 AI 作答字段（基于本节课已讲内容先行作答）
        try:
            conn.execute("ALTER TABLE live_questions ADD COLUMN ai_answer TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row):
    return dict(row) if row else None


# ---------- 用户 ----------
def create_user(username, pw_salt, pw_hash):
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, pw_salt, pw_hash, created_at) VALUES (?,?,?,?)",
            (username, pw_salt, pw_hash, int(time.time())),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_username(username):
    conn = _connect()
    try:
        return _row_to_dict(conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = _connect()
    try:
        return _row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
    finally:
        conn.close()


# ---------- 登录会话 ----------
def create_session(token, user_id, expires_at):
    conn = _connect()
    try:
        conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                     (token, user_id, expires_at))
        conn.commit()
    finally:
        conn.close()


def get_session(token):
    conn = _connect()
    try:
        return _row_to_dict(conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone())
    finally:
        conn.close()


def delete_session(token):
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
    finally:
        conn.close()


# ---------- 课程 ----------
def list_courses(user_id):
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM courses WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_course(course_id, user_id):
    conn = _connect()
    try:
        return _row_to_dict(conn.execute(
            "SELECT * FROM courses WHERE id=? AND user_id=?", (course_id, user_id)).fetchone())
    finally:
        conn.close()


def create_course(user_id, name, schedule_text, mode, start_date,
                  weekday=None, start_time="", end_time=""):
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO courses (user_id, name, schedule_text, mode, start_date,"
            " weekday, start_time, end_time, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, name, schedule_text, mode, start_date,
             weekday, start_time, end_time, int(time.time())),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_course(course_id, user_id, name, schedule_text, mode, start_date,
                  weekday=None, start_time="", end_time=""):
    conn = _connect()
    try:
        conn.execute(
            "UPDATE courses SET name=?, schedule_text=?, mode=?, start_date=?,"
            " weekday=?, start_time=?, end_time=? WHERE id=? AND user_id=?",
            (name, schedule_text, mode, start_date,
             weekday, start_time, end_time, course_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_course(course_id, user_id):
    conn = _connect()
    try:
        conn.execute("DELETE FROM notes WHERE course_id=? AND user_id=?", (course_id, user_id))
        conn.execute("DELETE FROM courses WHERE id=? AND user_id=?", (course_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ---------- 纪要 ----------
def list_notes(user_id, course_id):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, course_id, session_no, title, recorded_at, created_at, audio_path"
            " FROM notes WHERE user_id=? AND course_id=? ORDER BY session_no DESC, id DESC",
            (user_id, course_id),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def count_notes(user_id, course_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM notes WHERE user_id=? AND course_id=?",
            (user_id, course_id)).fetchone()
        return row["c"]
    finally:
        conn.close()


def get_note(note_id, user_id):
    conn = _connect()
    try:
        return _row_to_dict(conn.execute(
            "SELECT * FROM notes WHERE id=? AND user_id=?", (note_id, user_id)).fetchone())
    finally:
        conn.close()


def create_note(user_id, course_id, session_no, title, transcript, content, audio_path, recorded_at):
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO notes (user_id, course_id, session_no, title, transcript, content,"
            " audio_path, recorded_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, course_id, session_no, title, transcript, content,
             audio_path, recorded_at, int(time.time())),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_note(note_id, user_id):
    conn = _connect()
    try:
        conn.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ---------- 实时问答 ----------
def create_live_session(sid, user_id, course_id, session_no, title):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO live_sessions (id, user_id, course_id, session_no, title, status, created_at)"
            " VALUES (?,?,?,?,?,'live',?)",
            (sid, user_id, course_id, session_no, title, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def get_live_session(sid, user_id):
    conn = _connect()
    try:
        return _row_to_dict(conn.execute(
            "SELECT * FROM live_sessions WHERE id=? AND user_id=?", (sid, user_id)).fetchone())
    finally:
        conn.close()


def list_live_sessions(user_id):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM live_sessions WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def end_live_session(sid, user_id):
    conn = _connect()
    try:
        conn.execute("UPDATE live_sessions SET status='ended', ended_at=? WHERE id=? AND user_id=?",
                     (int(time.time()), sid, user_id))
        conn.commit()
    finally:
        conn.close()


def add_live_chunk(sid, seq, text, status="ok"):
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO live_chunks (session_id, seq, text, status, created_at)"
            " VALUES (?,?,?,?,?)",
            (sid, seq, text, status, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def list_live_chunks(sid, after_seq=0):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT seq, text, status FROM live_chunks WHERE session_id=? AND seq>? ORDER BY seq",
            (sid, after_seq)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def live_stream_text(sid, max_chars=20000):
    """整场文字流拼接（按 seq 排序，跳过失败 chunk），超长截断留尾部。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT text FROM live_chunks WHERE session_id=? AND status='ok' ORDER BY seq",
            (sid,)).fetchall()
        text = "".join(r["text"] for r in rows)
        return text[-max_chars:]
    finally:
        conn.close()


def create_live_question(sid, question):
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO live_questions (session_id, question, status, created_at)"
            " VALUES (?,?,'open',?)",
            (sid, question, int(time.time())),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_live_questions(sid, only_open=False):
    conn = _connect()
    try:
        q = "SELECT * FROM live_questions WHERE session_id=?"
        if only_open:
            q += " AND status='open'"
        q += " ORDER BY id"
        rows = conn.execute(q, (sid,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def answer_live_question(qid, answer):
    conn = _connect()
    try:
        conn.execute(
            "UPDATE live_questions SET answer=?, status='answered', answered_at=? WHERE id=?",
            (answer, int(time.time()), qid),
        )
        conn.commit()
    finally:
        conn.close()


def set_ai_answer(qid, ai_answer):
    """写入 AI 基于本节课已讲内容的先行作答（老师讲解出现前展示）。"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE live_questions SET ai_answer=? WHERE id=?",
            (ai_answer, qid),
        )
        conn.commit()
    finally:
        conn.close()
