"""Unit tests for generic laboratory terminology expansion."""

from __future__ import annotations


def test_generic_laboratory_query_triggers_expected_concept() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query(
        "환자의 혈액검사 결과와 정상범위를 확인하려면 어떤 테이블을 봐야 하나?"
    )

    assert "laboratory_test" in exp.matched_concepts
    assert "blood_glucose" not in exp.matched_concepts
    assert "liver_function" not in exp.matched_concepts
    assert "renal_function" not in exp.matched_concepts
    assert "임상검사" in exp.expanded_terms
    assert "lab" in exp.expanded_terms
    assert "reference range" in exp.expanded_terms


def test_generic_test_result_query_does_not_trigger_specific_lab_concepts() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("검사결과를 조회하고 싶다")

    assert exp.matched_concepts == ["laboratory_test"]
    assert "blood_glucose" not in exp.matched_concepts
    assert "liver_function" not in exp.matched_concepts
    assert "renal_function" not in exp.matched_concepts


def test_reference_range_english_query_triggers_generic_laboratory_concept() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("show the laboratory result reference range")

    assert "laboratory_test" in exp.matched_concepts
    assert "임상검사" in exp.expanded_terms
    assert "lab" in exp.expanded_terms


def test_generic_laboratory_dictionary_has_no_schema_leakage() -> None:
    from app.services.search.terminology import (
        assert_no_schema_leakage,
        clear_concept_cache,
        get_concepts,
    )

    clear_concept_cache()
    concepts = get_concepts()
    generic = next(c for c in concepts if c.id == "laboratory_test")

    assert assert_no_schema_leakage(concepts) == []
    for term in (generic.label, *generic.triggers, *generic.expansion_terms):
        assert not term.lower().startswith("tb_")
        assert "->" not in term
        assert "→" not in term
