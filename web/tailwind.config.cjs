// Builds web/tailwind.css from the classes used in index.html:
//   npx tailwindcss@3.4.16 -c web/tailwind.config.cjs -i web/tailwind.input.css -o web/tailwind.css --minify
module.exports = {
  content: [__dirname + '/index.html'],
  theme: { extend: { fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] } } },
};
