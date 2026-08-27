FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY templates ./templates
COPY static ./static
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app
EXPOSE 8088
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
