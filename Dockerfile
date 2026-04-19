FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTMCP_CHECK_FOR_UPDATES=off \
    FASTMCP_TRANSPORT=streamable-http \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8000

CMD ["/app/.venv/bin/python", "-m", "meme_indexer.mcp_server"]
