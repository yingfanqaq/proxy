/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,tsx,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        'dify-bg': '#0a0a0a',
        'dify-sidebar': '#121212',
        'dify-card': '#1a1a1a',
        'dify-border': '#2a2a2a',
        'dify-accent': '#2e66ff',
      }
    },
  },
  plugins: [],
}
