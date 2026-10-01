from agent_sample.domain.checks import (
    find_debug_leftovers,
    find_missing_tests,
    find_pending_markers,
    find_secrets,
)
from agent_sample.domain.diff import ChangeSet, normalize, parse_diff


def change(*files: tuple[str, list[str]]) -> ChangeSet:
    parts = []
    for path, lines in files:
        body = "\n".join(f"+{line}" for line in lines)
        parts.append(
            f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n{body}\n"
        )
    return normalize(parse_diff("".join(parts)), 1000)


def test_secrets_are_critical_security_and_redacted() -> None:
    found = find_secrets(
        change(
            ("src/c.py", ["x = 1", 'aws = "AKIAABCDEFGHIJKLMNOP"', 'password = "hunter2hunter2"'])
        )
    )
    assert [(f.start_line, f.severity, f.category) for f in found] == [
        (2, "critical", "security"),
        (3, "critical", "security"),
    ]
    assert "AKIAABCDEFGHIJKLMNOP" not in found[0].evidence
    assert "[redacted]" in found[0].evidence


def test_secret_placeholders_and_env_lookups_are_ignored() -> None:
    found = find_secrets(
        change(
            ("src/c.py", ['api_key = "your-api-key-here"', 'token = os.environ["TOKEN"]']),
        )
    )
    assert found == ()


def test_debug_leftovers_in_source_but_not_in_tests() -> None:
    found = find_debug_leftovers(
        change(
            ("src/a.py", ["print('x')", "breakpoint()", "log.info('ok')"]),
            ("web/a.ts", ["console.log(x)", "debugger;"]),
            ("tests/test_a.py", ["print('fine in tests')"]),
        )
    )
    assert [(f.file, f.start_line) for f in found] == [
        ("src/a.py", 1),
        ("src/a.py", 2),
        ("web/a.ts", 1),
        ("web/a.ts", 2),
    ]
    assert {f.severity for f in found} == {"minor"}


def test_commented_out_code_block() -> None:
    found = find_debug_leftovers(
        change(("src/a.py", ["# old = compute()", "# if old:", "#     return old", "x = 1"]))
    )
    assert len(found) == 1
    assert (found[0].start_line, found[0].end_line) == (1, 3)
    prose = find_debug_leftovers(change(("src/a.py", ["# explain", "# the idea", "# here"])))
    assert prose == ()


def test_missing_tests_only_when_source_changes_without_tests() -> None:
    (finding,) = find_missing_tests(change(("src/a.py", ["x = 1"])))
    assert (finding.category, finding.severity) == ("tests", "minor")
    assert find_missing_tests(change(("src/a.py", ["x = 1"]), ("tests/test_a.py", ["y"]))) == ()
    assert find_missing_tests(change(("README.md", ["docs"]))) == ()


def test_pending_markers() -> None:
    found = find_pending_markers(change(("src/a.py", ["# TODO: later", "todo_list = []"])))
    assert [(f.start_line, f.severity, f.description) for f in found] == [
        (1, "nit", "TODO marker added")
    ]
