import hashlib
from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageStat

import starskill
import starskill.public_data_fetcher as fetcher
import starskill.schemas as schemas


def make_jpeg(width: int = 512, height: int = 512) -> bytes:
    image = Image.new("RGB", (width, height), "#101820")
    draw = ImageDraw.Draw(image)
    draw.ellipse((120, 90, 390, 410), fill="#d9e5f2")
    draw.ellipse((190, 150, 330, 350), fill="#486581")
    output = BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


class StaticImageBackend:
    def __init__(self, content: bytes | None = None, content_type: str = "image/jpeg") -> None:
        self.content = content or make_jpeg()
        self.content_type = content_type
        self.call_count = 0
        self.last_url = ""
        self.last_timeout = 0
        self.last_max_bytes = 0

    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> tuple[bytes, str]:
        self.call_count += 1
        self.last_url = url
        self.last_timeout = timeout_seconds
        self.last_max_bytes = max_bytes
        return self.content, self.content_type


class MissingImageBackend(StaticImageBackend):
    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> tuple[bytes, str]:
        raise fetcher.PublicDataNotFoundError("no SDSS cutout")


def make_request(max_bytes: int = 5_000_000) -> "schemas.SDSSImageRequest":
    return schemas.SDSSImageRequest(max_bytes=max_bytes)


def test_fetch_sdss_image_is_bounded_cached_and_auditable(tmp_path) -> None:
    assert hasattr(schemas, "SDSSImageRequest"), "SDSS image request schema is missing"
    assert hasattr(starskill, "fetch_sdss_image"), "SDSS image fetcher is missing"
    backend = StaticImageBackend()
    cache_dir = tmp_path / "cache"

    first = starskill.fetch_sdss_image(
        make_request(),
        cache_dir=cache_dir,
        source_path=tmp_path / "first" / "m51_sdss.jpg",
        display_path=tmp_path / "first" / "m51_display.png",
        backend=backend,
    )
    second = starskill.fetch_sdss_image(
        make_request(),
        cache_dir=cache_dir,
        source_path=tmp_path / "second" / "m51_sdss.jpg",
        display_path=tmp_path / "second" / "m51_display.png",
        backend=backend,
    )

    assert backend.call_count == 1
    assert backend.last_timeout == 30
    assert backend.last_max_bytes == 5_000_000
    assert backend.last_url.startswith(
        "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg?"
    )
    assert "ra=202.4696" in backend.last_url
    assert "dec=47.1952" in backend.last_url
    assert first.source.from_cache is False
    assert second.source.from_cache is True
    assert first.source.expected_count == 1
    assert first.source.retrieved_count == 1
    assert first.source.authentication == "none"
    assert first.source.sha256 == hashlib.sha256(backend.content).hexdigest()
    assert first.processing_steps == [
        "validate_jpeg_512x512",
        "center_crop_512x512",
        "autocontrast_cutoff_0.5_percent",
        "annotate_60_arcsec_scale_and_source",
    ]
    with Image.open(first.display_path) as display:
        assert display.size == (512, 576)
        assert max(ImageStat.Stat(display.convert("RGB")).stddev) > 20


def test_fetch_sdss_image_rejects_response_over_size_limit(tmp_path) -> None:
    backend = StaticImageBackend(content=make_jpeg())

    with pytest.raises(Exception) as exc_info:
        starskill.fetch_sdss_image(
            make_request(max_bytes=100),
            cache_dir=tmp_path / "cache",
            source_path=tmp_path / "m51.jpg",
            display_path=tmp_path / "m51.png",
            backend=backend,
        )

    assert getattr(exc_info.value, "code", None) == "public_data_size_limit"
    assert not (tmp_path / "m51.jpg").exists()
    assert not (tmp_path / "m51.png").exists()


def test_fetch_sdss_image_rejects_untrusted_non_jpeg_payload(tmp_path) -> None:
    backend = StaticImageBackend(
        content=b"<html>service error</html>",
        content_type="image/jpeg",
    )

    with pytest.raises(Exception) as exc_info:
        starskill.fetch_sdss_image(
            make_request(),
            cache_dir=tmp_path / "cache",
            source_path=tmp_path / "m51.jpg",
            display_path=tmp_path / "m51.png",
            backend=backend,
        )

    assert getattr(exc_info.value, "code", None) == "public_data_invalid_image"
    assert not (tmp_path / "m51.jpg").exists()
    assert not (tmp_path / "m51.png").exists()


def test_fetch_sdss_image_reports_no_data_without_fake_files(tmp_path) -> None:
    with pytest.raises(fetcher.PublicDataNotFoundError):
        starskill.fetch_sdss_image(
            make_request(),
            cache_dir=tmp_path / "cache",
            source_path=tmp_path / "m51.jpg",
            display_path=tmp_path / "m51.png",
            backend=MissingImageBackend(),
        )

    assert not (tmp_path / "m51.jpg").exists()
    assert not (tmp_path / "m51.png").exists()
