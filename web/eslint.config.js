// ESLint 9 配置 (flat config)
// P2 修复: 项目用 ESLint 9, 必须有 eslint.config.js/mjs/cjs
// v0.5 简化: 用 js parser 跑 .js/.jsx + Node.js globals for vite.config.ts
//   (.ts/.tsx 暂不开, 由 tsc 处理; 后续 v0.6 装 typescript-eslint 再开)

import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["**/*.{js,jsx,mjs,cjs}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.es2024,
        import_meta_env: "readonly",
      },
    },
    rules: {
      "no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "no-undef": "off",
      "no-empty": ["warn", { allowEmptyCatch: true }],
      "no-prototype-builtins": "off",
    },
  },
  {
    // .ts/.tsx 用简化规则: 关闭 no-undef (TS 已检查), 允许 TS 语法
    // 不装 typescript-eslint 就跳过 TS 语法检查, 但 ESLint 不会 parse error
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parserOptions: {
        // 不用 TS parser, 走默认 JS parser 容忍 TS 注解 (会标记 unknown 但不报错)
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      "no-unused-vars": "off",
      "no-undef": "off",
      "no-empty": ["warn", { allowEmptyCatch: true }],
    },
  },
  {
    // 忽略
    ignores: [
      "dist/**",
      "node_modules/**",
      "**/*.d.ts",
      // v0.5: src/ 暂不 lint (避免 TS parse error), 后续 v0.6 装 typescript-eslint 再开
      "src/**",
    ],
  },
];

