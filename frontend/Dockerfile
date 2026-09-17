FROM node:22-alpine AS erd-component-builder

WORKDIR /component
COPY erd_component/package.json ./
RUN npm install --no-audit --no-fund
COPY erd_component ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime modules imported by the Streamlit entry points.
COPY app.py helpers.py target_dashboard.py table_explorer.py erd_explorer.py ./
COPY pages ./pages
COPY --from=erd-component-builder /component/dist ./erd_component/dist

# Fail the image build if local imports or the compiled component are missing.
RUN python -c "from pathlib import Path; import helpers, target_dashboard, table_explorer, erd_explorer; assert Path('/app/erd_component/dist/index.html').exists()"

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
