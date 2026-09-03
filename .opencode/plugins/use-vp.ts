import type { Plugin } from "@opencode-ai/plugin";

type Rewrite = { pattern: RegExp; replacement: string };

const PM = "(npm|pnpm|yarn|bun)";
const RUNNERS = "(npx|bunx|pnpm\\s+dlx|yarn\\s+dlx)";
const TSC_VITEST_PREFIX = `(${RUNNERS}|vpx|${PM}\\s+exec)`;

const DEP_SUBCOMMANDS: Record<string, string> = {
	install: "install",
	i: "install",
	ci: "install",
	add: "add",
	remove: "remove",
	rm: "remove",
	uninstall: "remove",
	un: "remove",
	update: "update",
	up: "update",
	upgrade: "update",
	dedupe: "dedupe",
	outdated: "outdated",
	list: "list",
	ls: "list",
	why: "why",
	link: "link",
	rebuild: "rebuild",
};

const REWRITES: Rewrite[] = [
	{ pattern: new RegExp(`(^|\\s)${RUNNERS}(?=\\s|$)`, "g"), replacement: "$1vpx" },
	{ pattern: new RegExp(`(^|\\s)${TSC_VITEST_PREFIX}\\s+tsc(\\s+--noEmit)?(?=\\s|$)`, "g"), replacement: "$1vp check" },
	{ pattern: new RegExp(`(^|\\s)${TSC_VITEST_PREFIX}\\s+vitest(?=\\s|$)`, "g"), replacement: "$1vp test" },
	{ pattern: /(^|\s)tsc(\s+--noEmit)?(?=\s|$)/g, replacement: "$1vp check" },
	...Object.entries(DEP_SUBCOMMANDS).map(
		([from, to]) =>
			({
				pattern: new RegExp(`(^|\\s)${PM}\\s+${from}(?=\\s|$)`, "g"),
				replacement: `$1vp ${to}`,
			}) satisfies Rewrite,
	),
	{ pattern: new RegExp(`(^|\\s)${PM}\\s+(run\\s+)?test(?=\\s|$)`, "g"), replacement: "$1vp test" },
	{ pattern: /(?<!\brun\b)(^|\s)vitest(?=\s|$)/g, replacement: "$1vp test" },
	{ pattern: new RegExp(`(^|\\s)${PM}\\s+run(?=\\s|$)`, "g"), replacement: "$1vp run" },
	{ pattern: new RegExp(`(^|\\s)${PM}\\s+exec(?=\\s|$)`, "g"), replacement: "$1vp exec" },
	{ pattern: new RegExp(`(^|\\s)${PM}\\s+start(?=\\s|$)`, "g"), replacement: "$1vp run start" },
];

export function rewriteCommand(command: string): string {
	return REWRITES.reduce((cmd, { pattern, replacement }) => cmd.replace(pattern, replacement), command);
}

export const UseVp: Plugin = async () => {
	return {
		"tool.execute.before": async (input, output) => {
			if (input.tool !== "bash") return;
			output.args.command = rewriteCommand(output.args.command);
		},
	};
};
