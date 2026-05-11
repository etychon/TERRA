/**
 * Local ESLint plugin — TERRA design guardrails (Tailwind hues + raw hex).
 */

const FORBIDDEN_TAILWIND_HUE = /\b(purple|indigo|violet|fuchsia)(-[a-z0-9]+)?\b/;
const RAW_HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

/** @param {string} filePath */
function isPrimitivesFile(filePath) {
  const normalized = filePath.replaceAll("\\", "/");
  return normalized.endsWith("/src/tokens/primitives.ts");
}

/** @param {string} filePath */
function shouldSkipHexRule(filePath) {
  const normalized = filePath.replaceAll("\\", "/");
  if (isPrimitivesFile(normalized)) return true;
  if (normalized.includes("/scripts/")) return true;
  if (normalized.endsWith(".config.mjs")) return true;
  if (normalized.includes(".test.")) return true;
  return false;
}

/** @type {import('eslint').ESLint.Plugin} */
const plugin = {
  meta: {
    name: "eslint-plugin-terra-design",
    version: "0.0.0",
  },
  rules: {
    "no-disallowed-tailwind-hues": {
      meta: {
        type: "problem",
        docs: {
          description:
            "Disallow Tailwind classes using purple / indigo / violet / fuchsia families (not Cisco-aligned).",
        },
        schema: [],
        messages: {
          forbiddenHue:
            "Disallowed Tailwind hue (purple/indigo/violet/fuchsia). Use semantic + token-backed classes instead.",
        },
      },
      create(context) {
        function checkString(value, node) {
          if (typeof value !== "string") return;
          if (FORBIDDEN_TAILWIND_HUE.test(value)) {
            context.report({ node, messageId: "forbiddenHue" });
          }
        }

        return {
          Literal(node) {
            if (typeof node.value === "string") {
              checkString(node.value, node);
            }
          },
          TemplateElement(node) {
            checkString(node.value.cooked ?? node.value.raw, node);
          },
        };
      },
    },
    "no-raw-hex-outside-primitives": {
      meta: {
        type: "problem",
        docs: {
          description:
            "Disallow raw #hex color literals outside primitives.ts (use tokens + CSS variables).",
        },
        schema: [],
        messages: {
          rawHex:
            "Raw hex color literals belong in src/tokens/primitives.ts only. Use semantic tokens or CSS variables.",
        },
      },
      create(context) {
        const filename = context.filename;

        return {
          Literal(node) {
            if (shouldSkipHexRule(filename)) return;
            if (typeof node.value !== "string") return;
            if (RAW_HEX.test(node.value)) {
              context.report({ node, messageId: "rawHex" });
            }
          },
          TemplateElement(node) {
            if (shouldSkipHexRule(filename)) return;
            const raw = node.value.cooked ?? node.value.raw;
            if (RAW_HEX.test(raw)) {
              context.report({ node, messageId: "rawHex" });
            }
          },
        };
      },
    },
  },
};

export default plugin;
