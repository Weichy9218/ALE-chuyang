# argus — the Argus 4-role harness as an ALE agent

Argus (`argus-skill`) drives Manager → Planner → Engineer → Reviewer, each role
being one `codex exec` subprocess. It has no model of its own, so this agent is
"the codex agent under a supervisor" rather than a new engine.

## Why `executor: sandbox` and nothing else

`ale_claw` is the only ALE agent that runs on the harness host, and it can only
do that because it implements its own tool layer: every exec and file call it
makes is an RPC into the eval VM. Argus's execution surface is the codex CLI's
*built-in* shell and file tools, which act on whichever machine codex runs on.
Host-side, the roles would work on the harness box while the graded deliverable
was supposed to appear in the VM.

Under `SandboxExecutor` the deployer, argus, codex, and every role's shell all
live inside the evaluation VM. The task's exact output paths become ordinary
local paths, the harness host is unreachable by construction, and the only
thing still needing a bridge is the GUI — supplied by the same cua MCP server
the codex agent uses.

## Flow

```
lifecycle
  -> ArgusDeployer.install()
       provision the pinned codex fork + node + cua MCP bridge + ~/.codex/config.toml
         (delegated verbatim to CodexDeployer.install via a config view)
       pip install argus-skill, then assert the ale_last_exam vertical loads
  -> ArgusDeployer.launch(prompt)
       spawn: python -m ale_run.agents.argus._launcher <spec.json>   (own process group)
         chdir into work_dir/project
         open an episode-private ARGUS_SKILL_HOME under work_dir
         commit vertical=ale_last_exam into research/PIPELINE_STATE.json
         pin Manager.decide_vertical (unless config.manager_division)
         _invoke_supervisor(continuous=True, objective=<ALE instruction>)
       poll; on episode timeout SIGTERM/SIGKILL the whole group
  -> ArgusDeployer.parse_artifacts()
       merge events.jsonl + agent_io.jsonl on ts, reuse the codex NDJSON mapping
```

## work_dir layout (gathered to the host)

```
prompt.txt                                  the ALE instruction
spec.json                                   launcher input
argus_summary.json                           supervisor summary, or a traceback
argus_stdout.log / argus_stderr.log
argus_home/projects/ale/events.jsonl        orchestration events + role start/complete
argus_home/projects/ale/agent_io.jsonl      raw codex frames per role invocation
argus_home/projects/ale/research/PIPELINE_STATE.json
project/                                    the roles' cwd
```

## Two things that silently break the run

**The vertical.** `resolve_vertical` reads `research/PIPELINE_STATE.json`, and a
missing marker does not fail — it falls back to the `research` (paper) vertical
and the episode spends its budget on a paper pipeline. Worse, several
prompt-building layers resolve it from `Path.cwd()` rather than from the workdir
they were handed, which is why the launcher `chdir`s instead of only exporting
`ARGUS_SKILL_WORKDIR`. Both roots get the marker.

**The model catalog.** codex refuses a model that is not in its catalog. Any
gateway model outside the bundled set (`gpt-5.6-sol` included) needs
`model_catalog_path`; `install()` only warns, because the warning is cheaper to
read than a failure in every role.

## Cost

One episode is at minimum: Manager division (skipped by default via the pin),
one Planner cycle, then N × (Engineer + Reviewer). Budget several times an
ale_claw episode on the same task and measure on a small task subset before
committing to the full set.
