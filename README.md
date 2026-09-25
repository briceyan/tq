# tq

`tq` is a small Python package and CLI for querying JSON records.

It reads JSON Lines, JSON arrays, multiline objects, and consecutive JSON objects from a file or stdin, and writes matching records as JSON.

## Get started

Install:

```sh
uv tool install tq-query
# or: pip install tq-query
```

To try `tq` with OpenRouter model data from models.dev, download the catalog and convert it to `models.jsonl`:

```sh
curl -fsSL https://models.dev/catalog.json \
  | jq '.providers.openrouter.models[] | {id, modalities, limit, reasoning, tool_call}' -c \
  > models.jsonl
```

Each line is one model record. Query by identity or fields:

```sh
tq 'openai/*[reasoning;tool_call]' models.jsonl
tq '[limit.context>=200000]' models.jsonl
tq '[modalities.input has image]' models.jsonl
tq '[modalities.input has all (text,image)]' models.jsonl
```

## CLI

```text
usage: tq [OPTIONS] QUERY [FILE]

Arguments:
  query                 match expression
  file                  JSON input file; defaults to stdin

Options:
  -h, --help            show this help message and exit
  -k KEY                identity field (default: ref, then id)
  -r, --reorder         order matches by query branch, then input position
  -C, --color           force colored output
  -M, --no-color        force uncolored output
  -c, --compact         compact JSON output, one record per line
```

Color is enabled for terminals and disabled for pipes. `-c` controls formatting independently.

## Query syntax

A query is a comma-separated list of branches. Each branch may combine an identity pattern with predicates:

```text
IDENTITY[PREDICATE;PREDICATE],IDENTITY[PREDICATE]
```

Omit the identity to match any record. Branches are OR-ed; predicates within a branch are AND-ed and may be separated by commas or semicolons.

| Syntax | Meaning |
| --- | --- |
| `foo*` / `foo?` | Identity glob: `*` matches any sequence; `?` matches one character |
| `"foo*"` | Exact identity; wildcards are literal |
| `f` / `!f` | `f = true` / `f = false` |
| `f = v` / `f != v` | Equal / not equal |
| `f < v`, `f <= v`, `f > v`, `f >= v` | Ordered comparison |
| `f has v` / `f has no v` | Array contains / does not contain `v` |
| `f has any (a,b)` | Array contains at least one candidate |
| `f has all (a,b)` | Array contains every candidate |
| `f has none (a,b)` | Array contains no candidate |
| `v in f` / `v not in f` | Aliases for `f has v` / `f has no v` |
| `a.b.c` | Access a nested field |

`has any`, `has all`, and `has none` require at least two candidates.

Quote values when needed; for example, `"true"` is the text value `true`. Missing fields never match a predicate, including negative predicates. Explicit `null` is distinct from a missing field.

## Python API

```python
from tq import Query

schema = {"key": "id", "filter": ["reasoning", "tool_call"]}
query = Query.parse("openai/*[reasoning;tool_call]").validate(schema)

record = {
    "id": "openai/gpt-5",
    "reasoning": True,
    "tool_call": True,
}

branch = query.match(record)
```
