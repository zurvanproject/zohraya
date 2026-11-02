FROM python:3.12-slim
WORKDIR /app
COPY nasurayaza_watch /app/nasurayaza_watch
RUN groupadd --gid 10001 nasurayaza && useradd --uid 10001 --gid 10001 --no-create-home nasurayaza \
 && mkdir /data && chown -R 10001:10001 /data
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 POLL_SECONDS=900 NASURAYAZA_DATA=/data
VOLUME /data
HEALTHCHECK --interval=60s --timeout=8s --start-period=60s --retries=3 \
 CMD python -m nasurayaza_watch.health
CMD ["python", "-m", "nasurayaza_watch"]
