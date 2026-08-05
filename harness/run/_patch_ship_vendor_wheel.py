"""One-shot idempotent patch: add the argus _vendor wheel ship pattern to pgl's
sandbox.py. The committed pgl version ships only *.py (+ pyproject, cua json,
seed_skills md); it drops the argus wheel, so in-sandbox pip install fails with
"no vendored wheel". Restores what the base arm ran with. Delete after use.
"""
from pathlib import Path

p = Path("/home/ubuntu/ale/agents-last-exam/ale_run/executors/sandbox.py")
src = p.read_text()

if "agents/*/_vendor/*.whl" in src:
    print("ALREADY PRESENT -- no change")
    raise SystemExit(0)

anchor = "            # WS2 skills-lever seed data. The .py-only sweep above drops these"
n = src.count(anchor)
assert n == 1, "anchor not unique: %d" % n

insert = (
    "            # argus vendored wheel: the agent package is pip-installed\n"
    "            # in-sandbox from this wheel (deployer._resolve_argus_requirement).\n"
    "            # The .py-only sweep drops it, so ship it explicitly. Scoped to\n"
    "            # _vendor so it cannot sweep stray wheels elsewhere in the tree.\n"
    '            "agents/*/_vendor/*.whl",\n'
)

src = src.replace(anchor, insert + anchor, 1)
p.write_text(src)
print("PATCHED -- inserted _vendor/*.whl pattern before the seed_skills block")
