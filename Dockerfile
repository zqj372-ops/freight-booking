FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# OCR/PDF 依赖 (poppler-utils 用于 pdf2image, libgl 等用于 PIL/PaddleOCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖, 利用 docker layer 缓存
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install -e . && \
    pip install "paddleocr>=2.7" "paddlepaddle>=2.6" streamlit

# 复制代码
COPY . .

# 上传 + 数据目录
RUN mkdir -p uploads/so uploads/bills uploads/attachments data logs

EXPOSE 8000 8501

# 默认启动 API, 用 docker-compose 覆盖跑 streamlit
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
