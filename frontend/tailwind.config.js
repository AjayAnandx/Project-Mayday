/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        crust: '#050505',
        mantle: '#0d0d0d',
        base: '#141414',
        surface0: '#1c1c1c',
        surface1: '#262626',
        surface2: '#303030',
        overlay0: '#525252',
        overlay1: '#737373',
        overlay2: '#999999',
        subtext0: '#a3a3a3',
        subtext1: '#cccccc',
        text: '#e5e5e5',
        accent: '#22c55e',
        green: '#22c55e',
        red: '#ef4444',
        yellow: '#eab308',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
