"""CLI for matching JSON records and rendering results."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .query import Query, QueryError


def _read_records(source: str) -> list[Mapping[str, Any]]:
    decoder = json.JSONDecoder()
    records: list[Mapping[str, Any]] = []
    position = 0
    while position < len(source):
        while position < len(source) and source[position].isspace():
            position += 1
        if position == len(source):
            break
        try:
            value, position = decoder.raw_decode(source, position)
        except json.JSONDecodeError as error:
            line = source.count("\n", 0, error.pos) + 1
            raise QueryError(f"invalid JSON near line {line}: {error.msg}") from error
        for record in value if isinstance(value, list) else (value,):
            if not isinstance(record, Mapping):
                raise QueryError("input records must be JSON objects")
            records.append(record)
    return records


def _infer_key(records: Sequence[Mapping[str, Any]], explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in ("ref", "id"):
        if any(candidate in record for record in records):
            return candidate
    raise QueryError("cannot infer key field; provide -k KEY")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Filter JSON records with tq match union syntax",
        usage="tq [-h] [-k KEY] [-r] [-C | -M] [-c] query [file]",
    )
    parser.add_argument("query", metavar="query", help="match union expression")
    parser.add_argument(
        "file", nargs="?", metavar="file", help="JSON input file; defaults to stdin"
    )
    parser.add_argument(
        "-k",
        "--key",
        metavar="KEY",
        dest="key",
        help="record key field (default: ref, then id)",
    )
    parser.add_argument(
        "-r",
        "--reorder",
        action="store_true",
        help="order matches by query branch, then input position",
    )
    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="compact output to one line per record",
    )
    colors = parser.add_mutually_exclusive_group()
    colors.add_argument(
        "-C",
        "--color",
        action="store_true",
        help="force color even when output is piped",
    )
    colors.add_argument(
        "-M", "--no-color", action="store_true", help="force plain output"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Filter records and render each result as JSON."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        from rich.console import Console
        from rich.json import JSON
    except ModuleNotFoundError:
        parser.error("the CLI requires the optional extra; install `tq-query[cli]`")
    try:
        source = (
            Path(args.file).read_text(encoding="utf-8")
            if args.file
            else sys.stdin.read()
        )
        records = _read_records(source)
        query = Query.parse(args.query)
        key = _infer_key(records, args.key)
        matched = [
            (index, branch)
            for index, item in enumerate(records)
            if (branch := query.match(item, key=key)) is not None
        ]
        if args.reorder:
            matched.sort(key=lambda result: (result[1], result[0]))

        is_terminal = bool(getattr(sys.stdout, "isatty", lambda: False)())
        color_enabled = args.color or (
            is_terminal and not args.no_color and "NO_COLOR" not in os.environ
        )
        console = Console(
            file=sys.stdout,
            force_terminal=color_enabled,
            no_color=not color_enabled,
            color_system="standard" if color_enabled else None,
            width=100_000,
        )
        for item_index, _branch in matched:
            record = records[item_index]
            if args.compact:
                compact = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                console.print(
                    JSON(compact, indent=None, ensure_ascii=False), soft_wrap=True
                )
            else:
                console.print(JSON.from_data(record, indent=2, ensure_ascii=False))
    except (OSError, QueryError, TypeError, ValueError) as error:
        parser.error(str(error))
    return 0
