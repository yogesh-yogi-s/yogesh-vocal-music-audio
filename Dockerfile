# Experimental Alpine runtime candidate. The CI container-security job
# must pass before this image can replace the release image.
FROM python:3.13-alpine3.24

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp/vma \
    VMA_TEMP_ROOT=/tmp/vma \
    VMA_ENVIRONMENT=production

WORKDIR /app
COPY requirements.lock ./
RUN apk upgrade --no-cache \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip uninstall --yes pip \
    && rm -f /usr/local/lib/python3.13/ensurepip/_bundled/*.whl \
    && addgroup -S -g 10001 vma \
    && adduser -S -D -u 10001 -G vma vma \
    && mkdir -p /tmp/vma \
    && chown vma:vma /tmp/vma \
    && chmod 700 /tmp/vma

COPY backend ./backend
COPY frontend ./frontend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request,sys; host=os.getenv('VMA_HEALTHCHECK_HOST','127.0.0.1').strip(); request=urllib.request.Request('http://127.0.0.1:8000/api/ready',headers={'Host':host}); sys.exit(0 if urllib.request.urlopen(request,timeout=3).status==200 else 1)"]

USER vma
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--timeout-keep-alive", "5"]
