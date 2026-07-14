/**
 * budget-guard: 预算护栏(镜子非地图)。
 *
 * 挂点:turn_end(轮末控制)+ message_end(token 记账)+ tool_call(超预算封锁)。
 * 注入内容只有两类:
 *   1. 预算事实:已用轮数/上限、上下文占用百分比、累计 token。
 *   2. 控制信号:预算耗尽后拒绝执行新工具调用,并要求立即收工。
 * 不含任何任务内容。strip 测试:删掉本扩展,模型仍能解题,只是长任务可能失控超时。
 *
 * 硬止损是分层的,原因是 json 模式下 ctx.abort()/ctx.shutdown() 都停不掉循环
 * (abort 只打断进行中的流,轮末无流可断;shutdown 依赖 _extensionShutdownHandler,
 * 只有 interactive/rpc 模式会绑定,json/print 模式是静默空操作):
 *   L1 到达上限:tool_call 一律 block(附预算事实),同时 steer 一条"预算耗尽,
 *      立即停止并总结"。真实模型一两轮内自然收工,得到干净的 agent_end 和轨迹。
 *   L2 超限后又跑了 PI_BUDGET_GRACE_TURNS 轮还不停:process.exit(0) 兜底,
 *      防病态循环把墙钟烧完。exit 前把事实写进会话与 stderr。
 *
 * 环境变量(全部可由 ale_run 的 extra_envs 下发,用于消融):
 *   PI_GUARD_BUDGET=off            整体关闭(默认 on)
 *   PI_BUDGET_MAX_TURNS=60        硬止损轮数上限(<=0 表示不设上限)
 *   PI_BUDGET_WARN_FRAC=0.8       软提醒阈值(上限的比例)
 *   PI_BUDGET_REMIND_EVERY=10     软提醒后每 N 轮再反射一次用量事实(0=不重复)
 *   PI_BUDGET_MAX_TOTAL_TOKENS=0  可选的总 token(input+output)硬上限(0=关)
 *   PI_BUDGET_GRACE_TURNS=3       超限后允许的收尾轮数,再不停就 exit
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TAG = "[harness budget]";

function envInt(name: string, dflt: number): number {
	const v = Number.parseInt(process.env[name] ?? "", 10);
	return Number.isFinite(v) ? v : dflt;
}
function envFloat(name: string, dflt: number): number {
	const v = Number.parseFloat(process.env[name] ?? "");
	return Number.isFinite(v) ? v : dflt;
}

export default function budgetGuard(pi: ExtensionAPI) {
	if ((process.env.PI_GUARD_BUDGET ?? "on") === "off") return;

	const maxTurns = envInt("PI_BUDGET_MAX_TURNS", 60);
	const warnFrac = envFloat("PI_BUDGET_WARN_FRAC", 0.8);
	const remindEvery = envInt("PI_BUDGET_REMIND_EVERY", 10);
	const maxTotalTokens = envInt("PI_BUDGET_MAX_TOTAL_TOKENS", 0);
	const graceTurns = Math.max(1, envInt("PI_BUDGET_GRACE_TURNS", 3));

	let turns = 0;
	let totalTokens = 0;
	let warned = false;
	let lastRemindTurn = 0;
	let exhausted = false;
	let exhaustedAtTurn = 0;

	const overBudget = () =>
		(maxTurns > 0 && turns >= maxTurns) ||
		(maxTotalTokens > 0 && totalTokens >= maxTotalTokens);

	// token 记账:每条 assistant message_end 携带本轮 usage。
	pi.on("message_end", (ev) => {
		const m = ev.message as { role?: string; usage?: { input?: number; output?: number } };
		if (m.role !== "assistant" || !m.usage) return;
		totalTokens += (m.usage.input ?? 0) + (m.usage.output ?? 0);
	});

	// L1:预算耗尽后,新工具调用一律拦下,只反射事实与控制信号。
	pi.on("tool_call", () => {
		if (!exhausted) return undefined;
		return {
			block: true,
			reason:
				`${TAG} budget exhausted (${turns} turns used, limit ${maxTurns}` +
				`${maxTotalTokens > 0 ? `; ${totalTokens}/${maxTotalTokens} tokens` : ""}). ` +
				`No further tool calls will be executed. Stop and summarize the current state now.`,
		};
	});

	pi.on("turn_end", (ev, ctx) => {
		turns = ev.turnIndex + 1;
		const usage = ctx.getContextUsage();
		const ctxPct = usage?.percent != null ? `${Math.round(usage.percent)}%` : "unknown";

		if (exhausted) {
			// L2:超限后模型仍不收工,兜底退出,防止烧墙钟。
			if (turns - exhaustedAtTurn >= graceTurns) {
				console.error(
					`${TAG} grace exceeded (${turns - exhaustedAtTurn} turns past limit), exiting. ` +
					`isIdle=${ctx.isIdle()} signal=${String(ctx.signal !== undefined)}`,
				);
				pi.sendMessage({
					customType: "ale-budget-stop",
					content: `${TAG} hard exit after grace: turns=${turns}, limit=${maxTurns}.`,
					display: true,
				});
				// json 模式下 abort/shutdown 均不可用,这是唯一可靠的终止手段。
				console.error(`${TAG} calling process.exit(0) now`);
				process.exit(0);
			}
			return;
		}

		if (overBudget()) {
			exhausted = true;
			exhaustedAtTurn = turns;
			pi.sendMessage({
				customType: "ale-budget-stop",
				content:
					`${TAG} budget exhausted: turns=${turns}/${maxTurns > 0 ? maxTurns : "-"}, ` +
					`totalTokens=${totalTokens}${maxTotalTokens > 0 ? `/${maxTotalTokens}` : ""}.`,
				display: true,
			});
			pi.sendUserMessage(
				`${TAG} fact: the turn budget (${maxTurns}) is used up. From now on tool calls are ` +
				`rejected. Stop and write a final summary of what is done and what is not.`,
				{ deliverAs: "steer" },
			);
			return;
		}

		if (maxTurns <= 0) return;
		const warnAt = Math.max(1, Math.floor(maxTurns * warnFrac));
		const shouldWarnFirst = !warned && turns >= warnAt;
		const shouldRemind = warned && remindEvery > 0 && turns - lastRemindTurn >= remindEvery;
		if (shouldWarnFirst || shouldRemind) {
			warned = true;
			lastRemindTurn = turns;
			// 只反射用量事实与终止条件,不建议做什么。
			pi.sendUserMessage(
				`${TAG} usage fact: ${turns}/${maxTurns} turns used; context window ${ctxPct} full` +
					`${maxTotalTokens > 0 ? `; ${totalTokens}/${maxTotalTokens} tokens used` : ""}. ` +
					`Tool calls are rejected once the limit is reached.`,
				{ deliverAs: "steer" },
			);
		}
	});
}
