FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Tables are created by main.py's lifespan (Base.metadata.create_all) on a fresh
# DB. Alembic's single migration is an ALTER and is meant for already-populated
# DBs only — run it manually if needed (see DEPLOY.md), not at container start.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
