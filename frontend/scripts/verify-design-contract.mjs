/**
 * Cross-cutting design contract checks (CSS + TS/TSX string literals).
 * Complements ESLint rules in eslint/terra-design-plugin.mjs.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

// Node 18 compatible (import.meta.dirname is Node 20.11+ only).
const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const SRC = join(ROOT, "src");

const FORBIDDEN_TAILWIND_HUE = /\b(purple|indigo|violet|fuchsia)(-[a-z0-9]+)?\b/;

/** @param {string} dir */
function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === "dist") continue;
      walk(full, acc);
    } else {
      acc.push(full);
    }
  }
  return acc;
}

function stripLineComments(line) {
  const idx = line.indexOf("//");
  if (idx === -1) return line;
  return line.slice(0, idx);
}

/** @param {string} filePath */
function checkFile(filePath) {
  const rel = relative(ROOT, filePath).replaceAll("\\", "/");
  if (rel === "src/tokens/primitives.ts") return [];

  const text = readFileSync(filePath, "utf8");
  const issues = [];

  const ext = rel.endsWith(".css") ? "css" : rel.endsWith(".tsx") || rel.endsWith(".ts") ? "ts" : "other";
  if (ext === "other") return issues;

  const lines = text.split(/\r?\n/);
  lines.forEach((rawLine, i) => {
    const line = stripLineComments(rawLine);
    if (!line.trim()) return;
    if (FORBIDDEN_TAILWIND_HUE.test(line)) {
      issues.push(`${rel}:${i + 1}: forbidden hue keyword in ${ext} source`);
    }
  });

  return issues;
}

const files = walk(SRC);
const all = files.flatMap(checkFile);

if (all.length) {
  console.error("Design contract violations:\n" + all.join("\n"));
  process.exitCode = 1;
}
