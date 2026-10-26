FROM python:3.11-slim

WORKDIR /app

# 👇 ADD THIS LINE to tell Python where your modules are
ENV PYTHONPATH="/app/src:/app"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Download the database directly from GitHub Releases
RUN mkdir -p data/processed
RUN curl -L "https://github.com/ishitacodes67/retail-memory/releases/download/v1.0/demo.duckdb" -o data/processed/demo.duckdb

ENV STREAMLIT_SERVER_PORT=7860
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV RETAIL_MEMORY_API_URL=http://127.0.0.1:8000/chat

EXPOSE 7860

CMD ["python", "run.py"]