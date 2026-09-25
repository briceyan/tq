import io
import json

import pytest

from tq.cli import main


def test_cli_preserves_input_order_or_reorders_by_query(monkeypatch, capsys):
    source = '{"ref":"worker/1"}\n{"ref":"api/1"}\n{"ref":"api/2"}\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(source))
    assert main(["api/*,worker/*", "-M", "-c"]) == 0
    assert [
        json.loads(line)["ref"] for line in capsys.readouterr().out.splitlines()
    ] == ["worker/1", "api/1", "api/2"]

    monkeypatch.setattr("sys.stdin", io.StringIO(source))
    assert main(["api/*,worker/*", "-r", "-M", "-c"]) == 0
    assert [
        json.loads(line)["ref"] for line in capsys.readouterr().out.splitlines()
    ] == ["api/1", "api/2", "worker/1"]


def test_cli_accepts_multiline_and_concatenated_json(monkeypatch, capsys):
    sources = (
        '{\n"ref":"one","ok":true\n}',
        '[\n{"ref":"one","ok":true},\n{"ref":"two","ok":false}\n]',
        '{\n"ref":"one","ok":true\n}\n{\n"ref":"two","ok":false\n}',
    )
    for source in sources:
        monkeypatch.setattr("sys.stdin", io.StringIO(source))
        assert main(["*[ok]", "-M", "-c"]) == 0
        assert [
            json.loads(line)["ref"] for line in capsys.readouterr().out.splitlines()
        ] == ["one"]


def test_compact_output_is_one_line_and_color_independent(monkeypatch, capsys):
    source = '{"ref":"one","nested":{"ok":true}}'
    monkeypatch.setattr("sys.stdin", io.StringIO(source))
    assert main(["one", "-M", "-c"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == json.loads(source)


def test_rich_colors_by_default_on_terminal_and_flags_override(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    output = Terminal()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"ref":"one","ok":true}'))
    monkeypatch.setattr("sys.stdout", output)
    assert main(["one"]) == 0
    assert "\x1b[" in output.getvalue()

    output.seek(0)
    output.truncate(0)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"ref":"one","ok":true}'))
    assert main(["one", "-M", "-c"]) == 0
    assert "\x1b[" not in output.getvalue()


def test_rich_forced_color_and_monochrome_are_mutually_exclusive(monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    output = Terminal()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"ref":"one"}'))
    monkeypatch.setattr("sys.stdout", output)
    assert main(["one", "-C", "-c"]) == 0
    assert "\x1b[" in output.getvalue()

    monkeypatch.setattr("sys.stdin", io.StringIO('{"ref":"one"}'))
    with pytest.raises(SystemExit):
        main(["one", "-C", "-M"])


def test_cli_rejects_non_object_records(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("[1,2]"))
    with pytest.raises(SystemExit):
        main(["*", "-M"])
