FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY data/ ./data/

ENV PORT=8000
ENV FOOD_TRACKER_DB=/data/food_tracker.db

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn src.server:app --host 0.0.0.0 --port ${PORT}"]
