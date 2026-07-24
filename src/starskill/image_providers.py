"""Registered metadata contracts for trusted astronomy image archives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from starskill.schemas import (
    AstronomyImageSearchRequest,
    ImageCandidate,
    ImageProviderDescriptor,
    ResolvedImageTarget,
)


class ImageProvider(Protocol):
    descriptor: ImageProviderDescriptor

    def discover(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> list[ImageCandidate]: ...


@dataclass(frozen=True)
class RegisteredImageProvider:
    """Registry entry whose adapter implementation is introduced in task 2."""

    descriptor: ImageProviderDescriptor

    def discover(
        self,
        request: AstronomyImageSearchRequest,
        target: ResolvedImageTarget,
    ) -> list[ImageCandidate]:
        raise NotImplementedError("metadata-only provider discovery is not implemented")


IMAGE_PROVIDER_REGISTRY: Mapping[str, ImageProvider] = MappingProxyType(
    {
        "sdss_dr18": RegisteredImageProvider(
            ImageProviderDescriptor(
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
            )
        ),
        "mast": RegisteredImageProvider(
            ImageProviderDescriptor(
                provider_id="mast",
                organization="Space Telescope Science Institute MAST",
                allowed_hosts=("mast.stsci.edu",),
                allowed_redirect_hosts=("mast.stsci.edu",),
                endpoint_roots=("https://mast.stsci.edu/api/v0.1/",),
                formats=("jpeg", "png", "fits"),
                max_bytes=50_000_000,
                license_url=(
                    "https://archive.stsci.edu/missions-and-data/"
                    "mission-acknowledgments"
                ),
            )
        ),
        "esa_sky": RegisteredImageProvider(
            ImageProviderDescriptor(
                provider_id="esa_sky",
                organization="European Space Agency ESA Sky",
                allowed_hosts=("sky.esa.int",),
                allowed_redirect_hosts=("sky.esa.int",),
                endpoint_roots=("https://sky.esa.int/esasky-tap/tap/",),
                formats=("jpeg", "png", "fits"),
                max_bytes=50_000_000,
                license_url="https://www.cosmos.esa.int/web/esdc/esasky",
            )
        ),
        "panstarrs": RegisteredImageProvider(
            ImageProviderDescriptor(
                provider_id="panstarrs",
                organization="Pan-STARRS at Space Telescope Science Institute",
                allowed_hosts=("ps1images.stsci.edu",),
                allowed_redirect_hosts=("ps1images.stsci.edu",),
                endpoint_roots=("https://ps1images.stsci.edu/cgi-bin/",),
                formats=("jpeg", "png", "fits"),
                max_bytes=50_000_000,
                license_url="https://outerspace.stsci.edu/display/PANSTARRS/",
            )
        ),
    }
)
