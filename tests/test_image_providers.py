import pytest
from pydantic import ValidationError

from starskill.image_providers import IMAGE_PROVIDER_REGISTRY
from starskill.schemas import ImageCandidate


def test_registry_has_only_declared_tier_one_archives() -> None:
    assert set(IMAGE_PROVIDER_REGISTRY) == {
        "sdss_dr18",
        "mast",
        "esa_sky",
        "panstarrs",
    }
    assert all(
        descriptor.license_url.startswith("https://")
        for descriptor in (
            provider.descriptor for provider in IMAGE_PROVIDER_REGISTRY.values()
        )
    )


def test_registry_descriptors_expose_only_https_fixed_api_roots() -> None:
    for provider in IMAGE_PROVIDER_REGISTRY.values():
        descriptor = provider.descriptor
        assert descriptor.allowed_hosts
        assert descriptor.allowed_redirect_hosts
        assert all(root.startswith("https://") for root in descriptor.endpoint_roots)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "unregistered_provider"),
        ("download_url", "http://example.test/image.jpg"),
    ],
)
def test_candidate_rejects_unregistered_provider_or_arbitrary_download_url(
    field: str, value: str
) -> None:
    payload = {
        "candidate_id": "candidate-1",
        "provider_id": "sdss_dr18",
        "source_url": "https://skyserver.sdss.org/dr18/",
        "download_url": "https://skyserver.sdss.org/dr18/image.jpg",
        "format": "jpeg",
        "query_parameters": {"ra": 10.684708, "dec": 41.26875},
        "license_url": "https://www.sdss.org/science/image-gallery/",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        ImageCandidate.model_validate(payload)
