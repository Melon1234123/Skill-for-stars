import hashlib
import json
from datetime import datetime, timezone

import pytest

import starskill
import starskill.image_providers as providers
from starskill.cli import main
from starskill.image_providers import (
    IMAGE_PROVIDER_REGISTRY,
    build_image_provider,
    discover_image_candidates,
    require_provider_url,
)
from starskill.schemas import (
    AstronomicalTargetSource,
    AstronomyImageSearchRequest,
    ImageSearchResult,
    ResolvedImageTarget,
)


PS1_TABLE = (
    "projcell subcell ra dec filter mjd type filename shortname badflag\n"
    "1164 67 83.8 -5.39 g 0.0 stack /rings.v3.skycell/1164/067/a.stk.g.unconv.fits a 0\n"
    "1164 67 83.8 -5.39 r 0.0 stack /rings.v3.skycell/1164/067/a.stk.r.unconv.fits a 0\n"
    "1164 67 83.8 -5.39 i 0.0 stack /rings.v3.skycell/1164/067/a.stk.i.unconv.fits a 0\n"
)


class StaticMetadataBackend:
    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
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


class FailingMetadataBackend:
    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> tuple[bytes, str]:
        raise providers.ImageDiscoveryServiceError("archive is unreachable")


def make_request(**overrides) -> AstronomyImageSearchRequest:
    payload = {
        "target": {
            "kind": "coordinates",
            "label": "M42",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
        },
        "provider_mode": "panstarrs",
    }
    payload.update(overrides)
    return AstronomyImageSearchRequest.model_validate(payload)


def make_target() -> ResolvedImageTarget:
    return ResolvedImageTarget(
        label="M42",
        ra_deg=83.822083,
        dec_deg=-5.391111,
        source=AstronomicalTargetSource(
            provider="input_coordinates",
            from_cache=False,
            accessed_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        ),
    )


def test_panstarrs_discovery_is_bounded_cached_and_auditable(tmp_path) -> None:
    backend = StaticMetadataBackend(PS1_TABLE.encode("utf-8"), "text/plain")
    cache_dir = tmp_path / "cache"
    provider = build_image_provider("panstarrs", backend=backend, cache_dir=cache_dir)

    first = provider.discover_with_provenance(make_request(), make_target())
    second = provider.discover_with_provenance(make_request(), make_target())

    assert backend.call_count == 1
    assert backend.last_timeout == 30
    assert backend.last_max_bytes == 20_000_000
    assert backend.last_url.startswith(
        "https://ps1images.stsci.edu/cgi-bin/ps1filenames.py?"
    )
    assert "filters=grizy" in backend.last_url
    assert first.provenance.from_cache is False
    assert first.provenance.network_used is True
    assert second.provenance.from_cache is True
    assert first.provenance.sha256 == hashlib.sha256(backend.content).hexdigest()
    assert first.provenance.candidate_count == len(first.candidates) == 4
    assert [candidate.candidate_id for candidate in first.candidates] == [
        "panstarrs-stack-color",
        "panstarrs-stack-g",
        "panstarrs-stack-r",
        "panstarrs-stack-i",
    ]
    descriptor = IMAGE_PROVIDER_REGISTRY["panstarrs"].descriptor
    for candidate in first.candidates:
        assert candidate.download_url.startswith(
            "https://ps1images.stsci.edu/cgi-bin/fitscut.cgi?"
        )
        assert candidate.format == "jpeg"
        assert candidate.width == candidate.height == 2048
        assert require_provider_url(candidate.download_url, descriptor)


def test_panstarrs_refetches_when_cached_body_is_tampered(tmp_path) -> None:
    backend = StaticMetadataBackend(PS1_TABLE.encode("utf-8"), "text/plain")
    cache_dir = tmp_path / "cache"
    provider = build_image_provider("panstarrs", backend=backend, cache_dir=cache_dir)

    provider.discover_with_provenance(make_request(), make_target())
    for body_path in (cache_dir / "panstarrs").glob("*.body"):
        body_path.write_bytes(b"tampered")
    refreshed = provider.discover_with_provenance(make_request(), make_target())

    assert backend.call_count == 2
    assert refreshed.provenance.from_cache is False


def test_panstarrs_rejects_untrusted_content_type(tmp_path) -> None:
    backend = StaticMetadataBackend(b"<html>error</html>", "text/html")
    provider = build_image_provider(
        "panstarrs", backend=backend, cache_dir=tmp_path / "cache"
    )

    with pytest.raises(providers.ImageDiscoveryValidationError) as exc_info:
        provider.discover(make_request(), make_target())

    assert exc_info.value.code == "image_discovery_invalid_response"
    assert not list((tmp_path / "cache").rglob("*"))


def test_panstarrs_rejects_response_over_size_limit() -> None:
    backend = StaticMetadataBackend(PS1_TABLE.encode("utf-8"), "text/plain")
    provider = build_image_provider("panstarrs", backend=backend)

    with pytest.raises(providers.ImageDiscoverySizeError) as exc_info:
        provider.discover(make_request(max_bytes=16), make_target())

    assert exc_info.value.code == "image_discovery_size_limit"


def test_panstarrs_rejects_traversal_filename() -> None:
    table = (
        "projcell subcell ra dec filter mjd type filename shortname badflag\n"
        "1164 67 83.8 -5.39 g 0.0 stack /rings/../../../etc/passwd.fits a 0\n"
    )
    backend = StaticMetadataBackend(table.encode("utf-8"), "text/plain")
    provider = build_image_provider("panstarrs", backend=backend)

    with pytest.raises(providers.ImageDiscoveryValidationError) as exc_info:
        provider.discover(make_request(), make_target())

    assert exc_info.value.code == "image_discovery_invalid_response"


def test_panstarrs_empty_table_yields_no_candidates_without_fake_data() -> None:
    header_only = "projcell subcell ra dec filter mjd type filename shortname badflag\n"
    backend = StaticMetadataBackend(header_only.encode("utf-8"), "text/plain")
    provider = build_image_provider("panstarrs", backend=backend)

    discovery = provider.discover_with_provenance(make_request(), make_target())

    assert discovery.candidates == []
    assert discovery.provenance.candidate_count == 0


def test_sdss_discovery_is_offline_and_deterministic() -> None:
    provider = build_image_provider("sdss_dr18", backend=FailingMetadataBackend())

    discovery = provider.discover_with_provenance(
        make_request(provider_mode="sdss_dr18"), make_target()
    )

    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.download_url.startswith(
        "https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg?"
    )
    assert candidate.query_parameters["width"] == 2048
    assert discovery.provenance.network_used is False
    assert discovery.provenance.sha256 is None


def test_mast_two_step_emits_only_trusted_mast_uri_previews() -> None:
    payload = {
        "status": "COMPLETE",
        "data": [
            {
                "dataproduct_type": "image",
                "obsid": 24800511,
                "obs_id": "hst_05390_02",
                "filters": "F547M",
                "jpegURL": "mast:HST/product/w1b70203t_c0f.jpg",
            },
            {
                "dataproduct_type": "image",
                "obsid": 999,
                "jpegURL": "https://evil.example.test/steal.jpg",
            },
            {"dataproduct_type": "spectrum", "obsid": 5, "jpegURL": "mast:HST/a.jpg"},
            {"dataproduct_type": "image", "obsid": 6, "jpegURL": None},
        ],
    }
    backend = StaticMetadataBackend(
        json.dumps(payload).encode("utf-8"), "application/json"
    )
    provider = build_image_provider("mast", backend=backend)

    discovery = provider.discover_with_provenance(
        make_request(provider_mode="mast"), make_target()
    )

    assert backend.last_url.startswith("https://mast.stsci.edu/api/v0/invoke?request=")
    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.candidate_id == "mast-24800511"
    assert candidate.band == "F547M"
    assert candidate.download_url.startswith(
        "https://mast.stsci.edu/api/v0.1/Download/file?uri=mast%3AHST%2Fproduct%2F"
    )


def test_mast_incomplete_status_is_a_service_error() -> None:
    backend = StaticMetadataBackend(
        json.dumps({"status": "EXECUTING", "data": []}).encode("utf-8"),
        "application/json",
    )
    provider = build_image_provider("mast", backend=backend)

    with pytest.raises(providers.ImageDiscoveryServiceError) as exc_info:
        provider.discover(make_request(provider_mode="mast"), make_target())

    assert exc_info.value.code == "image_discovery_service_error"


def test_esa_sky_emits_only_allowlisted_postcards() -> None:
    payload = {
        "metadata": [
            {"name": "observation_id"},
            {"name": "instrument_name"},
            {"name": "filter"},
            {"name": "postcard_url"},
        ],
        "data": [
            [
                "hst_13419_07_wfc3_uvis_f656n_icaz07f4",
                "WFC3/UVIS",
                "F656N",
                "https://hst.esac.esa.int/tap-server/data?OBSERVATIONID=x&RETRIEVAL_TYPE=POSTCARD",
            ],
            [
                "hst_evil",
                "WFC3/UVIS",
                "F656N",
                "https://evil.example.test/tap-server/data?OBSERVATIONID=y",
            ],
        ],
    }
    backend = StaticMetadataBackend(
        json.dumps(payload).encode("utf-8"), "application/json"
    )
    provider = build_image_provider("esa_sky", backend=backend)

    discovery = provider.discover_with_provenance(
        make_request(provider_mode="esa_sky"), make_target()
    )

    assert backend.last_url.startswith("https://sky.esa.int/esasky-tap/tap/sync?")
    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.candidate_id == "esasky-hst-hst_13419_07_wfc3_uvis_f656n_icaz07f4"
    assert candidate.download_url.startswith("https://hst.esac.esa.int/tap-server/data?")


@pytest.mark.parametrize(
    "url",
    [
        "http://ps1images.stsci.edu/cgi-bin/fitscut.cgi?x=1",
        "https://evil.example.test/cgi-bin/fitscut.cgi?x=1",
        "https://user:secret@ps1images.stsci.edu/cgi-bin/fitscut.cgi",
        "https://ps1images.stsci.edu:8443/cgi-bin/fitscut.cgi",
        "https://ps1images.stsci.edu/other-path/fitscut.cgi",
    ],
)
def test_require_provider_url_rejects_untrusted_urls(url: str) -> None:
    descriptor = IMAGE_PROVIDER_REGISTRY["panstarrs"].descriptor

    with pytest.raises(providers.ImageDiscoveryUrlError) as exc_info:
        require_provider_url(url, descriptor)

    assert exc_info.value.code == "image_discovery_untrusted_url"


def test_auto_trusted_mode_records_degraded_providers_without_fabrication() -> None:
    assert hasattr(starskill, "discover_image_candidates")
    backends = {
        "panstarrs": FailingMetadataBackend(),
        "mast": FailingMetadataBackend(),
        "esa_sky": FailingMetadataBackend(),
    }

    result = discover_image_candidates(
        make_request(provider_mode="auto_trusted"),
        make_target(),
        backends=backends,
    )

    assert isinstance(result, ImageSearchResult)
    assert result.decisions["sdss_dr18"].allowed is True
    for degraded in ("panstarrs", "mast", "esa_sky"):
        assert result.decisions[degraded].allowed is False
        assert result.decisions[degraded].reason_code == "image_discovery_service_error"
    assert [candidate.provider_id for candidate in result.candidates] == ["sdss_dr18"]
    assert len(result.provenance) == 1


def test_named_provider_mode_propagates_structured_errors() -> None:
    with pytest.raises(providers.ImageDiscoveryServiceError):
        discover_image_candidates(
            make_request(provider_mode="panstarrs"),
            make_target(),
            backends={"panstarrs": FailingMetadataBackend()},
        )


def write_request(tmp_path, payload) -> str:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    return str(request_path)


def test_cli_discover_images_writes_validated_offline_result(tmp_path, capsys) -> None:
    request_path = write_request(
        tmp_path,
        {
            "target": {
                "kind": "coordinates",
                "label": "M42",
                "ra_deg": 83.822083,
                "dec_deg": -5.391111,
            },
            "provider_mode": "sdss_dr18",
        },
    )
    output_path = tmp_path / "out" / "image_search.json"

    exit_code = main(
        [
            "discover-images",
            request_path,
            "--output",
            str(output_path),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["discovered"] is True
    assert summary["candidate_count"] == 1
    result = ImageSearchResult.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    assert result.candidates[0].provider_id == "sdss_dr18"
    assert result.provenance[0].network_used is False


def test_cli_discover_images_rejects_solar_system_targets(tmp_path, capsys) -> None:
    request_path = write_request(
        tmp_path,
        {
            "target": {"kind": "solar_system", "body": "moon"},
            "observed_at": "2026-08-25T00:00:00+00:00",
            "provider_mode": "sdss_dr18",
        },
    )

    exit_code = main(
        ["discover-images", request_path, "--output", str(tmp_path / "out.json")]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err)["error"] == "unsupported_image_target"
    assert not (tmp_path / "out.json").exists()


def test_cli_discover_images_rejects_malformed_json_input(tmp_path, capsys) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text("{not json", encoding="utf-8")

    exit_code = main(
        ["discover-images", str(request_path), "--output", str(tmp_path / "out.json")]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err)["error"] == "validation_error"
    assert not (tmp_path / "out.json").exists()
