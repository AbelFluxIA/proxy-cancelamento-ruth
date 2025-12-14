FROM python:3.11-slim

WORKDIR /app

# Vibe Coding: Cache das camadas de dependência
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Porta padrão do Railway
ENV PORT=8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
