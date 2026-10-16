# 给 CODEX 的部署交接说明

> 转交人：请把这份文档 + 项目压缩包一起发给 CODEX。
> CODEX 看完后需要回答文末的「待确认事项」，答案转回给我即可。

---

## 一、项目是什么

**课堂纪要 Web App**：大学生上课录音 → 后端调用阿里云百炼 AI 转写 →
按考试/论文模板生成纪要 → 按课表自动归档。另有实时课堂问答模式
（30 秒切片转写 + 老师提问检测）。

- 技术栈：FastAPI（Python 3.12）+ 原生 HTML/CSS/JS + SQLite，无外部数据库依赖
- 监听端口：应用 `8000`（容器内），对外由 Caddy 反代 80/443 并自动申请 HTTPS 证书
- AI 全部走阿里云百炼 HTTP API，无本地模型，2核2G 够用

## 二、压缩包内容

`classnotes-deploy.tgz`（已排除 `.venv`、`__pycache__`、本地测试 `data/`）：

| 文件 | 说明 |
|---|---|
| `Dockerfile` | Python 3.12-slim 镜像，`uvicorn backend.app:app --host 0.0.0.0 --port 8000` |
| `docker-compose.yml` | 两个服务：`app` + `caddy:2-alpine`；`./data` 挂载做持久化 |
| `Caddyfile.example` | 模板，复制为 `Caddyfile` 后把域名替换成真实域名 |
| `.env.example` | 环境变量模板，见第三节 |
| `DEPLOY_ALIYUN.md` | 完整中文部署步骤（买服务器/防火墙/解析/传代码/Docker/启动/备份/迁移） |
| `backend/`、`frontend/` | 应用代码 |
| `requirements.txt` | `fastapi / uvicorn / python-multipart / requests` |

## 三、`.env` 怎么配（在服务器上 `cp .env.example .env` 后改）

```ini
DASHSCOPE_API_KEY=新Key            # 去百炼控制台重建一个！聊天记录里出现过的旧 Key 作废
PUBLIC_BASE_URL=https://真实域名    # 末尾不带斜杠；转写服务靠它从公网拉音频，必填
QWEN_MODEL=qwen-plus
ASR_MODEL=qwen-audio-3.0-asr-flash
QWEN_DETECT_MODEL=qwen-flash
QWEN_VL_MODEL=qwen3-vl-plus
# 千万不要加 MOCK_AI=1（那是本地假数据模式）
```

## 四、部署步骤（精简版，详细见 DEPLOY_ALIYUN.md）

1. **服务器**：优先给旧实例续费（IP 不变，域名解析零改动）；若已释放则新购香港轻量 2核2G / Ubuntu 22.04
2. **下掉旧网站**：旧站数据如需保留先备份，再释放 80/443 端口
3. 防火墙放行 80、443
4. 域名 A 记录确认指向服务器公网 IP（续费则不用动）
5. 传代码、装 Docker、写 `Caddyfile` + `.env`、`mkdir -p data`
6. `docker compose up -d --build`，等 1 分钟让 Caddy 申请证书
7. 浏览器打开 `https://域名` 验证：注册 → 截图导入课表 → 录音 → 纪要

## 五、待确认事项（请 CODEX 回答，转交回我）

1. 旧服务器实例现在是什么状态？能否续费？公网 IP 是多少？
2. 旧服务器上装过 Docker 吗？操作系统版本是？
3. 域名当前解析到哪个 IP？（判断续费后是否需要改解析）
4. 之前的网站是怎么部署的？旧站数据是否需要备份保留？
5. 新服务器（如果买新的）计划选哪个地域/配置？

## 六、后续

- 测试期用现有域名；验证成功后换正式域名只需改 `Caddyfile` + `.env` 的
  `PUBLIC_BASE_URL` 并重启，`./data` 整个目录一搬即走。
- 日常：`docker compose logs -f app` 看日志；备份 = 拷贝 `./data` 目录。
- 录音文件按用户要求**转写完即删**，只留转写文本和纪要入库（代码里已实现，
  调试可用 `KEEP_AUDIO=1` 保留）。
