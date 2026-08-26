"""Load and enforce the bundled allowlist of IVOA TAP services."""

from __future__ import annotations

from importlib.resources import files
from types import MappingProxyType
from typing import Mapping

import yaml

from starskill.query.errors import UnknownVOServiceError
from starskill.query.models import VOService


class VOServiceRegistry:
    """Immutable service lookup that never accepts caller-provided endpoints."""

    def __init__(self, services: Mapping[str, VOService]) -> None:
        normalized = {service_id.casefold(): service for service_id, service in services.items()}
        if not normalized:
            raise ValueError("VO service registry must not be empty")
        if len(normalized) != len(services):
            raise ValueError("VO service IDs must be unique")
        for service_id, service in normalized.items():
            if service.service_id != service_id:
                raise ValueError("registry key must match service_id")
        self._services = MappingProxyType(normalized)

    @classmethod
    def from_yaml(cls, text: str) -> "VOServiceRegistry":
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError("VO service registry YAML is invalid") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise ValueError("VO service registry schema version is unsupported")
        raw_services = payload.get("services")
        if not isinstance(raw_services, list):
            raise ValueError("VO service registry requires a services list")
        services = [VOService.model_validate(item) for item in raw_services]
        if len({service.service_id for service in services}) != len(services):
            raise ValueError("VO service IDs must be unique")
        return cls({service.service_id: service for service in services})

    @property
    def services(self) -> Mapping[str, VOService]:
        return self._services

    def get(self, service_id: str) -> VOService:
        service = self._services.get(service_id.casefold())
        if service is None:
            raise UnknownVOServiceError(
                f"VO service is not allowlisted: {service_id}"
            )
        return service


def default_registry() -> VOServiceRegistry:
    """Return a fresh registry loaded only from the packaged YAML allowlist."""
    text = files("starskill").joinpath("data/vo_services.yaml").read_text(encoding="utf-8")
    return VOServiceRegistry.from_yaml(text)
