# 部署到阿里云香港轻量服务器（测试阶段用）

> 目标：把 App 跑在你自己的香港服务器上，用你现有的域名访问，
> 找几个同学测试。成功后换正式域名时，只改两处配置 + 搬一个数据目录。

---

## 一、买服务器（约 5 分钟）

1. 阿里云控制台 → 轻量应用服务器 → 购买
2. 地域选 **中国香港**（免备案；之前那台也是香港，流程你熟）
3. 套餐 **2核2G**（三四十/月，按月付就行，测试阶段不用按年）
4. 镜像选 **Ubuntu 22.04**
5. 买好后记下 **公网 IP**

## 二、防火墙放行（2 分钟）

轻量服务器控制台 → 服务器详情 → 防火墙 → 添加规则：
放行 **80（HTTP）** 和 **443（HTTPS）**，22（SSH）默认已放行。

## 三、域名解析（2 分钟，生效最多等 10 分钟）

去你的域名控制台（万网/阿里云域名），加两条 A 记录指向新服务器公网 IP：

| 主机记录 | 记录类型 | 记录值 |
|---|---|---|
| @ | A | 新服务器公网 IP |
| www | A | 新服务器公网 IP |

## 四、传代码到服务器（5 分钟）

在**你自己的电脑**上打包（项目根目录执行）：

```bash
cd ~/workspace/class-notes-app
tar --exclude='.venv' --exclude='__pycache__' --exclude='data' -czf /tmp/app.tgz .
scp /tmp/app.tgz root@<服务器公网IP>:/root/
```

SSH 登录服务器并解压：

```bash
ssh root@<服务器公网IP>
mkdir -p /opt/classnotes && tar -xzf /root/app.tgz -C /opt/classnotes
cd /opt/classnotes
```

> `data/` 不打包——里面是本机的测试数据库，上线用全新的。

## 五、装 Docker（3 分钟，服务器上执行）

```bash
curl -fsSL https://get.docker.com | sh
```

## 六、写配置（5 分钟，服务器上执行）

**1. 复制 Caddyfile 并填你的真实域名：**

```bash
cp Caddyfile.example Caddyfile
sed -i 's/your-domain.example.com/你的真实域名/' Caddyfile
```

**2. 写 `.env`（从模板复制后改）：**

```bash
cp .env.example .env
nano .env
```

必须改的三处：
- `DASHSCOPE_API_KEY=` → 填**新的** Key（⚠️ 聊天里粘过的 Key 建议先去百炼控制台删掉重建一个，生产环境不要用泄露过的 Key）
- `PUBLIC_BASE_URL=https://你的真实域名`（末尾不带斜杠；转写服务靠它拉音频，必填）
- 确认没有 `MOCK_AI=1` 这一行（上线必须用真实 AI）

其余模型名保持默认即可：
`QWEN_MODEL=qwen-plus` / `ASR_MODEL=qwen-audio-3.0-asr-flash` /
`QWEN_DETECT_MODEL=qwen-flash` / `QWEN_VL_MODEL=qwen3-vl-plus`

## 七、启动（2 分钟）

```bash
cd /opt/classnotes
mkdir -p data
docker compose up -d --build
docker compose ps        # 两个容器都 Up 即正常
```

Caddy 会自动申请 HTTPS 证书（1 分钟左右）。然后手机/电脑浏览器打开
`https://你的真实域名`，注册一个账号，全流程走一遍：
截图导入课表 → 录一段音 → 看纪要 → 试一次实时问答。

## 八、日常运维

```bash
docker compose logs -f app     # 看日志
docker compose restart app     # 重启
docker compose down             # 停服（数据在 ./data，不会丢）
```

- **备份**：拷贝 `/opt/classnotes/data` 整个目录即可（SQLite 单文件 + 音频）。
- **升级代码**：重新 scp 打包的代码，`docker compose up -d --build`，`data` 不动。
- 录音文件按你的要求**转写完即删**，`data/uploads` 里不会堆积；只有转写文本和纪要进数据库。

## 九、以后换正式域名（迁移）

1. 新域名解析到服务器 IP（或同一台机器，直接换解析也行）
2. 服务器上改两处：`Caddyfile` 里的域名、` .env` 里的 `PUBLIC_BASE_URL`
3. `docker compose up -d` 重启
4. 数据不动，天然跟着走

---

## 常见问题

- **打开是 Caddy 默认页 / 证书报错**：域名解析还没生效，等 10 分钟再试；`docker compose logs caddy` 看原因。
- **录音转写失败**：先看 `docker compose logs app`；确认 `.env` 里 Key 有效且 `PUBLIC_BASE_URL` 能从公网访问（在手机浏览器打开 `https://你的域名` 能访问即 OK）。
- **微信里打不开**：域名需要在微信公众平台加业务域名（小程序阶段再处理，测试期用浏览器即可）。
