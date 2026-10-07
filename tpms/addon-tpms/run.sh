#!/usr/bin/with-contenv bashio
set -e

exec python3 /app/tpms_mqtt_bridge.py \
  --serial "$(bashio::config 'serial_device')" \
  --mqtt-host "$(bashio::config 'mqtt_host')" \
    --mqtt-port "$(bashio::config 'mqtt_port')" \
    --mqtt-user "$(bashio::config 'mqtt_username')" \
    --mqtt-password "$(bashio::config 'mqtt_password')" \
    --usb
