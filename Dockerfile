FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 数据目录挂载点（SQLite + 上传音频），compose 里挂宿主机目录做持久化
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
