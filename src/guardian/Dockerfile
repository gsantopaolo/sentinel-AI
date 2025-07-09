# Using Python 3.11.0 as the new supported by PyTorch
FROM python:3.11.7-slim-bookworm

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt first to leverage Docker cache
COPY guardian/requirements.txt /app/

# Install dependencies and clean up
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache

# Copy the rest of the application code
COPY guardian/guardian_service.py /app/guardian/guardian_service.py
COPY lib/lib_py /app/lib_py

# Set the PYTHONPATH environment variable
ENV PYTHONPATH="/app"

# Command to run your application
CMD ["python", "guardian/guardian_service.py"]