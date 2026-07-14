/**
 * action-guard: 动作前守卫(镜子非地图)。
 *
 * 挂点:tool_call(动作前拦截)+ tool_result(状态记账)。
 * 两条规则,都只反射 agent 自己行为的事实:
 *   1. 改前先读:edit/write 一个磁盘上已存在、但本会话从未 read 过的文件时拦截一次。
 *   2. 重复失败:同一条 bash 命令已连续失败 >=2 次、又要原样执行时拦截一次。
 *
 * 拦截语义是一次性的:同一目标只拦一次,agent 重发同一动作即放行。
 * 这保证守卫最多给任何动作加一步延迟,绝不会把 agent 锁死。
 * 拦截文本只含事实(未读过/已失败 N 次)与放行规则,不含怎么改、怎么修。
 * strip 测试:删掉本扩展,模型仍会自己读文件、自己换命令,只是有时忘。
 *
 * 环境变量:
 *   PI_GUARD_ACTION=off          整体关闭(默认 on)
 *   PI_GUARD_READ_BEFORE=off     单独关闭规则 1
 *   PI_GUARD_REPEAT_FAIL=off     单独关闭规则 2
 *   PI_GUARD_REPEAT_N=2          规则 2 的连续失败次数阈值
 */
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TAG = "[harness guard]";

function normCmd(cmd: string): string {
	return cmd.replace(/\s+/g, " ").trim();
}

export default function actionGuard(pi: ExtensionAPI) {
	if ((process.env.PI_GUARD_ACTION ?? "on") === "off") return;
	const readBeforeOn = (process.env.PI_GUARD_READ_BEFORE ?? "on") !== "off";
	const repeatFailOn = (process.env.PI_GUARD_REPEAT_FAIL ?? "on") !== "off";
	const repeatN = Math.max(1, Number.parseInt(process.env.PI_GUARD_REPEAT_N ?? "2", 10) || 2);

	/** 本会话已"见过"内容的文件:read/write/edit 成功过的路径。 */
	const knownFiles = new Set<string>();
	/** 规则 1 已拦截过的路径(一次性)。 */
	const blockedPaths = new Set<string>();
	/** 命令 -> 连续失败次数。任何一次成功即清零。 */
	const failStreak = new Map<string, number>();
	/** 规则 2 已拦截过的命令(一次性,直到该命令下次成功才重新武装)。 */
	const blockedCmds = new Set<string>();

	pi.on("tool_result", (ev, ctx) => {
		const input = ev.input as Record<string, unknown>;
		if ((ev.toolName === "read" || ev.toolName === "write" || ev.toolName === "edit") && !ev.isError) {
			const p = input.path ?? input.file_path ?? input.filePath;
			if (typeof p === "string" && p) knownFiles.add(path.resolve(ctx.cwd, p));
		}
		if (ev.toolName === "bash") {
			const cmd = typeof input.command === "string" ? normCmd(input.command) : "";
			if (!cmd) return;
			if (ev.isError) {
				failStreak.set(cmd, (failStreak.get(cmd) ?? 0) + 1);
			} else {
				failStreak.delete(cmd);
				blockedCmds.delete(cmd);
			}
		}
	});

	pi.on("tool_call", (ev, ctx) => {
		const input = ev.input as Record<string, unknown>;

		// 规则 1:改前先读(仅对磁盘上已存在的文件;新建文件不拦)。
		if (readBeforeOn && (ev.toolName === "edit" || ev.toolName === "write")) {
			const raw = input.path ?? input.file_path ?? input.filePath;
			if (typeof raw === "string" && raw) {
				const p = path.resolve(ctx.cwd, raw);
				if (!knownFiles.has(p) && !blockedPaths.has(p) && fs.existsSync(p)) {
					blockedPaths.add(p);
					return {
						block: true,
						reason:
							`${TAG} fact: ${p} already exists on disk and has not been read in this session. ` +
							`This ${ev.toolName} was not executed. Re-issuing the same call will go through.`,
					};
				}
			}
		}

		// 规则 2:重复执行同一条已连续失败的命令。
		if (repeatFailOn && ev.toolName === "bash") {
			const cmd = typeof input.command === "string" ? normCmd(input.command) : "";
			const streak = cmd ? (failStreak.get(cmd) ?? 0) : 0;
			if (cmd && streak >= repeatN && !blockedCmds.has(cmd)) {
				blockedCmds.add(cmd);
				return {
					block: true,
					reason:
						`${TAG} fact: this exact command has failed ${streak} times in a row in this session. ` +
						`This call was not executed. Re-issuing the same command will go through.`,
				};
			}
		}
		return undefined;
	});
}
