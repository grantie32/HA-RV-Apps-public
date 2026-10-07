"""Read the ATOTO AC-UTP1 receiver and publish Home Assistant MQTT entities."""

from __future__ import annotations

import argparse
import fcntl
import json
import struct
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial
import usb.core
import usb.util

FRAME_PREFIX = b"\x55\xAA\x08"
FRAME_LENGTH = 8
DUPLICATE_IDS = {0x05}
NAMES = {0x00: "front_left", 0x01: "rear_left", 0x10: "front_right", 0x11: "rear_right"}
TIOCMBIS = 0x5418
TIOCM_DTR = 0x002
TIOCM_RTS = 0x004
PUBLISH_HEARTBEAT_SECONDS = 60
last_published: dict[str, tuple[float, str]] = {}


def assert_modem_lines(receiver: serial.Serial) -> None:
    fcntl.ioctl(receiver.fileno(), TIOCMBIS, struct.pack("I", TIOCM_DTR | TIOCM_RTS))
    print("DTR/RTS asserted via Linux ioctl", flush=True)


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
    object_id = f"motorhome_tpms_{name}_{component}"
    topic = f"homeassistant/sensor/{object_id}/config"
    payload = {
        "name": f"{name.replace('_', ' ').title()} {component.title()}",
        "unique_id": object_id,
        "object_id": object_id,
        "state_topic": f"{prefix}/{name}",
        "value_template": value_template,
        "availability_topic": f"{prefix}/availability",
        "unit_of_measurement": unit,
        "state_class": "measurement",
        "device": {"identifiers": ["motorhome_tpms"], "name": "Motorhome TPMS", "manufacturer": "ATOTO", "model": "AC-UTP1"},
    }
    if device_class == "temperature":
        payload["device_class"] = "temperature"
    client.publish(topic, json.dumps(payload), retain=True)


def publish_reading(client: mqtt.Client, reading: dict) -> bool:
    """Publish meaningful changes and an occasional heartbeat only.

    The receiver can repeat identical frames rapidly. Re-publishing those
    frames creates unnecessary MQTT traffic and recorder work in Home
    Assistant, so unchanged readings are limited to one update per minute.
    Any pressure, temperature, or status change is still sent immediately.
    """
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


def publish_frames(buffer: bytearray, client: mqtt.Client) -> None:
    while True:
        start = buffer.find(FRAME_PREFIX)
        if start < 0:
            buffer[:] = buffer[-2:]
            return
        del buffer[:start]
        if len(buffer) < FRAME_LENGTH:
            return
        frame = bytes(buffer[:FRAME_LENGTH])
        del buffer[:FRAME_LENGTH]
        reading = decode(frame)
        if not reading or reading["id"] in DUPLICATE_IDS:
            continue
        reading["received_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if publish_reading(client, reading):
            print(f"TPMS {reading}", flush=True)


def configure_ch341(device: usb.core.Device) -> None:
    version = bytes(device.ctrl_transfer(0xC0, 0x5F, 0, 0, 2))
    chip_version = version[0] if version else 0
    print(f"CH340 version 0x{chip_version:02X}; replaying Windows setup", flush=True)

    # These are the CH341 vendor requests visible in the USBPcap capture from
    # the working Windows/RealTerm session.  The earlier implementation used
    # values derived from the Linux kernel driver, but that left this receiver
    # silent when accessed directly through libusb.
    requests = [
        (0x40, 0xA1, 0x0000, 0x0000),  # serial init
        (0x40, 0x9A, 0x1312, 0xD982),
        (0x40, 0x9A, 0x0F2C, 0x0007),
        (0x40, 0x9A, 0x2727, 0x0000),
        (0x40, 0x9A, 0x0F2C, 0x0007),
        (0x40, 0xA4, 0x00DF, 0x0000),
        (0x40, 0xA4, 0x009F, 0x0000),
    ]
    for bm_request_type, request, value, index in requests:
        print(f"CH341 ctrl {bm_request_type:02X} {request:02X} {value:04X} {index:04X}", flush=True)
        device.ctrl_transfer(bm_request_type, request, value, index, None)


def read_usb(client: mqtt.Client) -> None:
    device = usb.core.find(idVendor=0x1A86, idProduct=0x7523)
    if device is None:
        raise RuntimeError("CH340 USB receiver 1A86:7523 was not found")
    interface = device.get_active_configuration()[(0, 0)]
    if device.is_kernel_driver_active(interface.bInterfaceNumber):
        print("Detaching Linux CH341 driver for raw USB access", flush=True)
        device.detach_kernel_driver(interface.bInterfaceNumber)
    configure_ch341(device)
    endpoint = usb.util.find_descriptor(interface, bEndpointAddress=0x82)
    if endpoint is None:
        raise RuntimeError("USB endpoint 0x82 was not found")
    print("Reading raw USB endpoint 0x82", flush=True)
    buffer = bytearray()
    while True:
        try:
            data = device.read(endpoint.bEndpointAddress, endpoint.wMaxPacketSize, timeout=1000)
        except usb.core.USBTimeoutError:
            # No packet during this interval is normal; keep the receiver alive.
            continue
        buffer.extend(bytes(data))
        publish_frames(buffer, client)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", default="/dev/ttyUSB2")
    parser.add_argument("--mqtt-host", default="core-mosquitto")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-user", required=True)
    parser.add_argument("--mqtt-password", required=True)
    parser.add_argument("--usb", action="store_true")
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

    if args.usb:
        read_usb(client)
        return

    print(f"Opening serial receiver {args.serial} at 19200 baud", flush=True)
    receiver = serial.Serial(port=None, baudrate=19200, bytesize=serial.EIGHTBITS,
                             parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                             timeout=1, xonxoff=False, rtscts=False, dsrdtr=False)
    receiver._dtr_state = True
    receiver._rts_state = True
    receiver.port = args.serial
    receiver.open()
    try:
        assert_modem_lines(receiver)
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
                publish_frames(bytearray(frame), client)
    finally:
        receiver.close()


if __name__ == "__main__":
    main()
