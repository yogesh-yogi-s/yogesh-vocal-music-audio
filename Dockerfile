# VMA local web application image.
# The container runs the FastAPI app, which serves the static frontend and the
# VMA API. The `vma` library itself has no third-party runtime dependencies.
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp/vma \
    VMA_TEMP_ROOT=/tmp/vma \
    VMA_ENVIRONMENT=production

WORKDIR /app

COPY requirements.lock ./
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip uninstall --yes pip \
    && rm -f /usr/local/lib/python3.13/ensurepip/_bundled/*.whl \
    && test ! -d /usr/local/lib/python3.13/site-packages/pip

COPY backend ./backend
COPY frontend ./frontend

RUN groupadd --system --gid 10001 vma \
    && useradd --system --uid 10001 --gid vma --home-dir /nonexistent --shell /usr/sbin/nologin vma \
    && mkdir -p /tmp/vma \
    && chown vma:vma /tmp/vma \
    && chmod 700 /tmp/vma

# Uploads and sessions use /tmp/vma. The deploy pack mounts a disk-backed,
# size-capped filesystem here; the application also enforces a process budget.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; host=os.getenv('VMA_HEALTHCHECK_HOST','127.0.0.1').strip(); request=urllib.request.Request('http://127.0.0.1:8000/api/ready',headers={'Host':host}); sys.exit(0 if urllib.request.urlopen(request,timeout=3).status==200 else 1)"

USER vma

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--timeout-keep-alive", "5"]
