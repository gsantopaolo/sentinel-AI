FROM python:3.12.10-slim-bookworm

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt first to leverage Docker cache
COPY api/requirements.txt /app/

# Install dependencies and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache

# Copy the rest of the application code
COPY api/main.py /app/api/main.py
COPY lib_py /app/lib_py

# Set the PYTHONPATH environment variable
ENV PYTHONPATH="/app/api"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081", "--reload"]



