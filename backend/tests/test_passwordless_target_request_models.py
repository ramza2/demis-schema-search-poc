"""Request-model coverage for explicit passwordless Target operations."""

from app.schemas.target_api import AnalyzeRequest, PasswordRequest


def test_password_request_accepts_explicit_empty_password() -> None:
    request = PasswordRequest(password="")
    assert request.password == ""


def test_analyze_request_accepts_explicit_empty_password() -> None:
    request = AnalyzeRequest(password="", schemas=["demo"])
    assert request.password == ""
