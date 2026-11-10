FROM python:3.14.4-slim
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY services/brain /app/services/brain
ENV PYTHONPATH=/app/services/brain
RUN useradd --uid 10001 --create-home gobot
USER gobot
CMD ["python", "-m", "uvicorn", "gobot.brain:create_app", "--factory", "--host", "127.0.0.1", "--port", "18781", "--no-access-log"]
