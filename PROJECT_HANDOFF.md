# 课堂纪要／学习网站 · 独立项目交接

整理日期：2026-10-14。用途：发送给另一个会话，接续本项目的验收、开发和维护。

> 本项目已经上线，不是待从零部署的空项目。先检查现状，再按用户的新需求修改。本文不包含密码、API Key 或邀请码明文。

## 1. 项目定位与范围

- 名称：**课堂纪要**；页面标语：**录下课堂，带走重点**。
- 面向大学生日常学习：课程管理 → 课堂录音／上传音频 → 转写 → 按考核方式生成学习纪要。
- 形态：中文、手机优先的 Web App，电脑浏览器也可用；当前界面是柔白浅色风格，已有深色切换。
- 当前地址：<https://shynarbuy.com>。这是复用的域名，**本项目不是购买／代购网站**，不要带入商品、支付、批发或原网站多语言等需求。
- 用户希望将它作为独立项目继续推进；不要混入原购买网站的产品背景、人物照片或业务规划。

## 2. 当前状态：哪些确认了，哪些还没确认

### 交接时独立核验（2026-10-14）

- 首页 HTTP 200，页面标题为“课堂纪要”。
- `/api/config` 返回 `asr_configured=true`、`mock=false`、`registration_code_required=true`。
- 公网首页、`/static/app.js`、`/static/style.css` 三份文件的 SHA256 与本机对应前端文件一致。
- 以上只证明页面可访问、相关配置已开启／关闭及前端文件一致；**不等于再次完成真实 AI 调用，也不能证明线上后端与本地逐文件一致**。

### MUSE 的上线交接报告（用户提供截图，本轮未在服务器重复执行）

- 已部署并切换到新应用，`nginx -t` 通过。
- 报告称服务器验收 7 项通过，包含真实语音转写、真实纪要生成、课表截图识别、音频处理后删除、未知媒体链接 404 和测试账号清理。
- 报告称转写时已验证阿里云经公网 HTTPS 拉取音频的链路。
- 原服务和切换前配置保留，可回退。

### 仍需完成／确认

1. 用户在公网用邀请码注册、登录，走一遍截图导入课表的完整交互。
2. 手机真实录音并生成纪要，尤其测试 Safari／Chrome、锁屏、切后台、断网与麦克风拒绝等情况。
3. 实时问答模式的生产端到端验收：持续多段录音、提问卡片、答案回填、最后一段上传、结束生成纪要。
4. 旧服务备份是否已下载到本机；MUSE 报告时尚未完成异地副本。
5. 修改线上程序前，核实实际 release、systemd 和 Nginx 配置，确认 MUSE 是否在服务器上做过本地未同步的调整。

**不要把“本地旧文档写着未上线”当作当前状态，也不要把“已经上线”写成全部功能均已实测。**

## 3. 项目文件与版本

建议新会话直接使用这个工作目录，不要使用包含旧网站的上层目录：

`C:\Users\Lenovo\Documents\ChatGPT\网站\classnotes`

本地 Git：分支 `codex/deploy-readiness`；业务代码基线提交 `99a4e63`，原始 MUSE 包基线为 `1bdd0ea`。尚未配置 Git remote，不能声称已经上传 GitHub。本交接文档是基线之上新建的资料。

可发送给无本机文件访问能力的会话的源码包：

`C:\Users\Lenovo\Documents\ChatGPT\网站\output\deployment-20261013\classnotes-handoff-20261014.tgz`

该包含修正版源码、部署脚本、虚构验收素材；不含 `.env`、`.git`、数据库和用户数据，也不含本次后写的交接文档。跨环境交接时应同时发送本文件和源码包。

### 主要代码入口

| 位置 | 作用 |
|---|---|
| `frontend/index.html`、`style.css`、`app.js` | 原生 HTML/CSS/JavaScript 单页应用，无 React/Vue 或 npm 构建步骤 |
| `backend/app.py` | FastAPI 入口、鉴权路由、课程、上传、实时会话与临时媒体接口 |
| `backend/db.py`、`auth.py` | SQLite 数据与账号会话；PBKDF2 密码哈希、Bearer token |
| `backend/transcriber.py`、`audio_segments.py` | 百炼 ASR、ffmpeg 私密音频分段 |
| `backend/summarizer.py`、`prompts.py` | 纪要生成及考试／论文／PRE 展示提示词 |
| `backend/detector.py` | 实时提问检测、答案关联与辅助作答 |
| `backend/course_import.py` | 课表图片识别与结果校验 |
| `backend/matcher.py`、`sessioncalc.py` | 按上课时间匹配课程、计算第几次课 |
| `tests/` | 后端音频安全回归、前端录音状态与竞态检查 |
| `deployment/` | 环境校验、首次安装、Nginx 切换、真实验收等工具 |

## 4. 功能与实现约束

### 账号、课程和课表

- 用户注册／登录，课程和纪要按账号访问。
- 注册需要邀请码；`REGISTRATION_CODE` 为空会变成开放注册，不能随意清空。
- 课程包含：名称、上课星期、起止时间、学期开始日期、考核方式（考试／论文／PRE 展示）。
- 截图识别先返回预览，用户修改确认后才创建课程，不应识别完就自动入库。
- API 课程星期是 `0=周一…6=周日`；视觉识别结果为 `1…7`，前端会换算，修改时避免错一天。
- 自动匹配时间窗口为上课前后 30 分钟，可手动换课；“第 N 次课”按每周固定日期推算，暂未处理节假日调课。

### 普通录音／上传

- 使用浏览器 `MediaRecorder`，支持上传 m4a／mp3／wav／webm 等音频。
- 整份上传上限 **18 MiB**；之后 ffmpeg 转为独立 MP3，按 **240 秒**分段，再顺序转写、合并并生成纪要。
- 解码保护最多 45 段，约三小时；这**不是承诺任意格式都能录三小时**，整份 18 MiB 上传限制依旧存在。
- 默认 `KEEP_AUDIO` 不开启：处理后删除录音，保存转写和纪要，所以处理完不能回听是预期行为。
- 不要将 README 中保留的“回听录音”接口描述理解为生产默认保留音频。

### 实时问答

- 前端每 30 秒停止并重新启动录音器，生成可独立解码的文件，按顺序上传。
- 显示实时文字；检测到提问显示蓝色卡片；回答出现后回填；结束时生成纪要。
- 结束必须等待最后一段和上传队列完成，不能悄悄丢失尾段或把不同会话的音频混在一起。
- 已修过重复启动、路由切换、旧回调干扰新录音、结束上传和失败重试问题；后续修改须保留对应回归测试。

## 5. 运行与 AI 配置

后端：Python 3.12 已验证，FastAPI + Uvicorn + SQLite；真实音频处理依赖系统 `ffmpeg`。

当前锁定的生产依赖：`fastapi==0.143.0`、`uvicorn==0.54.0`、`python-multipart==0.0.32`、`requests==2.34.2`。

| 环境变量 | 当前代码默认值／要求 |
|---|---|
| `DASHSCOPE_API_KEY` | 阿里云百炼密钥，仅从私密运行环境读取 |
| `PUBLIC_BASE_URL` | 当前为 `https://shynarbuy.com`，末尾无斜杠；真实 ASR 要通过公网拉音频 |
| `ASR_MODEL` | `qwen-audio-3.0-asr-flash` |
| `QWEN_MODEL` | `qwen-plus`，用于纪要 |
| `QWEN_DETECT_MODEL` | `qwen-flash`，用于实时问答 |
| `QWEN_VL_MODEL` | `qwen3-vl-plus`，用于课表图片 |
| `REGISTRATION_CODE` | 保持非空，部署校验要求至少 12 字符；不是账号密码 |
| `MOCK_AI` | 只允许本地联调设为 `1`，生产必须关闭 |
| `KEEP_AUDIO` | 默认关闭；不要为方便回听擅自开启 |

重要：程序没有自动加载 `.env` 的逻辑，也没有 `python-dotenv` 依赖。**只放置 `.env` 文件不会让直接启动的 Python 自动读到配置**。生产由 systemd 的 `EnvironmentFile` 注入；本地需明确注入环境。

本地不调用付费 AI 的最小启动示例（PowerShell，在项目目录执行）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:MOCK_AI = '1'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

随后访问 `http://127.0.0.1:8000`。此模式是假数据演示，不算真实 AI 验收。真实联调必须另行配置模型访问与模型可拉取的 HTTPS 音频地址，不要把生产域名指向本地假服务。模型授权与接口规则需按实际百炼工作空间核验，不要仅凭旧注释更换 ASR 模型或传输方式。

## 6. 部署维护信息

服务器已续费，不要重新购买或重装：腾讯云轻量应用服务器 `Ubuntu-F4j3`，实例 `lhins-eq8f1eh7`，中国香港，公网 IP `43.128.20.59`；此前确认到期时间为 **2026-11-06 17:29:39**，后续续费情况以控制台为准。

部署脚本约定的布局（变更前应只读核对服务器实际情况）：

- 程序入口：`/opt/classnotes/current`，实际版本位于 `/opt/classnotes/releases/`。
- 数据目录：`/var/lib/classnotes`，SQLite 为其中的 `app.db`；程序的 `data` 链接到该目录。
- 私密配置：`/etc/classnotes.env`，权限 600；不要输出或上传到聊天、Git。
- 服务：`classnotes.service`，账号 `classnotes`，时区 `Asia/Shanghai`。
- Uvicorn：**仅 `127.0.0.1:8000`、一个 worker**；现有 Nginx 提供外部 80/443 与 HTTPS。
- Nginx 需保留正确的上传大小、长请求超时、`microphone=(self)` 和 `/media/` 代理设置。

临时音频只在转写期间可通过随机媒体地址访问，处理完成移除映射。授权映射存在单个进程内，**不能直接增加 worker／多实例，也不能把 uploads 整个目录改成无条件公开静态目录**。

首次安装与切换脚本不是日常更新脚本：`prepare_release.sh` 在已有 `current` 时会拒绝，`switch_nginx.py` 依赖旧上游和备份保护条件。站点已经切换，不要为了“再部署一遍”删掉检查条件或盲目重跑。

现有 `README.md` 的 Sealos、`DEPLOY_ALIYUN.md` 的 Docker/Caddy 是历史说明，不能代表现状；旧 Dockerfile 也未包含新增的 ffmpeg 依赖。

仅保留一条历史运维背景：当前服务器曾托管别的网站，其回退资料在 `/root/site-backups/shynarbuy-20261013-200644/`。MUSE 报告原 Node 服务保留未停；不要删除该目录、旧服务或证书。**本项目不接续旧网站的业务开发。**

## 7. 测试与后续优先级

交接当天再次执行：17 项 Python 单元测试、9 组 JavaScript 行为检查，以及 `acceptance.py --self-test`、`prepare_media_proxy.py --self-test` 均通过，没有调用付费 API。Python 测试有 Starlette/httpx 弃用警告，当前不导致失败。

可复用的本机测试 Python：

`C:\Users\Lenovo\Documents\ChatGPT\网站\tmp\classnotes-hardening-venv\Scripts\python.exe`

测试命令（项目目录中执行；Python 测试环境另需 TestClient 对应的测试依赖，如现有环境中的 httpx）：

```text
python -m unittest discover -s tests -v
node --test tests/frontend_live.test.cjs
python deployment/acceptance.py --self-test
python deployment/prepare_media_proxy.py --self-test
```

`acceptance.py --run-real` 与 `--self-test` 不同：它会真实调用计费模型、创建专用测试账号并精确清理测试记录，不能当成普通只读检查随手执行。它依赖服务器 staging 下的 `test-lesson.wav` 和 `test-timetable.png`；缺图片会跳过，不能因此宣称课表识别验收通过。若长请求断连并报告 `deferred cleanup`，后台可能仍在处理，不能立刻删测试账号或父记录。

后续建议顺序：

1. 完成第 2 节中尚未覆盖的公网、手机录音与实时问答测试。
2. 核对并保存异地备份，再完善新应用 SQLite 数据的定期备份与恢复验证。
3. 将线上变更与本地源码对齐；如用户要求，再建立独立私有 GitHub 仓库和规范发布流程。
4. 扩大用户范围前再评估登录限流、模型调用配额、长任务队列、注销 token 失效和密码策略；不擅自重置现有密码。

## 8. 给接手会话的边界

- 不改已有密码；密钥、邀请码、数据库和学生材料不进入公开仓库或交接聊天。
- 录音和课表图片会发送到阿里云百炼，不能宣称完全离线／只在本机处理；使用真实课堂材料前应取得必要同意。
- 先读取源码和实际状态，做最小修改；不要顺手重构、迁移服务器、换域名、改模型或引入支付系统。
- 遇到登录、扫码、二次验证或凭据变更，由用户亲自完成；不要以关闭安全机制解决操作问题。
- 只报告有证据的完成项，清楚区分单元测试、服务器真实模型测试、手机实测和未测试内容。

可直接发给新会话的开场白：

> 这是独立的“课堂纪要／学习网站”项目，请先阅读这份交接文档。本机工作目录为 `C:\Users\Lenovo\Documents\ChatGPT\网站\classnotes`。网站已经上线，请不要从头部署或混入原购买网站需求。先只读核对现有代码与上线状态，列出未完成的验收项，再根据我接下来的具体需求继续；不要改密码或泄露密钥。
