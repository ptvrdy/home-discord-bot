"""Download a recipe image so /fix_image can attach the bytes to the recipe
card itself, instead of asking Discord to hotlink an outside URL (which many
sites block, leaving a card with no picture and no error). Split like
nyt_fallback.py: pure helpers (unit tested) plus a thin network wrapper."""

import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from services.embed import ATTACHMENT_PREFIX, mirrored_image_filename
from services.image_layout import dimensions_need_thumbnail

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

_EXTENSION_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_UNTYPED = ("", "application/octet-stream", "binary/octet-stream")

# Some hosts only serve their images to what looks like a link-preview
# fetcher, so identify the way Discord's own embed fetcher does.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"}


class ImageFetchError(Exception):
    """A problem with an image link, worded for the person who pasted it.
    `fallback_to_link` marks failures that are ambiguous (the site may just
    be blocking *us*), where the caller can still save the link as-is."""

    def __init__(self, message: str, fallback_to_link: bool = False):
        super().__init__(message)
        self.message = message
        self.fallback_to_link = fallback_to_link


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def classify_image_response(url: str, status_code: int, content_type: str | None) -> str | None:
    """Return a plain-English problem with `url` given how the server
    answered, or None if it looks like a usable direct image link. Only
    definitive failures are reported - anything ambiguous (e.g. a 403 that
    might just be blocking us) passes."""
    if status_code in (404, 410):
        return f"That link is broken (the site says it doesn't exist, HTTP {status_code})."
    if status_code >= 400:
        return None  # can't tell - might be blocking us

    media_type = _media_type(content_type)
    if media_type.startswith("image/"):
        return None
    if media_type in _UNTYPED and urlparse(url).path.lower().endswith(IMAGE_EXTENSIONS):
        return None  # untyped download, but the URL itself says it's an image
    return (
        f"That link isn't a direct image (it returned `{media_type or 'unknown'}`). "
        "Right-click the picture and choose **Copy image address**, then paste that."
    )


def image_extension(content_type: str | None, name: str) -> str | None:
    """A file extension (".jpg", ".png", ".gif", ".webp") for an image of this
    content type / file name, or None if it isn't a format Discord will show
    inline (e.g. SVG or AVIF)."""
    media_type = _media_type(content_type)
    if media_type in _EXTENSION_BY_TYPE:
        return _EXTENSION_BY_TYPE[media_type]
    suffix = PurePosixPath(urlparse(name).path).suffix.lower()
    if media_type in _UNTYPED and suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    return None


@dataclass
class PreparedImage:
    """What /fix_image should save and show for a pasted link."""

    image_url: str            # stored on the recipe: "attachment://..." or the link itself
    data: bytes | None = None  # attach these bytes to the card, as `filename`
    filename: str | None = None
    note: str | None = None    # extra word for the person, e.g. why it's only linked


def prepare_recipe_image(url: str) -> PreparedImage:
    """Download a pasted image so it can live on the recipe card itself
    (immune to the site later moving it or blocking Discord), with its
    thumbnail-vs-banner layout decided from the real dimensions.

    Raises ImageFetchError for definite problems (a page instead of an
    image, a dead link, too big, unsupported format). If the site merely
    won't let *us* download it, falls back to saving the link as-is."""
    try:
        data, extension = fetch_image(url)
    except ImageFetchError as error:
        if not error.fallback_to_link:
            raise
        return PreparedImage(
            image_url=url,
            note=f"{error.message} I saved the link instead — Discord may still be able to show it.",
        )

    filename = mirrored_image_filename(extension, dimensions_need_thumbnail(data))
    return PreparedImage(image_url=ATTACHMENT_PREFIX + filename, data=data, filename=filename)


def fetch_image(url: str, max_bytes: int = DEFAULT_MAX_IMAGE_BYTES) -> tuple[bytes, str]:
    """Download `url` and return (image bytes, extension). Raises
    ImageFetchError with a user-facing message otherwise."""
    if urlparse(url).scheme not in ("http", "https"):
        raise ImageFetchError("That doesn't look like a web link — it needs to start with http:// or https://.")

    try:
        with httpx.stream("GET", url, headers=_HEADERS, follow_redirects=True, timeout=10.0) as response:
            problem = classify_image_response(url, response.status_code, response.headers.get("content-type"))
            if problem:
                raise ImageFetchError(problem)
            if response.status_code >= 400:
                raise ImageFetchError(
                    f"The site wouldn't let me download that image (HTTP {response.status_code}).",
                    fallback_to_link=True,
                )

            extension = image_extension(response.headers.get("content-type"), url)
            if extension is None:
                raise ImageFetchError("That image format isn't supported — use a JPG, PNG, GIF, or WebP.")

            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ImageFetchError(f"That image is too large (over {max_bytes // (1024 * 1024)} MB).")
                chunks.append(chunk)
    except httpx.HTTPError as error:
        LOGGER.warning("Couldn't download image %s: %s", url, error)
        raise ImageFetchError("I couldn't download that link.", fallback_to_link=True) from error

    return b"".join(chunks), extension
