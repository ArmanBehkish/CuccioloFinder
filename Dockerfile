FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

WORKDIR /app

# Install deps (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN pip install uv && uv sync --no-dev --frozen --extra docker

# Install Chromium + deps
RUN uv run playwright install --with-deps chromium

# Copy app code
COPY src/ src/

# Data directory for volume mount
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

CMD ["uv", "run", "python", "-m", "cucciolofinder.main"]
