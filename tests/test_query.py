from dataclasses import FrozenInstanceError

import pytest

from tq import Match, Predicate, Query, QueryError


def test_supported_predicate_grammar():
    query = Query.parse(
        "*[f=v;f!=v;f has v;f has no v;f has any (a,b);f has all (a,b);f has none (c,d)]"
    )
    assert [p.operator for p in query.matches[0].predicates] == [
        "=",
        "!=",
        "has",
        "has no",
        "has any",
        "has all",
        "has none",
    ]


def test_query_parses_branches_and_is_immutable():
    query = Query.parse('api/*[active;score>=8],"exact,identity"')
    assert query.matches[0] == Match(
        "api/*",
        predicates=(
            Predicate(query.matches[0].predicates[0].field, "=", (True,)),
            Predicate(query.matches[0].predicates[1].field, ">=", (8,)),
        ),
    )
    assert query.matches[1] == Match("exact,identity", exact=True)
    with pytest.raises((AttributeError, FrozenInstanceError)):
        query.matches = ()


def test_query_match_returns_first_branch_and_accepts_key_field():
    query = Query.parse("api/*[enabled;formats has pdf],*")
    record = {"id": "api/1", "enabled": True, "formats": ["pdf"]}
    assert query.match(record, key="id") == 0
    assert (
        query.match({"id": "api/2", "enabled": True, "formats": ["text"]}, key="id")
        == 1
    )
    assert query.match({"id": "other/1"}, key="id") == 1
    assert query.match({"id": "api/1"}, key="missing") is None


def test_query_match_supports_object_fields_and_dotted_paths():
    class Details:
        enabled = True

    class Record:
        id = "service/one"
        details = Details()

    assert Query.parse("service/*[details.enabled]").match(Record()) == 0


def test_has_any_all_none_and_no_semantics():
    one = {"id": "one", "items": ["a"]}
    both = {"id": "both", "items": ["a", "b"]}
    other = {"id": "other", "items": ["z"]}
    empty = {"id": "empty", "items": []}
    assert Query.parse("items has any (a,b)").match(one, key="id") == 0
    assert Query.parse("items has all (a,b)").match(one, key="id") is None
    assert Query.parse("items has all (a,b)").match(both, key="id") == 0
    assert Query.parse("items has none (a,b)").match(other, key="id") == 0
    assert Query.parse("items has none (a,b)").match(empty, key="id") == 0
    assert Query.parse("items has no a").match(other, key="id") == 0


def test_in_aliases_and_missing_fields():
    assert (
        Query.parse("pdf in formats").match({"id": "yes", "formats": ["pdf"]}, key="id")
        == 0
    )
    assert (
        Query.parse("pdf not in formats").match(
            {"id": "no", "formats": ["text"]}, key="id"
        )
        == 0
    )
    assert Query.parse("pdf not in formats").match({"id": "missing"}, key="id") is None


def test_quantified_candidate_lists_require_multiple_values():
    expressions = (
        "items has any (a)",
        "items has all (a)",
        "items has none (a)",
    )
    for expression in expressions:
        with pytest.raises(QueryError, match="at least two"):
            Query.parse(expression)


def test_empty_candidate_list_is_rejected():
    with pytest.raises(QueryError):
        Query.parse("items has any ()")


def test_schema_binds_key_and_filter_allowlist():
    schema = {"key": "id", "filter": ["active", "formats", "nested.name"]}
    query = Query.parse("api/*[active;formats has pdf;nested.name=demo]").validate(
        schema
    )
    record = {
        "id": "api/1",
        "active": True,
        "formats": ["pdf"],
        "nested": {"name": "demo"},
    }
    assert query.match(record) == 0
    with pytest.raises(QueryError, match="not in the filter fields"):
        Query.parse("*[private=value]").validate(schema)


def test_schema_defaults_to_id_and_all_non_key_fields():
    query = Query.parse("*[active;formats has pdf]").validate(None)
    assert query.match({"id": "one", "active": True, "formats": ["pdf"]}) == 0
    with pytest.raises(QueryError, match="key field"):
        Query.parse("*[id=one]").validate(None)


def test_custom_key_defaults_filter_to_all_other_fields():
    query = Query.parse("api/*[active]").validate({"key": "ref"})
    assert query.match({"ref": "api/1", "active": True}) == 0
    with pytest.raises(QueryError, match="key field"):
        Query.parse("*[ref=api/1]").validate({"key": "ref"})


def test_explicit_empty_filter_allows_identity_only_queries():
    assert Query.parse("api/*").validate({"filter": []}).match({"id": "api/1"}) == 0
    with pytest.raises(QueryError, match="not in the filter fields"):
        Query.parse("*[active]").validate({"filter": []})


def test_validation_does_not_check_operation_or_value_types():
    query = Query.parse("*[items>=true]").validate({"filter": ["items"]})
    assert query.match({"id": "one", "items": ["anything"]}) is None


def test_invalid_schema_options_and_filter_paths_are_rejected():
    with pytest.raises(QueryError, match="unknown schema option"):
        Query.parse("*").validate({"fields": ["active"]})
    with pytest.raises(QueryError, match="invalid key field path"):
        Query.parse("*").validate({"key": "not a path"})
    with pytest.raises(QueryError, match="duplicate field paths"):
        Query.parse("*").validate({"filter": ["active", "active"]})
    with pytest.raises(QueryError, match="key field cannot also be a filter"):
        Query.parse("*").validate({"key": "id", "filter": ["id"]})
    with pytest.raises(TypeError, match="sequence of field paths"):
        Query.parse("*").validate({"filter": "active"})


def test_flat_annotation_mapping_is_no_longer_a_schema():
    with pytest.raises(QueryError, match="unknown schema option"):
        Query.parse("*").validate({"id": str, "active": bool})
    with pytest.raises(TypeError, match="mapping or None"):
        Query.parse("*").validate(object())
