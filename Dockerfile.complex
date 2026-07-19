FROM python:3.12-slim

ARG VERSION=0.2.0
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="bkw-tariff-proxy" \
      org.opencontainers.image.description="HTTP proxy for BKW dynamic feed-in tariffs and Loxone virtual HTTP inputs" \
      org.opencontainers.image.source="https://github.com/4FingerEddy/bkw-tariff-proxy" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.created="$BUILD_DATE" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TZ=Europe/Zurich

WORKDIR /app

RUN addgroup --system appuser \
    && adduser --system --ingroup appuser --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

USER appuser
VOLUME ["/data"]
EXPOSE 8785

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8785/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "bkw_tariff_proxy.main:app", "--host", "0.0.0.0", "--port", "8785"]
