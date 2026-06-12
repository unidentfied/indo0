/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'sindio-dark': 'var(--sindio-dark)',
        'sindio-panel': 'var(--sindio-panel)',
        'sindio-border': 'var(--sindio-border)',
        'sindio-accent': 'var(--sindio-accent)',
        'sindio-accent-hover': 'var(--sindio-accent-hover)',
        'sindio-critical': 'var(--sindio-critical)',
        'sindio-warning': 'var(--sindio-warning)',
        'sindio-advisory': 'var(--sindio-advisory)',
        'sindio-text': 'var(--sindio-text)',
        'sindio-muted': 'var(--sindio-muted)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'card': '0 1px 3px 0 rgba(0, 0, 0, 0.06), 0 1px 2px -1px rgba(0, 0, 0, 0.06)',
        'panel': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
      },
    },
  },
  plugins: [],
}
