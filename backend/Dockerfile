# API image. YOLO runs through ONNX Runtime here, so PyTorch and Ultralytics are only
# needed to export the model, and the running API fits in 512 MB of memory.

# Stage 1: export the YOLO weights to ONNX.
FROM python:3.12-slim AS model
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir "ultralytics>=8.4,<9" onnx onnxslim
WORKDIR /export
RUN yolo export model=yolo11n.pt format=onnx dynamic=True imgsz=640

# Stage 2: the API.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
# ffmpeg encodes the annotated video as H.264, which browsers can play.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-deploy.txt .
RUN pip install -r requirements-deploy.txt
COPY . .
COPY --from=model /export/yolo11n.onnx models/yolo11n.onnx

RUN useradd --create-home --uid 1000 app && mkdir -p storage && chown app storage
USER app

ENV AI_MODEL_PATH=models/yolo11n.onnx \
    AI_DEVICE=cpu
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
