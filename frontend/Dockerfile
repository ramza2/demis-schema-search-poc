FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime modules imported by app.py (keep explicit — do not rely on full-tree COPY).
COPY app.py helpers.py ./
# Fail the image build if a local import used by app.py is missing from /app.
RUN python -c "import helpers"

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
