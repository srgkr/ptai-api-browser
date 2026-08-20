FROM python:3.12-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .

USER appuser

EXPOSE 8501

CMD ["streamlit", "run", "ptai-api-browser.py", "--server.port=8501", "--server.address=0.0.0.0"]

