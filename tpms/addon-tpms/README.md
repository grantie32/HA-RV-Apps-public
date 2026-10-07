# Motorhome TPMS Home Assistant add-on

This local add-on reads the ATOTO AC-UTP1 receiver from `/dev/ttyUSB2`,
asserts DTR/RTS, decodes the eight-byte frames, and publishes Home Assistant
MQTT discovery entities through the Mosquitto broker.

The receiver currently appears on the Raspberry Pi as:

```text
/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 -> /dev/ttyUSB2
```

The add-on maps `/dev/ttyUSB2`; if the device number changes after a reboot,
the `devices:` entry and `serial_device` option must be updated together.
