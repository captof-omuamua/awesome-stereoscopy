#!/usr/bin/env python3
"""Exercise the documented field-sequential conversion against independent pixels.

Requires Python 3 and an FFmpeg build with separatefields/stereo3d. No media,
NumPy, display, encoder, or downloaded test vectors are needed.
"""

import argparse
from fractions import Fraction
import itertools
import re
import subprocess
import unittest


WIDTH, HEIGHT, PAIRS = 48, 24, 4  # HEIGHT is one field, not the woven frame.
DISPARITY, MOTION = 6, 2
FFMPEG = "ffmpeg"


def eye_image(eye, capture):
    """Independently identify eye, capture sample, row, and column in RGB bytes."""
    image = bytearray()
    box = 8 + MOTION * capture + (DISPARITY if eye == "R" else 0)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixel = (40 if eye == "L" else 180, 20 + capture * 20, x + y * 3)
            if y >= 4 and box <= x < box + 3:
                pixel = (250, 250, 250)
            image.extend(pixel)
    return bytes(image)


def fixture(field_order, first_eye, capture_model):
    """Weave fields directly; do not use FFmpeg to manufacture the oracle."""
    woven, expected = bytearray(), []
    stride = WIDTH * 3
    for pair in range(PAIRS):
        eyes = {}
        fields = []
        for field, eye in enumerate((first_eye, "R" if first_eye == "L" else "L")):
            # Capture time is a fixture assumption, not inferred from a format tag.
            capture = pair if capture_model == "synchronized" else 2 * pair + field
            eyes[eye] = eye_image(eye, capture)
            fields.append(eyes[eye])
        expected.append((eyes["L"], eyes["R"]))
        top, bottom = fields if field_order == "tff" else fields[::-1]
        for y in range(HEIGHT):
            woven.extend(top[y * stride:(y + 1) * stride])
            woven.extend(bottom[y * stride:(y + 1) * stride])
    return bytes(woven), expected


def pack(left, right, layout):
    if layout == "abl":
        return left + right
    stride = WIDTH * 3
    return b"".join(left[y * stride:(y + 1) * stride]
                    + right[y * stride:(y + 1) * stride] for y in range(HEIGHT))


def convert(source, frame_rate, field_order, first_eye, layout):
    eye_order = "al" if first_eye == "L" else "ar"
    filters = f"setfield={field_order},separatefields,stereo3d={eye_order}:{layout},showinfo"
    command = [FFMPEG, "-hide_banner", "-loglevel", "info", "-f", "rawvideo",
               "-pixel_format", "rgb24", "-video_size", f"{WIDTH}x{2 * HEIGHT}",
               "-framerate", str(frame_rate), "-i", "pipe:0", "-vf", filters,
               "-fps_mode", "passthrough", "-threads:v", "1", "-pix_fmt", "rgb24",
               "-f", "rawvideo", "pipe:1"]
    result = subprocess.run(command, input=source, capture_output=True, timeout=30)
    log = result.stderr.decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"FFmpeg exited {result.returncode}:\n{log}")
    time_base = re.search(r"config in time_base: (\d+/\d+)", log)
    if not time_base:
        raise RuntimeError(f"Missing showinfo time base:\n{log}")
    stamps = [int(x) * Fraction(time_base.group(1))
              for x in re.findall(r"\bn:\s*\d+\s+pts:\s*(-?\d+)\s+pts_time:", log)]
    return result.stdout, stamps


class FieldSequentialTests(unittest.TestCase):
    def test_pixels_and_cadence(self):
        """32 combinations; every pixel, frame count, and exact rational PTS."""
        combinations = itertools.product(
            (Fraction(25), Fraction(30000, 1001)), ("tff", "bff"),
            ("L", "R"), ("sbsl", "abl"), ("synchronized", "staggered"))
        for rate, fields, first, layout, capture in combinations:
            with self.subTest(rate=str(rate), fields=fields, first=first,
                              layout=layout, capture=capture):
                source, pairs = fixture(fields, first, capture)
                output, stamps = convert(source, rate, fields, first, layout)
                expected = b"".join(pack(l, r, layout) for l, r in pairs)
                self.assertTrue(output == expected,
                                f"Pixel mismatch: got {len(output)} bytes, expected {len(expected)}")
                self.assertEqual(stamps, [Fraction(n, 1) / rate for n in range(PAIRS)])

    def test_staggered_motion_is_preserved_not_synchronized(self):
        """Sequential exposure adds/subtracts motion from apparent disparity."""
        def bar_x(image):
            row = image[HEIGHT // 2 * WIDTH * 3:(HEIGHT // 2 + 1) * WIDTH * 3]
            return next(x for x in range(WIDTH) if row[x * 3:x * 3 + 3] == b"\xfa" * 3)

        for first, fields in itertools.product(("L", "R"), ("tff", "bff")):
            for capture in ("synchronized", "staggered"):
                with self.subTest(first=first, fields=fields, capture=capture):
                    source, _ = fixture(fields, first, capture)
                    output, _ = convert(source, Fraction(25), fields, first, "abl")
                    size = WIDTH * HEIGHT * 3
                    disparity = bar_x(output[size:2 * size]) - bar_x(output[:size])
                    offset = 0 if capture == "synchronized" else MOTION * (1 if first == "L" else -1)
                    self.assertEqual(disparity, DISPARITY + offset)
                    if capture == "staggered":
                        self.assertNotEqual(disparity, DISPARITY)

    def test_wrong_field_or_eye_order_swaps_views(self):
        """Negative controls: the oracle must reject either wrong declaration."""
        source, pairs = fixture("tff", "L", "staggered")
        correct = b"".join(pack(l, r, "abl") for l, r in pairs)
        swapped = b"".join(pack(r, l, "abl") for l, r in pairs)
        for fields, first in (("bff", "L"), ("tff", "R")):
            with self.subTest(fields=fields, first=first):
                output, _ = convert(source, Fraction(25), fields, first, "abl")
                self.assertNotEqual(output, correct)
                self.assertTrue(output == swapped, "Wrong-order control did not swap both views")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable or path")
    args = parser.parse_args()
    FFMPEG = args.ffmpeg
    version = subprocess.run([FFMPEG, "-version"], capture_output=True, text=True,
                             check=True, timeout=10).stdout.splitlines()[0]
    print(version, flush=True)
    unittest.main(argv=[__file__], verbosity=2)
