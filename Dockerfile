# The API as a container image.
#
#   docker build -t pune-aqi-api .          # builds, and runs the API tests inside the image on the way
#   docker compose up --build               # see docker-compose.yml and docs/docker.md
#
# What is in it: FastAPI + four small Python files + the model file. No pandas, no scikit-learn:
# the model is numbers in models/*.json and the forecasts are already in the database, so serving
# them needs neither. No secrets: .env is excluded by .dockerignore and DATABASE_URL arrives as an
# environment variable when the container starts.

# ---- base: Python, the API's libraries, the API's files -------------------------------------
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-api.txt .
RUN pip install -r requirements-api.txt
COPY app.py service.py modelfile.py db.py healthcheck.py ./
COPY models/ models/

# ---- test: the API tests run INSIDE the image; a failing test fails the build ----------------
FROM base AS test
RUN pip install pytest==8.3.4 httpx==0.28.1
COPY tests/test_api.py tests/test_api.py
RUN python -m pytest tests/test_api.py -q && touch /tests-passed

# ---- runtime: what actually ships -------------------------------------------------------------
FROM base AS runtime
# this line makes the final image depend on the test stage: no passing tests, no image
COPY --from=test /tests-passed /tests-passed
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# liveness asks "/" (a static answer), not "/health": /health queries the database, and a check every
# 30 seconds would stop the free-tier database from ever going to sleep
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.getenv('PORT','8000'), timeout=2)"
# PORT is set by the host (Render sets it); 8000 otherwise
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
