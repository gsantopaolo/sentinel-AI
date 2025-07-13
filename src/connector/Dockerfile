FROM python:3.12.10-slim-bookworm

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt first to leverage Docker cache
COPY src/connector/requirements.txt /app/

# Install dependencies and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    # Remove only pip cache to reduce image size; keep Playwright browser binaries in /root/.cache/ms-playwright
    && rm -rf /root/.cache/pip

# Copy the rest of the application code
COPY src/connector/main.py /app/src/connector/main.py
COPY src/lib_py /app/src/lib_py

# Set the PYTHONPATH environment variable
ENV PYTHONPATH="/app"

ENV PYTHONUNBUFFERED=1

CMD ["python", "src/connector/main.py"]