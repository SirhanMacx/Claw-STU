FROM python:3.12-slim

WORKDIR /app

# Copy source and install
COPY pyproject.toml README.md LICENSE ./
COPY clawstu/ clawstu/
RUN pip install --no-cache-dir .

# Create the data directory with correct perms
RUN mkdir -p /data/.claw-stu && chmod 700 /data/.claw-stu
ENV CLAW_STU_DATA_DIR=/data/.claw-stu

EXPOSE 8000

# Default: start the FastAPI server
CMD ["clawstu", "serve", "--host", "0.0.0.0", "--port", "8000"]
