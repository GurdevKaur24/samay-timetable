// Builds web/tailwind.css from the classes used in index.html:
//   npx tailwindcss@3.4.16 -c web/tailwind.config.cjs -i web/tailwind.input.css -o web/tailwind.css --minify
module.exports = {
  content: [__dirname + '/index.html'],
  theme: { extend: {
    // Samay's dark blue: the frame (navy) and a deeper blue in place of Tailwind's indigo everywhere.
    colors: {
      navy: { 700: '#1b2d5e', 800: '#142350', 900: '#0e1a3f', 950: '#09122e' },
      indigo: { 50: '#eef3ff', 100: '#dce6fd', 200: '#c0d1fb', 300: '#94b2f7', 400: '#6189f1', 500: '#3d66e8', 600: '#2a4fd4', 700: '#2340b0', 800: '#1f358c', 900: '#1c2f6e', 950: '#121c44' },
    },
    fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'], display: ['"Plus Jakarta Sans"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] } } },
};
