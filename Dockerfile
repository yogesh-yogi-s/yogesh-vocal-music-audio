# Experimental distroless runtime candidate. The CI container-security job
# must pass before this image can replace the release image.
FROM python:3.13-slim-trixie AS builder

WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --target=/opt/vma-site -r requirements.lock \
    && mkdir -p /tmp/vma

FROM gcr.io/distroless/python3-debian13:nonroot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/vma-site:/app \
    TMPDIR=/tmp/vma \
    VMA_TEMP_ROOT=/tmp/vma \
    VMA_ENVIRONMENT=production

WORKDIR /app
COPY --from=builder /opt/vma-site /opt/vma-site
COPY --from=builder --chown=65532:65532 /tmp/vma /tmp/vma
COPY backend ./backend
COPY frontend ./frontend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/usr/bin/python3", "-c", "import os,urllib.request,sys; host=os.getenv('VMA_HEALTHCHECK_HOST','127.0.0.1').strip(); request=urllib.request.Request('http://127.0.0.1:8000/api/ready',headers={'Host':host}); sys.exit(0 if urllib.request.urlopen(request,timeout=3).status==200 else 1)"]

USER 65532:65532
ENTRYPOINT ["/usr/bin/python3"]
CMD ["-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--timeout-keep-alive", "5"]
