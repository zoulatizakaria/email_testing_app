"""Utilities for making HTML emails Outlook-friendly.

This module rewrites supported <img src=...> values to cid: references and
attaches the underlying image bytes as related MIME parts. It supports both
data: URIs and public http(s) image URLs.
"""

from __future__ import annotations

import base64
import binascii
import email.policy
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.core.mail import EmailMultiAlternatives


IMG_SRC_PATTERN = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=)(?P<quote>["\'])(?P<src>[^"\']+)(?P=quote)',
    re.IGNORECASE | re.DOTALL,
)

DATA_URI_PATTERN = re.compile(
    r"^data:(?P<mime>image/(?P<subtype>[a-zA-Z0-9.+-]+));base64,(?P<data>.+)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class InlineImage:
    content_id: str
    content: bytes
    subtype: str


@dataclass(frozen=True, slots=True)
class FileAttachment:
    filename: str
    content: bytes
    mimetype: str


def _normalize_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    normalized = content_type.split(";", 1)[0].strip().lower()
    return normalized or None


def _decode_data_uri(src: str) -> tuple[bytes, str] | None:
    match = DATA_URI_PATTERN.match(src)
    if match is None:
        return None

    raw_base64 = re.sub(r"\s+", "", match.group("data"))

    try:
        image_bytes = base64.b64decode(raw_base64, validate=True)
    except (binascii.Error, ValueError):
        return None

    return image_bytes, match.group("subtype").lower()


def _fetch_remote_image(src: str) -> tuple[bytes, str] | None:
    request = Request(
        src,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/*,*/*;q=0.8",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            image_bytes = response.read()
            header_type = _normalize_content_type(response.headers.get("Content-Type"))

            if header_type and header_type.startswith("image/"):
                return image_bytes, header_type.split("/", 1)[1]

            guessed_type, _ = mimetypes.guess_type(urlparse(response.geturl()).path)
            if guessed_type and guessed_type.startswith("image/"):
                return image_bytes, guessed_type.split("/", 1)[1].lower()
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None

    if b"<svg" in image_bytes[:512].lower():
        return image_bytes, "svg+xml"

    return None


def _load_inline_image(src: str) -> InlineImage | None:
    normalized_src = unescape(src.strip())

    if normalized_src.startswith("data:"):
        decoded = _decode_data_uri(normalized_src)
    elif normalized_src.startswith(("http://", "https://", "//")):
        remote_src = normalized_src if not normalized_src.startswith("//") else f"https:{normalized_src}"
        decoded = _fetch_remote_image(remote_src)
    else:
        return None

    if decoded is None:
        return None

    image_bytes, subtype = decoded
    digest = hashlib.sha1(image_bytes).hexdigest()
    content_id = f"inline-{digest}@mail.local"
    return InlineImage(content_id=content_id, content=image_bytes, subtype=subtype)


def inline_image_sources(html_text: str) -> tuple[str, list[InlineImage]]:
    """Replace supported image sources with Content-ID references."""

    images_by_id: dict[str, InlineImage] = {}
    ordered_images: list[InlineImage] = []
    source_cache: dict[str, InlineImage | None] = {}

    def replace(match: re.Match[str]) -> str:
        source = unescape(match.group("src").strip())

        if source not in source_cache:
            source_cache[source] = _load_inline_image(source)

        inline_image = source_cache[source]
        if inline_image is None:
            return match.group(0)

        if inline_image.content_id not in images_by_id:
            images_by_id[inline_image.content_id] = inline_image
            ordered_images.append(inline_image)

        quote = match.group("quote")
        return f'{match.group(1)}{quote}cid:{inline_image.content_id}{quote}'

    return IMG_SRC_PATTERN.sub(replace, html_text), ordered_images


def inline_base64_images(html_text: str) -> tuple[str, list[InlineImage]]:
    """Backward-compatible wrapper that now handles all supported image sources."""

    return inline_image_sources(html_text)


def load_image_attachments(paths: list[str]) -> list[FileAttachment]:
    """Load local image files so they can be attached to outgoing emails."""

    attachments: list[FileAttachment] = []

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Attachment file not found: {path}")

        mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        attachments.append(
            FileAttachment(
                filename=path.name,
                content=path.read_bytes(),
                mimetype=mimetype,
            )
        )

    return attachments


class InlineImageEmailMultiAlternatives(EmailMultiAlternatives):
    """EmailMultiAlternatives with inline image support."""

    def __init__(self, *args, inline_images=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.inline_images = list(inline_images or [])

    def message(self, *, policy=email.policy.default):
        msg = super().message(policy=policy)
        html_part = msg.get_body(("html",))

        if html_part is None or not self.inline_images:
            return msg

        # Keep the HTML body in a multipart/related container so Outlook sees
        # the images as inline parts instead of blocked remote resources.
        for image in self.inline_images:
            html_part.add_related(
                image.content,
                maintype="image",
                subtype=image.subtype,
                cid=f"<{image.content_id}>",
            )

        return msg
