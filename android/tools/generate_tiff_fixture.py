#!/usr/bin/env python3
"""Build a synthetic ARW-like TIFF fixture for the IFD-parser unit tests.

Layout (little-endian): IFD0 carries a mid-size preview (0x0201/0x0202) plus a
SubIFD pointer (0x014A) whose IFD carries the LARGEST preview, an ExifIFD
(0x8769) with DateTimeOriginal + ExposureTime, and a chained IFD1 with a tiny
thumbnail — exercising every branch the parser walks on a real Sony file.
"""
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "core/src/test/resources/fixtures/synthetic.tiff"
OUT.parent.mkdir(parents=True, exist_ok=True)

le = "<"


def entry(tag, typ, count, value):
    return struct.pack(le + "HHI", tag, typ, count) + struct.pack(le + "I", value)


# fake JPEG payloads
jpeg_small = b"\xff\xd8" + b"S" * 60 + b"\xff\xd9"          # 64 bytes (thumbnail)
jpeg_mid = b"\xff\xd8" + b"M" * 252 + b"\xff\xd9"           # 256 bytes (IFD0 preview)
jpeg_big = b"\xff\xd8" + b"B" * 1020 + b"\xff\xd9"          # 1024 bytes (SubIFD preview)
datetime_str = b"2026:07:17 10:00:00\x00"

# --- fixed layout ------------------------------------------------------------
# header(8) | IFD0 | ExifIFD | SubIFD | IFD1 | datetime | rational | jpegs
ifd0_off = 8
ifd0_size = 2 + 5 * 12 + 4
exif_off = ifd0_off + ifd0_size
exif_size = 2 + 2 * 12 + 4
subifd_off = exif_off + exif_size
subifd_size = 2 + 2 * 12 + 4
ifd1_off = subifd_off + subifd_size
ifd1_size = 2 + 2 * 12 + 4
dt_off = ifd1_off + ifd1_size
rat_off = dt_off + len(datetime_str)
jpeg_mid_off = rat_off + 8
jpeg_big_off = jpeg_mid_off + len(jpeg_mid)
jpeg_small_off = jpeg_big_off + len(jpeg_big)

header = b"II" + struct.pack(le + "H", 42) + struct.pack(le + "I", ifd0_off)

ifd0 = struct.pack(le + "H", 5)
ifd0 += entry(0x0100, 3, 1, 6192)                      # ImageWidth
ifd0 += entry(0x0201, 4, 1, jpeg_mid_off)              # preview offset
ifd0 += entry(0x0202, 4, 1, len(jpeg_mid))             # preview length
ifd0 += entry(0x014A, 4, 1, subifd_off)                # SubIFD pointer
ifd0 += entry(0x8769, 4, 1, exif_off)                  # ExifIFD pointer
ifd0 += struct.pack(le + "I", ifd1_off)                # next IFD

exif = struct.pack(le + "H", 2)
exif += entry(0x829A, 5, 1, rat_off)                   # ExposureTime rational
exif += entry(0x9003, 2, len(datetime_str), dt_off)    # DateTimeOriginal
exif += struct.pack(le + "I", 0)

subifd = struct.pack(le + "H", 2)
subifd += entry(0x0201, 4, 1, jpeg_big_off)
subifd += entry(0x0202, 4, 1, len(jpeg_big))
subifd += struct.pack(le + "I", 0)

ifd1 = struct.pack(le + "H", 2)
ifd1 += entry(0x0201, 4, 1, jpeg_small_off)
ifd1 += entry(0x0202, 4, 1, len(jpeg_small))
ifd1 += struct.pack(le + "I", 0)

rational = struct.pack(le + "II", 1, 2)                # 0.5s shutter

blob = header + ifd0 + exif + subifd + ifd1 + datetime_str + rational
blob += jpeg_mid + jpeg_big + jpeg_small
OUT.write_bytes(blob)
print(OUT, len(blob), "bytes; big preview at", jpeg_big_off, "len", len(jpeg_big))
