FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app
COPY data ./data

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e ".[ui]"

EXPOSE 8501

CMD ["sh", "-c", "streamlit run app/streamlit_app.py --server.address=0.0.0.0 --server.port=${PORT:-8501} --server.headless=true --server.fileWatcherType=none --browser.gatherUsageStats=false"]
