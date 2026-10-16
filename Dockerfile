FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scenario ./scenario
ENV PRICING_PATH=/config/pricing.py
EXPOSE 8000
# Seed the shared config volume with the shipped pricing code on first start, then serve.
CMD ["sh", "-c", "mkdir -p /config && { [ -f /config/pricing.py ] || cp app/pricing.py /config/pricing.py; } && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
