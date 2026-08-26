"""Discovery adapters for the registered trusted astronomy image archives."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from starskill.schemas import (
    AstronomyImageSearchRequest,
    ImageCandidate,
    ImageDiscoveryProvenance,
    ImageProviderDescriptor,
    ImageSearchResult,
    ImageTrustDecision,
    ResolvedImageTarget,
)


MAX_CANDIDATES_PER_PROVIDER = 8
PS1_PIXEL_SCALE_ARCSEC = 0.25
SDSS_MAX_CUTOUT_PIXELS = 2048
SDSS_MIN_SCALE_ARCSEC = 0.015
SDSS_MAX_SCALE_ARCSEC = 60.0

_PS1_STACK_FILTERS = ("g", "r", "i", "z", "y")
_PS1_FILENAME_PATTERN = re.compile(r"^/?[A-Za-z0-9][A-Za-z0-9/._-]*\.fits$")
_MAST_JPEG_URI_PATTERN = re.compile(
    r"^mast:[A-Za-z0-9][A-Za-z0-9/._+-]*\.(?:jpg|jpeg|png)$", re.IGNORECASE
)
_CANDIDATE_ID_SANITIZER = re.compile(r"[^A-Za-z0-9_.:-]+")


class ImageDiscoveryError(RuntimeError):
    code = "image_discovery_error"


class ImageDiscoveryNotFoundError(ImageDiscoveryError):
    code = "image_discovery_no_data"


class ImageDiscoveryServiceError(ImageDiscoveryError):
    code = "image_discovery_service_error"


class ImageDiscoverySizeError(ImageDiscoveryError):
    code = "image_discovery_size_limit"


class ImageDiscoveryValidationError(ImageDiscoveryError):
    code = "image_discovery_invalid_response"


class ImageDiscoveryUrlError(ImageDiscoveryError):
    code = "image_discovery_untrusted_url"


class MetadataBackend(Protocol):
    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> tuple[bytes, str]: ...


class UrlMetadataBackend:
    def __init__(self, accept: str = "*/*") -> None:
        self.accept = accept

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
                "Accept": self.accept,
                "User-Agent": "StarSkill/0.1 (+educational astronomy workflow)",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise ImageDiscoverySizeError(
                        "archive metadata response exceeds the byte limit"
                    )
                content = response.read(max_bytes + 1)
                content_type = response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code == 404:
                raise ImageDiscoveryNotFoundError(
                    "archive metadata endpoint returned no data"
                ) from exc
            raise ImageDiscoveryServiceError(
                f"archive metadata HTTP error: {exc.code}"
            ) from exc
        except URLError as exc:
            raise ImageDiscoveryServiceError(
                "archive metadata request failed"
            ) from exc
        if len(content) > max_bytes:
            raise ImageDiscoverySizeError(
                "archive metadata response exceeds the byte limit"
            )
        return content, content_type


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _url_matches_root(url: str, root: str) -> bool:
    if root.endswith("/"):
        return url.startswith(root)
    return url == root or url.startswith(root + "?") or url.startswith(root + "/")


def require_provider_url(url: str, descriptor: ImageProviderDescriptor) -> str:
    """Accept a URL only when the registered descriptor explicitly trusts it."""
    normalized = url.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise ImageDiscoveryUrlError(
            f"{descriptor.provider_id} URL must be plain HTTPS without credentials"
        )
    if parsed.hostname.casefold() not in descriptor.allowed_hosts:
        raise ImageDiscoveryUrlError(
            f"{descriptor.provider_id} URL host is not in the trusted allowlist"
        )
    if not any(_url_matches_root(normalized, root) for root in descriptor.endpoint_roots):
        raise ImageDiscoveryUrlError(
            f"{descriptor.provider_id} URL is outside the registered endpoint roots"
        )
    return normalized


def _normalized_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def _sanitize_candidate_id(provider_prefix: str, raw: str) -> str:
    cleaned = _CANDIDATE_ID_SANITIZER.sub("-", raw).strip("-.:_")
    if not cleaned:
        cleaned = "candidate"
    return f"{provider_prefix}-{cleaned}"[:128]


@dataclass(frozen=True)
class ImageDiscovery:
    """One provider's candidate list with the query evidence that produced it."""

    candidates: list[ImageCandidate]
    provenance: ImageDiscoveryProvenance


class ImageProvider(Protocol):
    descriptor: ImageProviderDescriptor

    def discover(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> list[ImageCandidate]: ...


class _DiscoveryAdapter:
    """Shared bounded fetch, cache, and provenance mechanics for one archive."""

    def __init__(
        self,
        descriptor: ImageProviderDescriptor,
        *,
        backend: MetadataBackend | None = None,
        cache_dir: Path | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.descriptor = descriptor
        self.backend = backend
        self.cache_dir = cache_dir
        self.clock = clock

    accept_header = "*/*"
    expected_content_type = "text/plain"

    def discover(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> list[ImageCandidate]:
        return self.discover_with_provenance(request, target).candidates

    def discover_with_provenance(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> ImageDiscovery:
        raise NotImplementedError

    def _offline_provenance(
        self, endpoint: str, source_url: str, candidate_count: int
    ) -> ImageDiscoveryProvenance:
        return ImageDiscoveryProvenance(
            provider_id=self.descriptor.provider_id,
            endpoint=endpoint,
            source_url=source_url,
            accessed_at=self.clock(),
            network_used=False,
            from_cache=False,
            candidate_count=candidate_count,
        )

    def _fetch_document(
        self,
        source_url: str,
        request: AstronomyImageSearchRequest,
        endpoint: str,
    ) -> tuple[bytes, ImageDiscoveryProvenance]:
        source_url = require_provider_url(source_url, self.descriptor)
        endpoint = require_provider_url(endpoint, self.descriptor)
        max_bytes = min(request.max_bytes, self.descriptor.max_bytes)

        cached = self._read_cache(source_url)
        if cached is not None:
            return cached

        backend = self.backend or UrlMetadataBackend(accept=self.accept_header)
        content, content_type = backend.fetch(
            source_url,
            timeout_seconds=request.timeout_seconds,
            max_bytes=max_bytes,
        )
        if len(content) > max_bytes:
            raise ImageDiscoverySizeError(
                f"{self.descriptor.provider_id} metadata response exceeds the byte limit"
            )
        if _normalized_content_type(content_type) != self.expected_content_type:
            raise ImageDiscoveryValidationError(
                f"{self.descriptor.provider_id} metadata content type is not "
                f"{self.expected_content_type}"
            )
        provenance = ImageDiscoveryProvenance(
            provider_id=self.descriptor.provider_id,
            endpoint=endpoint,
            source_url=source_url,
            accessed_at=self.clock(),
            network_used=True,
            from_cache=False,
            content_type=self.expected_content_type,
            bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            candidate_count=0,
        )
        self._write_cache(source_url, content, provenance)
        return content, provenance

    def _cache_paths(self, source_url: str) -> tuple[Path, Path] | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        provider_dir = self.cache_dir / self.descriptor.provider_id
        return provider_dir / f"{key}.body", provider_dir / f"{key}.json"

    def _read_cache(
        self, source_url: str
    ) -> tuple[bytes, ImageDiscoveryProvenance] | None:
        paths = self._cache_paths(source_url)
        if paths is None:
            return None
        body_path, metadata_path = paths
        if not body_path.exists() or not metadata_path.exists():
            return None
        try:
            content = body_path.read_bytes()
            stored = ImageDiscoveryProvenance.model_validate_json(
                metadata_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if (
            stored.provider_id != self.descriptor.provider_id
            or stored.source_url != source_url
            or stored.sha256 != hashlib.sha256(content).hexdigest()
        ):
            return None
        return content, stored.model_copy(update={"from_cache": True})

    def _write_cache(
        self,
        source_url: str,
        content: bytes,
        provenance: ImageDiscoveryProvenance,
    ) -> None:
        paths = self._cache_paths(source_url)
        if paths is None:
            return
        body_path, metadata_path = paths
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(content)
        metadata_path.write_text(provenance.model_dump_json(indent=2), encoding="utf-8")


class PanStarrsImageProvider(_DiscoveryAdapter):
    """Two-step ps1filenames.py table lookup then fitscut.cgi cutout URLs."""

    accept_header = "text/plain"
    expected_content_type = "text/plain"

    @property
    def _root(self) -> str:
        return self.descriptor.endpoint_roots[0]

    def discover_with_provenance(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> ImageDiscovery:
        endpoint = f"{self._root}ps1filenames.py"
        requested_bands = {band.strip().casefold() for band in request.bands}
        selected = [
            band
            for band in _PS1_STACK_FILTERS
            if not requested_bands or band in requested_bands
        ]
        if not selected or "jpeg" not in request.allowed_formats:
            source_url = f"{endpoint}?{urlencode({'ra': target.ra_deg, 'dec': target.dec_deg})}"
            return ImageDiscovery([], self._offline_provenance(endpoint, source_url, 0))

        source_url = endpoint + "?" + urlencode(
            {
                "ra": target.ra_deg,
                "dec": target.dec_deg,
                "filters": "".join(selected),
            }
        )
        content, provenance = self._fetch_document(source_url, request, endpoint)
        stack_files = self._parse_filename_table(content, selected)

        pixels = round(request.field_of_view_arcmin * 60 / PS1_PIXEL_SCALE_ARCSEC)
        pixels = max(64, min(pixels, request.max_width, request.max_height))
        candidates = [
            self._cutout_candidate(
                candidate_id=f"panstarrs-stack-{band}",
                band=band,
                target=target,
                pixels=pixels,
                source_url=source_url,
                channels={"red": stack_files[band]},
            )
            for band in _PS1_STACK_FILTERS
            if band in stack_files
        ]
        if len(stack_files) >= 3:
            ordered = [band for band in _PS1_STACK_FILTERS if band in stack_files]
            candidates.insert(
                0,
                self._cutout_candidate(
                    candidate_id="panstarrs-stack-color",
                    band="".join(ordered),
                    target=target,
                    pixels=pixels,
                    source_url=source_url,
                    channels={
                        "red": stack_files[ordered[-1]],
                        "green": stack_files[ordered[len(ordered) // 2]],
                        "blue": stack_files[ordered[0]],
                    },
                ),
            )
        candidates = candidates[:MAX_CANDIDATES_PER_PROVIDER]
        return ImageDiscovery(
            candidates,
            provenance.model_copy(update={"candidate_count": len(candidates)}),
        )

    def _parse_filename_table(
        self, content: bytes, selected: list[str]
    ) -> dict[str, str]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ImageDiscoveryValidationError(
                "Pan-STARRS filename table is not UTF-8 text"
            ) from exc
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            raise ImageDiscoveryValidationError(
                "Pan-STARRS filename table is empty"
            )
        header = lines[0].split()
        try:
            filename_index = header.index("filename")
            filter_index = header.index("filter")
        except ValueError as exc:
            raise ImageDiscoveryValidationError(
                "Pan-STARRS filename table header is missing required columns"
            ) from exc

        stack_files: dict[str, str] = {}
        for line in lines[1:]:
            row = line.split()
            if len(row) != len(header):
                raise ImageDiscoveryValidationError(
                    "Pan-STARRS filename table row width does not match the header"
                )
            band = row[filter_index].casefold()
            filename = row[filename_index]
            if band not in selected or ".." in filename or not _PS1_FILENAME_PATTERN.fullmatch(filename):
                raise ImageDiscoveryValidationError(
                    "Pan-STARRS filename table row failed validation"
                )
            stack_files.setdefault(band, filename)
        return stack_files

    def _cutout_candidate(
        self,
        *,
        candidate_id: str,
        band: str,
        target: ResolvedImageTarget,
        pixels: int,
        source_url: str,
        channels: dict[str, str],
    ) -> ImageCandidate:
        parameters: dict[str, str | int | float] = {
            "ra": target.ra_deg,
            "dec": target.dec_deg,
            "size": pixels,
            "format": "jpeg",
        }
        parameters.update(channels)
        download_url = require_provider_url(
            f"{self._root}fitscut.cgi?{urlencode(parameters)}", self.descriptor
        )
        return ImageCandidate(
            candidate_id=candidate_id,
            provider_id=self.descriptor.provider_id,
            source_url=source_url,
            download_url=download_url,
            band=band,
            format="jpeg",
            width=pixels,
            height=pixels,
            query_parameters=parameters,
            license_url=self.descriptor.license_url,
        )


class SdssDr18ImageProvider(_DiscoveryAdapter):
    """Deterministic offline SkyServer getjpeg cutout URL construction."""

    def discover_with_provenance(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> ImageDiscovery:
        endpoint = f"{self.descriptor.endpoint_roots[0]}/getjpeg"
        if "jpeg" not in request.allowed_formats:
            return ImageDiscovery([], self._offline_provenance(endpoint, endpoint, 0))

        pixels = min(request.max_width, request.max_height, SDSS_MAX_CUTOUT_PIXELS)
        scale = request.field_of_view_arcmin * 60 / pixels
        scale = round(
            min(max(scale, SDSS_MIN_SCALE_ARCSEC), SDSS_MAX_SCALE_ARCSEC), 6
        )
        parameters: dict[str, str | int | float] = {
            "ra": target.ra_deg,
            "dec": target.dec_deg,
            "scale": scale,
            "width": pixels,
            "height": pixels,
        }
        download_url = require_provider_url(
            f"{endpoint}?{urlencode(parameters)}", self.descriptor
        )
        candidate = ImageCandidate(
            candidate_id="sdss-dr18-color",
            provider_id=self.descriptor.provider_id,
            source_url=download_url,
            download_url=download_url,
            band="gri",
            format="jpeg",
            width=pixels,
            height=pixels,
            query_parameters=parameters,
            license_url=self.descriptor.license_url,
        )
        return ImageDiscovery(
            [candidate], self._offline_provenance(endpoint, download_url, 1)
        )


class MastImageProvider(_DiscoveryAdapter):
    """Mast.Caom.Cone metadata query then Download/file preview URLs."""

    accept_header = "application/json"
    expected_content_type = "application/json"

    def discover_with_provenance(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> ImageDiscovery:
        invoke_root = next(
            root
            for root in self.descriptor.endpoint_roots
            if root.endswith("/invoke")
        )
        download_root = next(
            root for root in self.descriptor.endpoint_roots if root.endswith("/v0.1/")
        )
        radius_deg = min(max(request.field_of_view_arcmin / 120, 0.001), 1.0)
        service_request = {
            "service": "Mast.Caom.Cone",
            "params": {
                "ra": target.ra_deg,
                "dec": target.dec_deg,
                "radius": round(radius_deg, 6),
            },
            "format": "json",
            "pagesize": 50,
            "page": 1,
        }
        source_url = invoke_root + "?" + urlencode(
            {"request": json.dumps(service_request, separators=(",", ":"))}
        )
        content, provenance = self._fetch_document(source_url, request, invoke_root)
        payload = self._parse_json_object(content)
        if payload.get("status") != "COMPLETE":
            raise ImageDiscoveryServiceError(
                "MAST cone search did not complete"
            )
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ImageDiscoveryValidationError(
                "MAST cone search response has no data table"
            )

        candidates: list[ImageCandidate] = []
        seen_ids: set[str] = set()
        for row in rows:
            candidate = self._row_candidate(row, source_url, download_root)
            if candidate is None or candidate.candidate_id in seen_ids:
                continue
            if candidate.format not in request.allowed_formats:
                continue
            seen_ids.add(candidate.candidate_id)
            candidates.append(candidate)
            if len(candidates) >= MAX_CANDIDATES_PER_PROVIDER:
                break
        return ImageDiscovery(
            candidates,
            provenance.model_copy(update={"candidate_count": len(candidates)}),
        )

    def _parse_json_object(self, content: bytes) -> dict[str, object]:
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImageDiscoveryValidationError(
                "MAST cone search response is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ImageDiscoveryValidationError(
                "MAST cone search response is not a JSON object"
            )
        return payload

    def _row_candidate(
        self, row: object, source_url: str, download_root: str
    ) -> ImageCandidate | None:
        if not isinstance(row, dict):
            return None
        jpeg_uri = row.get("jpegURL")
        if (
            row.get("dataproduct_type") != "image"
            or not isinstance(jpeg_uri, str)
            or not _MAST_JPEG_URI_PATTERN.fullmatch(jpeg_uri)
        ):
            return None
        try:
            download_url = require_provider_url(
                f"{download_root}Download/file?{urlencode({'uri': jpeg_uri})}",
                self.descriptor,
            )
        except ImageDiscoveryUrlError:
            return None
        obsid = row.get("obsid")
        obs_id = row.get("obs_id")
        raw_id = str(obsid) if obsid is not None else str(obs_id or "")
        band = row.get("filters")
        return ImageCandidate(
            candidate_id=_sanitize_candidate_id("mast", raw_id),
            provider_id=self.descriptor.provider_id,
            source_url=source_url,
            download_url=download_url,
            band=str(band)[:64] if band else None,
            format="png" if jpeg_uri.lower().endswith(".png") else "jpeg",
            query_parameters={"uri": jpeg_uri},
            license_url=self.descriptor.license_url,
        )


class EsaSkyImageProvider(_DiscoveryAdapter):
    """ESASky TAP cone search over HST observations with postcard previews."""

    accept_header = "application/json"
    expected_content_type = "application/json"

    _TABLE = "observations.mv_v_v_hst_mmi_observation_fdw_fdw"

    def discover_with_provenance(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> ImageDiscovery:
        tap_root = next(
            root
            for root in self.descriptor.endpoint_roots
            if root.endswith("/tap/")
        )
        endpoint = f"{tap_root}sync"
        radius_deg = min(max(request.field_of_view_arcmin / 120, 0.001), 1.0)
        adql = (
            "SELECT TOP 50 observation_id, instrument_name, filter, postcard_url "
            f"FROM {self._TABLE} WHERE 1=CONTAINS(POINT('ICRS', ra_deg, dec_deg), "
            f"CIRCLE('ICRS', {target.ra_deg:.6f}, {target.dec_deg:.6f}, "
            f"{radius_deg:.6f}))"
        )
        source_url = endpoint + "?" + urlencode(
            {
                "REQUEST": "doQuery",
                "LANG": "ADQL",
                "FORMAT": "json",
                "QUERY": adql,
            }
        )
        content, provenance = self._fetch_document(source_url, request, endpoint)
        rows = self._parse_tap_rows(content)

        candidates: list[ImageCandidate] = []
        seen_ids: set[str] = set()
        for row in rows:
            candidate = self._row_candidate(row, source_url)
            if candidate is None or candidate.candidate_id in seen_ids:
                continue
            if candidate.format not in request.allowed_formats:
                continue
            seen_ids.add(candidate.candidate_id)
            candidates.append(candidate)
            if len(candidates) >= MAX_CANDIDATES_PER_PROVIDER:
                break
        return ImageDiscovery(
            candidates,
            provenance.model_copy(update={"candidate_count": len(candidates)}),
        )

    def _parse_tap_rows(self, content: bytes) -> list[dict[str, object]]:
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImageDiscoveryValidationError(
                "ESASky TAP response is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ImageDiscoveryValidationError(
                "ESASky TAP response is not a JSON object"
            )
        metadata = payload.get("metadata")
        data = payload.get("data")
        if not isinstance(metadata, list) or not isinstance(data, list):
            raise ImageDiscoveryValidationError(
                "ESASky TAP response is missing metadata or data sections"
            )
        names = [
            column.get("name") if isinstance(column, dict) else None
            for column in metadata
        ]
        if any(not isinstance(name, str) for name in names):
            raise ImageDiscoveryValidationError(
                "ESASky TAP response metadata is malformed"
            )
        rows: list[dict[str, object]] = []
        for values in data:
            if not isinstance(values, list) or len(values) != len(names):
                raise ImageDiscoveryValidationError(
                    "ESASky TAP response row width does not match its metadata"
                )
            rows.append(dict(zip(names, values, strict=True)))
        return rows

    def _row_candidate(
        self, row: dict[str, object], source_url: str
    ) -> ImageCandidate | None:
        postcard_url = row.get("postcard_url")
        observation_id = row.get("observation_id")
        if not isinstance(postcard_url, str) or not isinstance(observation_id, str):
            return None
        try:
            download_url = require_provider_url(postcard_url, self.descriptor)
        except ImageDiscoveryUrlError:
            return None
        band = row.get("filter")
        return ImageCandidate(
            candidate_id=_sanitize_candidate_id("esasky-hst", observation_id),
            provider_id=self.descriptor.provider_id,
            source_url=source_url,
            download_url=download_url,
            band=str(band)[:64] if band else None,
            format="jpeg",
            query_parameters={"observation_id": observation_id},
            license_url=self.descriptor.license_url,
        )


_PROVIDER_DESCRIPTORS: Mapping[str, ImageProviderDescriptor] = MappingProxyType(
    {
        "sdss_dr18": ImageProviderDescriptor(
            provider_id="sdss_dr18",
            organization="Sloan Digital Sky Survey",
            allowed_hosts=("skyserver.sdss.org",),
            allowed_redirect_hosts=("skyserver.sdss.org",),
            endpoint_roots=(
                "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout",
            ),
            formats=("jpeg",),
            max_bytes=20_000_000,
            license_url="https://www.sdss.org/science/image-gallery/",
        ),
        "mast": ImageProviderDescriptor(
            provider_id="mast",
            organization="Space Telescope Science Institute MAST",
            allowed_hosts=("mast.stsci.edu",),
            allowed_redirect_hosts=("mast.stsci.edu",),
            endpoint_roots=(
                "https://mast.stsci.edu/api/v0.1/",
                "https://mast.stsci.edu/api/v0/invoke",
            ),
            formats=("jpeg", "png", "fits"),
            max_bytes=50_000_000,
            license_url=(
                "https://archive.stsci.edu/missions-and-data/"
                "mission-acknowledgments"
            ),
        ),
        "esa_sky": ImageProviderDescriptor(
            provider_id="esa_sky",
            organization="European Space Agency ESA Sky",
            allowed_hosts=("sky.esa.int", "hst.esac.esa.int"),
            allowed_redirect_hosts=("sky.esa.int", "hst.esac.esa.int"),
            endpoint_roots=(
                "https://sky.esa.int/esasky-tap/tap/",
                "https://hst.esac.esa.int/tap-server/data",
            ),
            formats=("jpeg", "png", "fits"),
            max_bytes=50_000_000,
            license_url="https://www.cosmos.esa.int/web/esdc/esasky",
        ),
        "panstarrs": ImageProviderDescriptor(
            provider_id="panstarrs",
            organization="Pan-STARRS at Space Telescope Science Institute",
            allowed_hosts=("ps1images.stsci.edu",),
            allowed_redirect_hosts=("ps1images.stsci.edu",),
            endpoint_roots=("https://ps1images.stsci.edu/cgi-bin/",),
            formats=("jpeg", "png", "fits"),
            max_bytes=50_000_000,
            license_url="https://outerspace.stsci.edu/display/PANSTARRS/",
        ),
    }
)

_PROVIDER_ADAPTERS: Mapping[str, type[_DiscoveryAdapter]] = MappingProxyType(
    {
        "sdss_dr18": SdssDr18ImageProvider,
        "mast": MastImageProvider,
        "esa_sky": EsaSkyImageProvider,
        "panstarrs": PanStarrsImageProvider,
    }
)


def build_image_provider(
    provider_id: str,
    *,
    backend: MetadataBackend | None = None,
    cache_dir: Path | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> _DiscoveryAdapter:
    descriptor = _PROVIDER_DESCRIPTORS.get(provider_id)
    adapter = _PROVIDER_ADAPTERS.get(provider_id)
    if descriptor is None or adapter is None:
        raise ImageDiscoveryUrlError(f"unregistered image provider: {provider_id}")
    return adapter(descriptor, backend=backend, cache_dir=cache_dir, clock=clock)


IMAGE_PROVIDER_REGISTRY: Mapping[str, ImageProvider] = MappingProxyType(
    {provider_id: build_image_provider(provider_id) for provider_id in _PROVIDER_DESCRIPTORS}
)


def discover_image_candidates(
    request: AstronomyImageSearchRequest,
    target: ResolvedImageTarget,
    *,
    cache_dir: Path | None = None,
    backends: Mapping[str, MetadataBackend] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> ImageSearchResult:
    """Run the requested trusted providers and aggregate validated candidates.

    A named provider mode propagates that provider's structured error. The
    ``auto_trusted`` mode records each provider failure as a per-provider trust
    decision instead, so one degraded archive cannot hide the others.
    """
    if request.provider_mode == "auto_trusted":
        provider_ids = list(_PROVIDER_DESCRIPTORS)
    else:
        provider_ids = [request.provider_mode]

    candidates: list[ImageCandidate] = []
    decisions: dict[str, ImageTrustDecision] = {}
    provenance: list[ImageDiscoveryProvenance] = []
    for provider_id in provider_ids:
        provider = build_image_provider(
            provider_id,
            backend=(backends or {}).get(provider_id),
            cache_dir=cache_dir,
            clock=clock,
        )
        try:
            discovery = provider.discover_with_provenance(request, target)
        except ImageDiscoveryError as exc:
            if request.provider_mode != "auto_trusted":
                raise
            decisions[provider_id] = ImageTrustDecision(
                allowed=False, reason_code=exc.code
            )
            continue
        decisions[provider_id] = ImageTrustDecision(
            allowed=True, reason_code="discovery_ok"
        )
        candidates.extend(discovery.candidates)
        provenance.append(discovery.provenance)

    return ImageSearchResult(
        request=request,
        target=target,
        candidates=candidates,
        decisions=decisions,
        provenance=provenance,
    )
