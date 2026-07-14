#!/usr/bin/env python3
"""从 ALE 的 pi 运行日志抽取 SFT / 偏好训练数据。

数据源是 ale_run 的输出目录(每个任务一次 attempt 一个目录):
    <run_root>/<domain__task>/v<k>/<timestamp>/
        run.json                     分数、状态、用量(可验证奖励)
        origin_log/pi/transcript.jsonl   pi 原始事件流(高保真训练源)
        origin_log/pi/prompt.txt     任务 prompt

产出三个文件(写到 --out 目录):
    sft.jsonl    通过筛选的成功轨迹,消息级完整(thinking/text/tool_calls/工具结果)
    pairs.jsonl  同一任务不同 attempt 的 (高分, 低分) 轨迹对,做偏好/过程监督
    stats.json   抽取统计与被筛掉原因的计数

筛选规则(都可调):
    SFT:status=completed 且 score >= --min-score;无泄露标记;步数 <= --max-steps。
    pairs:同任务两 attempt 分差 >= --pair-margin。
    泄露审计:扫描所有消息文本,命中参考答案路径样式(reference/answer/ground_truth/
    eval_result 等)即打 leak_flags;默认剔除并计数。[harness ...] 注入单独计数,
    --strip-harness 时从消息里剥掉(用于训练"无 harness 也会做"的干净样本)。

用法示例:
    python3 extract_pi_training_data.py \
        --run-root .logs/ale/gpt56_full_pi/pi/gpt-5-6-sol \
        --out samples/gpt56 --min-score 1.0 --pair-margin 0.3
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# 泄露检测分两级。
# 硬标记(剔除):agent 的工具调用实际触碰了评测专用的答案目录。
#   ALE 任务布局是 base/{input,reference,software}:base/reference/ 是评测答案,
#   base/input/ 是 agent 合法输入。答案目录统一直接挂在 base/ 下,因此只锚定
#   "base/reference" 这一层。input 子树里出现的 reference 字样(参考基因组
#   input/.../reference/GRCh38.fa、自检数据 input/reference_output)都是合法输入,
#   不会命中。prompt 只口头要求不读 base/reference,所以必须行为级核查工具参数。
TOUCH_REFERENCE = re.compile(r"\bbase/reference(?:/|\b)", re.I)
# 软标记(只记录):文本里出现这些字样(可能来自任务说明自身,不剔除)。
MENTION_PATTERNS = [
    re.compile(r"ground[_-]?truth", re.I),
    re.compile(r"answer[_-]?key", re.I),
]
HARNESS_TAG = "[harness"


def toolcall_touches_reference(name: str, arguments: dict) -> str | None:
    """工具调用参数里出现评测专用 reference 路径则返回证据串。"""
    try:
        blob = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = str(arguments)
    for m in TOUCH_REFERENCE.finditer(blob):
        seg = blob[max(0, m.start() - 60): m.end() + 20]
        if not LEGIT_INPUT_REF.search(seg):
            return f"{name}: ...{seg}..."
    return None


@dataclass
class Attempt:
    task_slug: str
    variant: str
    ts: str
    dir: Path
    score: float
    status: str
    model: str
    usage: dict
    prompt_sha: str = ""


@dataclass
class Stats:
    attempts_seen: int = 0
    no_transcript: int = 0
    sft_kept: int = 0
    drop_score: int = 0
    drop_status: int = 0
    drop_steps: int = 0
    drop_leak: int = 0
    pairs_kept: int = 0
    harness_injection_msgs: int = 0
    truncated_tool_results: int = 0
    by_task: dict = field(default_factory=dict)


def iter_attempts(run_root: Path):
    for task_dir in sorted(p for p in run_root.iterdir() if p.is_dir()):
        for vdir in sorted(task_dir.glob("v*")):
            for ts_dir in sorted(p for p in vdir.iterdir() if p.is_dir()):
                rj = ts_dir / "run.json"
                if rj.exists():
                    yield task_dir.name, vdir.name, ts_dir


def load_attempt(task_slug: str, variant: str, ts_dir: Path) -> Attempt | None:
    try:
        run = json.loads((ts_dir / "run.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return Attempt(
        task_slug=task_slug,
        variant=variant,
        ts=ts_dir.name,
        dir=ts_dir,
        score=float(run.get("score") or 0.0),
        status=str(run.get("status") or "unknown"),
        model=str((run.get("agent") or {}).get("model") or ""),
        usage=run.get("usage") or {},
    )


def transcript_path(ts_dir: Path) -> Path | None:
    for cand in (ts_dir / "origin_log" / "pi" / "transcript.jsonl",
                 ts_dir / "transcript.jsonl"):
        if cand.exists():
            return cand
    return None


def truncate_text(text: str, cap: int, stats: Stats) -> str:
    if len(text) <= cap:
        return text
    stats.truncated_tool_results += 1
    head = int(cap * 0.7)
    tail = cap - head
    return (f"{text[:head]}\n...[truncated {len(text) - cap} chars by extractor]...\n"
            f"{text[-tail:]}")


def build_messages(tpath: Path, max_obs_chars: int, strip_harness: bool, stats: Stats):
    """流式读 transcript.jsonl,只消费 message_end,重建消息序列。"""
    messages: list[dict] = []
    hard_leaks: list[str] = []
    mentions: set[str] = set()
    injections = 0
    stop_reasons: list[str] = []

    def scan_leak(text: str):
        for pat in MENTION_PATTERNS:
            if pat.search(text):
                mentions.add(pat.pattern)

    with tpath.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or '"message_end"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "message_end":
                continue
            msg = event.get("message") or {}
            role = msg.get("role")
            content = msg.get("content")

            if role == "user":
                text = content if isinstance(content, str) else "".join(
                    c.get("text", "") for c in content or []
                    if isinstance(c, dict) and c.get("type") == "text")
                if HARNESS_TAG in text:
                    injections += 1
                    if strip_harness:
                        continue
                scan_leak(text)
                messages.append({"role": "user", "content": text})

            elif role == "assistant":
                thinking_parts, text_parts, tool_calls = [], [], []
                for c in content or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "thinking":
                        thinking_parts.append(c.get("thinking", ""))
                    elif c.get("type") == "text":
                        text_parts.append(c.get("text", ""))
                    elif c.get("type") == "toolCall":
                        call = {
                            "id": c.get("id", ""),
                            "name": c.get("name", ""),
                            "arguments": c.get("arguments", {}),
                        }
                        evidence = toolcall_touches_reference(call["name"], call["arguments"])
                        if evidence:
                            hard_leaks.append(evidence)
                        tool_calls.append(call)
                rec: dict = {"role": "assistant"}
                if thinking_parts:
                    rec["thinking"] = "\n".join(thinking_parts)
                if text_parts:
                    rec["content"] = "".join(text_parts)
                if tool_calls:
                    rec["tool_calls"] = tool_calls
                if msg.get("stopReason"):
                    stop_reasons.append(msg["stopReason"])
                    if msg["stopReason"] not in ("stop", "toolUse"):
                        rec["stop_reason"] = msg["stopReason"]
                usage = msg.get("usage") or {}
                if usage:
                    rec["usage"] = {k: usage.get(k) for k in ("input", "output", "cacheRead")
                                    if usage.get(k)}
                scan_leak((rec.get("content") or "") + (rec.get("thinking") or ""))
                messages.append(rec)

            elif role == "toolResult":
                text = "".join(
                    c.get("text", "") if isinstance(c, dict) and c.get("type") == "text"
                    else json.dumps(c, ensure_ascii=False)
                    for c in content or [])
                if HARNESS_TAG in text:
                    injections += 1
                scan_leak(text)
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("toolCallId", ""),
                    "content": truncate_text(text, max_obs_chars, stats),
                    "is_error": bool(msg.get("isError")),
                })

    stats.harness_injection_msgs += injections
    return messages, hard_leaks, sorted(mentions), injections, stop_reasons


def attempt_record(a: Attempt, messages, hard_leaks, mentions, injections, stop_reasons) -> dict:
    domain, _, name = a.task_slug.partition("__")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {"harness": "pi", "run_dir": str(a.dir), "attempt_ts": a.ts},
        "task": {"slug": a.task_slug, "domain": domain, "name": name, "variant": a.variant},
        "model": a.model,
        "reward": {"score": a.score, "status": a.status, "verifier": "ale.evaluate"},
        "usage": {
            "steps": a.usage.get("total_steps"),
            "input_tokens": a.usage.get("total_input_tokens"),
            "output_tokens": a.usage.get("total_output_tokens"),
            "cache_read_tokens": a.usage.get("total_cache_read_tokens"),
            "duration_ms": a.usage.get("total_duration_ms"),
        },
        "quality": {
            "reference_touches": hard_leaks[:10],
            "leak_mentions": mentions,
            "harness_injections": injections,
            "abnormal_stop_reasons": [s for s in stop_reasons if s not in ("stop", "toolUse")],
        },
        "messages": messages,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-root", action="append", required=True, type=Path,
                    help="形如 .logs/ale/<run>/pi/<model> 的目录,可多次传")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--min-score", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=200)
    ap.add_argument("--pair-margin", type=float, default=0.3)
    ap.add_argument("--max-obs-chars", type=int, default=8000)
    ap.add_argument("--strip-harness", action="store_true",
                    help="从样本中剥掉 [harness ...] 注入消息(训练无 harness 的干净行为)")
    ap.add_argument("--keep-leaky", action="store_true",
                    help="调试用:命中泄露样式的轨迹也保留(默认剔除)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    stats = Stats()
    attempts: list[Attempt] = []

    for root in args.run_root:
        if not root.is_dir():
            raise SystemExit(f"run root 不存在: {root}")
        for task_slug, variant, ts_dir in iter_attempts(root):
            a = load_attempt(task_slug, variant, ts_dir)
            if a:
                attempts.append(a)
    stats.attempts_seen = len(attempts)

    sft_f = (args.out / "sft.jsonl").open("w", encoding="utf-8")
    with_msgs: dict[tuple, dict] = {}

    for a in attempts:
        tpath = transcript_path(a.dir)
        if not tpath:
            stats.no_transcript += 1
            continue
        messages, hard_leaks, mentions, injections, stop_reasons = build_messages(
            tpath, args.max_obs_chars, args.strip_harness, stats)
        rec = attempt_record(a, messages, hard_leaks, mentions, injections, stop_reasons)
        with_msgs[(a.task_slug, a.variant, a.ts)] = rec
        stats.by_task.setdefault(a.task_slug, []).append(
            {"ts": a.ts, "score": a.score, "status": a.status})

        # SFT 筛选,按序记录第一个命中的剔除原因。
        if hard_leaks and not args.keep_leaky:
            stats.drop_leak += 1
            continue
        if a.status != "completed":
            stats.drop_status += 1
            continue
        if a.score < args.min_score:
            stats.drop_score += 1
            continue
        steps = a.usage.get("total_steps") or 0
        if steps > args.max_steps:
            stats.drop_steps += 1
            continue
        sft_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        stats.sft_kept += 1
    sft_f.close()

    # 偏好对:同任务跨 attempt,分差达阈值。
    pairs_f = (args.out / "pairs.jsonl").open("w", encoding="utf-8")
    by_task: dict[str, list[Attempt]] = {}
    for a in attempts:
        by_task.setdefault(a.task_slug, []).append(a)
    for slug, group in sorted(by_task.items()):
        group = [a for a in group if (slug, a.variant, a.ts) in with_msgs]
        group.sort(key=lambda a: a.score, reverse=True)
        for hi in group:
            for lo in group:
                if hi.score - lo.score < args.pair_margin:
                    continue
                hi_rec = with_msgs[(slug, hi.variant, hi.ts)]
                lo_rec = with_msgs[(slug, lo.variant, lo.ts)]
                if hi_rec["quality"]["reference_touches"] or lo_rec["quality"]["reference_touches"]:
                    continue
                pairs_f.write(json.dumps({
                    "schema_version": SCHEMA_VERSION,
                    "task": slug,
                    "chosen": {"run_dir": str(hi.dir), "score": hi.score},
                    "rejected": {"run_dir": str(lo.dir), "score": lo.score},
                    "margin": round(hi.score - lo.score, 4),
                    "chosen_messages": hi_rec["messages"],
                    "rejected_messages": lo_rec["messages"],
                }, ensure_ascii=False) + "\n")
                stats.pairs_kept += 1
    pairs_f.close()

    (args.out / "stats.json").write_text(
        json.dumps(stats.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.__dict__.items() if k != "by_task"},
                     ensure_ascii=False, indent=2))
    print(f"输出: {args.out}/sft.jsonl, pairs.jsonl, stats.json")


if __name__ == "__main__":
    main()
