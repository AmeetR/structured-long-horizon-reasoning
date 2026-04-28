import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { mathjax } from "mathjax-full/js/mathjax.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import sharp from "sharp";

const input = await readStdin();
const formulas = JSON.parse(input);

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const tex = new TeX({
  packages: AllPackages,
});
const svg = new SVG({
  fontCache: "none",
});
const document = mathjax.document("", {
  InputJax: tex,
  OutputJax: svg,
});

const rendered = await Promise.all(formulas.map(async ({ tex: formula, display }) => {
  const node = document.convert(formula, { display: Boolean(display) });
  const svgSource = scaleSvgExUnits(adaptor.innerHTML(node), 18);
  const png = await sharp(Buffer.from(svgSource)).png().toBuffer();
  return { png: png.toString("base64") };
}));

process.stdout.write(JSON.stringify(rendered));

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function scaleSvgExUnits(svgSource, pixelsPerEx) {
  return svgSource
    .replace(/width="([0-9.]+)ex"/, (_, width) => `width="${Number(width) * pixelsPerEx}px"`)
    .replace(/height="([0-9.]+)ex"/, (_, height) => `height="${Number(height) * pixelsPerEx}px"`);
}
