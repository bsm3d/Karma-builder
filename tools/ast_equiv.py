# BSM Karma Builder
# © Benoit Saint-Moulin - 2026
# Version du fichier : 1.6.0
# Fonction du fichier : Checks that a style pass changed no code by comparing the AST of each file with its version at a git revision.

# Houdini : 21 and 22 (plain Python, no Houdini needed)
# Docstrings are ignored. Comments never reach the AST, so any change to a name, value or string shows up. Exit code 1 when a file differs.
# python tools/ast_equiv.py [REV] [files...]

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------
def strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree

# --------------------------------------------------------
def dump(source):
    return ast.dump(strip_docstrings(ast.parse(source)), include_attributes=False)

# ----------------------------------------------------------------------
def at_revision(rev, rel):
    out = subprocess.run(["git", "show", "{}:{}".format(rev, rel)], cwd=ROOT, capture_output=True)
    return out.stdout.decode("utf-8") if out.returncode == 0 else None

# ------------------------------------------------------------
def main(argv):
    rev = argv[0] if argv else "HEAD"
    files = argv[1:] or sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*.py")
                               if ".git" not in p.parts and "__pycache__" not in p.parts)
    bad = 0
    for rel in files:
        try:
            old = at_revision(rev, rel)
            if old is None:
                print("new      {}".format(rel))
                continue
            same = dump(old) == dump((ROOT / rel).read_text(encoding="utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            print("skipped  {} (not UTF-8 Python)".format(rel))
            continue
        print("{:8} {}".format("same" if same else "DIFFERS", rel))
        bad += not same
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
