FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY triager ./triager
RUN pip install . && useradd --uid 10001 --create-home desk && mkdir /data && chown desk:desk /data
COPY demo ./demo
COPY scripts/verify_demo.py ./scripts/verify_demo.py
COPY scripts/verify_recovery.py ./scripts/verify_recovery.py
USER desk
CMD ["uvicorn", "triager.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
