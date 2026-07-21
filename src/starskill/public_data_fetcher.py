"""Fetch and process one bounded SDSS DR18 image cutout."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from starskill.schemas import (
    PublicImageResult,
    SDSSImageRequest,
    SDSSImageSource,
)


SDSS_ENDPOINT = "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg"
PROCESSING_STEPS = [
    "validate_jpeg_512x512",
    "center_crop_512x512",
    "autocontrast_cutoff_0.5_percent",
    "annotate_60_arcsec_scale_and_source",
]


class PublicDataError(RuntimeError):
    code = "public_data_error"


class PublicDataNotFoundError(PublicDataError):
    code = "public_data_not_found"


class PublicDataServiceError(PublicDataError):
    code = "public_data_service_error"


class PublicDataSizeError(PublicDataError):
    code = "public_data_size_limit"


class PublicDataValidationError(PublicDataError):
    code = "public_data_invalid_image"


class ImageBackend(Protocol):
    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> tuple[bytes, str]: ...


class UrlImageBackend:
    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> tuple[bytes, str]:
        request = Request(
            url,
            headers={
                "Accept": "image/jpeg",
                "User-Agent": "StarSkill/0.1 (+educational astronomy workflow)",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise PublicDataSizeError("SDSS response exceeds the byte limit")
                content = response.read(max_bytes + 1)
                content_type = response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code == 404:
                raise PublicDataNotFoundError("SDSS returned no image") from exc
            raise PublicDataServiceError(f"SDSS HTTP error: {exc.code}") from exc
        except URLError as exc:
            raise PublicDataServiceError("SDSS image request failed") from exc
        if len(content) > max_bytes:
            raise PublicDataSizeError("SDSS response exceeds the byte limit")
        return content, content_type


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _query_parameters(request: SDSSImageRequest) -> dict[str, str | int | float]:
    return {
        "ra": request.ra_deg,
        "dec": request.dec_deg,
        "scale": request.scale_arcsec_per_pixel,
        "width": request.width,
        "height": request.height,
    }


def _source_url(request: SDSSImageRequest) -> str:
    return f"{SDSS_ENDPOINT}?{urlencode(_query_parameters(request))}"


def _validate_image(content: bytes, request: SDSSImageRequest) -> None:
    if len(content) > request.max_bytes:
        raise PublicDataSizeError("SDSS response exceeds the byte limit")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != "JPEG":
                raise PublicDataValidationError("SDSS response is not JPEG data")
            if image.size != (request.width, request.height):
                raise PublicDataValidationError(
                    "SDSS image dimensions do not match the request"
                )
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise PublicDataValidationError("SDSS response is not a valid JPEG") from exc


def _render_display(
    content: bytes,
    output_path: Path,
    request: SDSSImageRequest,
) -> None:
    with Image.open(BytesIO(content)) as source:
        image = source.convert("RGB")
    side = min(image.size)
    left = (image.width - side) // 2
    top = (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = ImageOps.autocontrast(image, cutoff=0.5)

    footer_height = 64
    display = Image.new("RGB", (side, side + footer_height), "#0b1118")
    display.paste(image, (0, 0))
    draw = ImageDraw.Draw(display)
    scale_pixels = min(round(60 / request.scale_arcsec_per_pixel), side - 40)
    bar_start = 24
    bar_end = bar_start + scale_pixels
    bar_y = side + 22
    draw.line((bar_start, bar_y, bar_end, bar_y), fill="white", width=4)
    draw.line((bar_start, bar_y - 5, bar_start, bar_y + 5), fill="white", width=2)
    draw.line((bar_end, bar_y - 5, bar_end, bar_y + 5), fill="white", width=2)
    draw.text((bar_start, side + 34), "60 arcsec", fill="white")
    draw.text((side - 168, side + 24), "M51 | SDSS DR18", fill="white")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    display.save(output_path, format="PNG")


def fetch_sdss_image(
    request: SDSSImageRequest,
    *,
    cache_dir: Path,
    source_path: Path,
    display_path: Path,
    backend: ImageBackend | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> PublicImageResult:
    """Fetch one validated cutout, cache it, and create a traceable display."""
    backend = backend or UrlImageBackend()
    source_url = _source_url(request)
    cache_key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
    cache_image_path = cache_dir / f"{cache_key}.jpg"
    cache_metadata_path = cache_dir / f"{cache_key}.json"

    content: bytes | None = None
    source: SDSSImageSource | None = None
    if cache_image_path.exists() and cache_metadata_path.exists():
        try:
            cached_content = cache_image_path.read_bytes()
            cached_source = SDSSImageSource.model_validate_json(
                cache_metadata_path.read_text(encoding="utf-8")
            )
            _validate_image(cached_content, request)
            if hashlib.sha256(cached_content).hexdigest() != cached_source.sha256:
                raise PublicDataValidationError("cached SDSS image hash mismatch")
        except (OSError, ValueError, PublicDataError):
            pass
        else:
            content = cached_content
            source = cached_source.model_copy(update={"from_cache": True})

    if content is None or source is None:
        content, content_type = backend.fetch(
            source_url,
            timeout_seconds=request.timeout_seconds,
            max_bytes=request.max_bytes,
        )
        if len(content) > request.max_bytes:
            raise PublicDataSizeError("SDSS response exceeds the byte limit")
        if content_type.split(";", 1)[0].strip().lower() != "image/jpeg":
            raise PublicDataValidationError("SDSS response content type is not JPEG")
        _validate_image(content, request)
        source = SDSSImageSource(
            endpoint=SDSS_ENDPOINT,
            source_url=source_url,
            accessed_at=clock(),
            from_cache=False,
            query_parameters=_query_parameters(request),
            content_type="image/jpeg",
            bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            pixel_scale_arcsec=request.scale_arcsec_per_pixel,
            wavebands=["SDSS optical color composite"],
            license_notice=(
                "Use and acknowledge under the SDSS image-use policy: "
                "https://www.sdss.org/science/image-gallery/"
            ),
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_image_path.write_bytes(content)
        cache_metadata_path.write_text(source.model_dump_json(indent=2), encoding="utf-8")

    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(content)
    _render_display(content, display_path, request)
    return PublicImageResult(
        request=request,
        source=source,
        source_path=str(source_path),
        display_path=str(display_path),
        processing_steps=PROCESSING_STEPS,
    )


def write_public_image_metadata(result: PublicImageResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_root = output_path.parent.resolve()
    payload = result.model_dump(mode="json")
    for field in ("source_path", "display_path"):
        value = Path(payload[field])
        try:
            payload[field] = value.resolve().relative_to(output_root).as_posix()
        except ValueError:
            raise PublicDataValidationError(
                f"{field} must be located under the metadata output directory"
            )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
