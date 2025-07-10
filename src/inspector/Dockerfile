FROM python:3.11-slim

WORKDIR /app

COPY ./src/inspector/requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src /app/src
COPY ./src/inspector/inspector_config.yaml /app/

ENV PYTHONPATH=/app

CMD ["python", "-u", "src/inspector/main.py"]
