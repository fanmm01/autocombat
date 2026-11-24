FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8889 \
    TCP_PORT=8892 \
    AUTOCOMBAT_TRUST_WX_CLOUD_HEADERS=0 \
    AUTOCOMBAT_RUNTIME_DIR=/data/.ui-runtime

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY VERSION /app/VERSION
COPY backend/ /app/backend/
COPY scripts/merge_backend.py /app/scripts/merge_backend.py

RUN python /app/scripts/merge_backend.py && mkdir -p /data/.ui-runtime

EXPOSE 8889

CMD ["sh", "-c", "python /app/backend/autocombat_backend.py --host 0.0.0.0 --port ${PORT:-8889} --tcp-port ${TCP_PORT:-8892}"]
