"""Gate: fails if Spanish prose is left in a source file.

Deliberately crude — a word list, not a language detector. The point is to be a gate a
model cannot argue with, and a false positive is cheap to fix by hand. It only looks at
comments and docstrings, because string literals may legitimately hold Spanish (a phrase
list for detecting abstention, a question from a Spanish corpus).

Usage:  python3 scripts/check_english.py <file> [file...]
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Function words that are unambiguous in Spanish and rare in English prose.
SPANISH = re.compile(
    r"\b(que|para|una|del|los|las|por|con|sin|este|esta|esto|como|cuando|donde|"
    r"porque|pero|mas|muy|todo|toda|todos|hay|son|ser|esta|estan|tiene|tienen|"
    r"hace|hacer|puede|pueden|si|no se|lo que|de la|en el|al |es un|es una)\b",
    re.IGNORECASE,
)
# Accented characters only appear in Spanish here.
ACCENTS = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡]")


def offending_lines(path: Path) -> list[tuple[int, str]]:
    src = path.read_text("utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()

    # Docstring spans, so string literals that are NOT docstrings are excluded.
    doc_spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body:
                first = node.body[0]
                doc_spans.append((first.lineno, getattr(first, "end_lineno", first.lineno)))

    bad = []
    for i, line in enumerate(lines, start=1):
        in_doc = any(a <= i <= b for a, b in doc_spans)
        stripped = line.strip()
        is_comment = stripped.startswith("#")
        if not (in_doc or is_comment):
            continue
        hits = len(SPANISH.findall(line))
        if hits >= 2 or (hits >= 1 and ACCENTS.search(line)):
            bad.append((i, stripped[:88]))
    return bad


def main(paths: list[str]) -> int:
    total = 0
    for p in paths:
        bad = offending_lines(Path(p))
        total += len(bad)
        for n, text in bad:
            print(f"{p}:{n}: {text}")
    if total:
        print(f"\n✗ {total} line(s) still look Spanish")
        return 1
    print(f"✓ {len(paths)} file(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
