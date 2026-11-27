# RGLoader flash backup

Back up flash from an Actiontec MI424-WR Rev C using its RGLoader serial console. The script sends a carriage return to synchronize and uses RGLoader's read-only `flash_dump` command. Enter RGLoader manually before running it.

## Setup

Use Python 3.9 or later on Linux with pyserial.

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest
```

Connect a 3.3 V USB-to-UART adapter to J20. Connect pin 1 to ground, pin 2 (router TX) to adapter RX, and pin 3 (router RX) to adapter TX. Leave the power pins disconnected. Keep the router offline. In Picocom, use 115200 baud, 8N1, and no flow control. Confirm the `Actiontec Home Router boot>` prompt and close Picocom before starting the script.

## Usage

```sh
python3 dump_flash.py --port /dev/ttyUSB0 --start 0x0 --length 0x1000 --output sample.bin
python3 dump_flash.py --port /dev/ttyUSB0 --start 0x0 --length 0x800000 --output actiontec-revc.bin
```

The defaults are `/dev/ttyUSB0`, 115200 baud, start 0, and 4096-byte chunks. Use decimal or `0x` hexadecimal for start, length, and chunk size. All three must be multiples of 16 and the requested range must fit within 8 MiB. The script prints progress, then the saved size and SHA-256. Compare hashes from two separate reads to check repeatability.

Keep backups and serial logs local and out of version control. They may contain credentials, licensing data, and device identifiers.

## Interrupted reads

The script flushes validated chunks to `<output>.part`. Once the file reaches the requested size, it publishes the final name and removes the partial name. The output filesystem must support hard links. Existing output files are protected, and existing partial files require explicit `--resume`.

Before resuming, check that the router is at the RGLoader prompt again. Rerun the same command with `--resume` only after confirming the router, start, length, chunk size, and output match the original run. The script checks the partial file size against the chunk boundaries and cannot authenticate the router or original range. To restart, choose a new output name or move the old partial file aside.

## Bench checks

The tests run without hardware. The final flash sector and a full uninterrupted extraction still need bench verification.

1. In Picocom, run `flash_dump -r 0x7FFF00 -l 0x100 -1` and check for row `007ffff0` and the returning prompt.
2. Close Picocom. Read the first 256 bytes with the script and check for the prefix `e1 a0 c0 00 e3 a0 00 d3`.
3. Read the first 4 KiB twice into distinct files and compare sizes and hashes.
4. Read the image headers at `0xA0000` and `0x400000` and check that both start with `fe ed ba be`.
5. Interrupt a multi-chunk read, resume it, and compare its hash with a fresh read.
6. After those checks pass, read all 8 MiB and check for 8,388,608 bytes. A full read can take an hour or more. Repeat and compare hashes when possible.
