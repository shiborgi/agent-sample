import pytest

from agent_sample.domain.errors import UnknownOption
from agent_sample.domain.review.change import (
    is_test,
    language_of,
    prepare_change,
    split_parts,
    triage,
)
from agent_sample.domain.review.diff import parse_diff
from agent_sample.domain.review.model import EmptyDiff, InvalidDiff
from agent_sample.domain.review.policy import MAX_FILE_LINES

GIT_DIFF = """\
diff --git a/app/pricing.py b/app/pricing.py
index 1111111..2222222 100644
--- a/app/pricing.py
+++ b/app/pricing.py
@@ -1,4 +1,5 @@
 def total(items):
-    return sum(items)
+    subtotal = sum(items)
+    return subtotal


@@ -10 +11,3 @@ def tax(value):
     return value * 0.1
+
+VERSION = 2
diff --git a/README.md b/README.md
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/README.md
@@ -0,0 +1 @@
+# Pricing
"""


def test_git_diff_reads_files_status_and_new_line_numbers() -> None:
    pricing, readme = parse_diff(GIT_DIFF)
    assert (pricing.path, pricing.status, readme.path, readme.status) == (
        "app/pricing.py",
        "modified",
        "README.md",
        "added",
    )
    assert [(line.new_line, line.text) for line in pricing.added] == [
        (2, "    subtotal = sum(items)"),
        (3, "    return subtotal"),
        (12, ""),
        (13, "VERSION = 2"),
    ]
    assert pricing.removed_count == 1
    assert 4 in pricing.new_lines and 11 in pricing.new_lines
    assert pricing.evidence(2, 3) == "+    subtotal = sum(items)\n+    return subtotal"
    assert pricing.text.startswith("diff --git a/app/pricing.py")
    assert readme.text.startswith("diff --git a/README.md")


def test_plain_diff_without_prefixes_and_with_timestamps() -> None:
    text = (
        "--- src/calc.py\t2026-01-01 10:00:00\n"
        "+++ src/calc.py\t2026-01-02 10:00:00\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
        "--- src/other.py\n"
        "+++ src/other.py\n"
        "@@ -1 +1,2 @@\n"
        " y = 1\n"
        "+z = 3\n"
    )
    calc, other = parse_diff(text)
    assert (calc.path, other.path) == ("src/calc.py", "src/other.py")
    assert [line.new_line for line in other.added] == [2]


def test_no_newline_marker_and_blank_context_lines_keep_the_count() -> None:
    text = (
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,3 +1,3 @@\n"
        " first\n"
        "\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
        "\\ No newline at end of file\n"
    )
    (file,) = parse_diff(text)
    assert [(line.kind, line.new_line) for line in file.lines] == [
        (" ", 1),
        (" ", 2),
        ("-", None),
        ("+", 3),
    ]


def test_binary_deleted_and_renamed_files() -> None:
    text = (
        "diff --git a/logo.png b/logo.png\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "Binary files /dev/null and b/logo.png differ\n"
        "diff --git a/old.py b/old.py\n"
        "deleted file mode 100644\n"
        "--- a/old.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-gone = True\n"
        "diff --git a/a.py b/b.py\n"
        "similarity index 100%\n"
        "rename from a.py\n"
        "rename to b.py\n"
    )
    logo, old, renamed = parse_diff(text)
    assert (logo.path, logo.binary, logo.status) == ("logo.png", True, "added")
    assert (old.path, old.status, old.added) == ("old.py", "deleted", ())
    assert (renamed.path, renamed.old_path, renamed.status) == ("b.py", "a.py", "renamed")


@pytest.mark.parametrize("text", ["", "   \n\n"])
def test_empty_diff_is_an_error(text: str) -> None:
    with pytest.raises(EmptyDiff, match="diff is empty"):
        parse_diff(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("isto não é um diff\n", "no file headers found"),
        ("@@ -1 +1 @@\n-a\n+b\n", "hunk without a file header"),
        ("--- a/x\n+++ b/x\n@@ -a +b @@\n", "invalid hunk header"),
        ("--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n a\n", "hunk ends early"),
        ("--- a/x\n+++ b/x\n@@ -1 +1 @@\n*a\n", "unexpected line in hunk"),
    ],
)
def test_unreadable_diff_is_a_clear_error(text: str, message: str) -> None:
    with pytest.raises(InvalidDiff, match=message):
        parse_diff(text)


def test_prepare_validates_focus_and_language() -> None:
    with pytest.raises(UnknownOption, match="unknown focus: speed"):
        prepare_change(GIT_DIFF, focus=("speed",))
    with pytest.raises(UnknownOption, match="unknown language: cobol"):
        prepare_change(GIT_DIFF, language="cobol")
    change = prepare_change(GIT_DIFF, focus=("security",), language="ruby")
    assert [file.language for file in change.files] == ["python", None]
    assert change.focus == ("security",)


def test_language_hint_only_applies_to_files_without_extension() -> None:
    assert language_of("bin/tool", "python") == "python"
    assert language_of("notes.md", "python") is None
    assert language_of("src/app.TS") == "typescript"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_rules.py", True),
        ("pkg/rules_test.go", True),
        ("web/button.spec.ts", True),
        ("src/__tests__/app.js", True),
        ("src/testing.py", False),
        ("src/contest.py", False),
    ],
)
def test_test_files_are_recognized(path: str, expected: bool) -> None:
    assert is_test(path) is expected


def test_triage_records_binary_and_large_files() -> None:
    big = "".join(f"+line {n}\n" for n in range(MAX_FILE_LINES + 1))
    text = (
        "diff --git a/logo.png b/logo.png\n"
        "Binary files a/logo.png and b/logo.png differ\n"
        f"--- a/big.py\n+++ b/big.py\n@@ -0,0 +1,{MAX_FILE_LINES + 1} @@\n{big}"
        "--- a/ok.py\n+++ b/ok.py\n@@ -0,0 +1 @@\n+ok = 1\n"
    )
    reviewable, unreviewed = triage(prepare_change(text).files)
    assert [file.path for file in reviewable] == ["ok.py"]
    assert [(item.path, item.reason.split(":")[0]) for item in unreviewed] == [
        ("logo.png", "arquivo binário"),
        ("big.py", "grande"),
    ]


def test_parts_group_whole_files_within_the_budget() -> None:
    files = prepare_change(GIT_DIFF).files
    sizes = [len(file.text) for file in files]
    assert split_parts(files, budget=sum(sizes)) == (files,)
    assert split_parts(files, budget=max(sizes)) == ((files[0],), (files[1],))
    assert split_parts((), budget=10) == ()
