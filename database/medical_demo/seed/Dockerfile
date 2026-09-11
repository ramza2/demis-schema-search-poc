FROM python:3.11-slim

WORKDIR /seed

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir "psycopg[binary]==2.9.10"

COPY seed_medical_demo.py .

CMD ["python", "seed_medical_demo.py"]
