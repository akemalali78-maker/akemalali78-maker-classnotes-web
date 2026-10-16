# 课堂纪要 · Web App（MVP）

大学生课堂录音 → 转写 → AI 纪要。手机/电脑浏览器即开即用，无需安装 App。

**两期功能**

- **第一期 · 录播模式**：课程页"开始记录"（页内录音 / 上传音频）→ 语音转写 → 按课程考核方式生成纪要。
  - 点"开始录音"自动识别当前是哪门课（上课时间前后 30 分钟窗口），顶部横幅展示，可一键切换；
  - 标题自动生成"第N次《课程名》· M月d日"，第N次按"学期开始日期 + 上课星期"推算；
  - 考试课纪要以"知识点按重点程度排序（★★★必考/★★很可能考/★了解）+ 老师原话"开头；
    论文/PRE 课以"可直接用的硬货排序 + 老师夸过的论文要求"开头。
- **第二期 · 实时问答模式**：课程页"实时问答模式" → 每 30 秒切片上传 → 实时转写成文字流 →
  AI 检测到老师提问即弹出**蓝色卡片**置顶，答案出现自动回填（卡片变"已解答"）→ 下课一键生成标准纪要。

---

## 快速开始（本地运行）

```bash
cd class-notes-app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 配置 Key（二选一）
export DASHSCOPE_API_KEY="sk-xxxx"   # 真实调用：转写 + 纪要 + 问答检测
export MOCK_AI=1                     # 无 Key 联调：全部用假数据（见下）

.venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000
```

`.env.example` 列出了全部环境变量，复制为 `.env` 使用（不要提交真实 Key）。

### 环境变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DASHSCOPE_API_KEY` | 是（非 MOCK） | — | 阿里云百炼 API Key，**只从环境变量读取，绝不硬编码** |
| `QWEN_MODEL` | 否 | `qwen-plus` | 纪要生成模型，可换 `qwen-max` / `qwen-turbo` |
| `ASR_MODEL` | 否 | `qwen-audio-3.0-asr-flash` | 语音转写模型（DashScope 原生接口；注意 `qwen3-asr-flash` 未必在你的工作空间授权列表里） |
| `QWEN_DETECT_MODEL` | 否 | `qwen-flash` | 实时问答检测用便宜模型；若你的百炼账号没有该模型，改为 `qwen-turbo` |
| `QWEN_VL_MODEL` | 否 | `qwen3-vl-plus` | 课表截图识别用视觉模型 |
| `PUBLIC_BASE_URL` | 是（非 MOCK） | — | 公网访问地址（如 `https://xxx.sealos.run`，末尾不带斜杠）。转写服务需通过公网 URL 拉取音频，本地开发无公网域名时转写不可用 |
| `MOCK_AI` | 否 | — | 设为 `1` 时转写/纪要/检测全部走本地假数据，仅联调测试用 |

### 无 Key 跑通演示（含"提问→蓝卡→答案回填"）

```bash
export MOCK_AI=1
.venv/bin/uvicorn backend.app:app --port 8000 &
B=http://localhost:8000
TOKEN=$(curl -s -X POST $B/api/auth/register -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -X POST $B/api/courses -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"教育心理学","weekday":1,"start_time":"15:30","end_time":"17:10","mode":"考试","start_date":"2026-09-07"}' > /dev/null
SID=$(curl -s -X POST $B/api/live/sessions -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"course_id":1}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
# 依次上传 4 个 30 秒切片（任意小音频文件即可，内容走固定演示脚本）
for i in 0 1 2 3; do
  curl -s -X POST $B/api/live/chunk -H "Authorization: Bearer $TOKEN" \
    -F "session_id=$SID" -F "seq=$i" -F "audio=@任意音频.wav" | python3 -m json.tool
done
# 第 2 个 chunk 应返回 new_questions（蓝色卡片），第 3 个返回 answered（自动回填）
curl -s "$B/api/live/$SID/feed?after_seq=-1" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# 下课生成纪要
curl -s -X POST $B/api/live/$SID/end -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

MOCK 演示脚本（`backend/app.py` 中 `MOCK_CHUNK_SCRIPT`）：第 2 段含提问
"马斯洛的需要层次理论有哪五个层次？"→ 触发蓝卡；第 3 段含回答 → 自动回填。

---

## 获取 DashScope API Key（阿里云百炼）

1. 打开 https://bailian.console.aliyun.com/ ，用阿里云账号登录；
2. 左侧 **API Key** → 创建，复制 `sk-...`；
3. 确认已开通模型调用：控制台 → **模型广场**，`qwen-plus`（纪要）、
   `qwen-audio-3.0-asr-flash`（转写）、`qwen3-vl-plus`（截图识别）；
   `qwen-flash`/`qwen-turbo`（问答检测）选其一。
   注意：工作空间 API Key（`sk-ws-` 开头）只看得到已授权模型，
   若 `/v1/models` 列表里没有某模型，先在控制台给业务空间开通。
4. 把 Key 填进环境变量 `DASHSCOPE_API_KEY`（本地 `export`，线上填平台的环境变量配置）。

---

## 部署上线（Sealos，一次配好）

以 Sealos 公有云为例（国内访问快、有免费额度）：

1. 把本目录推到 GitHub 私有/公开仓库；
2. 打开 https://cloud.sealos.io/ 注册登录 → **应用管理** → **新建应用**；
3. 选择 **从 Git 仓库部署**，填写仓库地址与分支；
4. 构建配置：语言选 **Python**，构建命令 `pip install -r requirements.txt`，
   启动命令 `.venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000`
   （或直接用 `python -m uvicorn`，按 Sealos 的 Python 模板提示填）；
5. **环境变量**里添加 `DASHSCOPE_API_KEY=sk-...`（生产环境不要开 `MOCK_AI`）；
6. 端口填 `8000`，开启**外网访问**，部署；
7. 拿到公网域名（如 `xxx.cloud.sealos.io`），手机/电脑浏览器打开即用，
   发给同学注册即可（每人数据隔离）。

> 数据持久化：SQLite 文件在 `data/` 目录。Sealos 上如需重启不丢数据，
> 请给应用挂载一块持久卷并把 `data/` 指向它；用户量起来后建议迁到 Postgres。

---

## 后端 API 清单（小程序可 100% 复用）

前端页面只调这些 REST API，不依赖服务端模板渲染。鉴权：`Authorization: Bearer <token>`。

**认证**

- `POST /api/auth/register` `{username, password}` → `{token}`
- `POST /api/auth/login` `{username, password}` → `{token}`
- `GET /api/auth/me` → 当前用户
- `GET /api/config` → `{asr_configured, mock}`（前端判断转写服务是否可用）

**课程**

- `GET /api/courses` → 课程列表（含 `weekday/start_time/end_time/mode`）
- `POST /api/courses` `{name, weekday(0=周一..6), start_time:"HH:MM", end_time:"HH:MM", mode:"考试|论文|PRE展示", start_date:"YYYY-MM-DD"}` → 课程
- `PUT /api/courses/{id}` → 更新课程
- `DELETE /api/courses/{id}` → 删除课程（含纪要与音频）
- `GET /api/courses/match?at=2026-10-13T15:20:00` → `{selected, candidates, mode:"window|nearest|none", label}`
  （自动识别课程：`[start-30分钟, end+30分钟]` 命中；多门命中选开始时间最近的；都没命中选最近的一门）
- `POST /api/courses/import-image`（multipart: `image` 图片，jpg/png/webp ≤10MB）
  → `{courses: [{name, weekday(1=周一..7), start_time:"HH:MM", end_time:"HH:MM"}]}`（课表截图识别）

**录播纪要**

- `POST /api/courses/{id}/recordings`（multipart: `audio` 文件, `recorded_at:"YYYY-MM-DD"`）
  → 转写 + 生成纪要 + 自动标题，返回纪要对象
- `GET /api/courses/{id}/notes` → 纪要列表
- `GET /api/notes/{id}` → 纪要详情（含 `transcript` 原文）
- `DELETE /api/notes/{id}` → 删除
- `GET /api/notes/{id}/audio` → 回听录音

**实时问答**

- `POST /api/live/sessions` `{course_id}` → `{id, title}` 开一场
- `POST /api/live/chunk`（multipart: `session_id`, `seq`, `audio`）
  → `{seq, status:"ok|skipped", text, new_questions, answered}`（转写失败标记跳过不中断）
- `GET /api/live/{sid}/feed?after_seq=-1` → `{status, title, chunks, questions, after_seq}`（轮询增量）
- `POST /api/live/{sid}/end` → `{note_id, title}` 整场生成标准纪要
- `GET /api/live/sessions` → 历史场次

---

## 课表截图导入

课程管理页顶部有"📷 截图导入课表"入口，免去手动逐门录入：

1. 上传课表截图（jpg/png/webp，≤10MB）→ `POST /api/courses/import-image`
2. 后端 `backend/course_import.py` 调视觉模型（`QWEN_VL_MODEL`，默认 `qwen3-vl-plus`）识别，
   只返回 JSON 数组：`[{name, weekday(1=周一..7), start_time, end_time}]`
3. 前端逐行展示识别结果：可改课程名、星期、起止时间、考核方式（考试/论文/PRE展示，默认考试），可删除误识别的行
4. 点"确认导入 N 门课程"→ 逐个调 `POST /api/courses` 创建（星期会自动从 1-7 换算成后端的 0-6）
5. 识别失败显示中文错误 + "改为手动添加"入口

`MOCK_AI=1` 时返回 3 门演示课程（教育心理学/课程与教学论/教育研究方法），无 Key 也可联调全链路。

## 后续转微信小程序

后端 **100% 复用**，只需重写前端（按上面 API 清单对接）。主要重写点：

- **录音页**：用 `wx.getRecorderManager()` 代替浏览器 MediaRecorder；
  注意**小程序单段录音最长 10 分钟**，实时模式需分段续录（到时调用 `recorder.stop()` 再 `start()`），
  或逐段上传后由后端转写拼接；
- 音频格式用 `mp3`/`aac`（`format: 'mp3'`），与现有 `POST /api/live/chunk` 兼容；
- 轮询 `GET /api/live/{sid}/feed` 保持 3 秒间隔即可，无需 WebSocket；
- 登录页复用 `POST /api/auth/*`，token 存 `wx.setStorageSync`；
- 蓝色提问卡片、星级标签的样式按本仓库 `frontend/style.css` 的设计变量翻写为 WXSS。

---

## 成本说明

- **录播模式**：一次 `qwen3-asr-flash` 转写（按音频时长）+ 一次 `qwen-plus` 纪要。转写是主要成本。
- **实时模式**：每 30 秒 1 次转写 + 1 次问答检测（`QWEN_DETECT_MODEL`，默认 `qwen-flash` 级别的便宜模型，
  只发"新增文字+最近上下文+未解答问题"，token 量小）。**实时模式 token 消耗明显高于录播模式**，
  定价时建议实时模式单独计次或限时。
- 单次转写音频上限约 18MB（`backend/transcriber.py` 中 `MAX_AUDIO_BYTES`），超限会提示分段。

## 简化假设（README 即文档）

1. **第N次课**：从"学期开始日期"起，每到该课程的上课星期记一次，到录音当天为止是第几次。
   节假日调课/停课**不考虑**（放假那周会多计一次，介意可手动删除对应纪要）。
2. **自动识别课程**：`[上课开始-30分钟, 上课结束+30分钟]` 为命中窗口；连堂多门命中时选开始时间最近的；
   都没命中时选"接下来最近的一门"。用户可在录音页一键手动切换。
3. 课程每周固定星期几上一次；一周多节的课请拆成多门录入（如"高数(周二)""高数(周四)"）。

## 目录结构

```
class-notes-app/
├── backend/
│   ├── app.py          # FastAPI 入口：全部 /api/* 接口
│   ├── db.py           # SQLite 数据层
│   ├── auth.py         # PBKDF2 密码哈希 + token 会话
│   ├── matcher.py      # 按时间自动匹配课程
│   ├── sessioncalc.py  # 第N次课推算
│   ├── transcriber.py  # DashScope qwen3-asr-flash 转写（可替换）
│   ├── summarizer.py   # Qwen 纪要生成（可替换）
│   ├── detector.py     # 实时问答检测（可替换，便宜模型）
│   └── prompts.py      # 纪要 system prompt（由两份模板改写）
├── frontend/
│   ├── index.html      # 页面结构
│   ├── style.css       # 设计系统：风格C「柔光云白」（浅色+深色，CSS 变量切换；深色模式暂沿用旧变量未精修）
│   └── app.js          # SPA 逻辑：只调 API，无业务硬编码
├── requirements.txt
├── .env.example
└── README.md
```
