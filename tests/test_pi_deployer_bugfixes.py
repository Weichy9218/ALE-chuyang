"""自包含单测:验证 pi deployer 的两个 bug 修复。

副本未安装 ale_run 依赖,直接 import ale_run.agents.pi.deployer 会因
`from ale_run.base_interface import ...` 失败。这里改用 ast 从 deployer.py 源码里
只摘出要测的纯逻辑(常量 _ERROR_STOP_REASONS 与函数 detect_llm_error_stop),在一个
干净命名空间里 exec 出来,从而测的就是真实源码,而非拷贝的副本。

覆盖:
  (a) exit 0 但最后一条 assistant stopReason=error → detect 返回非 None(判失败)
  (b) 正常 stop → detect 返回 None(不误判)
  (c) 含 U+2028 的 NDJSON:split("\n") 不撕碎、splitlines() 会撕碎(对比证明修复有效)
另附:aborted / 中途报错后恢复 / 空跑 三个边界,以及对 deployer.py 源码本身的静态断言
(parse_artifacts 已改用 split("\n"),detect_llm_error_stop 未再引入 splitlines)。

运行:python3 tests/test_pi_deployer_bugfixes.py
"""
from __future__ import annotations

import ast
import json
import tempfile
from pathlib import Path

DEPLOYER = Path(__file__).resolve().parent.parent / "ale_run" / "agents" / "pi" / "deployer.py"


def _load_pure_symbols() -> dict:
    """从 deployer.py 源码里只摘出 _ERROR_STOP_REASONS 与 detect_llm_error_stop。

    用 ast 定位这两个顶层节点,单独编译执行,避免触发文件顶部的 ale_run 依赖导入。
    """
    src = DEPLOYER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted_func = "detect_llm_error_stop"
    wanted_const = "_ERROR_STOP_REASONS"
    picked: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == wanted_func:
            picked.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == wanted_const for t in node.targets
        ):
            picked.append(node)
    assert len(picked) == 2, f"未能从源码摘出目标符号,只拿到 {len(picked)} 个"
    module = ast.Module(body=picked, type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict = {"json": json, "Path": Path, "frozenset": frozenset}
    exec(compile(module, str(DEPLOYER), "exec"), ns)
    return ns


def _write_transcript(lines: list[dict]) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return p


def test_detect_llm_error_stop() -> None:
    ns = _load_pure_symbols()
    detect = ns["detect_llm_error_stop"]

    # (a) exit 0 但最后一条 assistant 是网关错误(402 配额)→ 必须判失败
    err = _write_transcript([
        {"type": "message_end",
         "message": {"role": "user", "content": [{"type": "text", "text": "task"}]}},
        {"type": "message_end",
         "message": {"role": "assistant", "stopReason": "error",
                     "errorMessage": "402 insufficient_quota"}},
    ])
    got = detect(err)
    assert got == "402 insufficient_quota", f"(a) 应捕获 402,实得 {got!r}"
    print("[a] exit0 + stopReason=error -> 判定失败,error =", got)

    # (b) 正常收尾(stopReason=stop)→ 不误判
    ok = _write_transcript([
        {"type": "message_end",
         "message": {"role": "assistant", "stopReason": "stop",
                     "content": [{"type": "text", "text": "done"}]}},
    ])
    assert detect(ok) is None, "(b) 正常结束不应判错"
    print("[b] 正常 stopReason=stop -> 不误判 (None)")

    # 边界:aborted 也算错误层
    aborted = _write_transcript([
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "aborted"}},
    ])
    assert detect(aborted) == "assistant stopReason=aborted", "aborted 应判错"
    print("[+] aborted -> 判定失败")

    # 边界:中途报错但最后一条 assistant 正常 → 不误判(只看最后一条)
    recovered = _write_transcript([
        {"type": "message_end",
         "message": {"role": "assistant", "stopReason": "error", "errorMessage": "transient"}},
        {"type": "message_end", "message": {"role": "toolResult", "content": []}},
        {"type": "message_end",
         "message": {"role": "assistant", "stopReason": "stop",
                     "content": [{"type": "text", "text": "recovered"}]}},
    ])
    assert detect(recovered) is None, "最后一条正常则不判错"
    print("[+] 中途 error 但末条正常 -> 不误判 (None)")

    # 边界:空跑(无 assistant)→ 交回 exit_code 逻辑,返回 None
    empty = _write_transcript([
        {"type": "message_end",
         "message": {"role": "user", "content": [{"type": "text", "text": "task"}]}},
    ])
    assert detect(empty) is None, "空跑应交给 exit_code 逻辑"
    print("[+] 空跑(无 assistant)-> None")

    # 边界:transcript 不存在 → None,不误伤
    assert detect(Path(tempfile.mkdtemp()) / "nope.jsonl") is None
    print("[+] transcript 缺失 -> None")


def _parse_ndjson(raw: str, splitter) -> tuple[int, int]:
    """用给定的切分方式解析 NDJSON,返回 (成功解析事件数, json.loads 失败行数)。"""
    ok = 0
    bad = 0
    for line in splitter(raw):
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
            ok += 1
        except json.JSONDecodeError:
            bad += 1
    return ok, bad


def test_split_vs_splitlines_u2028() -> None:
    # 构造 3 条 NDJSON 事件,其中一条的文本里嵌了 U+2028(行分隔符)。
    U2028 = " "
    events = [
        {"type": "message_end", "message": {"role": "user",
                                            "content": [{"type": "text", "text": "hello"}]}},
        {"type": "message_end", "message": {"role": "assistant",
                                            "content": [{"type": "text",
                                                         "text": f"line1{U2028}line2"}]}},
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop"}},
    ]
    raw = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)

    # 修复后:只按 \n 切 → 3 条事件全部完好,0 条解析失败
    ok_split, bad_split = _parse_ndjson(raw, lambda s: s.split("\n"))
    # 修复前:splitlines() 会把含 U+2028 的那条从中间切开 → 出现 json.loads 失败的碎片
    ok_lines, bad_lines = _parse_ndjson(raw, lambda s: s.splitlines())

    assert (ok_split, bad_split) == (3, 0), f"split(\\n) 应完好解析 3 条,实得 {(ok_split, bad_split)}"
    assert bad_lines > 0, "splitlines() 应把含 U+2028 的事件撕碎并产生解析失败碎片"
    assert ok_lines < 3, "splitlines() 下完好事件数应少于 3(证明发生了撕碎/丢步)"
    print(f"[c] split('\\n'): ok={ok_split} bad={bad_split}  |  "
          f"splitlines(): ok={ok_lines} bad={bad_lines}  -> 修复有效")

    # \r\n 兼容:split('\n') 后的尾部 \r 被 strip() 去掉,仍能解析
    crlf = "\r\n".join(json.dumps(e, ensure_ascii=False) for e in events)
    ok_crlf, bad_crlf = _parse_ndjson(crlf, lambda s: s.split("\n"))
    assert (ok_crlf, bad_crlf) == (3, 0), f"\\r\\n 应兼容,实得 {(ok_crlf, bad_crlf)}"
    print(f"[c] \\r\\n 兼容: ok={ok_crlf} bad={bad_crlf}")


def _called_methods(func: ast.FunctionDef) -> set[str]:
    """收集函数体内所有 `x.method(...)` 调用的方法名(只看真实调用,忽略注释)。"""
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _find_func(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"未找到函数 {name}")


def test_source_static_assertions() -> None:
    """直接对真实源码断言:修复确实落在 deployer.py(只看 AST 调用,不看注释文本)。"""
    src = DEPLOYER.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # parse_artifacts:确认真实调用了 split(...) 且不再调用 splitlines()
    pa = _find_func(tree, "parse_artifacts")
    pa_calls = _called_methods(pa)
    assert "split" in pa_calls, "parse_artifacts 应调用 raw.split(...)"
    assert "splitlines" not in pa_calls, "parse_artifacts 不应再调用 splitlines()"
    print("[static] parse_artifacts 已调用 split(),无 splitlines() 调用")

    # detect_llm_error_stop:同样不应引入 splitlines() 调用
    ds = _find_func(tree, "detect_llm_error_stop")
    assert "splitlines" not in _called_methods(ds), "detect_llm_error_stop 不应调用 splitlines()"
    print("[static] detect_llm_error_stop 未引入 splitlines() 调用")


if __name__ == "__main__":
    test_detect_llm_error_stop()
    test_split_vs_splitlines_u2028()
    test_source_static_assertions()
    print("\nALL PASSED: pi deployer 两个 bug 修复均验证通过")
