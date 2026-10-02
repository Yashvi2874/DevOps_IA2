FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY receiver.py test_receiver.py ./
RUN useradd --uid 10001 opschat
USER opschat
EXPOSE 5002
HEALTHCHECK --interval=15s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5002/health', timeout=2)"
CMD ["python", "receiver.py"]
