import pytest

from agent_sample.domain.diff import is_test_path, language_of, normalize, parse_diff
from agent_sample.domain.model import EmptyDiff, InvalidDiff
from tests.fakes import SOURCE_DIFF

MIXED = """diff --git a/old.py b/new.py
similarity index 90%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1,2 +1,2 @@
 a = 1
-b = 2
+b = 3
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
diff --git a/img.png b/img.png
new file mode 100644
Binary files /dev/null and b/img.png differ
diff --git a/uv.lock b/uv.lock
--- a/uv.lock
+++ b/uv.lock
@@ -1 +1 @@
-a
+b
diff --git a/docs/a.md b/docs/a.md
--- a/docs/a.md
+++ b/docs/a.md
@@ -1 +1,2 @@
 # A
+text
\\ No newline at end of file
"""


def test_parses_files_hunks_and_new_line_numbers() -> None:
    (file,) = parse_diff(SOURCE_DIFF)
    assert file.path == "src/app.py"
    assert file.status == "modified"
    assert [line.new_line for line in file.added] == [2, 3, 4]
    assert file.has_new_line(1) and file.has_new_line(4)
    assert not file.has_new_line(9)
    assert file.contains("+    return total / len(items)")
    assert not file.contains("return nothing")


def test_statuses_and_unreviewed_reasons() -> None:
    files = {file.path: file for file in parse_diff(MIXED)}
    assert files["new.py"].status == "renamed"
    assert files["new.py"].old_path == "old.py"
    assert files["gone.py"].status == "deleted"
    assert files["img.png"].binary
    change = normalize(tuple(files.values()), max_file_lines=100)
    assert change.paths == ("new.py", "docs/a.md")
    reasons = {item.file: item.reason for item in change.unreviewed}
    assert reasons == {
        "gone.py": "file deleted",
        "img.png": "binary file",
        "uv.lock": "generated file",
    }


def test_large_files_are_not_reviewed() -> None:
    change = normalize(parse_diff(SOURCE_DIFF), max_file_lines=2)
    assert change.files == ()
    assert change.unreviewed[0].reason.startswith("too large")


def test_classic_unified_diff_without_git_header() -> None:
    (file,) = parse_diff("--- a/x.go\n+++ b/x.go\n@@ -1 +1 @@\n-a\n+b\n")
    assert file.path == "x.go"
    assert file.language == "go"


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_diff_is_an_error(text: str) -> None:
    with pytest.raises(EmptyDiff):
        parse_diff(text)


@pytest.mark.parametrize(
    "text",
    [
        "hello world",
        "--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n",
        "--- a/x\n+++ b/x\n@@ nonsense @@\n",
    ],
)
def test_unreadable_diff_is_an_error(text: str) -> None:
    with pytest.raises(InvalidDiff):
        parse_diff(text)


def test_languages_and_test_paths() -> None:
    assert language_of("a/b.tsx") == "typescript"
    assert language_of("README.md") == "docs"
    assert language_of("Makefile") == "unknown"
    assert is_test_path("tests/test_x.py")
    assert is_test_path("pkg/x_test.go")
    assert is_test_path("web/a.spec.ts")
    assert not is_test_path("src/testing_utils.py")
