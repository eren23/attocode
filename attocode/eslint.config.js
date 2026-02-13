import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';
import eslintConfigPrettier from 'eslint-config-prettier';
import importX from 'eslint-plugin-import-x';

export default tseslint.config(
  // Global ignores
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'tools/trace-dashboard/**',
      'tools/eval/**',
      'scripts/**',
      '*.config.js',
      '*.config.mjs',
    ],
  },

  // Base JS recommended rules
  eslint.configs.recommended,

  // TypeScript recommended (type-aware disabled for speed)
  ...tseslint.configs.recommended,

  // Import ordering
  {
    plugins: {
      'import-x': importX,
    },
    rules: {
      'import-x/order': [
        'warn',
        {
          groups: [
            'builtin',
            'external',
            'internal',
            'parent',
            'sibling',
            'index',
          ],
          'newlines-between': 'never',
          alphabetize: { order: 'asc', caseInsensitive: true },
        },
      ],
      'import-x/no-duplicates': 'warn',
    },
  },

  // Project-specific rules
  {
    rules: {
      // Console usage — warn to track migration to structured logger
      'no-console': 'warn',

      // TypeScript strictness — warn first, upgrade to error in Phase 6
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],

      // Allow empty functions (common in stubs/defaults)
      '@typescript-eslint/no-empty-function': 'off',

      // Allow non-null assertions (used heavily in existing code)
      '@typescript-eslint/no-non-null-assertion': 'off',

      // Allow require imports (used in some dynamic loading)
      '@typescript-eslint/no-require-imports': 'off',

      // Downgrade recommended errors to warnings for existing code debt (Phase 6 cleanup)
      'no-case-declarations': 'warn',
      'no-duplicate-case': 'warn',
      'no-async-promise-executor': 'warn',
      'no-useless-escape': 'warn',
      'no-control-regex': 'warn',
      '@typescript-eslint/no-this-alias': 'warn',
      '@typescript-eslint/no-unsafe-function-type': 'warn',

      // General quality
      'no-constant-condition': ['warn', { checkLoops: false }],
      'no-debugger': 'error',
      'prefer-const': 'warn',
      eqeqeq: ['warn', 'always', { null: 'ignore' }],
      'no-var': 'error',
    },
  },

  // Test file overrides
  {
    files: ['tests/**/*.ts', '**/*.test.ts', '**/*.spec.ts'],
    rules: {
      'no-console': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },

  // Prettier must be last to override formatting rules
  eslintConfigPrettier,
);
