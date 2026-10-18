# syntax=docker/dockerfile:1.7
ARG SOURCE_DATE_EPOCH=315532800

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ARG SOURCE_DATE_EPOCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/python \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN --mount=type=bind,source=.,target=/src,ro \
    mkdir -p /tmp/src && cp -a /src/. /tmp/src/ && \
    find /tmp/src -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} + && \
    python -m pip wheel --no-cache-dir --no-deps --wheel-dir /tmp/wheels /tmp/src && \
    python -m pip install --no-cache-dir --no-compile --no-deps --target /opt/python \
      "argon2-cffi==25.1.0" \
      "argon2-cffi-bindings==26.1.0" \
      "cffi==2.1.1" \
      "pycparser==3.11" \
      /tmp/wheels/*.whl && \
    mkdir -p /var/lib/es-rag-workbench && \
    useradd --system --uid 10001 --create-home --home-dir /home/workbench workbench && \
    chown -R workbench:workbench /var/lib/es-rag-workbench && \
    find /opt/python /home/workbench /var/lib/es-rag-workbench -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} + && \
    touch -h -d "@${SOURCE_DATE_EPOCH}" \
      /opt /var /var/lib /var/lib/es-rag-workbench \
      /home /home/workbench /etc /etc/passwd /etc/group /etc/shadow /etc/gshadow /tmp && \
    rm -rf /tmp/src /tmp/wheels /root/.cache/pip && \
    touch -h -d "@${SOURCE_DATE_EPOCH}" /tmp

USER 10001:10001

EXPOSE 18765
VOLUME ["/var/lib/es-rag-workbench"]

ENTRYPOINT ["python", "-m", "es_rag_tuner"]
CMD ["--host", "127.0.0.1", "--port", "18765"]
