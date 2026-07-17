import struct
import unittest

from services.image_layout import _image_dimensions


class ImageLayoutTests(unittest.TestCase):
    def test_reads_png_dimensions(self):
        image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 800, 600)

        self.assertEqual(_image_dimensions(image_data), (800, 600))

    def test_reads_gif_dimensions(self):
        image_data = b"GIF89a" + struct.pack("<HH", 320, 480)

        self.assertEqual(_image_dimensions(image_data), (320, 480))


if __name__ == "__main__":
    unittest.main()
