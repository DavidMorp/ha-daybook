ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24
FROM ${BUILD_FROM}

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY daybook_app /app/daybook_app
COPY rootfs /
RUN chmod a+x /etc/services.d/daybook/run /etc/services.d/daybook/finish

WORKDIR /app

ARG BUILD_ARCH
ARG BUILD_VERSION
LABEL \
  io.hass.name="Daybook" \
  io.hass.description="A private journal for what you take, how you feel and sport" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}" \
  org.opencontainers.image.source="https://github.com/DavidMorp/ha-daybook" \
  org.opencontainers.image.licenses="MIT"
