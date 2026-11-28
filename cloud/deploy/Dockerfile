FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/cvcloud
RUN groupadd --gid 10001 cvcloud && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin cvcloud
COPY cloud/deploy/requirements-health.txt /tmp/requirements-health.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-health.txt && rm /tmp/requirements-health.txt
COPY cloud/__init__.py cloud/app.py cloud/auth.py ./cloud/
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "cloud.app"]
