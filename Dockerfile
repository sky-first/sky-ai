FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENAI_API_KEY=""
ENV OPENAI_MODEL=""
ENV TEMPERATURE=0.0
ENV ENV=prod

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY src /app/src

# Entry point placeholder; replace with your app start command when ready.
CMD ["python", "-c", "print('LangGraph container pronto')"]

