// Lint for the phone app: npm run lint. Expo's rules for React Native and TypeScript.
const { defineConfig } = require("eslint/config");
const expo = require("eslint-config-expo/flat");

module.exports = defineConfig([expo, { ignores: ["dist/", ".expo/", "ios/", "android/", ".claude/"] }]);
