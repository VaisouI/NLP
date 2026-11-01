FROM python:3.12.16-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
WORKDIR /app
COPY requirements-runtime.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements-runtime.txt \
    && groupadd --gid 10001 mlapp \
    && useradd --uid 10001 --gid mlapp --no-create-home --shell /usr/sbin/nologin mlapp
COPY src/__init__.py src/artifacts.py src/preprocessing.py src/prediction.py src/smoke.py src/api.py src/api_settings.py src/api_observability.py src/inference_process.py src/inference_worker.py src/serve.py src/healthcheck.py ./src/
COPY config/lab2.json config/api.json ./config/
COPY static/index.html static/app.js static/style.css ./static/
COPY artifacts/ci/model.skops ./models/lab2-v1/model.skops
COPY artifacts/ci/model-manifest.json ./security/model-manifest-lab2-v1.json
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=25s --retries=2 \
    CMD ["python", "-m", "src.healthcheck"]
ENTRYPOINT ["python", "-m", "src.serve", "--host", "0.0.0.0"]
