FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 核心依赖（不含图像识别的 torch/CLIP，镜像更小；需要识图时再加 requirements-vision.txt）
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "httpx>=0.28" \
    "pydantic>=2.9" "pydantic-settings>=2.6" \
    "python-multipart>=0.0.9" "cryptography>=43" "pywebpush>=2.0"

COPY backend/ /app/

# 数据目录（SQLite 演示库）随镜像带入，可用 volume 覆盖
EXPOSE 8100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
