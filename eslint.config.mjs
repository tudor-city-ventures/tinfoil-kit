// Lint for the kit's page: npm run lint (see package.json). A developer tool: nothing on a drive uses it.
import js from "@eslint/js";
import html from "eslint-plugin-html";
import globals from "globals";

export default [
  {
    files: ["tools/portal.html"],
    plugins: { html },
    ...js.configs.recommended,
    languageOptions: {
      sourceType: "script",
      // module: the page exports its logic for the node tests; maplibregl and basemaps: the map code the kit adds
      globals: { ...globals.browser, module: "readonly", maplibregl: "readonly", basemaps: "readonly" },
    },
    rules: {
      ...js.configs.recommended.rules,
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-unused-vars": ["error", { caughtErrors: "none" }],
    },
  },
];
