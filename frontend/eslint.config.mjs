import eslint from "@eslint/js";
import terraDesign from "./eslint/terra-design-plugin.mjs";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "node_modules/**",
      "dist/**",
      "coverage/**",
      "**/*.css",
      "eslint.config.mjs",
      "scripts/**",
      "tailwind.config.ts",
      "postcss.config.mjs",
    ],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts"],
    plugins: {
      "terra-design": terraDesign,
    },
    rules: {
      "terra-design/no-disallowed-tailwind-hues": "error",
      "terra-design/no-raw-hex-outside-primitives": "error",
    },
  },
  {
    files: ["eslint.config.mjs", "scripts/**/*.mjs"],
    languageOptions: {
      globals: {
        console: "readonly",
        process: "readonly",
      },
    },
  },
);
