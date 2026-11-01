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
COPY --chown=10001:10001 src/__init__.py src/artifacts.py src/preprocessing.py src/prediction.py src/smoke.py ./src/
COPY --chown=10001:10001 config/lab2.json ./config/lab2.json
COPY --chown=10001:10001 artifacts/ci/model.skops ./models/lab2-v1/model.skops
COPY --chown=10001:10001 artifacts/ci/model-manifest.json ./security/model-manifest-lab2-v1.json
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=2 \
    CMD ["python", "-m", "src.smoke", "--self-test"]
ENTRYPOINT ["python", "-m", "src.smoke"]
