#!/usr/bin/env python3
"""User-facing launcher. Reads harness/run/settings.yaml (the single control
surface), generates one ale_claw preset per requested arm + one experiment yaml
into the stack, and prints (or runs with --launch) the exact launch command.

Every arm changes exactly the switches its ARMS row declares; after the presets
are written, the launcher reads them back and aborts on any mismatch, and it
prints the resolved switch matrix. Both exist because one round was lost to an
arm whose label did not describe its real manipulation.

Stdlib only (no PyYAML) — runs with any python3. See harness/run/README.md.

Usage on the run box, from the stack dir:
  python3 harness/run/launch.py --stack . --per-arm            # print the command
  python3 harness/run/launch.py --stack . --per-arm --launch   # generate + run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import presets as brc  # noqa: E402  (stdlib-only helper library; see presets.py)

# The experimental switches, per arm. Skills stay code-compatible but are
# absent as an axis after the v2 run showed no positive signal at 26/26
# successful loads.
#   task_specific_prep - a prep sub-agent scouts the task and writes a plan
#                        before the writer starts. Isolates the "understand
#                        first" lever.
#   reviewer_audit     - independent, source-grounded delivery audit with a HARD
#                        zero-discrepancy gate (a faithful port of argus's
#                        Reviewer). It coerces the writer's "done" to "continue"
#                        until every discrepancy counter is zero over the bundle.
#                        The `reviewer` arm turns it on with everything else off,
#                        so it is A/B-comparable against `base`.
# NOTE: the LLM-verifier arm family (verifier / verifier_l1 / prep_verifier /
# self_review_hint) was retired 2026-08-05 — the candidate-suite/self-check layer
# showed no measurable effect and only confounded the harness lever. All its
# switches, config fields, and code paths were removed 2026-08-05; only the
# snapshot infrastructure it shared with the reviewer arm survives.
ARM_SWITCHES = (
    "task_specific_prep",
    "reviewer_audit",
)
ARMS: dict[str, dict[str, bool]] = {
    "base": dict(task_specific_prep=False, reviewer_audit=False),
    "prep": dict(task_specific_prep=True, reviewer_audit=False),
    # The high-value arm: base solver + argus-style independent audit gate.
    "reviewer": dict(task_specific_prep=False, reviewer_audit=True),
}
# WS2 skills-lever arms: identical switches to base/reviewer, but the config-gen
# loop turns skill_sources ON for these (see SKILL_ARMS below). This keeps the
# skills lever an independent on/off switch layered over each harness arm, so
# {base, base_skills, reviewer, reviewer_skills} is a clean 2x2 (harness x skills).
ARMS["base_skills"] = dict(ARMS["base"])
ARMS["reviewer_skills"] = dict(ARMS["reviewer"])
SKILL_ARMS = {"base_skills", "reviewer_skills"}

# Shared budget defaults. The one source for both preset generation and the
# startup printout: a printout with its own defaults once misreported the
# actual prep budget by 20 steps.
DEFAULTS = {
    "prep_max_steps": 50,
    "prep_timeout_s": 1800,
    "reviewer_audit_max_steps": 40,
    "reviewer_audit_max_rounds": 2,
}

DEFAULT_EXP_NAME = "verifier_compare"


def _scalar(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip() for x in v[1:-1].split(",") if x.strip()]
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        return v.strip("\"'")


def load_settings(path: Path) -> dict:
    """Minimal stdlib parser for our own settings.yaml (flat keys + one nested
    level + inline lists). Avoids a PyYAML dependency so the launcher runs with
    any python, like presets.py."""
    root: dict = {}
    cur = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line[:1].isspace():
            key, _, val = line.partition(":")
            key = key.strip()
            if val.strip() == "":
                cur = root[key] = {}
            else:
                root[key] = _scalar(val)
                cur = None
        elif cur is not None:
            key, _, val = line.strip().partition(":")
            cur[key.strip()] = _scalar(val)
    return root


def verify_arm_preset(yaml_text: str, arm: str, budgets: dict[str, int]) -> list[str]:
    """Assert the generated preset carries exactly the declared manipulation.

    Line-exact matching against the file that will actually run, not against
    what the generator intended to write.
    """
    problems = []
    expected_lines = {
        f"  {key}: {'true' if flag else 'false'}"
        for key, flag in ARMS[arm].items()
    }
    expected_lines.update({
        f"  task_specific_prep_max_steps: {budgets['prep_max_steps']}",
        f"  task_specific_prep_timeout_s: {budgets['prep_timeout_s']}",
        f"  reviewer_audit_max_steps: {budgets['reviewer_audit_max_steps']}",
        f"  reviewer_audit_max_rounds: {budgets['reviewer_audit_max_rounds']}",
    })
    lines = set(yaml_text.splitlines())
    for expected in sorted(expected_lines):
        if expected not in lines:
            problems.append(f"arm {arm}: generated preset lacks {expected.strip()!r}")
    return problems


def experiment_yaml(name, agent_ids, suffix, tasks, out_root, concurrency, wall_time_s,
                    cleanup_mode="delete", secret_file="secret/.env") -> str:
    # cleanup_mode=delete removes each unit's container when it ends. Outputs are
    # pulled to .logs before cleanup, so nothing is lost. "keep" accumulates one
    # live sandbox per unit and will starve the box on a large run.
    #
    # secret_file is the ONLY effective way to select an api endpoint: the
    # runner reloads it with override=True, clobbering any env prefix on the
    # launch command. The api_endpoints prefixes therefore cannot rotate
    # endpoints on their own; a run that needs a non-default endpoint points
    # run.secret_file at a variant env file instead.
    y = (
        "# GENERATED by harness/run/launch.py — do not hand-edit.\n"
        f"name: {name}\nsecret_file: {secret_file}\n\nagents:\n"
        + "".join(f"  - configs/agents/{a}.yaml\n" for a in agent_ids)
        + "environment: configs/environments/docker_nogcs_keep.yaml\n"
        f"tasks: {tasks}\n\noutput:\n  root: {out_root}\n"
        f"concurrency: {concurrency}\nwall_time_s: {wall_time_s}\n"
        f"cleanup_mode: {cleanup_mode}\n"
    )
    if suffix:
        y += "prompt_suffix: " + brc.yaml_block_scalar(suffix, 2) + "\n"
    return y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", required=True, help="ale_run stack dir")
    ap.add_argument("--settings", default=str(HERE / "settings.yaml"))
    ap.add_argument("--launch", action="store_true", help="also run the command (nohup)")
    ap.add_argument("--per-arm", action="store_true",
                    help="one run per arm, each at run.concurrency, all launched together "
                         "(arms progress simultaneously; total = arms x concurrency)")
    ap.add_argument("--allow-endpoint-rotation", action="store_true",
                    help="permit fixing a different api endpoint per arm. This "
                         "confounds arm effects with gateway effects and is "
                         "refused by default for causal comparisons.")
    args = ap.parse_args()

    stack = Path(args.stack).resolve()
    if not (stack / "ale_run").is_dir():
        print(f"error: {stack} is not an ale_run stack", file=sys.stderr)
        return 2

    st = load_settings(Path(args.settings))
    arms = st.get("arms") or list(ARMS)
    all_skills = brc.load_skills()
    which = (st.get("skills") or {}).get("which") or list(all_skills)
    skills = {k: all_skills[k] for k in which if k in all_skills}
    prep = st.get("prep") or {}
    reviewer = st.get("reviewer") or {}
    run = st.get("run") or {}
    exp_name = str(run.get("name", DEFAULT_EXP_NAME))
    tasks = run.get("tasks", "selected_tasks/research_batch_26.txt")
    concurrency = int(run.get("concurrency", 8))
    out_root = run.get("output_root", ".logs/ale/verifier_compare")
    wall = int(run.get("wall_time_s", 86400))
    cleanup = run.get("cleanup_mode", "delete")
    secret_file = str(run.get("secret_file", "secret/.env"))
    api_eps = run.get("api_endpoints") or []
    agent = st.get("agent") or {}
    model = agent.get("model", "openai/gpt-5.6-sol")
    max_turns = int(agent.get("max_turns", 100000))
    thinking = agent.get("thinking_level", "medium")
    budgets = {
        "prep_max_steps": int(prep.get("max_steps", DEFAULTS["prep_max_steps"])),
        "prep_timeout_s": int(prep.get("timeout_s", DEFAULTS["prep_timeout_s"])),
        "reviewer_audit_max_steps": int(
            reviewer.get("max_steps", DEFAULTS["reviewer_audit_max_steps"])
        ),
        "reviewer_audit_max_rounds": int(
            reviewer.get("max_rounds", DEFAULTS["reviewer_audit_max_rounds"])
        ),
    }

    agent_ids = []
    problems: list[str] = []
    for arm in arms:
        if arm not in ARMS:
            print(f"warn: unknown arm {arm!r} (skip); valid: {list(ARMS)}", file=sys.stderr)
            continue
        switches = ARMS[arm]
        aid = f"ale_claw_{arm}"
        y = brc.ale_claw_agent_yaml(
            skills,
            with_skills=(arm in SKILL_ARMS),
            agent_id=aid,
            task_specific_prep=switches["task_specific_prep"],
            prep_max_steps=budgets["prep_max_steps"],
            prep_timeout_s=budgets["prep_timeout_s"],
            reviewer_audit=switches["reviewer_audit"],
            reviewer_audit_max_steps=budgets["reviewer_audit_max_steps"],
            reviewer_audit_max_rounds=budgets["reviewer_audit_max_rounds"],
            model=model,
            max_turns=max_turns,
            thinking_level=thinking,
        )
        problems.extend(verify_arm_preset(y, arm, budgets))
        (stack / f"configs/agents/{aid}.yaml").write_text(y, encoding="utf-8")
        agent_ids.append(aid)
    if not agent_ids:
        print("error: no valid arms", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print("error: generated presets do not match the declared arm "
              "manipulations; refusing to continue", file=sys.stderr)
        return 2

    if args.per_arm and len(agent_ids) > 1 and len(api_eps) > 1:
        if not args.allow_endpoint_rotation:
            print(
                "error: multiple api_endpoints with multiple arms fixes a "
                "different endpoint per arm, confounding arm effects with "
                "gateway effects. Use one shared endpoint, or pass "
                "--allow-endpoint-rotation if this run is not a causal "
                "comparison.",
                file=sys.stderr,
            )
            return 2
        print(
            "warning: endpoint rotation enabled; arm effects are confounded "
            "with endpoint effects in this run.",
            file=sys.stderr,
        )

    env_block = (
        "unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY\n"
        "set -a; . secret/.env; set +a\n"
        "export PATH=$HOME/.local/bin:$PATH\n"
        "GPT_SUB2API_OPENAI_BASE=${GPT_sub2api_URL%/}\n"
        "BOYUE_OPENAI_BASE=${ale_url%/}\n"
        "case $BOYUE_OPENAI_BASE in */v1) ;; *) BOYUE_OPENAI_BASE=$BOYUE_OPENAI_BASE/v1 ;; esac\n"
        "export GPT_SUB2API_OPENAI_BASE BOYUE_OPENAI_BASE\n"
    )

    if args.per_arm:
        # One experiment per arm, each at `concurrency`, all launched together so
        # the arms advance simultaneously. All nest under out_root -> summarize
        # reads the shared root and groups by arm id.
        runs = []
        for aid in agent_ids:
            nm = f"{exp_name}_{aid.replace('ale_claw_', '')}"
            (stack / f"exp_{nm}.yaml").write_text(
                experiment_yaml(nm, [aid], brc.INVARIANT, tasks, out_root, concurrency, wall, cleanup, secret_file),
                encoding="utf-8")
            runs.append(nm)
        launch = env_block + "".join(
            ((api_eps[i % len(api_eps)] + " ") if api_eps else "")
            + f"nohup .venv/bin/python -m ale_run run exp_{nm}.yaml > {nm}.log 2>&1 & disown\n"
            for i, nm in enumerate(runs))
        target = out_root
        mode = f"per-arm ({len(runs)} runs x concurrency {concurrency} = {len(runs) * concurrency} total)"
    else:
        (stack / f"exp_{exp_name}.yaml").write_text(
            experiment_yaml(exp_name, agent_ids, brc.INVARIANT, tasks, out_root, concurrency, wall, cleanup, secret_file),
            encoding="utf-8")
        launch = env_block + (
            f"nohup .venv/bin/python -m ale_run run exp_{exp_name}.yaml > {exp_name}.log 2>&1 & disown\n")
        target = f"{out_root}/{exp_name}"
        mode = f"combined (1 run x concurrency {concurrency})"

    print(f"# agent:  model={model} max_turns={max_turns} thinking={thinking}")
    print(f"# mode:   {mode}   cleanup_mode={cleanup}")
    print("# arm matrix (verified against the generated presets):")
    for aid in agent_ids:
        arm = aid.replace("ale_claw_", "")
        flags = " ".join(
            f"{key}={'on' if ARMS[arm][key] else 'off'}" for key in ARM_SWITCHES
        )
        print(f"#   {arm:<17} {flags}")
    api_mode = (
        f"{len(api_eps)} endpoint(s) rotated across arms"
        if api_eps
        else "one shared endpoint from secret/.env"
    )
    print(f"# api:    {api_mode}")
    print(f"# secret: {secret_file} (the runner reloads this with override; "
          "it decides the real endpoint)")
    print(
        f"# prep:   max_steps={budgets['prep_max_steps']} "
        f"timeout_s={budgets['prep_timeout_s']}"
    )
    print(
        f"# review: max_steps={budgets['reviewer_audit_max_steps']} "
        f"max_rounds={budgets['reviewer_audit_max_rounds']} "
        "(reviewer arm: independent source-grounded audit + hard zero-diff gate)"
    )
    print("# ---- launch command (run from the stack dir) ----")
    print(launch)
    print("# ---- inspect results ----")
    print(f"python3 harness/run/summarize.py {target} --baseline ale_claw_base")

    if args.launch:
        print("# ---- launching ----", flush=True)
        subprocess.run(["bash", "-lc", launch], cwd=str(stack), check=False)
        print("launched (nohup).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
