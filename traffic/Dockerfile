FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY generator.py .
RUN useradd --uid 10001 traffic
USER traffic
CMD ["python", "generator.py"]
