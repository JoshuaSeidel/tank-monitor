ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
# Alpine 3.19 ships a PEP 668 "externally managed" Python. The container is
# single-purpose, so installing into the system interpreter is the point.
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY tankmcp /opt/tank-mcp/tankmcp
COPY run.sh /run.sh
RUN chmod a+x /run.sh

WORKDIR /opt/tank-mcp
CMD [ "/run.sh" ]
