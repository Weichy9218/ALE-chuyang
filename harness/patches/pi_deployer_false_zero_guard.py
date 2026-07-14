"""假零分补丁:pi --mode json 把 LLM 错误吞成 exit 0 → 被记 completed+0 分。

对应 system_issues.md 第 3.1 条。这是一个不改 pi、只改 ale_run pi deployer 的
最小修复片段:在 launch() 里 proc 退出后,倒序扫 transcript.jsonl 找最后一条
role=assistant 的 message_end,若它的 stopReason 属于 {error, aborted},就把
status 从 completed 改判 failed,并把 errorMessage 写进 AgentRunResult.error。

这样 lifecycle 的状态提升会记 failed,--resume 会重跑,基础设施故障不再和
"真做错拿 0 分"混淆。

用法:把 detect_llm_error_stop 拷进 ale_run/agents/pi/deployer.py,在 launch()
里算出 status 之后、构造 AgentRunResult 之前插一段(见文件末尾 PATCH 示意)。
本文件可独立运行做单元自检:python3 pi_deployer_false_zero_guard.py
"""
from __future__ import annotations

import json
from pathlib import Path

# stopReason 属于这些即认为是 LLM/网关层失败,不是模型正常收尾。
_ERROR_STOP_REASONS = frozenset({"error", "aborted"})


def detect_llm_error_stop(transcript_path: Path) -> str | None:
    """返回最后一条 assistant 消息的错误信息;正常结束返回 None。

    只读最后一条 assistant message_end 的 stopReason;倒序扫,遇到第一条
    assistant 即判定,避免整文件解析。transcript 缺失/空按"无法判定"处理,
    返回 None(交给既有 exit_code 逻辑),不误伤。
    """
    if not transcript_path.exists():
        return None
    try:
        lines = transcript_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
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
        if msg.get("role") != "assistant":
            continue
        stop = msg.get("stopReason")
        if stop in _ERROR_STOP_REASONS:
            return msg.get("errorMessage") or f"assistant stopReason={stop}"
        return None  # 最后一条 assistant 正常结束
    return None  # 没有 assistant 消息(空跑),交给 exit_code 逻辑


# ---- PATCH 示意:launch() 里 status 判定之后 ----
#
#     duration_s = time.monotonic() - t0
#     exit_code = proc.returncode
#     status = "completed" if exit_code == 0 else "failed"
#     error: str | None = None
#     if status == "failed":
#         error = self._diagnose_failure(stderr_log, transcript_file, exit_code)
#     # --- 新增:即便 exit 0,也要看轨迹末尾有没有 LLM 层错误 ---
#     if status == "completed":
#         llm_err = detect_llm_error_stop(transcript_file)
#         if llm_err:
#             status = "failed"
#             error = f"LLM error stop (exit 0 but stopReason=error): {llm_err[:400]}"
#     # --- 新增结束 ---
#     return AgentRunResult(status=status, ...)


def _selftest() -> None:
    import tempfile

    def write(lines: list[dict]) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "transcript.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        return p

    # 1) 正常结束
    ok = write([
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
                                             "content": [{"type": "text", "text": "done"}]}},
    ])
    assert detect_llm_error_stop(ok) is None, "正常结束不应判错"

    # 2) 网关错误(exit 0 但 stopReason=error)
    err = write([
        {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "task"}]}},
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "error",
                                            "errorMessage": "402 insufficient_quota"}},
    ])
    assert detect_llm_error_stop(err) == "402 insufficient_quota", "应捕获网关 402"

    # 3) 中途报错但最后一条 assistant 正常(不应误判)
    recovered = write([
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "transient"}},
        {"type": "message_end", "message": {"role": "toolResult", "content": []}},
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop",
                                            "content": [{"type": "text", "text": "recovered"}]}},
    ])
    assert detect_llm_error_stop(recovered) is None, "最后一条正常则不判错"

    # 4) 空跑(无 assistant)
    empty = write([
        {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "task"}]}},
    ])
    assert detect_llm_error_stop(empty) is None, "空跑交给 exit_code 逻辑"

    # 5) aborted
    aborted = write([
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "aborted"}},
    ])
    assert detect_llm_error_stop(aborted) == "assistant stopReason=aborted"

    print("pi_deployer_false_zero_guard: 5/5 selftest passed")


if __name__ == "__main__":
    _selftest()
