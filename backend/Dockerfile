FROM python:3.13-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --create-home --uid 10001 echo
COPY echo ./echo
COPY certs ./certs
USER echo
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "echo.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
