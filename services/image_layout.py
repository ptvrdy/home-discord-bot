"""Choose a Discord embed image layout from basic image dimensions."""

import struct

import httpx


MIN_FULL_IMAGE_WIDTH = 500
MIN_FULL_IMAGE_ASPECT_RATIO = 1.1


def _image_dimensions(image_data: bytes) -> tuple[int, int] | None:
    """Read dimensions from PNG, GIF, or JPEG headers."""
    if image_data.startswith(b"\x89PNG\r\n\x1a\n") and len(image_data) >= 24:
        return struct.unpack(">II", image_data[16:24])

    if image_data[:6] in {b"GIF87a", b"GIF89a"} and len(image_data) >= 10:
        return struct.unpack("<HH", image_data[6:10])

    if image_data.startswith(b"\xff\xd8"):
        position = 2
        while position + 9 < len(image_data):
            if image_data[position] != 0xFF:
                position += 1
                continue

            marker = image_data[position + 1]
            position += 2
            if marker in {0xD8, 0xD9}:
                continue

            block_length = struct.unpack(">H", image_data[position:position + 2])[0]
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                height, width = struct.unpack(">HH", image_data[position + 3:position + 7])
                return width, height
            position += block_length

    return None


def should_use_thumbnail(image_url: str) -> bool:
    """Return true only when a source image is too narrow for a card banner.

    The request is capped at the first 64 KiB because image dimensions are in
    the file header. Failed or unsupported checks preserve the full image.
    """
    try:
        with httpx.stream(
            "GET",
            image_url,
            headers={"Range": "bytes=0-65535"},
            follow_redirects=True,
            timeout=5.0,
        ) as response:
            response.raise_for_status()
            chunks = []
            remaining = 65536
            for chunk in response.iter_bytes():
                chunks.append(chunk[:remaining])
                remaining -= len(chunk)
                if remaining == 0:
                    break
            image_data = b"".join(chunks)
    except httpx.HTTPError:
        return False

    dimensions = _image_dimensions(image_data)
    if dimensions is None:
        return False

    width, height = dimensions
    return height > 0 and (
        width < MIN_FULL_IMAGE_WIDTH
        or width / height < MIN_FULL_IMAGE_ASPECT_RATIO
    )
