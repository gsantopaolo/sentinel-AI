FROM python:3.12.10-slim-bookworm

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt first to leverage Docker cache
COPY src/scheduler/requirements.txt /app/

# Install dependencies and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
#RUN pip install --no-cache-dir -r requirements.txt \
#    && rm -rf /root/.cache \
# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm -rf /root/.cache

# Copy the rest of the application code
COPY src/scheduler/main.py /app/src/scheduler/main.py
COPY src/lib_py /app/src/lib_py

# Set the PYTHONPATH environment variable
ENV PYTHONPATH="/app"

ENV PYTHONUNBUFFERED=1

CMD ["python", "src/scheduler/main.py"]