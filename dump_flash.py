"""Back up flash from the Actiontec MI424-WR Rev C RGLoader console."""

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

FLASH_SIZE = 0x800000
ROW_SIZE = 16
PROMPT = b"Actiontec Home Router boot>"
ROW_ADDRESS = re.compile(r"^([0-9a-fA-F]{8}):")
BYTE = re.compile(r"[0-9a-fA-F]{2}")


def parse_dump(response, start, length):
    data = bytearray()
    for line in response.splitlines():
        match = ROW_ADDRESS.match(line)
        if match is None:
            continue
        address = int(match[1], 16)
        expected = start + len(data)
        if address != expected:
            raise ValueError(f"Expected row at 0x{expected:08x}, got 0x{address:08x}")
        if len(data) + ROW_SIZE > length:
            raise ValueError(f"Unexpected extra row at 0x{address:08x}")
        tokens = line[match.end():].partition("|")[0].split()
        if len(tokens) != ROW_SIZE or any(not BYTE.fullmatch(token) for token in tokens):
            raise ValueError(f"Malformed data row at 0x{address:08x}")
        data.extend(int(token, 16) for token in tokens)
    if len(data) != length:
        raise ValueError(f"Expected {length} bytes, received {len(data)}")
    return bytes(data)


def read_until_prompt(port, timeout):
    deadline = time.monotonic() + timeout
    response = bytearray()
    while time.monotonic() < deadline:
        incoming = port.read(min(port.in_waiting, 4096) or 1)
        if not incoming:
            continue
        response.extend(incoming)
        last_line = response[max(response.rfind(b"\r"), response.rfind(b"\n")) + 1:]
        if last_line.rstrip(b" ") == PROMPT:
            return bytes(response)
    raise TimeoutError("Timed out waiting for the RGLoader prompt")


def read_chunk(port, start, length):
    command = f"flash_dump -r 0x{start:x} -l 0x{length:x} -1\r"
    try:
        port.write(command.encode("ascii"))
        response = read_until_prompt(port, 30)
        return parse_dump(response.decode("ascii", errors="replace"), start, length)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Read at 0x{start:08x} failed: {exc}") from exc


def validate_range(start, length, chunk_size):
    if start < 0 or length <= 0 or chunk_size <= 0:
        raise ValueError("Start must be nonnegative; length and chunk size must be positive")
    if any(value % ROW_SIZE for value in (start, length, chunk_size)):
        raise ValueError("Start, length and chunk size must be multiples of 16")
    if start + length > FLASH_SIZE:
        raise ValueError("Requested range exceeds the 8 MiB flash")


def transfer(args, partial, completed):
    import serial

    with serial.Serial(
        args.port, args.baud, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE, timeout=0.1, write_timeout=2,
        xonxoff=False, rtscts=False, dsrdtr=False, exclusive=True,
    ) as port:
        port.reset_input_buffer()
        port.write(b"\r")
        read_until_prompt(port, 5)
        while completed < args.length:
            size = min(args.chunk_size, args.length - completed)
            chunk = read_chunk(port, args.start + completed, size)
            partial.write(chunk)
            partial.flush()
            completed += size
            print(f"{completed}/{args.length} bytes ({completed / args.length:.1%})", flush=True)


def extract(args):
    import fcntl

    output = args.output
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    part = output.with_name(output.name + ".part")
    mode = "r+b" if args.resume else "x+b"
    with open(part, mode, opener=open_partial) as partial:
        fcntl.flock(partial, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Output already exists: {output}")
        completed = partial.seek(0, 2)
        if completed > args.length or (
            completed != args.length and completed % args.chunk_size
        ):
            raise ValueError("Partial file length is outside the requested range or off a chunk boundary")
        if completed < args.length:
            transfer(args, partial, completed)
        if partial.seek(0, 2) != args.length:
            raise ValueError("Partial file size does not match the requested length")
        # Publish atomically and fail if another process created the output.
        os.link(part, output)
        part.unlink()

    digest = hashlib.sha256()
    with output.open("rb") as result:
        for block in iter(lambda: result.read(65536), b""):
            digest.update(block)
    print(f"Saved {args.length} bytes to {output}")
    print(f"SHA-256 {digest.hexdigest()}")


def open_partial(path, flags):
    return os.open(path, flags | os.O_NOFOLLOW, 0o600)


def parse_number(value):
    base = 16 if value.lstrip("+-").lower().startswith("0x") else 10
    return int(value, base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--start", type=parse_number, default=0)
    parser.add_argument("--length", type=parse_number, required=True)
    parser.add_argument("--chunk-size", type=parse_number, default=0x1000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true",
                        help="continue an existing .part file using the same router and arguments")
    args = parser.parse_args(argv)
    try:
        validate_range(args.start, args.length, args.chunk_size)
        if args.baud <= 0:
            raise ValueError("Baud rate must be positive")
        extract(args)
    except (OSError, ValueError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Any partial data is in the .part file.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
