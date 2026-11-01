FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

# Use the image's Python, precompile for faster startup, and copy (not hard-link) packages into the venv.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /code
# Install exactly what uv.lock pins (the build fails if it's out of date with pyproject.toml); no dev tools.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY app ./app

# Run as an unprivileged user; the code and packages stay owned by root, so the app can't modify them.
RUN useradd --system --uid 10001 --no-create-home app
USER app

ENV PATH="/code/.venv/bin:$PATH" \
    WEB_CONCURRENCY=2 \
    FORWARDED_ALLOW_IPS=127.0.0.1
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]
# Shell form so the env vars expand; exec keeps fastapi as PID 1 to receive stop signals.
CMD exec fastapi run app/main.py --host 0.0.0.0 --port 8000 \
    --workers "$WEB_CONCURRENCY" --proxy-headers --forwarded-allow-ips "$FORWARDED_ALLOW_IPS"
