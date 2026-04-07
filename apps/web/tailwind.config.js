/** @type {import('tailwindcss').Config} */

/**
 * Horion.pro — Tailwind is used for LAYOUT and SPACING ONLY.
 * All colors must come from CSS variables (--hz-*) defined in globals.css.
 * Never use Tailwind color classes (text-gray-*, bg-blue-*, etc.) in components.
 */
const config = {
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}

module.exports = config
