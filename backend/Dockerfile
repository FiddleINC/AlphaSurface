FROM python:3.12-slim

WORKDIR /app

# Install uv (astral)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Install the locked runtime dependencies (no test tools) into /app/.venv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
# Default port; hosts like Cloud Run override PORT
ENV PORT=8000
EXPOSE $PORT

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
