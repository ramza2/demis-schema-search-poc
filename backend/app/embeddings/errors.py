"""Shared embedding error types (provider-agnostic)."""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base embedding error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ModelNotAvailableError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("MODEL_NOT_AVAILABLE", message)


class ModelLoadFailedError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("MODEL_LOAD_FAILED", message)


class EmbeddingFailedError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("EMBEDDING_FAILED", message)


class DimensionMismatchError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("DIMENSION_MISMATCH", message)


class ConfigurationError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("CONFIGURATION_ERROR", message)


class RequestTimeoutError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("REQUEST_TIMEOUT", message)


class InvalidResponseError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_RESPONSE", message)
