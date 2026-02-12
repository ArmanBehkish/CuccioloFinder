FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# System tools
RUN apt-get update && apt-get install -y --no-install-recommends vim-tiny && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

WORKDIR /app

# Install deps (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN pip install uv && uv sync --no-dev --frozen --extra docker

# Install Chromium + deps (shared path readable by appuser at runtime)
RUN uv run playwright install --with-deps chromium

# Copy app code + entrypoint
COPY src/ src/
COPY docker-entrypoint.sh /app/

# Data directory for volume mount + uv cache for appuser
RUN mkdir -p /app/data /home/appuser/.cache && chown -R appuser:appuser /app /home/appuser/.cache

USER appuser

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uv", "run", "python", "-m", "cucciolofinder.main"]
