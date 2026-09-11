FROM node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 1000 relay && useradd --uid 1000 --gid 1000 --create-home relay && mkdir -p /var/lib/djq /var/lib/djq-metrics && chown -R relay:relay /var/lib/djq /var/lib/djq-metrics
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY --from=frontend /build/frontend/dist ./frontend/dist
USER relay
EXPOSE 8000
CMD ["job-api"]
