FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy source and install
COPY pyproject.toml README.md LICENSE ./
COPY clawstu/ clawstu/
RUN pip install --no-cache-dir .

# Create the data directory with correct perms
RUN mkdir -p /data/.claw-stu && chmod 700 /data/.claw-stu
ENV CLAW_STU_DATA_DIR=/data/.claw-stu

# Run as non-root — matches Claw-ED's Docker hardening.
RUN groupadd -r clawstu && useradd -r -g clawstu -m clawstu \
    && chown -R clawstu:clawstu /data
USER clawstu

EXPOSE 8000

# Default: localhost-only.  Use a reverse proxy (nginx, Caddy) to
# expose to external networks.
CMD ["clawstu", "serve", "--host", "127.0.0.1", "--port", "8000"]
