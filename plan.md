






RGLoader flash extractor — implementation plan
Goal
Build a small, reliable Python command-line script to read the flash of an owned Actiontec MI424-WR Rev C router over its RGLoader serial console and reconstruct a raw binary backup. Simplicity is the highest priority. Do not build a general-purpose firmware extraction framework.

Instructions for Codex
Inspect the existing repository before making changes. Reuse its conventions where practical; do not restructure it.
Implement only the requirements below. Prefer straightforward procedural Python and a few small functions over classes or abstractions.
Use Python 3.9+ and pyserial as the only runtime dependency. Use standard-library argparse, re, hashlib, pathlib, and unittest as needed.
Do not add a package hierarchy, bootloader adapters, configuration files, databases, services, threads, async code, UI, or automatic device discovery.
Do not implement speculative features. If a hardware assumption fails, report the evidence rather than adding a complex workaround.
Never send commands that change router configuration, flash contents or boot state. The operator enters the bootloader manually.
Known hardware and protocol
These facts come from bench experiments on November 27, 2026:

Router: Actiontec MI424-WR Rev C; Intel IXP425 XScale ARM; 32 MiB RAM; 8 MiB flash.
Bootloader: RGLoader 3.15.11.1.14.
Serial: CP2102, /dev/ttyUSB0, 115200 baud, 8 data bits, no parity, 1 stop bit, no flow control.
J20: pin 1 GND, pin 2 router TX, pin 3 router RX; bidirectional communication verified. Pin 5 measured 3.27 V; leave power pins disconnected.
Prompt: Actiontec Home Router boot>.
Read command: flash_dump -r 0xADDRESS -l 0xLENGTH -1.
Hexadecimal addresses and lengths work. Reads of 256 bytes and 4096 bytes have succeeded. The 4096-byte sample has 256 rows of 16 bytes each.
Nonzero reads at 0x100, 0xA0000, and 0x400000 have succeeded.
The final 256 bytes at 0x7FFF00 and uninterrupted full-range extraction are not yet verified. Do not assume success.
Default to 4096-byte chunks; larger chunks are unnecessary for the MVP.
Example response (command echo and blank lines may also appear):

Actiontec Home Router boot> flash_dump -r 0x0 -l 0x20 -1
00000000: e1 a0 c0 00 e3 a0 00 d3  e1 21 f0 00 e3 a0 00 78  |.........!.....x|
00000010: e3 80 00 80 ee 01 0f 10  ee 12 0f 10 e1 a0 00 00  |................|

Actiontec Home Router boot>
Deliverables
Keep the implementation to these files unless the repository already has equivalent files:

dump_flash.py — complete CLI and extraction logic.
test_dump_flash.py — small standard-library unit test suite.
README.md — setup, usage, limitations and recovery from an interrupted read.
requirements.txt — pyserial only.
No packaging or installable CLI is needed.

CLI
python3 dump_flash.py --port /dev/ttyUSB0 --start 0x0 --length 0x1000 --output sample.bin
python3 dump_flash.py --port /dev/ttyUSB0 --start 0x0 --length 0x800000 --output actiontec-revc.bin
Arguments:

--port: default /dev/ttyUSB0.
--baud: default 115200.
--start: default 0x0.
--length: required; accept decimal or hexadecimal.
--chunk-size: default 0x1000.
--output: required.
--resume: optional; continue an existing partial file only for the same requested start and length, as confirmed by the operator. No automatic resume on existing files.
Validate that start, length and chunk size are positive where applicable, multiples of 16 (start may be zero), and that the requested range fits within the known 8 MiB flash. Refuse to overwrite an existing output file. Do not expose a generic command execution option.

Implementation
Serial synchronization. Open the port with explicit 8N1 settings and flow control disabled. The operator must already be at the RGLoader prompt and must close Picocom first. Send only a carriage return to obtain a fresh prompt. Wait for the exact prompt with a bounded timeout; abort if it does not arrive. Do not interrupt boot or reset the router automatically.
Read a chunk. Send the formatted flash_dump command followed by carriage return. Read until the next prompt, including prompts without a newline. Use a bounded deadline (e.g. 30 seconds for a 4 KiB chunk); do not silently accept timeout or truncated output. If a command fails, stop with a clear error rather than sending further commands into an unknown console state.
Parse and validate. Parse only lines beginning with eight hexadecimal address digits and a colon. Extract the byte tokens before the first ASCII delimiter |. Ignore echo, blank lines and prompt. Require 16 valid hex bytes per data row, contiguous ascending addresses starting at the requested address, and exactly the requested byte count. Reject missing, duplicate, out-of-order, malformed or extra rows. Never pad missing bytes or guess their values.
Write validated bytes. Append a chunk only after validation succeeds. Use <output>.part while incomplete, flush after each chunk, and rename to the final filename only after checking exact total length. Keep partial data if interrupted. On resume, require the partial length to be a valid completed chunk boundary (or the exact requested total); reject mismatches. Document that resume does not authenticate the source device or original range and that the operator must use the same router and arguments. If this cannot be implemented simply and safely, omit resume and document restarting instead.
Progress and integrity. Print progress after each chunk (bytes read and percentage). At completion, print file size and SHA-256 computed over the final binary. SHA-256 fingerprints the result; it does not independently prove the serial data is correct. Verify repeatability with a second read and compare hashes when needed.
Suggested functions: parse_dump, read_until_prompt, read_chunk, main. Add helpers only if they clearly simplify the code.

Tests and acceptance criteria
Use python3 -m unittest without physical hardware. Test the parser using the example above and representative synthetic responses:

Correct reconstruction of bytes including 00 and ff.
Nonzero starting address and command echo.
Missing, duplicate, out-of-order, malformed and extra rows rejected.
Incorrect byte count rejected.
Address-range validation and output overwrite protection.
If resume is implemented, invalid partial lengths rejected.
Keep tests focused on data integrity. No elaborate serial mock framework is required. Do not claim hardware validation from unit tests.

Bench validation (operator performs with router attached)
Manually test the last 256 bytes: flash_dump -r 0x7FFF00 -l 0x100 -1. Confirm the final row is 007ffff0 and the prompt returns.
Close Picocom. Run a 256-byte dump with the script. Compare to the known sample beginning e1 a0 c0 00 e3 a0 00 d3.
Dump 4 KiB twice into distinct files; verify identical SHA-256 hashes and exact size.
Dump the primary image header at 0xA0000 and secondary at 0x400000. Both must begin fe ed ba be.
If resume is implemented, interrupt a multi-chunk test and verify resumed output matches a fresh dump.
Only after these tests pass, extract the full 8 MiB (0x800000 bytes) and verify exact size. Ideally repeat and compare hashes.
The full backup may take an hour or more at 115200 baud. Measure actual throughput rather than optimizing prematurely.

Safety and privacy
Keep the old router offline and electrically isolated from production networks.
Do not send flash_erase, flash_commit, load, restore_default, lock, unlock, bset, boot, or other state-changing commands.
Full flash images may contain credentials, licensing data and device identifiers. Store locally, exclude dumps and serial logs from version control, and never upload them automatically.
No firmware modification, checksum algorithm research, JTAG, filesystem extraction, Ghidra integration or support for other bootloaders in this implementation.
Definition of done
A small readable script that extracts validated flash bytes to a local file without changing the router, reports useful errors, passes focused tests, and has concise usage instructions. Hardware verification remains pending until the operator runs the bench tests. Stop when these requirements are met; do not expand the scope.





⋮⋮⋮⋮