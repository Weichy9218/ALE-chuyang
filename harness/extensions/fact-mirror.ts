/**
 * fact-mirror: 事实反射(镜子非地图)。
 *
 * 三面镜子,全部只反射客观可核查的事实:
 *   1. 失败连击:同一条 bash 命令连续失败 >=N 次时,在工具结果末尾追加一行
 *      "这条命令已连续失败 N 次"。(agent 自己行为的事实)
 *   2. 声明文件存在性:agent 准备收工(assistant 消息不含工具调用)时,检查任务
 *      描述里提到的文件路径当前是否存在,把"仍不存在的路径清单"作为 follow-up
 *      事实反射回去。只查存在性,不查内容,不说该怎么产出。
 *   3. 指标对照(可选,默认关):从 agent 自己产出的结果文件里读一个数值,与任务
 *      公开规格声明的阈值并排反射:"当前值 X,任务声明的目标 op T,当前不满足"。
 *      阈值必须来自 agent 本就可见的任务规格(task_specification),不许来自
 *      评测器或参考答案。不说怎么达标。
 *
 * strip 测试:三面镜子反射的都是 agent 能自己查到的事实(重跑命令、ls 输出目录、
 * cat 自己的结果文件)。删掉扩展,模型仍能产出正确行为,只是可能忘记核对就收工。
 *
 * 环境变量:
 *   PI_GUARD_MIRROR=off          整体关闭(默认 on)
 *   PI_MIRROR_FAIL_STREAK_N=2    镜子 1 的阈值
 *   PI_MIRROR_FILES=off          单独关闭镜子 2
 *   PI_MIRROR_MAX_NUDGES=2       镜子 2/3 各自最多反射次数(防无限循环)
 *   PI_MIRROR_METRIC_SPEC        镜子 3 的 JSON 配置,如
 *     [{"file":"results.json","path":"tier3.exploitability","op":"<=","target":0.05,"label":"tier3 exploitability"}]
 *     只能从任务公开规格抄阈值;设了才启用。
 */
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TAG = "[harness mirror]";

interface MetricSpec {
	file: string;
	path: string;
	op: "<=" | ">=" | "<" | ">" | "==";
	target: number;
	label?: string;
}

function normCmd(cmd: string): string {
	return cmd.replace(/\s+/g, " ").trim();
}

/** 从任务 prompt 里抓出看起来是文件路径的 token(带扩展名的相对/绝对路径)。 */
function extractDeclaredPaths(prompt: string): string[] {
	const re = /(?:[A-Za-z0-9_.\-~]+\/)*[A-Za-z0-9_.\-]+\.(?:json|jsonl|npy|npz|csv|tsv|txt|md|xml|sgf|yaml|yml|h5|hdf5|pkl|pt|safetensors|py|sh|cfg|ini|idf|urdf)\b/g;
	const seen = new Set<string>();
	for (const m of prompt.match(re) ?? []) {
		// 过滤明显不是产物路径的噪声(URL 片段、版本号样式)。
		if (m.includes("://")) continue;
		seen.add(m);
	}
	return [...seen];
}

function jsonPath(obj: unknown, dotted: string): unknown {
	let cur: any = obj;
	for (const key of dotted.split(".")) {
		if (cur == null || typeof cur !== "object") return undefined;
		cur = cur[key];
	}
	return cur;
}

function opHolds(v: number, op: MetricSpec["op"], t: number): boolean {
	switch (op) {
		case "<=": return v <= t;
		case ">=": return v >= t;
		case "<": return v < t;
		case ">": return v > t;
		case "==": return v === t;
	}
}

export default function factMirror(pi: ExtensionAPI) {
	if ((process.env.PI_GUARD_MIRROR ?? "on") === "off") return;

	const streakN = Math.max(2, Number.parseInt(process.env.PI_MIRROR_FAIL_STREAK_N ?? "2", 10) || 2);
	const filesOn = (process.env.PI_MIRROR_FILES ?? "on") !== "off";
	const maxNudges = Math.max(0, Number.parseInt(process.env.PI_MIRROR_MAX_NUDGES ?? "2", 10) || 2);

	let metricSpecs: MetricSpec[] = [];
	try {
		const raw = process.env.PI_MIRROR_METRIC_SPEC;
		if (raw) metricSpecs = JSON.parse(raw);
	} catch {
		// 配置坏了就当没配,镜子绝不能让运行崩溃。
	}

	const failStreak = new Map<string, number>();
	let declaredPaths: string[] = [];
	let fileNudges = 0;
	let metricNudges = 0;

	pi.on("before_agent_start", (ev) => {
		declaredPaths = extractDeclaredPaths(ev.prompt);
	});

	// 镜子 1:失败连击,附加在工具结果末尾(afterToolCall 反射面)。
	pi.on("tool_result", (ev) => {
		if (ev.toolName !== "bash") return;
		const input = ev.input as Record<string, unknown>;
		const cmd = typeof input.command === "string" ? normCmd(input.command) : "";
		if (!cmd) return;
		if (!ev.isError) {
			failStreak.delete(cmd);
			return;
		}
		const n = (failStreak.get(cmd) ?? 0) + 1;
		failStreak.set(cmd, n);
		if (n >= streakN) {
			return {
				content: [...ev.content, { type: "text" as const, text: `\n${TAG} fact: this exact command has now failed ${n} times in a row.` }],
			};
		}
	});

	// 镜子 2 + 3:收工时机的事实反射(turn_end 看这轮 assistant 消息是否不含工具调用)。
	pi.on("turn_end", (ev, ctx) => {
		const parts = (ev.message as { content?: Array<{ type?: string }> }).content ?? [];
		const stopping = Array.isArray(parts) && !parts.some((p) => p?.type === "toolCall");
		if (!stopping) return;

		const facts: string[] = [];

		if (filesOn && fileNudges < maxNudges && declaredPaths.length) {
			const missing = declaredPaths.filter((p) => !fs.existsSync(path.resolve(ctx.cwd, p)));
			if (missing.length) {
				fileNudges += 1;
				facts.push(
					`${TAG} fact: these paths are mentioned in the task description and currently do not exist under ${ctx.cwd}: ` +
						`${missing.slice(0, 12).join(", ")}${missing.length > 12 ? ` (+${missing.length - 12} more)` : ""}. ` +
						`This is an existence check only; decide for yourself whether they are required.`,
				);
			}
		}

		if (metricSpecs.length && metricNudges < maxNudges) {
			const unmet: string[] = [];
			for (const spec of metricSpecs) {
				try {
					const fp = path.resolve(ctx.cwd, spec.file);
					if (!fs.existsSync(fp)) continue;
					const v = jsonPath(JSON.parse(fs.readFileSync(fp, "utf-8")), spec.path);
					if (typeof v === "number" && !opHolds(v, spec.op, spec.target)) {
						unmet.push(`${spec.label ?? spec.path} in ${spec.file} is ${v}; the task-declared target is ${spec.op} ${spec.target}; the target is currently not met`);
					}
				} catch {
					// 结果文件读不动就沉默,镜子不制造新错误。
				}
			}
			if (unmet.length) {
				metricNudges += 1;
				facts.push(`${TAG} fact: ${unmet.join(". ")}.`);
			}
		}

		if (facts.length) {
			pi.sendUserMessage(facts.join("\n"), { deliverAs: "followUp" });
		}
	});
}
