"""Validation checks for partial Catalog Category updates."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.catalog_api import CategoryUpdate


@pytest.mark.parametrize("field_name", ["category_name", "sort_order", "active"])
def test_category_update_rejects_explicit_null_for_nonnullable_fields(field_name: str) -> None:
    with pytest.raises(ValidationError):
        CategoryUpdate.model_validate({field_name: None})


def test_category_update_allows_description_to_be_cleared() -> None:
    payload = CategoryUpdate.model_validate({"description": None})
    assert "description" in payload.model_fields_set
    assert payload.description is None
