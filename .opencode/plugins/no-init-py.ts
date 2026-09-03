import type { Plugin } from "@opencode-ai/plugin";

/**
 * Block creation of `__init__.py` files.
 *
 * This repo uses PEP 420 implicit namespace packages: packages are plain
 * directories and package-level logic lives in named modules (e.g.
 * config/settings.py). Creating `__init__.py` is forbidden.
 *
 * Any bash command that would create a `__init__.py` is rejected with an
 * error, so the model is forced to use namespace packages.
 */

const CREATE_VERBS = /\b(?:touch|mkdir|cp|mv|tee|install)\b/;

// Matches a __init__.py token anywhere (with optional path prefix / quotes).
const INIT_PY = /(?:^|[\/\s"'\\])(?:[^'"\s;|&]*\/)?__init__\.py/;

// Redirection that writes into a __init__.py path, e.g. `echo x > a/__init__.py`.
const REDIRECT = /(?:^|[\s;&|])>+?\s*['"]?[^'";&\n]*__init__\.py/;

function blocksInitPy(command: string): boolean {
  // 1. Explicit file-creation commands touching __init__.py
  if (CREATE_VERBS.test(command) && INIT_PY.test(command)) {
    return true;
  }
  // 2. Shell redirection writing into __init__.py (echo/printf/cat/tee >> / >)
  if (REDIRECT.test(command)) {
    return true;
  }
  // 3. Inline python writing __init__.py (open(...) / Path(...) with 'w'/'touch')
  if (
    /__init__\.py/.test(command) &&
    /(?:open\(|\.write_text|\.write_bytes|\.mkdir|\.touch)/.test(command)
  ) {
    return true;
  }
  return false;
}

export const NoInitPy: Plugin = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return;
      const cmd = String(output.args?.command ?? "");
      if (blocksInitPy(cmd)) {
        throw new Error(
          "BLOCKED: this repo uses PEP 420 namespace packages — creating " +
            "__init__.py is forbidden. Package-level logic belongs in named " +
            "modules (e.g. segdete/config/settings.py), not __init__.py.",
        );
      }
    },
  };
};
