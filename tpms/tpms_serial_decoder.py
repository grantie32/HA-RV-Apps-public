"""Decode the ATOTO AC-UTP1 USB TPMS serial protocol.

The receiver presents as a CH340 USB serial device. Frames are eight bytes:

    55 AA 08 SENSOR_ID PRESSURE TEMP_F STATUS CHECKSUM

The checksum is the XOR of bytes 0 through 6. Pressure is reported in
half-PSI increments by the tested receiver (raw value / 2).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

try:
    import serial
except ImportError as exc:  # pragma: no cover - exercised on user machines
    raise SystemExit("Missing dependency: install it with `py -m pip install pyserial`") from exc


FRAME_LENGTH = 8
FRAME_PREFIX = b"\x55\xAA\x08"

# Confirmed/working IDs so far. Positions can be revised as the remaining
# wheels are tested. ID 05 duplicates the active ID 10 frame in the captures.
SENSOR_NAMES = {
    0x00: "front_left",
    0x10: "front_right",
}
DUPLICATE_IDS = {0x05}


@dataclass(frozen=True)
class TpmsReading:
    sensor_id: int
    sensor_name: str
    pressure_psi: float | None
    temperature_f: int
    status: int
    valid: bool
    checksum: int
    received_at: str

    def as_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


def xor_checksum(frame_without_checksum: bytes) -> int:
    checksum = 0
    for value in frame_without_checksum:
        checksum ^= value
    return checksum


def decode_frame(frame: bytes) -> TpmsReading | None:
    """Decode one complete frame, returning None for invalid framing/checksum."""
    if len(frame) != FRAME_LENGTH or frame[:3] != FRAME_PREFIX:
        return None

    expected = xor_checksum(frame[:-1])
    if expected != frame[-1]:
        return None

    sensor_id = frame[3]
    raw_pressure = frame[4]
    status = frame[6]
    valid = status == 0 and raw_pressure > 0

    return TpmsReading(
        sensor_id=sensor_id,
        sensor_name=SENSOR_NAMES.get(sensor_id, f"sensor_{sensor_id:02x}"),
        pressure_psi=raw_pressure / 2 if valid else None,
        temperature_f=frame[5],
        status=status,
        valid=valid,
        checksum=frame[7],
        received_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


class FrameParser:
    """Incrementally recover frames from arbitrary serial read chunks."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.bad_frames = 0

    def feed(self, data: bytes) -> list[TpmsReading]:
        self.buffer.extend(data)
        readings: list[TpmsReading] = []

        while True:
            prefix_at = self.buffer.find(FRAME_PREFIX)
            if prefix_at < 0:
                # Preserve a possible partial prefix at the end of the buffer.
                self.buffer[:] = self.buffer[-2:]
                break
            if prefix_at:
                del self.buffer[:prefix_at]
            if len(self.buffer) < FRAME_LENGTH:
                break

            frame = bytes(self.buffer[:FRAME_LENGTH])
            del self.buffer[:FRAME_LENGTH]
            reading = decode_frame(frame)
            if reading is None:
                self.bad_frames += 1
            else:
                readings.append(reading)

        return readings


def format_reading(reading: TpmsReading) -> str:
    if reading.valid:
        pressure = f"{reading.pressure_psi:.1f} PSI"
        state = "OK"
    else:
        pressure = "no pressure"
        state = f"inactive/status 0x{reading.status:02X}"
    return (
        f"ID {reading.sensor_id:02X} ({reading.sensor_name}): "
        f"{pressure}, {reading.temperature_f} F, {state}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="Windows COM port, for example COM4")
    parser.add_argument("-b", "--baud", type=int, default=19200)
    parser.add_argument("--json", action="store_true", help="Print JSON lines")
    parser.add_argument(
        "--include-duplicates",
        action="store_true",
        help="Include duplicate/reference frames such as sensor ID 05",
    )
    args = parser.parse_args()

    try:
        with serial.Serial(args.port, args.baud, timeout=1) as receiver:
            # The ATOTO receiver produces data on Windows with the adapter's
            # modem-control lines asserted. Explicitly assert both on Linux;
            # this is harmless for ordinary USB serial adapters and avoids a
            # silent receiver when the host leaves DTR/RTS low.
            receiver.dtr = True
            receiver.rts = True
            time.sleep(0.25)
            receiver.reset_input_buffer()
            print(f"Listening on {args.port} at {args.baud} baud. Press Ctrl+C to stop.", file=sys.stderr)
            frame_parser = FrameParser()
            while True:
                readings = frame_parser.feed(receiver.read(64))
                for reading in readings:
                    if not args.include_duplicates and reading.sensor_id in DUPLICATE_IDS:
                        continue
                    print(reading.as_json() if args.json else format_reading(reading), flush=True)
    except KeyboardInterrupt:
        return 0
    except serial.SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
