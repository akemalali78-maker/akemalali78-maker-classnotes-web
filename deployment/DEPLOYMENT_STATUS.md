# 2026-10-13 / 2026-10-14 部署记录

## 已核实的服务器状态

- 腾讯云轻量应用服务器 `lhins-eq8f1eh7`，中国香港三区，运行中。
- IP `43.128.20.59`，2 核 / 2 GB / 40 GB；2026-11-06 17:29:39 到期。
- Ubuntu 24.04.4 LTS，Python 3.12.3。Docker 尚未安装。
- 旧站 `/var/www/shynarbuy`，Node 监听 `127.0.0.1:4173`，Nginx 占用 80/443。
- 当前域名和 HTTPS 已恢复访问。无需变更 DNS。
- 使用现有 Nginx + 独立 Python venv/systemd，不安装第二套占用 80/443 的 Caddy。

## 旧站备份

服务器实际备份已执行成功（2026-10-13 20:06:46，腾讯云执行记录 ExitCode 0）：

`/root/site-backups/shynarbuy-20261013-200644/`

- `site.tgz`：实际源码、配置、询盘与上传图片。SHA256 `128df730a5f99bcc588cd245eecba92f47e35d2d110b2b120822a7c7c61b0539`。
- `nginx.tgz`：Nginx 配置。SHA256 `00b7591a6efb363eba8f7692c956f9f50ee06454618271e5bd9843615772d798`。
- `letsencrypt.tgz`：HTTPS 配置和证书。SHA256 `f5844bb5ffe86e5e2e3511a6c65425212ba4ac8622a7c6d71fe93aa3605f426a`。
- 备份目录权限 700，归档权限 600；含敏感配置，不得放在公开静态目录或 Git。
- 服务实际为 `pm2-ubuntu.service`；后续执行成功的安装命令已补充其服务文件和存在时的 `/home/ubuntu/.pm2/dump.pm2` 备份。
- 上述是服务器本机备份，尚未下载到本地，不能当作异地备份。

本地另存一份原有网站源码备份（不代表服务器最新数据）：

`C:\Users\Lenovo\Documents\ChatGPT\网站\output\deployment-20261013\shynarbuy-local-source-backup.tgz`

SHA256 `9471067F1E49AF2ECAD332BA0E55B22AB9767296C7B8528B32EE6D82DA359F48`。

## 切换前验收条件

1. 部署包单独存于 `/opt/classnotes`，数据独立存于 `/var/lib/classnotes`，不覆盖旧站。
2. 私密 `/etc/classnotes.env` 已填有效百炼密钥，禁止测试假数据。
3. 仅单 Uvicorn worker；临时音频授权映射当前为进程内，不可直接增加 worker。
4. 新应用在 127.0.0.1:8000 完成启动、账号隔离、上传大小和媒体清理测试。
5. 新 Nginx 配置需允许 20M 请求体、长转写超时、麦克风 `self`，并通过 `nginx -t`。
6. 真实课表识别与录音转写/纪要通过；无需把课堂/个人材料用作测试，可用无敏感短语音。
7. 只有以上完成后才能报告正式上线。保留旧 Node 进程和原 Nginx 配置便于回退。

## 当前执行进度（未上线）

- 服务器已安装 Python venv 与 ffmpeg；腾讯云执行记录显示 ExitCode 0。
- 服务器 `/root/classnotes-staging/` 已有初版程序包与私密 `.env`；密钥不输出、不进 Git。
- 最后修正版 `classnotes-final-20261014.tgz` 已由 OrcaTerm 上传到 `/home/ubuntu/`，界面显示传输成功。SHA256 `85BAF61B258C0FEC9D0EDDCA44CA4D0C827CC91B9F8D999E6D9BF4DACA77BA79`。该版本里的媒体代理助手尚需同步后续已修正的 server_name 检查。
- 两份无个人信息的验收素材上传未确认完成，不可作为已上传记录。
- 本地 17 项 Python 测试、9 项前端行为检查、验收脚本自检与媒体代理脚本自检通过；没有执行真实 AI 验收。
- 腾讯云身份验证曾通过，随后 OrcaTerm 会话断开，内置浏览器的终端与服务器详情页反复崩溃。等待稳定的操作入口继续。
- 新应用尚未安装启动，Nginx 尚未修改，旧 Node 服务未停止，密码未改。

后续：同步最终助手及验收素材 → 启动独立应用 → 仅路由临时媒体进行真实 AI 验收 → 验收成功后全站切换 → 下载服务器备份到本地。
