// Builds prototype/tailwind.css from the classes used in index.html:
//   npx tailwindcss@3.4.16 -c prototype/tailwind.config.cjs -i prototype/tailwind.input.css -o prototype/tailwind.css --minify
module.exports = {
  content: [__dirname + '/index.html'],
  theme: { extend: { fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] } } },
};
