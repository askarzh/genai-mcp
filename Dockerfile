FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=3000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY server.py .

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import socket,sys,os; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', int(os.environ.get('PORT','3000')))); s.close()" || exit 1

CMD ["python", "server.py"]
