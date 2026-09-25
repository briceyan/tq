"""Schema-independent query parsing, schema validation, and record matching."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, ClassVar

_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


class QueryError(ValueError):
    """Invalid query syntax, schema, or literal."""


@dataclass(frozen=True, slots=True)
class Field:
    """A queryable dotted path."""

    name: str


@dataclass(frozen=True, slots=True)
class Predicate:
    """A field comparison or collection predicate."""

    field: Field
    operator: str
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Match:
    """Identity pattern and its AND-conjoined predicates."""

    identity: str = "*"
    exact: bool = False
    predicates: tuple[Predicate, ...] = ()


class Query:
    """Immutable parsed query with optional schema validation and record matching."""

    __slots__ = ("_frozen", "_key", "matches")
    OPERATORS: ClassVar[tuple[str, ...]] = ("<=", ">=", "!=", "=", "<", ">")
    MEMBERSHIP: ClassVar[tuple[str, ...]] = (
        "has any",
        "has all",
        "has none",
        "has no",
        "has",
        "not in",
        "in",
    )
    _COLLECTION_OPERATORS: ClassVar[frozenset[str]] = frozenset(
        {"has", "has no", "has any", "has all", "has none"}
    )

    def __init__(self, matches: Sequence[Match], *, key: str | None = None) -> None:
        branches = tuple(matches)
        if not branches:
            raise QueryError("query cannot be empty")
        object.__setattr__(self, "matches", branches)
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Query instances are immutable")
        object.__setattr__(self, name, value)

    @classmethod
    def parse(cls, expression: str | Sequence[str]) -> Query:
        """Parse an expression without requiring records or a schema."""

        expressions = (
            (expression,) if isinstance(expression, str) else tuple(expression)
        )
        if not expressions:
            raise QueryError("query cannot be empty")
        branches = [branch for text in expressions for branch in cls._parse_union(text)]
        return cls(branches)

    def validate(self, schema: Mapping[str, object] | None) -> Query:
        """Validate allowed predicate fields and bind the query key.

        ``schema`` accepts ``{"key": "id", "filter": ["name", "tags"]}``.
        The key defaults to ``"id"``. An omitted schema or ``filter`` allows any
        predicate field except the key. This intentionally does not inspect
        record types or check whether an operator is compatible with a field.
        """

        if schema is None:
            schema = {}
        if not isinstance(schema, Mapping):
            raise TypeError("schema must be a mapping or None")
        unknown_options = set(schema).difference({"key", "filter"})
        if unknown_options:
            option = min(map(str, unknown_options))
            raise QueryError(f"unknown schema option: {option!r}")
        key_name = schema.get("key", "id")
        if not isinstance(key_name, str) or not _FIELD_PATH.fullmatch(key_name):
            raise QueryError(f"invalid key field path: {key_name!r}")

        raw_filter = schema.get("filter")
        filter_fields: frozenset[str] | None = None
        if raw_filter is not None:
            if isinstance(raw_filter, str) or not isinstance(raw_filter, Sequence):
                raise TypeError("schema 'filter' must be a sequence of field paths")
            names = tuple(raw_filter)
            if any(
                not isinstance(name, str) or not _FIELD_PATH.fullmatch(name)
                for name in names
            ):
                raise QueryError("filter contains an invalid field path")
            if len(set(names)) != len(names):
                raise QueryError("filter contains duplicate field paths")
            if key_name in names:
                raise QueryError("key field cannot also be a filter field")
            filter_fields = frozenset(names)

        for branch in self.matches:
            for predicate in branch.predicates:
                field_name = predicate.field.name
                if field_name == key_name:
                    raise QueryError(
                        f"key field {key_name!r} cannot be used as a filter field"
                    )
                if filter_fields is not None and field_name not in filter_fields:
                    available = ", ".join(sorted(filter_fields)) or "(none)"
                    raise QueryError(
                        f"query field {field_name!r} is not in the filter fields: {available}"
                    )
        return Query(self.matches, key=key_name)

    def match(self, record: object, key: str | None = None) -> int | None:
        """Return the first matching branch index, or ``None``.

        A key bound by :meth:`validate` is used by default. An explicit ``key``
        overrides it; unvalidated queries default to the ``id`` record field.
        """

        key_path = (self._key or "id") if key is None else key
        if not isinstance(key_path, str) or not key_path:
            raise ValueError("key must be a non-empty record field path")
        identity = _get(record, key_path)
        if not isinstance(identity, str):
            return None
        for branch_index, branch in enumerate(self.matches):
            if _branch_matches(record, identity, branch):
                return branch_index
        return None

    @classmethod
    def _parse_union(cls, text: str) -> tuple[Match, ...]:
        if not text.strip():
            raise QueryError("query cannot be empty")
        return tuple(
            cls._parse_branch(part) for part in cls._split(text.strip(), ",", "query")
        )

    @classmethod
    def _parse_branch(cls, text: str) -> Match:
        opening = cls._unquoted(text, "[")
        if opening < 0:
            if cls._find_membership(text):
                return Match("*", predicates=(cls._parse_predicate(text),))
            if text.strip() == "()":
                raise QueryError("candidate list cannot be empty")
            return Match(*cls._parse_identity(text.strip()))
        if not text.endswith("]") or cls._unquoted(text[opening + 1 :], "[") >= 0:
            raise QueryError("predicate block must be last and not nested")
        identity = cls._parse_identity(text[:opening].strip())
        body = text[opening + 1 : -1]
        if not body.strip():
            raise QueryError("predicate block cannot be empty")
        predicates = tuple(
            cls._parse_predicate(part)
            for group in cls._split(body, ";", "predicates")
            for part in cls._split(group, ",", "predicates")
        )
        return Match(*identity, predicates)

    @staticmethod
    def _parse_identity(text: str) -> tuple[str, bool]:
        if not text:
            return "*", False
        if text.startswith('"'):
            identity = Query._parse_json_string(text)
            if not identity:
                raise QueryError("identity cannot be empty")
            return identity, True
        if any(char.isspace() or char in '[],;()"' for char in text):
            raise QueryError(
                "invalid identity pattern; quote exact text as a JSON string"
            )
        return text, False

    @classmethod
    def _parse_predicate(cls, raw: str) -> Predicate:
        text = raw.strip()
        if not text:
            raise QueryError("empty predicate")
        membership = cls._find_membership(text)
        if membership:
            start, end, operator = membership
            left, right = text[:start].strip(), text[end:].strip()
            if operator in {"in", "not in"}:
                path, candidate_text = right, left
                canonical = "has" if operator == "in" else "has no"
                allow_scalar = True
                require_multiple = False
            else:
                path, candidate_text = left, right
                canonical = operator
                allow_scalar = operator in {"has", "has no"}
                require_multiple = operator in {"has any", "has all", "has none"}
            cls._validate_field_path(path)
            candidates = cls._parse_candidates(
                candidate_text,
                allow_scalar=allow_scalar,
                require_multiple=require_multiple,
            )
            return Predicate(Field(path), canonical, candidates)
        comparison = cls._find_operator(text)
        if comparison:
            index, operator = comparison
            path = text[:index].strip()
            cls._validate_field_path(path)
            value = cls._parse_literal(text[index + len(operator) :].strip())
            return Predicate(Field(path), operator, (value,))
        negated = text.startswith("!")
        path = text[1:] if negated else text
        cls._validate_field_path(path)
        return Predicate(Field(path), "=", (not negated,))

    @classmethod
    def _parse_candidates(
        cls, text: str, *, allow_scalar: bool, require_multiple: bool = False
    ) -> tuple[Any, ...]:
        value = text.strip()
        if value.startswith("("):
            if not value.endswith(")"):
                raise QueryError("unclosed candidate list")
            candidates = cls._split(value[1:-1], ",", "candidates")
            if not candidates:
                raise QueryError("candidate list cannot be empty")
            if require_multiple and len(candidates) < 2:
                raise QueryError("has any/all/none requires at least two candidates")
        elif allow_scalar:
            candidates = (value,)
        else:
            raise QueryError("candidate list must be parenthesized")
        return tuple(cls._parse_literal(candidate) for candidate in candidates)

    @staticmethod
    def _validate_field_path(path: str) -> None:
        if not _FIELD_PATH.fullmatch(path):
            raise QueryError(f"invalid field path: {path!r}")

    @classmethod
    def _find_membership(cls, text: str) -> tuple[int, int, str] | None:
        quoted = escaped = False
        round_depth = 0
        for index, char in enumerate(text):
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
                continue
            if char == "(":
                round_depth += 1
                continue
            if char == ")":
                round_depth -= 1
                if round_depth < 0:
                    raise QueryError("unmatched parenthesis in membership")
                continue
            if char.isspace() and round_depth == 0:
                for operator in cls.MEMBERSHIP:
                    match = re.match(rf"\s+{re.escape(operator)}\s+", text[index:])
                    if match:
                        end = index + match.end()
                        if not text[end:].strip():
                            raise QueryError("membership requires a field and value(s)")
                        return index, end, operator
        if quoted:
            raise QueryError("unterminated JSON string")
        if round_depth:
            raise QueryError("unclosed candidate list")
        return None

    @staticmethod
    def _parse_literal(raw: str) -> Any:
        value = raw.strip()
        if not value:
            raise QueryError("empty query literal")
        if value == "null":
            return None
        if value.startswith('"'):
            return Query._parse_json_string(value)
        if value == "true":
            return True
        if value == "false":
            return False
        if re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)", value):
            return int(value)
        number = r"[+-]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
        if re.fullmatch(number, value):
            return float(value)
        if any(char.isspace() or char in '[],;()"=!<>' for char in value):
            raise QueryError(
                "use a JSON string for text containing spaces or query punctuation"
            )
        return value

    @staticmethod
    def _split(text: str, delimiter: str, context: str) -> tuple[str, ...]:
        parts: list[str] = []
        start = square = round_ = 0
        quoted = escaped = False
        for index, char in enumerate(text):
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == "[":
                square += 1
                if square > 1:
                    raise QueryError("nested predicate block")
            elif char == "]":
                square -= 1
                if square < 0:
                    raise QueryError(f"unmatched bracket in {context}")
            elif char == "(":
                round_ += 1
            elif char == ")":
                round_ -= 1
                if round_ < 0:
                    raise QueryError(f"unmatched parenthesis in {context}")
            elif char == delimiter and square == 0 and round_ == 0:
                part = text[start:index].strip()
                if not part:
                    raise QueryError(f"empty {context} item")
                parts.append(part)
                start = index + 1
        if quoted or square or round_:
            raise QueryError(f"unclosed delimiter in {context}")
        part = text[start:].strip()
        if not part:
            raise QueryError(f"empty {context} item")
        return (*parts, part)

    @staticmethod
    def _unquoted(text: str, target: str) -> int:
        quoted = escaped = False
        for index, char in enumerate(text):
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == target:
                return index
        if quoted:
            raise QueryError("unterminated JSON string")
        return -1

    @staticmethod
    def _find_operator(text: str) -> tuple[int, str] | None:
        quoted = escaped = False
        for index, char in enumerate(text):
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            else:
                for operator in Query.OPERATORS:
                    if text.startswith(operator, index):
                        return index, operator
        if quoted:
            raise QueryError("unterminated JSON string")
        return None

    @staticmethod
    def _parse_json_string(text: str) -> str:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise QueryError(f"invalid JSON string: {text!r}") from error
        if not isinstance(value, str):
            raise QueryError("expected JSON string")
        return value


def _branch_matches(record: object, identity: str, branch: Match) -> bool:
    if branch.exact:
        if identity != branch.identity:
            return False
    elif not _glob(identity, branch.identity):
        return False
    return all(_predicate_matches(record, predicate) for predicate in branch.predicates)


def _predicate_matches(record: object, predicate: Predicate) -> bool:
    actual = _get(record, predicate.field.name)
    if actual is _MISSING:
        return False
    operator, candidates = predicate.operator, predicate.values
    if operator in Query._COLLECTION_OPERATORS:
        values = _collection(actual)
        if values is None:
            return False
        hits = tuple(
            any(_same(value, candidate) for value in values) for candidate in candidates
        )
        if operator == "has":
            return bool(hits) and hits[0]
        if operator == "has no":
            return bool(hits) and not hits[0]
        if operator == "has any":
            return any(hits)
        if operator == "has all":
            return bool(hits) and all(hits)
        return not any(hits)
    if operator == "=":
        return _same(actual, candidates[0])
    if operator == "!=":
        return actual is not None and not _same(actual, candidates[0])
    if actual is None or not _compatible(actual, candidates[0]):
        return False
    try:
        if operator == "<":
            return actual < candidates[0]  # type: ignore[operator]
        if operator == "<=":
            return actual <= candidates[0]  # type: ignore[operator]
        if operator == ">":
            return actual > candidates[0]  # type: ignore[operator]
        if operator == ">=":
            return actual >= candidates[0]  # type: ignore[operator]
    except (TypeError, ValueError):
        return False
    return False


def _collection(value: object) -> tuple[object, ...] | None:
    if isinstance(value, Mapping):
        return tuple(value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(value)
    return None


def _same(left: object, right: object) -> bool:
    if isinstance(left, Enum):
        left = left.value
    if isinstance(right, Enum):
        right = right.value
    if left is None or right is None:
        return left is None and right is None
    return _compatible(left, right) and left == right


def _compatible(left: object, right: object) -> bool:
    if isinstance(left, Enum):
        left = left.value
    if isinstance(right, Enum):
        right = right.value
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return True
    return type(left) is type(right)


def _get(value: object, dotted_path: str) -> object:
    for part in dotted_path.split("."):
        if value is None:
            return None
        if isinstance(value, Mapping):
            if part not in value:
                return _MISSING
            value = value[part]
        else:
            try:
                value = getattr(value, part)
            except AttributeError:
                return _MISSING
    return value


_MISSING = object()


@lru_cache(maxsize=512)
def _glob_pattern(pattern: str) -> re.Pattern[str]:
    expression = "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"
    return re.compile(expression.replace(r"\?", "."), flags=re.DOTALL)


def _glob(value: str, pattern: str) -> bool:
    return _glob_pattern(pattern).fullmatch(value) is not None
