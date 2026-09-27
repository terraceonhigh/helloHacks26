# The fusion spike is a separate project with its own pyproject; the repo-root
# `uv run pytest` must not collect it. Run its tests from spike/fusion instead.
collect_ignore = ["fusion"]
