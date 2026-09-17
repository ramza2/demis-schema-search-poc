FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime modules imported by the Streamlit entry points.
COPY app.py helpers.py target_dashboard.py table_explorer.py ./
COPY pages ./pages
# Fail the image build if a local import used by the pages is missing from /app.
RUN python -c "import helpers, target_dashboard, table_explorer"

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
