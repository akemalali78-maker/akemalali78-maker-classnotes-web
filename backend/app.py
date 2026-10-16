# -*- coding: utf-8 -*-
"""课堂纪要 MVP · FastAPI 后端入口。

运行：uvicorn backend.app:app --host 0.0.0.0 --port 8000
环境变量见 .env.example。MOCK_AI=1 时用假数据代替真实 AI 调用（仅本地联调）。
"""
import hmac
import os
import re
import shutil
import uuid
from datetime import date, datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import auth, audio_segments, db, detector, matcher, sessioncalc, summarizer, transcriber, course_import

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

MOCK = os.environ.get("MOCK_AI") == "1"
# 用户决定：录音文件转写完成后即删，只保留转写文本和纪要（本地存储）。
# 调试时可设 KEEP_AUDIO=1 保留音频文件。
KEEP_AUDIO = os.environ.get("KEEP_AUDIO") == "1"

# 测试模式下每个 chunk 的固定"转写"文本（演示"提问→蓝卡→答案回填"用）
MOCK_CHUNK_SCRIPT = [
    "同学们好，今天我们讲教育心理学第三章，学习动机。",
    "我问大家一个问题：马斯洛的需要层次理论有哪五个层次？谁能回答一下？",
    "好，这位同学回答：生理、安全、归属与爱、尊重、自我实现。完全正确。",
    "这个知识点特别重要，期末一定会考，大家记一下。",
]

# 测试模式用的假数据（上线时 MOCK_AI 未设置，不会启用）
MOCK_TRANSCRIPT = (
    "同学们好，今天我们讲教育心理学第三章学习动机。先说一个重点，"
    "马斯洛的需要层次理论这个知识点特别重要，期末一定会考，大家把五个层次背下来。"
    "自我实现是最高层次。好，接下来讲归因理论，韦纳的归因理论了解即可，"
    "知道三个维度就行。最后补充一点，内在动机和外在动机的区别，论述题可能会考到举例。"
)
MOCK_NOTES_EXAM = """## 0. 本节知识点 · 按重点程度排序
- ★★★ 马斯洛需要层次理论（五个层次）
- ★★ 内在动机与外在动机的区别（论述题举例）
- ★ 韦纳归因理论三个维度（了解即可）

老师原话摘录：
- "马斯洛的需要层次理论这个知识点特别重要，期末一定会考"

## 1. 必背（闭眼要能默写）
- 马斯洛需要层次理论的五个层次：生理、安全、归属与爱、尊重、自我实现

## 2. 必备（理解+能举例，论述题素材）
- 内在动机 vs 外在动机：定义区分 + 各举一例

## 5. 本节完整逻辑线
本节从学习动机总论切入，重点讲马斯洛需要层次理论（必考），延伸到内外动机区分（论述素材），最后以韦纳归因理论收尾（了解）。

## 6. 待确认 / 存疑
- 无
"""
MOCK_NOTES_PAPER = """## 0. 本节可直接用的"硬货"（按价值排序）
1. 马斯洛需要层次理论：可作为论文分析学习动机的理论框架
2. 内外动机区分：适合做课堂展示的对比案例

## 2. 老师夸过的论文 & 提到的写作要求
- （测试数据）老师提到上届一篇用归因理论分析课堂案例的论文"结构很清楚"

## 5. 本节完整逻辑线
动机理论总览 → 马斯洛（核心理论） → 归因理论（补充视角）。
"""

app = FastAPI(title="课堂纪要")


@app.on_event("startup")
def _startup():
    db.init_db()
    # 转写服务需要通过公网 URL 拉取音频：/media 公开 serving（文件名 UUID，不可猜解）
    os.makedirs(LIVE_CHUNK_DIR, exist_ok=True)
    if MOCK:
        print("[课堂纪要] MOCK_AI=1：转写与纪要将使用假数据，仅用于本地联调测试")


# ---------- 认证 ----------
@app.post("/api/auth/register")
def register(payload: dict):
    registration_code = os.environ.get("REGISTRATION_CODE", "")
    supplied_code = payload.get("registration_code") or ""
    if registration_code and (
        not isinstance(supplied_code, str)
        or not hmac.compare_digest(supplied_code.encode(), registration_code.encode())
    ):
        raise HTTPException(403, "注册需要有效邀请码")
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or len(password) < 4:
        raise HTTPException(400, "用户名不能为空，密码至少 4 位")
    if db.get_user_by_username(username):
        raise HTTPException(400, "用户名已存在")
    salt = auth.new_salt()
    uid = db.create_user(username, salt, auth.hash_password(password, salt))
    return {"token": auth.create_token(uid)}


@app.post("/api/auth/login")
def login(payload: dict):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    user = db.get_user_by_username(username)
    if not user or user["pw_hash"] != auth.hash_password(password, user["pw_salt"]):
        raise HTTPException(401, "用户名或密码错误")
    return {"token": auth.create_token(user["id"])}


@app.get("/api/auth/me")
def me(user=Depends(auth.get_current_user)):
    return {"id": user["id"], "username": user["username"]}


@app.post("/api/auth/logout")
def logout(user=Depends(auth.get_current_user)):
    # 前端丢弃 token 即可；此处保留接口以备扩展
    return {"ok": True}


@app.get("/api/config")
def config():
    """前端用它判断转写服务是否可用，展示状态提示。"""
    return {"asr_configured": bool(os.environ.get("DASHSCOPE_API_KEY")), "mock": MOCK,
            "registration_code_required": bool(os.environ.get("REGISTRATION_CODE"))}


# ---------- 课程 ----------
MODES = ("考试", "论文", "PRE展示")
WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _parse_course_payload(payload: dict, fallback: dict = None):
    """解析课程表单：结构化时间（星期/起止）+ 自动生成展示文本。"""
    fallback = fallback or {}
    name = (payload.get("name") or fallback.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "课程名不能为空")
    mode = payload.get("mode") or fallback.get("mode") or "考试"
    if mode not in MODES:
        raise HTTPException(400, f"考核方式须为 {MODES} 之一")

    weekday = payload.get("weekday", fallback.get("weekday"))
    if weekday is not None:
        try:
            weekday = int(weekday)
        except (ValueError, TypeError):
            raise HTTPException(400, "星期须为 0-6 的数字（0=周一）")
        if not 0 <= weekday <= 6:
            raise HTTPException(400, "星期须为 0-6 的数字（0=周一）")

    start_time = (payload.get("start_time") or fallback.get("start_time") or "").strip()
    end_time = (payload.get("end_time") or fallback.get("end_time") or "").strip()
    for t in (start_time, end_time):
        if t and not TIME_RE.match(t):
            raise HTTPException(400, f"时间格式须为 HH:MM，如 15:30（收到 {t}）")

    schedule_text = (payload.get("schedule_text") or "").strip()
    if not schedule_text and weekday is not None and start_time and end_time:
        schedule_text = f"周{WEEKDAY_NAMES[weekday]} {start_time}–{end_time}"
    if not schedule_text:
        schedule_text = fallback.get("schedule_text") or ""

    return {
        "name": name,
        "schedule_text": schedule_text,
        "mode": mode,
        "start_date": (payload.get("start_date") or fallback.get("start_date") or "").strip(),
        "weekday": weekday,
        "start_time": start_time,
        "end_time": end_time,
    }


@app.get("/api/courses")
def list_courses(user=Depends(auth.get_current_user)):
    return db.list_courses(user["id"])


@app.get("/api/courses/match")
def match_course(at: str = "", user=Depends(auth.get_current_user)):
    """按时间自动匹配课程：?at=2026-10-13T15:20:00，不传则用服务器当前时间。"""
    now = datetime.now()
    if at:
        try:
            now = datetime.fromisoformat(at)
        except ValueError:
            raise HTTPException(400, "at 须为 ISO8601 时间，如 2026-10-13T15:20:00")
    return matcher.match_course(db.list_courses(user["id"]), now)


@app.post("/api/courses")
def create_course(payload: dict, user=Depends(auth.get_current_user)):
    p = _parse_course_payload(payload)
    cid = db.create_course(user["id"], p["name"], p["schedule_text"], p["mode"],
                           p["start_date"], p["weekday"], p["start_time"], p["end_time"])
    return db.get_course(cid, user["id"])


# ---------- 课表截图导入 ----------
# 注意：必须放在 /api/courses/{course_id} 系列路由之前，否则 "import-image"
# 会被 {course_id} 路径参数吞掉导致 405。
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMG_BYTES = 10 * 1024 * 1024


@app.post("/api/courses/import-image")
async def import_courses_image(image: UploadFile = File(...),
                               user=Depends(auth.get_current_user)):
    """上传课表截图，AI 识别后返回课程列表（前端确认后逐个调 POST /api/courses 保存）。"""
    ext = os.path.splitext(image.filename or "")[1].lower()
    if ext not in IMG_EXTS:
        raise HTTPException(400, "只支持 jpg / png / webp 格式的截图。")
    data = await image.read()
    if len(data) > MAX_IMG_BYTES:
        raise HTTPException(400, "截图超过 10MB，请压缩后再上传。")
    try:
        courses = await run_in_threadpool(course_import.extract_courses, data, ext)
    except course_import.ImportError as e:
        raise HTTPException(400, str(e))
    return {"courses": courses}


@app.put("/api/courses/{course_id}")
def update_course(course_id: int, payload: dict, user=Depends(auth.get_current_user)):
    course = db.get_course(course_id, user["id"])
    if not course:
        raise HTTPException(404, "课程不存在")
    p = _parse_course_payload(payload, course)
    db.update_course(course_id, user["id"], p["name"], p["schedule_text"], p["mode"],
                     p["start_date"], p["weekday"], p["start_time"], p["end_time"])
    return db.get_course(course_id, user["id"])


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int, user=Depends(auth.get_current_user)):
    course = db.get_course(course_id, user["id"])
    if not course:
        raise HTTPException(404, "课程不存在")
    # 同步删除音频文件
    for n in db.list_notes(user["id"], course_id):
        if n["audio_path"] and os.path.exists(n["audio_path"]):
            os.remove(n["audio_path"])
    db.delete_course(course_id, user["id"])
    return {"ok": True}


# ---------- 录音 → 转写 → 纪要 ----------
ALLOWED_EXTS = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".aac"}
MAX_AUDIO_BYTES = 18 * 1024 * 1024
# 单 Uvicorn worker：只让转写中使用的随机 URL 临时公开，不公开整个上传目录。
ACTIVE_AUDIO = {}


async def _save_audio(audio, save_path, max_bytes=None):
    """分块校验实际字节数，不信任 Content-Length，也不把整个文件载入内存。"""
    max_bytes = MAX_AUDIO_BYTES if max_bytes is None else max_bytes
    size = 0
    with open(save_path, "xb") as f:
        while chunk := await audio.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                limit_mb = max_bytes // (1024 * 1024)
                raise HTTPException(413, f"音频超过 {limit_mb}MB，请压缩或分段后再上传。")
            f.write(chunk)
    if not size:
        raise HTTPException(400, "音频为空，请重新录制或选择文件。")


def _remove_audio(save_path):
    try:
        os.remove(save_path)
    except FileNotFoundError:
        pass


def _transcribe_audio_sync(save_path, media_path):
    ACTIVE_AUDIO[media_path] = save_path
    try:
        return transcriber.transcribe(save_path, media_path)
    finally:
        ACTIVE_AUDIO.pop(media_path, None)


async def _transcribe_audio(save_path, media_path):
    # 同步 requests 必须离开事件循环，否则同一进程无法响应 ASR 的媒体拉取。
    return await run_in_threadpool(_transcribe_audio_sync, save_path, media_path)


def _transcribe_recording(save_path):
    """整堂录音先分成模型允许的短片；整个私有临时目录由同一线程 finally 清理。"""
    transcripts = []
    with audio_segments.split_audio(save_path) as segments:
        for segment_path in segments:
            media_path = f"uploads/{uuid.uuid4().hex}.mp3"
            try:
                transcripts.append(_transcribe_audio_sync(segment_path, media_path))
            finally:
                _remove_audio(segment_path)
    return "\n".join(transcripts)


@app.post("/api/courses/{course_id}/recordings")
async def upload_recording(course_id: int,
                           audio: UploadFile = File(...),
                           recorded_at: str = Form(""),
                           user=Depends(auth.get_current_user)):
    course = db.get_course(course_id, user["id"])
    if not course:
        raise HTTPException(404, "课程不存在")

    ext = os.path.splitext(audio.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的音频格式 {ext}，请上传 wav/mp3/m4a/webm")

    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(db.UPLOAD_DIR, filename)
    completed = False
    try:
        await _save_audio(audio, save_path)
        # 录音日期（默认今天）
        try:
            rec_date = date.fromisoformat(recorded_at) if recorded_at else date.today()
        except ValueError:
            rec_date = date.today()

        session_no = sessioncalc.compute_session_no(
            course.get("weekday"), course["start_date"], rec_date,
            db.count_notes(user["id"], course_id))
        title = sessioncalc.format_title(session_no, course["name"], rec_date)
        label = f"第{session_no}次课"

        if MOCK:
            transcript = MOCK_TRANSCRIPT
            content = MOCK_NOTES_EXAM if course["mode"] == "考试" else MOCK_NOTES_PAPER
        else:
            transcript = await run_in_threadpool(_transcribe_recording, save_path)
            if not KEEP_AUDIO:
                _remove_audio(save_path)
            content = await run_in_threadpool(
                summarizer.generate_notes, transcript, course["name"], course["mode"], label)

        note_id = db.create_note(user["id"], course_id, session_no, title,
                                 transcript, content,
                                 save_path if KEEP_AUDIO else "", rec_date.isoformat())
        note = db.get_note(note_id, user["id"])
        completed = True
        return note
    except (transcriber.TranscriptionError, summarizer.SummarizeError) as e:
        raise HTTPException(502, str(e))
    except audio_segments.AudioSplitError as e:
        raise HTTPException(400, str(e))
    finally:
        # 上传/转写/纪要/入库任一失败均清理，KEEP_AUDIO 仅保留成功的调试录音。
        if not KEEP_AUDIO or not completed:
            _remove_audio(save_path)


# ---------- 纪要 ----------
@app.get("/api/courses/{course_id}/notes")
def list_notes(course_id: int, user=Depends(auth.get_current_user)):
    if not db.get_course(course_id, user["id"]):
        raise HTTPException(404, "课程不存在")
    return db.list_notes(user["id"], course_id)


@app.get("/api/notes/{note_id}")
def get_note(note_id: int, user=Depends(auth.get_current_user)):
    note = db.get_note(note_id, user["id"])
    if not note:
        raise HTTPException(404, "纪要不存在")
    return note


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user=Depends(auth.get_current_user)):
    note = db.get_note(note_id, user["id"])
    if not note:
        raise HTTPException(404, "纪要不存在")
    if note["audio_path"] and os.path.exists(note["audio_path"]):
        os.remove(note["audio_path"])
    db.delete_note(note_id, user["id"])
    return {"ok": True}


@app.get("/api/notes/{note_id}/audio")
def get_audio(note_id: int, user=Depends(auth.get_current_user)):
    note = db.get_note(note_id, user["id"])
    if not note or not note["audio_path"] or not os.path.exists(note["audio_path"]):
        raise HTTPException(404, "音频不存在")
    return FileResponse(note["audio_path"])


# ---------- 第二期：实时课堂问答 ----------
LIVE_CHUNK_DIR = os.path.join(db.UPLOAD_DIR, "..", "live_chunks")


def _require_live_session(sid: str, user):
    sess = db.get_live_session(sid, user["id"])
    if not sess:
        raise HTTPException(404, "实时场次不存在")
    if sess["status"] != "live":
        raise HTTPException(400, "该场次已结束")
    return sess


@app.post("/api/live/sessions")
def create_live_session(payload: dict, user=Depends(auth.get_current_user)):
    """开一场实时记录：{course_id} → {id, title}。"""
    course = db.get_course(payload.get("course_id"), user["id"])
    if not course:
        raise HTTPException(404, "课程不存在")
    today = date.today()
    session_no = sessioncalc.compute_session_no(
        course.get("weekday"), course["start_date"], today,
        db.count_notes(user["id"], course["id"]))
    sid = uuid.uuid4().hex
    title = sessioncalc.format_title(session_no, course["name"], today)
    db.create_live_session(sid, user["id"], course["id"], session_no, title)
    os.makedirs(os.path.join(LIVE_CHUNK_DIR, sid), exist_ok=True)
    return {"id": sid, "title": title, "session_no": session_no,
            "course_name": course["name"], "status": "live"}


@app.get("/api/live/sessions")
def list_live_sessions(user=Depends(auth.get_current_user)):
    return db.list_live_sessions(user["id"])


@app.post("/api/live/chunk")
async def upload_live_chunk(session_id: str = Form(...),
                            seq: int = Form(...),
                            audio: UploadFile = File(...),
                            user=Depends(auth.get_current_user)):
    """上传一个 30 秒音频切片：转写 → 追加文字流 → 问答检测。转写失败则标记跳过，不中断整场。"""
    sess = _require_live_session(session_id, user)
    ext = os.path.splitext(audio.filename or "")[1].lower() or ".webm"
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的音频格式 {ext}")
    filename = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(LIVE_CHUNK_DIR, session_id, filename)
    completed = False
    try:
        await _save_audio(audio, save_path, audio_segments.MAX_SEGMENT_BYTES)
        # 转写失败 → 标记跳过，不中断；无论什么异常 finally 都清理临时文件。
        try:
            text = MOCK_CHUNK_SCRIPT[seq % len(MOCK_CHUNK_SCRIPT)] if MOCK else await _transcribe_audio(
                save_path, f"live/{session_id}/{filename}")
        except transcriber.TranscriptionError:
            db.add_live_chunk(session_id, seq, "", status="skipped")
            return {"seq": seq, "status": "skipped", "new_questions": [], "answered": []}
        db.add_live_chunk(session_id, seq, text, status="ok")
        completed = True
    finally:
        if not KEEP_AUDIO or not completed:
            _remove_audio(save_path)

    # 2) 问答检测（只看新增文字 + 最近上下文 + 未解答问题）
    context = db.live_stream_text(session_id)[-800:]
    open_qs = db.list_live_questions(session_id, only_open=True)
    open_texts = [q["question"] for q in open_qs]
    try:
        result = await run_in_threadpool(detector.detect, text, context, open_texts)
    except detector.DetectError:
        result = {"new_questions": [], "answers": []}

    new_questions, answered = [], []
    existing = {q["question"] for q in db.list_live_questions(session_id)}
    for q in result.get("new_questions") or []:
        q = str(q).strip()
        if q and not any(q in e or e in q for e in existing):
            qid = db.create_live_question(session_id, q)
            existing.add(q)
            # 老师提问后立刻用"本节课已讲内容"先行作答；失败也不影响卡片展示
            ai_ans = ""
            try:
                taught = db.live_stream_text(session_id)[-3000:]
                ai_ans = await run_in_threadpool(detector.answer_from_taught, q, taught) or ""
            except detector.AnswerError:
                ai_ans = ""
            if ai_ans:
                db.set_ai_answer(qid, ai_ans)
            new_questions.append({"id": qid, "question": q, "ai_answer": ai_ans})

    open_qs = db.list_live_questions(session_id, only_open=True)
    for a in result.get("answers") or []:
        ref, ans = str(a.get("question") or "").strip(), str(a.get("answer") or "").strip()
        if not ans:
            continue
        target = next((q for q in open_qs if q["question"] == ref), None)
        if not target:
            target = next((q for q in open_qs if ref and (ref in q["question"] or q["question"] in ref)), None)
        if not target and len(open_qs) == 1:
            target = open_qs[0]
        if target:
            db.answer_live_question(target["id"], ans)
            answered.append({"id": target["id"], "question": target["question"], "answer": ans})
            open_qs = [q for q in open_qs if q["id"] != target["id"]]

    return {"seq": seq, "status": "ok", "text": text,
            "new_questions": new_questions, "answered": answered}


@app.get("/api/live/{sid}/feed")
def live_feed(sid: str, after_seq: int = -1, user=Depends(auth.get_current_user)):
    """轮询增量：after_seq 之后的新文字 + 全部问答卡片。after_seq 为已收到的最大 seq，初始传 -1。"""
    sess = db.get_live_session(sid, user["id"])
    if not sess:
        raise HTTPException(404, "实时场次不存在")
    chunks = db.list_live_chunks(sid, after_seq)
    return {"status": sess["status"],
            "title": sess["title"],
            "chunks": chunks,
            "questions": db.list_live_questions(sid),
            "after_seq": max([c["seq"] for c in chunks], default=after_seq)}


@app.post("/api/live/{sid}/end")
def end_live_session(sid: str, user=Depends(auth.get_current_user)):
    """下课：整场文字流 + 问答卡片一键生成标准纪要（复用第一期模板）。"""
    sess = _require_live_session(sid, user)
    course = db.get_course(sess["course_id"], user["id"])
    stream = db.live_stream_text(sid)
    questions = db.list_live_questions(sid)

    qa_lines = ["", "", "【课堂问答回顾（实时模式记录）】"]
    for i, q in enumerate(questions, 1):
        qa_lines.append(f"Q{i}：{q['question']}")
        if q.get("ai_answer"):
            qa_lines.append(f"AI作答（基于本节课已讲内容）：{q['ai_answer']}")
        qa_lines.append(f"老师讲解：{q['answer'] if q['answer'] else '（课堂上未给出）'}")
    full_text = stream + "\n".join(qa_lines)
    label = f"第{sess['session_no']}次课"

    try:
        if MOCK:
            content = (MOCK_NOTES_EXAM if course["mode"] == "考试" else MOCK_NOTES_PAPER)
            content += "\n" + "\n".join(qa_lines) + "\n"
        else:
            content = summarizer.generate_notes(full_text, course["name"], course["mode"], label)
    except summarizer.SummarizeError as e:
        raise HTTPException(502, str(e))

    note_id = db.create_note(user["id"], course["id"], sess["session_no"], sess["title"],
                             full_text, content, "", date.today().isoformat())
    db.end_live_session(sid, user["id"])
    # 整场结束：兜底清掉该场次残留的切片音频（正常流程中每片转写完已删）
    if not KEEP_AUDIO:
        shutil.rmtree(os.path.join(LIVE_CHUNK_DIR, sid), ignore_errors=True)
    return {"note_id": note_id, "title": sess["title"],
            "chunks": len(db.list_live_chunks(sid, -1)), "questions": len(questions)}


# ---------- 前端静态页 ----------
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _active_audio_response(media_path):
    save_path = ACTIVE_AUDIO.get(media_path)
    if not save_path or not os.path.isfile(save_path):
        raise HTTPException(404, "音频不存在")
    return FileResponse(save_path, headers={"Cache-Control": "no-store, private"})


@app.get("/media/uploads/{filename}")
def temporary_upload_audio(filename: str):
    return _active_audio_response("uploads/" + filename)


@app.get("/media/live/{sid}/{filename}")
def temporary_live_audio(sid: str, filename: str):
    return _active_audio_response(f"live/{sid}/{filename}")


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
