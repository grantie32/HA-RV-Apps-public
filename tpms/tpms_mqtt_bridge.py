"""Read the ATOTO AC-UTP1 receiver and publish Home Assistant MQTT entities."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial

FRAME_PREFIX = b"\x55\xAA\x08"
FRAME_LENGTH = 8
DUPLICATE_IDS = {0x05}
NAMES = {0x00: "front_left", 0x01: "rear_left", 0x10: "front_right", 0x11: "rear_right"}
PUBLISH_HEARTBEAT_SECONDS = 60
last_published: dict[str, tuple[float, str]] = {}


def decode(frame: bytes) -> dict | None:
    if len(frame) != FRAME_LENGTH or frame[:3] != FRAME_PREFIX:
        return None
    checksum = 0
    for byte in frame[:7]:
        checksum ^= byte
    if checksum != frame[7]:
        return None
    sensor_id, raw_pressure, temperature, status = frame[3], frame[4], frame[5], frame[6]
    return {
        "id": sensor_id,
        "name": NAMES.get(sensor_id, f"sensor_{sensor_id:02x}"),
        "pressure": raw_pressure / 2 if status == 0 and raw_pressure else None,
        "temperature": temperature,
        "status": status,
        "valid": status == 0 and raw_pressure > 0,
    }


def discovery(client: mqtt.Client, prefix: str, name: str, component: str, device_class: str, unit: str, value_template: str) -> None:
    # The MQTT discovery topic already supplies the `sensor` domain. Including
    # it in the object id creates invalid topics such as
    # `homeassistant/sensor/sensor.motorhome_tpms_.../config`.
    object_id = f"motorhome_tpms_{name}_{component}"
    topic = f"homeassistant/sensor/{object_id}/config"
    payload = {
        "name": f"{name.replace('_', ' ').title()} {component.title()}",
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": f"{prefix}/{name}",
        "value_template": value_template,
        "availability_topic": f"{prefix}/availability",
        "device_class": device_class,
        "unit_of_measurement": unit,
        "device": {"identifiers": ["motorhome_tpms"], "name": "Motorhome TPMS", "manufacturer": "ATOTO", "model": "AC-UTP1"},
    }
    client.publish(topic, json.dumps(payload), retain=True)


def publish_reading(client: mqtt.Client, reading: dict) -> bool:
    """Avoid re-publishing identical receiver frames continuously."""
    name = reading["name"]
    fingerprint = json.dumps(
        {key: reading.get(key) for key in ("pressure", "temperature", "status", "valid")},
        sort_keys=True,
    )
    now = time.monotonic()
    previous = last_published.get(name)
    if previous and previous[1] == fingerprint and now - previous[0] < PUBLISH_HEARTBEAT_SECONDS:
        return False

    last_published[name] = (now, fingerprint)
    client.publish(f"motorhome/tpms/{name}", json.dumps(reading), retain=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    parser.add_argument("--mqtt-host", default="core-mosquitto")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-user", required=True)
    parser.add_argument("--mqtt-password", required=True)
    args = parser.parse_args()

    print(f"Connecting to MQTT broker {args.mqtt_host}:{args.mqtt_port}", flush=True)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="motorhome-tpms")
    client.username_pw_set(args.mqtt_user, args.mqtt_password)
    client.will_set("motorhome/tpms/availability", "offline", retain=True)
    client.connect(args.mqtt_host, args.mqtt_port, 60)
    client.loop_start()
    print("MQTT connected; publishing discovery", flush=True)

    for name in set(NAMES.values()):
        discovery(client, "motorhome/tpms", name, "pressure", "pressure", "psi", "{{ value_json.pressure }}")
        discovery(client, "motorhome/tpms", name, "temperature", "temperature", "°F", "{{ value_json.temperature }}")
    client.publish("motorhome/tpms/availability", "online", retain=True)

    print(f"Opening serial receiver {args.serial} at 19200 baud", flush=True)
    receiver = serial.Serial(port=None, baudrate=19200, bytesize=serial.EIGHTBITS,
                             parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                             timeout=1, xonxoff=False, rtscts=False, dsrdtr=False)
    receiver._dtr_state = True
    receiver._rts_state = True
    receiver.port = args.serial
    receiver.open()
    try:
        time.sleep(0.25)
        receiver.reset_input_buffer()
        buffer = bytearray()
        while True:
            buffer.extend(receiver.read(64))
            while True:
                start = buffer.find(FRAME_PREFIX)
                if start < 0:
                    buffer[:] = buffer[-2:]
                    break
                del buffer[:start]
                if len(buffer) < FRAME_LENGTH:
                    break
                frame = bytes(buffer[:FRAME_LENGTH])
                del buffer[:FRAME_LENGTH]
                reading = decode(frame)
                if not reading or reading["id"] in DUPLICATE_IDS:
                    continue
                reading["received_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if publish_reading(client, reading):
                    print(f"TPMS {reading}", flush=True)
    finally:
        receiver.close()


if __name__ == "__main__":
    main()
