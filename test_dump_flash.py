import contextlib
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dump_flash


ROWS = [
    "00000000: e1 a0 c0 00 e3 a0 00 d3  e1 21 f0 00 e3 a0 00 78  |.........!.....x|",
    "00000010: e3 80 00 80 ee 01 0f 10  ee 12 0f 10 e1 a0 00 00  |................|",
]
PROMPT = dump_flash.PROMPT.decode("ascii")


class ParseDumpTests(unittest.TestCase):
    def test_example(self):
        response = "\r\n".join(
            [f"{PROMPT} flash_dump -r 0x0 -l 0x20 -1", *ROWS, "", PROMPT]
        )
        self.assertEqual(
            dump_flash.parse_dump(response, 0, 32),
            bytes.fromhex("e1 a0 c0 00 e3 a0 00 d3 e1 21 f0 00 e3 a0 00 78 "
                          "e3 80 00 80 ee 01 0f 10 ee 12 0f 10 e1 a0 00 00"),
        )

    def test_nonzero_address_and_ff(self):
        row = ROWS[0].replace("00000000:", "00000100:").replace("e1", "ff", 1)
        response = f"flash_dump -r 0x100 -l 0x10 -1\n{row}\n{PROMPT}"
        result = dump_flash.parse_dump(response, 0x100, 16)
        self.assertEqual(result, bytes.fromhex("ff a0 c0 00 e3 a0 00 d3 e1 21 f0 00 e3 a0 00 78"))

    def test_invalid_rows(self):
        cases = {
            "missing": [ROWS[1]],
            "duplicate": [ROWS[0], ROWS[0]],
            "out of order": ROWS[::-1],
            "bad hex": [ROWS[0].replace("e1", "gg", 1), ROWS[1]],
            "short row": [ROWS[0].replace("e1 ", "", 1), ROWS[1]],
            "extra row": [*ROWS, ROWS[1].replace("00000010:", "00000020:")],
            "incorrect byte count": ROWS[:1],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                dump_flash.parse_dump("\n".join(rows), 0, 32)


class CliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "flash.bin"
        self.part = self.output.with_suffix(".bin.part")

    def run_cli(self, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = dump_flash.main([
                "--length", "32", "--chunk-size", "16", "--output", str(self.output), *options,
            ])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_range_validation(self):
        for values in ((-16, 16, 16), (1, 16, 16), (0, 0, 16), (0, 17, 16),
                       (0, 16, 0), (0, 16, 17), (0x7FFFF0, 32, 16)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                dump_flash.validate_range(*values)
        dump_flash.validate_range(0x7FFFF0, 16, 16)

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b"backup")
        for options in ((), ("--resume",)):
            status, _, error = self.run_cli(*options)
            self.assertEqual(status, 1)
            self.assertIn("Output already exists", error)
        self.assertEqual(self.output.read_bytes(), b"backup")

    def test_no_automatic_resume(self):
        self.part.write_bytes(b"a" * 16)
        status, _, _ = self.run_cli()
        self.assertEqual(status, 1)
        self.assertEqual(self.part.read_bytes(), b"a" * 16)

    def test_invalid_resume_lengths(self):
        for size in (15, 33, 48):
            with self.subTest(size=size):
                self.part.write_bytes(b"a" * size)
                status, _, error = self.run_cli("--resume")
                self.assertEqual(status, 1)
                self.assertIn("Partial file length", error)
                self.assertEqual(self.part.stat().st_size, size)
                self.assertFalse(self.output.exists())

    def test_resume_publishes_and_hashes(self):
        self.part.write_bytes(b"a" * 16)

        def finish(args, partial, completed):
            self.assertEqual(completed, 16)
            partial.write(b"b" * 16)

        with patch("dump_flash.transfer", side_effect=finish):
            status, stdout, error = self.run_cli("--resume")
        expected = b"a" * 16 + b"b" * 16
        self.assertEqual(status, 0, error)
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertIn(hashlib.sha256(expected).hexdigest(), stdout)
        self.assertFalse(self.part.exists())
