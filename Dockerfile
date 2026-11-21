FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./frontend
COPY tavrel ./tavrel
COPY scripts/build-rpc.mjs ./scripts/build-rpc.mjs
RUN npm run build

FROM node:24-bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    TAVREL_DATA_DIR=/data
RUN python3 -m venv /opt/venv
COPY pyproject.toml ./
COPY --from=build /app/tavrel ./tavrel
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["python", "-m", "tavrel.hosted"]
