"""Structured failures for bounded VO queries."""


class VOQueryError(RuntimeError):
    """Base error with a stable machine-readable code."""

    code = "vo_query_error"


class UnknownVOServiceError(VOQueryError):
    code = "vo_service_not_allowlisted"


class InvalidADQLError(VOQueryError):
    code = "invalid_adql"


class VOQueryTimeoutError(VOQueryError):
    code = "vo_query_timeout"


class VOQueryNetworkError(VOQueryError):
    code = "vo_query_network_error"


class VOQueryServiceError(VOQueryError):
    code = "vo_query_service_error"


class VOQueryArtifactError(VOQueryError):
    code = "vo_query_artifact_error"
