FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api.py db.py ./
COPY tests ./tests

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "api:create_app()"]
