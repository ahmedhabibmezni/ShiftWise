import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      // Type-checked rules require type information — `projectService` below
      // wires the TypeScript program in. `recommendedTypeChecked` is the
      // lighter of the two type-aware presets (vs `strictTypeChecked`).
      tseslint.configs.recommendedTypeChecked,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      // Matches `target: ES2022` in tsconfig.app.json — the two were out of
      // sync (config said 2020).
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // The codebase intentionally calls async mutation/query functions in
      // event handlers (TanStack Query's `mutate`, fire-and-forget refetches)
      // without awaiting them. The promise is handled by the library, so the
      // floating-promise warning is noise here.
      '@typescript-eslint/no-floating-promises': 'off',
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: { attributes: false } },
      ],
    },
  },
])
