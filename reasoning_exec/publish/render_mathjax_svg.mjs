import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { mathjax } from "mathjax-full/js/mathjax.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";
import { TeX } from "mathjax-full/js/input/tex.js";

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

const rendered = formulas.map(({ tex: formula, display }) => {
  const node = document.convert(formula, { display: Boolean(display) });
  return { svg: adaptor.innerHTML(node) };
});

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
