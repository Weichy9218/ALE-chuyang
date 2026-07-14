#!/usr/bin/env python3
"""冒烟断言:读 pi 的 transcript.jsonl,核对每个场景应触发的干预确实出现。"""
import json
import sys
from pathlib import Path


def load_events(run_root: Path):
    events = []
    for line in (run_root / "transcript.jsonl").read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def message_texts(events, role=None):
    out = []
    for e in events:
        if e.get("type") != "message_end":
            continue
        m = e.get("message") or {}
        if role and m.get("role") != role:
            continue
        parts = m.get("content")
        if isinstance(parts, str):
            out.append(parts)
            continue
        for c in parts or []:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(c.get("text", ""))
    return out


def main():
    scenario, run_root = sys.argv[1], Path(sys.argv[2])
    events = load_events(run_root)
    if not events:
        print("FAIL: transcript 为空,先看 stderr.log / mock.log")
        sys.exit(1)

    tool_results = message_texts(events, role="toolResult")
    user_msgs = message_texts(events, role="user")
    assistant_n = sum(
        1 for e in events
        if e.get("type") == "message_end" and (e.get("message") or {}).get("role") == "assistant"
    )
    all_text = "\n".join(tool_results + user_msgs)

    checks: list[tuple[str, bool]] = []
    if scenario == "guard":
        checks = [
            ("未读先改被拦(guard fact 出现在工具结果)",
             any("[harness guard] fact" in t and "has not been read" in t for t in tool_results)),
            ("重复失败命令被拦",
             any("[harness guard] fact" in t and "failed" in t and "in a row" in t for t in tool_results)),
            ("失败连击被镜子追加进结果",
             any("[harness mirror] fact" in t and "failed" in t for t in tool_results)),
            ("收工时缺文件事实被反射(follow-up user 消息)",
             any("[harness mirror] fact" in t and "do not exist" in t for t in user_msgs)),
            ("反射后 agent 补产出并再次收工(assistant 轮数 >= 8)", assistant_n >= 8),
        ]
    elif scenario == "loop":
        checks = [
            ("软提醒出现(budget usage fact)",
             any("[harness budget] usage fact" in t for t in user_msgs)),
            ("预算耗尽后工具调用被封锁(结果里出现 budget exhausted)",
             any("[harness budget]" in t and "budget exhausted" in t for t in tool_results)),
            ("收尾宽限后兜底退出(assistant 轮数 <= 上限3+宽限3+2)", assistant_n <= 8),
        ]
    elif scenario == "metric":
        checks = [
            ("指标对照事实被反射(1.17 vs <= 0.05)",
             any("[harness mirror] fact" in t and "not met" in t for t in user_msgs)),
            ("反射恰好一次(nudge 上限=1)",
             sum(1 for t in user_msgs if "[harness mirror] fact" in t) == 1),
        ]

    ok = True
    for name, passed in checks:
        print(("PASS  " if passed else "FAIL  ") + name)
        ok = ok and passed
    print(f"-- assistant turns: {assistant_n}, tool results: {len(tool_results)}, "
          f"injected user msgs: {sum(1 for t in user_msgs if '[harness' in t)}")
    if not ok:
        print(f"-- transcript: {run_root/'transcript.jsonl'}")
        sys.exit(1)


if __name__ == "__main__":
    main()
