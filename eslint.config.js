// Minimal flat config. Catches React Hooks misuse, unused vars, and obvious
// JS/TS bugs. Stricter rules can grow from here once findings burn down.
import js from '@eslint/js';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default [
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: { ecmaVersion: 'latest', sourceType: 'module', ecmaFeatures: { jsx: true } },
      globals: {
        window: 'readonly', document: 'readonly', console: 'readonly',
        localStorage: 'readonly', sessionStorage: 'readonly', fetch: 'readonly',
        URL: 'readonly', URLSearchParams: 'readonly', FormData: 'readonly',
        Blob: 'readonly', File: 'readonly', FileReader: 'readonly',
        setTimeout: 'readonly', clearTimeout: 'readonly',
        setInterval: 'readonly', clearInterval: 'readonly',
        EventSource: 'readonly', AbortController: 'readonly',
        navigator: 'readonly', location: 'readonly', alert: 'readonly',
        confirm: 'readonly', HTMLInputElement: 'readonly',
        HTMLTextAreaElement: 'readonly', HTMLElement: 'readonly',
        MessageEvent: 'readonly', ReadableStream: 'readonly',
        TextDecoder: 'readonly', Buffer: 'readonly', process: 'readonly',
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' }],
      'no-empty': ['error', { allowEmptyCatch: true }],
      // TS handles these via tsc:
      'no-undef': 'off',
      'no-redeclare': 'off',
      // Deferred: 6 existing useEffect/useCallback callsites declare
      // intentionally-stable deps and would loop if "fixed" naively. Re-enable
      // (case-by-case eslint-disable per call site) when next auditing
      // UI lifecycle bugs.
      'react-hooks/exhaustive-deps': 'off',
    },
  },
  { ignores: ['dist/**', 'node_modules/**', 'venv/**', 'data/**', 'fakecompanies/**', 'playwright-report/**', 'test-results/**', 'e2e/**'] },
];
