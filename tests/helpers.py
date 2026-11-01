import base64
import struct
import zlib


def png(width: int = 40, height: int = 10) -> bytes:
    """A small valid PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x00\x00\x00\xff" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def png_data_url(width: int = 40, height: int = 10) -> str:
    return "data:image/png;base64," + base64.b64encode(png(width, height)).decode()


PDF = b"%PDF-1.4\ntest receipt\n%%EOF"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 64
