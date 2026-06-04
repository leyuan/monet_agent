"""TEMP helper for the tools.py split. Extracts named top-level blocks from
tools/__init__.py verbatim into a submodule, removing them from __init__.

Usage: python _split_helper.py <module> "<header_file>" name1 name2 ...
Deleted after the refactor.
"""
import re
import sys

INIT = "src/stock_agent/tools/__init__.py"

module = sys.argv[1]
header_file = sys.argv[2]
names = sys.argv[3:]

with open(INIT) as f:
    lines = f.readlines()

# A top-level block starts at a non-indented def/class or `NAME =`/`NAME :` assignment.
boundary = re.compile(r"^(def |class |async def |[A-Za-z_][A-Za-z0-9_]*\s*[:=])")
starts = [i for i, ln in enumerate(lines) if boundary.match(ln)]
starts.append(len(lines))  # sentinel end

def name_of(line):
    m = re.match(r"^(?:async def |def |class )?([A-Za-z_][A-Za-z0-9_]*)", line)
    return m.group(1) if m else None

# Map each start line -> (name, end_line) where end = next boundary start
blocks = {}  # name -> (start_idx, end_idx)
for k in range(len(starts) - 1):
    s = starts[k]
    e = starts[k + 1]
    nm = name_of(lines[s])
    if nm and nm not in blocks:
        blocks[nm] = (s, e)

missing = [n for n in names if n not in blocks]
if missing:
    sys.exit(f"ERROR: symbols not found as top-level blocks: {missing}")

# Collect moved line indices (whole blocks, preserving original order in file)
move_idx = set()
ordered = sorted((blocks[n] for n in names), key=lambda t: t[0])
moved_text = []
for (s, e) in ordered:
    moved_text.append("".join(lines[s:e]))
    move_idx.update(range(s, e))

with open(header_file) as hf:
    header = hf.read()

with open(f"src/stock_agent/tools/{module}.py", "w") as f:
    f.write(header)
    if not header.endswith("\n\n"):
        f.write("\n")
    f.write("\n".join(moved_text))

kept = [ln for i, ln in enumerate(lines) if i not in move_idx]
with open(INIT, "w") as f:
    f.writelines(kept)

print(f"moved {len(names)} blocks ({len(move_idx)} lines) -> tools/{module}.py")
