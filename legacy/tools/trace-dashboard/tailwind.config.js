/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Custom colors for trace visualization
        'trace-success': '#22c55e',
        'trace-error': '#ef4444',
        'trace-warning': '#f59e0b',
        'trace-info': '#3b82f6',
        'trace-muted': '#6b7280',
        // Swarm task status colors
        'swarm-pending': '#6b7280',
        'swarm-ready': '#3b82f6',
        'swarm-dispatched': '#f59e0b',
        'swarm-completed': '#10b981',
        'swarm-failed': '#ef4444',
        'swarm-skipped': '#9ca3af',
        // Agent role colors
        'agent-root': '#a855f7',
        'agent-worker': '#3b82f6',
        'agent-orchestrator': '#f59e0b',
        'agent-judge': '#8b5cf6',
        // Flow type colors
        'flow-finding': '#3b82f6',
        'flow-file': '#6b7280',
        'flow-budget': '#10b981',
        'flow-task': '#f59e0b',
        'flow-result': '#22c55e',
        // Code type colors
        'code-entry': '#a855f7',
        'code-core': '#3b82f6',
        'code-types': '#06b6d4',
        'code-test': '#10b981',
      },
      animation: {
        'flow-pulse': 'flow-pulse 2s ease-in-out infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        'flow-pulse': {
          '0%, 100%': { opacity: '0.3' },
          '50%': { opacity: '1' },
        },
        'glow': {
          '0%': { filter: 'brightness(1)' },
          '100%': { filter: 'brightness(1.3)' },
        },
      },
    },
  },
  plugins: [],
};
