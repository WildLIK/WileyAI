FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WILEYAI_DATA_DIR=/nonexistent
WORKDIR /app
COPY deploy/gateway/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && groupadd --gid 10001 wiley && useradd --uid 10001 --gid wiley --no-create-home wiley
# Only our SIWC implementation; no desktop runtime, browser profiles or model weights.
COPY core/__init__.py core/chatgpt.py /app/core/
COPY gateway /app/gateway/
USER 10001:10001
EXPOSE 48500
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:48500/healthz', timeout=2)" || exit 1
ENTRYPOINT ["python", "-m", "gateway"]
