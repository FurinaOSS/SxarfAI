const fs = require("node:fs/promises");
const path = require("node:path");
const { minify } = require("html-minifier-terser");

async function main() {
  const source = path.join(__dirname, "..", "index.html");
  const output = path.join(__dirname, "..", "build", "index.html");
  const html = await fs.readFile(source, "utf8");
  const minified = await minify(html, {
    collapseWhitespace: true,
    keepClosingSlash: true,
    minifyCSS: true,
    minifyJS: false,
    removeComments: true,
  });

  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, minified);
  console.log(`Minified ${source} to ${output}`);
}

main().catch((error) => {
  console.error("Failed to build the web bundle:", error);
  process.exitCode = 1;
});
