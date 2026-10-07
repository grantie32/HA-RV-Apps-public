FROM ghcr.io/home-assistant/base:latest

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.type="app" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.arch="${BUILD_ARCH}"

WORKDIR /app
COPY tpms_mqtt_bridge.py /app/tpms_mqtt_bridge.py
COPY run.sh /app/run.sh

RUN apk add --no-cache python3 py3-pip \
    && apk add --no-cache libusb \
    && pip3 install --no-cache-dir --break-system-packages pyserial paho-mqtt pyusb \
    && chmod a+x /app/run.sh

CMD ["/app/run.sh"]
