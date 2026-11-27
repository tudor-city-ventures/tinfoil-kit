// Lint for the kit's page, the website and the JavaScript tests: npm run lint (see package.json). A developer tool:
// nothing on a drive uses it.
import js from "@eslint/js";
import html from "eslint-plugin-html";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

const rules = {
  ...js.configs.recommended.rules,
  "no-empty": ["error", { allowEmptyCatch: true }],
  "no-unused-vars": ["error", { caughtErrors: "none" }],
};

export default [
  { ignores: ["site/.next/", "site/out/", "tests/work/", "mobile/"] }, // the phone app lints itself (mobile/)
  {
    files: ["kit/tools/portal.html"],
    plugins: { html },
    languageOptions: {
      sourceType: "script",
      // module: the page exports its logic for the node tests; maplibregl and basemaps: the map code the kit adds
      globals: { ...globals.browser, module: "readonly", maplibregl: "readonly", basemaps: "readonly" },
    },
    rules,
  },
  {
    files: ["tests/**/*.js", "*.mjs"],
    languageOptions: { globals: globals.node },
    rules,
  },
  {
    // The website: a Next.js app in plain JavaScript, with React's two rules of hooks.
    files: ["site/**/*.{js,jsx,mjs}"],
    plugins: { "react-hooks": reactHooks },
    languageOptions: {
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      ...rules,
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
    },
  },
];
