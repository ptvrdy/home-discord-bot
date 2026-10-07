import unittest
from unittest.mock import MagicMock, patch

import httpx

from services.image_check import (
    ImageFetchError,
    classify_image_response,
    fetch_image,
    image_extension,
    prepare_recipe_image,
)

JPG = "https://example.com/photo.jpg"


def _png(width: int, height: int) -> bytes:
    """Just enough of a PNG for the dimension check: signature + IHDR."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")


def _stream(status_code=200, content_type="image/png", chunks=(b"",)):
    response = MagicMock(status_code=status_code, headers={"content-type": content_type} if content_type else {})
    response.iter_bytes.return_value = list(chunks)
    stream = MagicMock()
    stream.__enter__.return_value = response
    return stream


class ClassifyImageResponseTests(unittest.TestCase):
    def test_image_content_type_is_fine(self):
        self.assertIsNone(classify_image_response(JPG, 200, "image/jpeg"))

    def test_content_type_parameters_are_ignored(self):
        self.assertIsNone(classify_image_response(JPG, 200, "image/png; charset=binary"))

    def test_html_page_is_not_a_direct_image(self):
        problem = classify_image_response("https://example.com/recipe", 200, "text/html; charset=utf-8")
        self.assertIn("isn't a direct image", problem)
        self.assertIn("Copy image address", problem)

    def test_missing_content_type_is_rejected_without_an_image_extension(self):
        self.assertIsNotNone(classify_image_response("https://example.com/photo", 200, None))

    def test_octet_stream_passes_when_url_has_an_image_extension(self):
        self.assertIsNone(classify_image_response(JPG, 200, "application/octet-stream"))

    def test_octet_stream_rejected_without_an_image_extension(self):
        self.assertIsNotNone(classify_image_response("https://example.com/download", 200, "application/octet-stream"))

    def test_404_is_reported_as_a_broken_link(self):
        self.assertIn("broken", classify_image_response(JPG, 404, None))

    def test_ambiguous_errors_pass(self):
        # A 403 may just mean the host is blocking us, not Discord.
        self.assertIsNone(classify_image_response(JPG, 403, "text/html"))
        self.assertIsNone(classify_image_response(JPG, 500, None))


class ImageExtensionTests(unittest.TestCase):
    def test_from_content_type(self):
        self.assertEqual(image_extension("image/jpeg", "x"), ".jpg")
        self.assertEqual(image_extension("image/webp; q=1", "x"), ".webp")

    def test_untyped_falls_back_to_the_url(self):
        self.assertEqual(image_extension("application/octet-stream", "https://e.com/a.JPEG"), ".jpg")

    def test_unsupported_formats(self):
        self.assertIsNone(image_extension("image/svg+xml", "a.svg"))


class FetchImageTests(unittest.TestCase):
    def test_too_large_is_rejected(self):
        with patch("services.image_check.httpx.stream", return_value=_stream(chunks=[b"x" * 10, b"x" * 10])):
            with self.assertRaisesRegex(ImageFetchError, "too large"):
                fetch_image(JPG, max_bytes=15)

    def test_blocked_download_can_fall_back_to_the_link(self):
        with patch("services.image_check.httpx.stream", return_value=_stream(status_code=403, content_type="text/html")):
            with self.assertRaises(ImageFetchError) as raised:
                fetch_image(JPG)
        self.assertTrue(raised.exception.fallback_to_link)


class PrepareRecipeImageTests(unittest.TestCase):
    def test_wide_image_is_attached_as_a_banner(self):
        with patch("services.image_check.httpx.stream", return_value=_stream(chunks=[_png(1200, 800)])):
            prepared = prepare_recipe_image("https://example.com/photo.png")
        self.assertEqual(prepared.image_url, "attachment://recipe-image.png")
        self.assertEqual(prepared.filename, "recipe-image.png")
        self.assertEqual(prepared.data, _png(1200, 800))
        self.assertIsNone(prepared.note)

    def test_narrow_image_is_attached_as_a_thumbnail(self):
        with patch("services.image_check.httpx.stream", return_value=_stream(chunks=[_png(300, 600)])):
            prepared = prepare_recipe_image("https://example.com/photo.png")
        self.assertEqual(prepared.image_url, "attachment://recipe-image-thumb.png")

    def test_non_http_scheme_is_rejected_without_a_request(self):
        with patch("services.image_check.httpx.stream") as stream:
            with self.assertRaisesRegex(ImageFetchError, "http"):
                prepare_recipe_image("www.example.com/photo.jpg")
            stream.assert_not_called()

    def test_a_web_page_is_rejected(self):
        with patch("services.image_check.httpx.stream", return_value=_stream(content_type="text/html")):
            with self.assertRaisesRegex(ImageFetchError, "isn't a direct image"):
                prepare_recipe_image(JPG)

    def test_network_errors_fall_back_to_saving_the_link(self):
        with patch("services.image_check.httpx.stream", side_effect=httpx.ConnectTimeout("slow")):
            prepared = prepare_recipe_image(JPG)
        self.assertEqual(prepared.image_url, JPG)
        self.assertIsNone(prepared.data)
        self.assertIn("saved the link instead", prepared.note)


if __name__ == "__main__":
    unittest.main()
