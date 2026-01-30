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
      },
    },
  },
  plugins: [],
};
