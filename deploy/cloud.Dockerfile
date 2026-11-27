FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir flask==3.1.3 waitress==3.0.2 && useradd --create-home --uid 10001 cloudapp
COPY cloud/ ./cloud/
USER 10001
EXPOSE 8000
CMD ["python","-m","cloud.app"]
