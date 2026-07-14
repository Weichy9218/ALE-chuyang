#!/usr/bin/env python3
"""冒烟测试用 mock OpenAI 网关(stdlib,SSE chat completions)。

按请求里已有的 assistant 消息数决定这一轮回什么,脚本化地驱动 pi 走过
守卫/镜子/预算三类干预的触发路径。用 MOCK_SCRIPT 选剧本:

  guard  : 未读先改 -> 读 -> 改 -> 同一命令连败 -> 重复执行被拦 -> 提前收工
           -> 被反射缺文件 -> 补文件 -> 收工
  loop   : 永远发 bash echo,验证 budget-guard 硬止损
  metric : 产出 metric=1.17 的结果文件后收工,验证指标对照反射
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("MOCK_PORT", "18923"))
SCRIPT = os.environ.get("MOCK_SCRIPT", "guard")

FAIL_CMD = "definitely-missing-cmd-xyz --flag"
MAKE_RESULTS = "mkdir -p output && printf '{\"metric\": 1.17}' > output/results.json"


def tool(name, args):
    return {"tool": (name, json.dumps(args))}


def text(s):
    return {"text": s}


GUARD_STEPS = [
    tool("edit", {"path": "data.txt", "edits": [{"oldText": "hello", "newText": "HELLO"}]}),
    tool("read", {"path": "data.txt"}),
    tool("edit", {"path": "data.txt", "edits": [{"oldText": "hello", "newText": "HELLO"}]}),
    tool("bash", {"command": FAIL_CMD}),
    tool("bash", {"command": FAIL_CMD}),
    tool("bash", {"command": FAIL_CMD}),
    text("Done for now."),
    tool("bash", {"command": MAKE_RESULTS}),
    text("All done."),
]

METRIC_STEPS = [
    tool("bash", {"command": MAKE_RESULTS}),
    text("Done."),
    text("Still done."),
]


def pick_step(messages):
    n = sum(1 for m in messages if m.get("role") == "assistant")
    if SCRIPT == "loop":
        return tool("bash", {"command": "echo hi"})
    steps = GUARD_STEPS if SCRIPT == "guard" else METRIC_STEPS
    if n < len(steps):
        return steps[n]
    return text("Nothing left to do.")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[mock]", fmt % args, flush=True)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        req = json.loads(body or b"{}")
        step = pick_step(req.get("messages", []))

        if step.get("tool"):
            name, args = step["tool"]
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": f"call_{int(time.time()*1000) % 100000}",
                    "type": "function",
                    "function": {"name": name, "arguments": args},
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": step["text"]}
            finish = "stop"

        base = {"id": "chatcmpl-mock", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": req.get("model", "mock-1")}
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            chunks = [
                {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
            ]
            for c in chunks:
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            msg = {"role": "assistant"}
            if step.get("tool"):
                name, args = step["tool"]
                msg["tool_calls"] = [{"id": "call_1", "type": "function",
                                      "function": {"name": name, "arguments": args}}]
                msg["content"] = None
            else:
                msg["content"] = step["text"]
            resp = {**base, "object": "chat.completion",
                    "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                    "usage": usage}
            payload = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)


if __name__ == "__main__":
    print(f"[mock] script={SCRIPT} port={PORT}", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
