# Browser libraries (marked, DOMPurify, KaTeX), fetched from npm and checked against their published sha512.
FROM python:3.12-slim AS vendor
COPY tools/vendor.py /tmp/vendor.py
RUN python /tmp/vendor.py /vendor

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KNWLGE_DATA=/data KNWLGE_VENDOR=/srv/vendor
WORKDIR /srv

# DEV=1 adds pytest so tests can run inside the container.
ARG DEV=0
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r $([ "$DEV" = "1" ] && echo requirements-dev.txt || echo requirements.txt)

COPY --from=vendor /vendor ./vendor
COPY app ./app
COPY tests ./tests
COPY pytest.ini ./

EXPOSE 9180
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9180", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
