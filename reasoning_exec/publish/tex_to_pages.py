from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


BLOCK_ENVS = {
    "abstract": "abstract",
    "definition": "definition",
    "assumption": "assumption",
    "theorem": "theorem",
    "lemma": "lemma",
    "corollary": "corollary",
    "proposition": "proposition",
    "proof": "proof",
}


@dataclass(frozen=True)
class Metadata:
    title: str
    author: str
    date: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a LaTeX article as GitHub Pages HTML.")
    parser.add_argument(
        "source",
        nargs="?",
        default="docs/transactional_reasoning_theory.tex",
        help="Path to the .tex source article.",
    )
    parser.add_argument(
        "--output",
        default="docs/index.html",
        help="Path to write the rendered HTML page.",
    )
    parser.add_argument(
        "--medium-output",
        default="",
        help="Optional path to write a Pandoc-rendered Medium import page with equation images.",
    )
    parser.add_argument(
        "--canonical-url",
        default="",
        help="Optional public GitHub Pages URL for canonical links and Medium import.",
    )
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    tex = source.read_text(encoding="utf-8")
    html_page = render_article(tex, canonical_url=args.canonical_url, math_mode="mathjax")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_page, encoding="utf-8")
    print(f"Wrote {output}")
    if args.medium_output:
        medium_output = Path(args.medium_output)
        render_medium_with_pandoc(source, medium_output, canonical_url=args.canonical_url)
        print(f"Wrote {medium_output}")


def render_medium_with_pandoc(source: Path, output: Path, canonical_url: str = "") -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc is required for --medium-output. Install pandoc and rerun.")

    tex = source.read_text(encoding="utf-8")
    tex = tex.replace(r"\qedhere", "")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_source = Path(tmpdir) / source.name
        tmp_source.write_text(tex, encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "pandoc",
                str(tmp_source),
                "--from",
                "latex",
                "--to",
                "html5",
                "--standalone",
                "--webtex=https://tex2pages.invalid/svg?",
                "--metadata",
                "title=Transactional Structured Reasoning: Contamination Safety and Recovery",
                "-o",
                str(output),
            ],
            check=True,
        )

    if canonical_url:
        html_page = output.read_text(encoding="utf-8")
        canonical = f'<link rel="canonical" href="{html.escape(canonical_url, quote=True)}" />'
        html_page = html_page.replace("</head>", f"  {canonical}\n</head>", 1)
        output.write_text(html_page, encoding="utf-8")
    render_local_math_images(output)


def render_local_math_images(output: Path) -> None:
    html_page = output.read_text(encoding="utf-8")
    asset_dir = output.parent / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    for stale in asset_dir.glob("eq_*.svg"):
        stale.unlink()

    image_pattern = re.compile(
        r'<img\b(?=[^>]*\bsrc="https://tex2pages\.invalid/svg\?[^"]+")[^>]*>'
    )
    alt_pattern = re.compile(r'\balt="([^"]*)"')
    class_pattern = re.compile(r'\bclass="([^"]*)"')
    formulas: list[tuple[str, bool]] = []
    for image_tag in image_pattern.findall(html_page):
        alt_match = alt_pattern.search(image_tag)
        if alt_match is None:
            continue
        class_match = class_pattern.search(image_tag)
        class_names = class_match.group(1).split() if class_match else []
        formula = html.unescape(alt_match.group(1))
        formulas.append((formula, "display" in class_names))

    unique_formulas = list(dict.fromkeys(formulas))
    rendered_svgs = render_mathjax_svgs(unique_formulas)
    replacements: dict[tuple[str, bool], str] = {}
    for index, ((formula, display), svg) in enumerate(zip(unique_formulas, rendered_svgs), start=1):
        filename = f"eq_{index:03d}.svg"
        target = asset_dir / filename
        target.write_text(svg, encoding="utf-8")
        replacements[(formula, display)] = f"assets/{filename}"

    def replace_image_src(match: re.Match[str]) -> str:
        image_tag = match.group(0)
        alt_match = alt_pattern.search(image_tag)
        if alt_match is None:
            return image_tag
        class_match = class_pattern.search(image_tag)
        class_names = class_match.group(1).split() if class_match else []
        key = (html.unescape(alt_match.group(1)), "display" in class_names)
        return re.sub(
            r'\bsrc="https://tex2pages\.invalid/svg\?[^"]+"',
            f'src="{replacements[key]}"',
            image_tag,
            count=1,
        )

    html_page = image_pattern.sub(replace_image_src, html_page)
    output.write_text(html_page, encoding="utf-8")


def render_mathjax_svgs(formulas: list[tuple[str, bool]]) -> list[str]:
    if not formulas:
        return []
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to render local SVG math for --medium-output.")

    script = Path(__file__).with_name("render_mathjax_svg.mjs")
    payload = json.dumps([{"tex": formula, "display": display} for formula, display in formulas])
    result = subprocess.run(
        [node, str(script)],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    return [entry["svg"] for entry in json.loads(result.stdout)]


def render_article(
    tex: str,
    canonical_url: str = "",
    math_mode: str = "mathjax",
    asset_dir: Path | None = None,
    asset_url_prefix: str = "assets",
) -> str:
    metadata = extract_metadata(tex)
    macros = extract_macros(tex)
    body = extract_document_body(tex)
    body = strip_maketitle(body)
    math_assets = None
    if math_mode == "local-svg":
        if asset_dir is None:
            raise ValueError("asset_dir is required for local-svg math rendering.")
        math_assets = SvgMathAssets(asset_dir=asset_dir, url_prefix=asset_url_prefix)
    content = TexRenderer(math_mode=math_mode, macros=macros, math_assets=math_assets).render(body)
    if math_assets is not None:
        math_assets.render_pending()
    canonical_tag = (
        f'<link rel="canonical" href="{html.escape(canonical_url, quote=True)}">\n'
        if canonical_url
        else ""
    )
    mathjax_macros = ",\n".join(
        f"        {name}: {macro_to_js_array(definition)}" for name, definition in macros.items()
    )
    mathjax_config = ""
    if math_mode == "mathjax":
        mathjax_config = f"""
    <script>
      window.MathJax = {{
        tex: {{
          inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
          displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
          macros: {{
{mathjax_macros}
          }}
        }}
      }};
    </script>
    <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(metadata.title)}</title>
  {canonical_tag}<meta name="description" content="{html.escape(metadata.title, quote=True)}">
  <style>
    :root {{
      color-scheme: light;
      --bg: #f8f7f3;
      --paper: #fffdfa;
      --ink: #1c1f24;
      --muted: #606975;
      --line: #d9d6cc;
      --accent: #256f73;
      --accent-soft: #e7f1ef;
      --proof: #f2f5f8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: ui-serif, Georgia, Cambria, "Times New Roman", Times, serif;
      line-height: 1.62;
    }}
    main {{
      max-width: 860px;
      margin: 0 auto;
      padding: 48px 22px 72px;
      background: var(--paper);
      min-height: 100vh;
      box-shadow: 0 0 0 1px rgba(28, 31, 36, 0.05);
    }}
    header {{ margin-bottom: 36px; border-bottom: 1px solid var(--line); padding-bottom: 24px; }}
    h1, h2, h3 {{ line-height: 1.2; letter-spacing: 0; }}
    h1 {{ font-size: clamp(2rem, 7vw, 3.2rem); margin: 0 0 12px; }}
    h2 {{ font-size: 1.55rem; margin: 42px 0 16px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }}
    h3 {{ font-size: 1.1rem; margin: 24px 0 8px; color: var(--accent); }}
    p {{ margin: 0 0 16px; }}
    a {{ color: var(--accent); }}
    .byline {{ color: var(--muted); font-size: 0.98rem; }}
    .abstract, .statement, .proof {{
      border-left: 4px solid var(--accent);
      margin: 22px 0;
      padding: 14px 18px;
      background: var(--accent-soft);
    }}
    .proof {{ border-left-color: #708090; background: var(--proof); }}
    .statement-title, .proof-title {{ font-weight: 700; margin-bottom: 8px; }}
    .paragraph-title {{ font-weight: 700; color: var(--accent); }}
    ol, ul {{ padding-left: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.95rem; }}
    th, td {{ border: 1px solid var(--line); padding: 8px 10px; vertical-align: top; }}
    th {{ background: var(--accent-soft); text-align: left; }}
    .math-display {{ overflow-x: auto; margin: 18px 0; }}
    .math-display img {{ max-width: 100%; height: auto; }}
    .math-inline {{ display: inline; height: 1.15em; max-width: 100%; vertical-align: -0.2em; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    @media (max-width: 640px) {{
      main {{ padding: 32px 16px 56px; }}
      table {{ display: block; overflow-x: auto; white-space: nowrap; }}
    }}
  </style>{mathjax_config}
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(metadata.title)}</h1>
      {render_byline(metadata)}
    </header>
{content}
  </main>
</body>
</html>
"""


def extract_metadata(tex: str) -> Metadata:
    return Metadata(
        title=extract_braced(tex, "title") or "Article",
        author=extract_braced(tex, "author"),
        date=extract_braced(tex, "date"),
    )


def extract_braced(tex: str, command: str) -> str:
    match = re.search(rf"\\{command}\{{([^{{}}]*)\}}", tex, flags=re.S)
    return match.group(1).strip() if match else ""


def extract_macros(tex: str) -> dict[str, str]:
    macros: dict[str, str] = {}
    for match in re.finditer(r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", tex):
        macros[match.group(1)] = match.group(2)
    return macros


def macro_to_js_array(definition: str) -> str:
    escaped = definition.replace("\\", "\\\\").replace('"', '\\"')
    return f'["{escaped}"]'


def extract_document_body(tex: str) -> str:
    match = re.search(r"\\begin\{document\}(.*)\\end\{document\}", tex, flags=re.S)
    if not match:
        raise ValueError("No \\begin{document} ... \\end{document} block found.")
    return match.group(1).strip()


def strip_maketitle(body: str) -> str:
    return re.sub(r"\\maketitle\s*", "", body, count=1)


def render_byline(metadata: Metadata) -> str:
    parts = [part for part in [metadata.author, metadata.date] if part]
    if not parts:
        return ""
    return f'<div class="byline">{html.escape(" | ".join(parts))}</div>'


class TexRenderer:
    def __init__(
        self,
        math_mode: str = "mathjax",
        macros: dict[str, str] | None = None,
        math_assets: SvgMathAssets | None = None,
    ) -> None:
        self.env_stack: list[str] = []
        self.paragraph: list[str] = []
        self.section_index = 0
        self.math_mode = math_mode
        self.macros = macros or {}
        self.math_assets = math_assets

    def render(self, body: str) -> str:
        lines = body.splitlines()
        output: list[str] = []
        i = 0
        while i < len(lines):
            raw = lines[i].rstrip()
            stripped = raw.strip()

            if not stripped:
                self.flush_paragraph(output)
                i += 1
                continue

            if stripped.startswith(r"\["):
                self.flush_paragraph(output)
                block: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(r"\]"):
                    block.append(lines[i])
                    i += 1
                output.append(self.render_display_math("\n".join(block)))
                i += 1
                continue

            tabular_match = re.match(r"\\begin\{tabular\}\{.*\}", stripped)
            if tabular_match:
                self.flush_paragraph(output)
                table_lines: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(r"\end{tabular}"):
                    table_lines.append(lines[i].strip())
                    i += 1
                output.append(render_table(table_lines, self.convert_inline))
                i += 1
                continue

            if section := re.match(r"\\section\{(.+)\}", stripped):
                self.flush_paragraph(output)
                self.section_index += 1
                title = self.convert_inline(section.group(1))
                output.append(f'<h2 id="{slugify(strip_commands(section.group(1)))}">{title}</h2>')
                i += 1
                continue

            if stripped.startswith(r"\paragraph{") and "}" not in stripped:
                self.flush_paragraph(output)
                paragraph_lines = [stripped]
                i += 1
                while i < len(lines) and "}" not in lines[i]:
                    paragraph_lines.append(lines[i].strip())
                    i += 1
                if i < len(lines):
                    paragraph_lines.append(lines[i].strip())
                    i += 1
                stripped = " ".join(paragraph_lines)

            if paragraph := re.match(r"\\paragraph\{(.+)\}\.?", stripped):
                self.flush_paragraph(output)
                title = self.convert_inline(paragraph.group(1))
                remainder = stripped[paragraph.end() :].strip()
                if remainder:
                    self.paragraph.append(f'<span class="paragraph-title">{title}.</span> {remainder}')
                else:
                    output.append(f'<p><span class="paragraph-title">{title}.</span></p>')
                i += 1
                continue

            if begin := re.match(r"\\begin\{([^}]+)\}(?:\[([^]]+)\])?", stripped):
                env = begin.group(1)
                title = begin.group(2)
                if env in BLOCK_ENVS:
                    self.flush_paragraph(output)
                    output.append(render_env_start(env, title))
                    self.env_stack.append(env)
                    i += 1
                    continue
                if env in {"enumerate", "itemize", "center"}:
                    self.flush_paragraph(output)
                    output.append({"enumerate": "<ol>", "itemize": "<ul>", "center": '<div class="center">'}[env])
                    self.env_stack.append(env)
                    i += 1
                    continue

            if end := re.match(r"\\end\{([^}]+)\}", stripped):
                env = end.group(1)
                self.flush_paragraph(output)
                if env in BLOCK_ENVS:
                    output.append("</section>")
                elif env == "enumerate":
                    output.append("</ol>")
                elif env == "itemize":
                    output.append("</ul>")
                elif env == "center":
                    output.append("</div>")
                if self.env_stack and self.env_stack[-1] == env:
                    self.env_stack.pop()
                i += 1
                continue

            if item := re.match(r"\\item\s*(.*)", stripped):
                self.flush_paragraph(output)
                output.append(f"<li>{self.convert_inline(item.group(1))}</li>")
                i += 1
                continue

            self.paragraph.append(stripped)
            i += 1

        self.flush_paragraph(output)
        return "\n".join(f"    {line}" for line in output)

    def flush_paragraph(self, output: list[str]) -> None:
        if not self.paragraph:
            return
        text = " ".join(self.paragraph)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            output.append(f"<p>{self.convert_inline(text)}</p>")
        self.paragraph.clear()

    def render_display_math(self, content: str) -> str:
        math = content.strip()
        if self.math_mode == "local-svg":
            if self.math_assets is None:
                raise ValueError("math_assets is required for local SVG rendering.")
            return self.math_assets.render_image(math, display=True, macros=self.macros)
        escaped = html.escape(math)
        return f'<div class="math-display">\\[\n{escaped}\n\\]</div>'

    def convert_inline(self, text: str) -> str:
        return convert_inline(
            text,
            math_mode=self.math_mode,
            macros=self.macros,
            math_assets=self.math_assets,
        )


def render_env_start(env: str, title: str | None) -> str:
    if env == "abstract":
        return '<section class="abstract"><div class="statement-title">Abstract</div>'
    if env == "proof":
        return '<section class="proof"><div class="proof-title">Proof</div>'
    label = BLOCK_ENVS[env].title()
    if title:
        label += f": {html.escape(strip_commands(title))}"
    return f'<section class="statement {env}"><div class="statement-title">{label}</div>'


def render_table(lines: list[str], inline_renderer: Callable[[str], str] | None = None) -> str:
    if inline_renderer is None:
        inline_renderer = convert_inline
    rows: list[list[str]] = []
    for line in lines:
        if not line or line == r"\hline":
            continue
        line = line.replace(r"\\", "").strip()
        if not line:
            continue
        rows.append([inline_renderer(cell.strip()) for cell in line.split("&")])
    if not rows:
        return ""
    html_rows = []
    for index, row in enumerate(rows):
        tag = "th" if index == 0 else "td"
        cells = "".join(f"<{tag}>{cell}</{tag}>" for cell in row)
        html_rows.append(f"<tr>{cells}</tr>")
    return "<table>\n" + "\n".join(html_rows) + "\n</table>"


def convert_inline(
    text: str,
    math_mode: str = "mathjax",
    macros: dict[str, str] | None = None,
    math_assets: SvgMathAssets | None = None,
) -> str:
    macros = macros or {}
    tokens: list[str] = []

    def keep_token(rendered: str) -> str:
        tokens.append(rendered)
        return f"@@TOKEN{len(tokens) - 1}@@"

    text = re.sub(
        r"\$[^$]+\$",
        lambda m: keep_token(
            render_inline_math(
                m.group(0), math_mode=math_mode, macros=macros, math_assets=math_assets
            )
        ),
        text,
    )
    text = re.sub(r"\\label\{[^}]+\}", "", text)
    text = re.sub(r"\\ref\{([^}]+)\}", lambda m: keep_token(html.escape(m.group(1))), text)
    text = re.sub(
        r"\\href\{([^}]+)\}\{([^}]+)\}",
        lambda m: keep_token(
            f'<a href="{html.escape(m.group(1), quote=True)}">{html.escape(m.group(2))}</a>'
        ),
        text,
    )
    text = replace_text_command(text, "textbf", "strong", keep_token)
    text = replace_text_command(text, "emph", "em", keep_token)
    text = replace_text_command(text, "textit", "em", keep_token)
    text = html.escape(text)
    text = re.sub(r"\\label\{[^}]+\}", "", text)
    text = text.replace(r"~", " ")
    text = text.replace(r"\ ", " ")
    text = text.replace(r"\,", " ")
    text = text.replace(r"\;", " ")
    text = text.replace(r"\quad", " ")
    text = text.replace(r"\qquad", " ")
    text = re.sub(r"\\[A-Za-z]+\*?", lambda m: html.escape(m.group(0)), text)
    for index, rendered in enumerate(tokens):
        text = text.replace(f"@@TOKEN{index}@@", rendered)
    return text


def render_inline_math(
    math: str,
    math_mode: str,
    macros: dict[str, str],
    math_assets: SvgMathAssets | None,
) -> str:
    if math_mode == "local-svg":
        if math_assets is None:
            raise ValueError("math_assets is required for local SVG rendering.")
        return math_assets.render_image(math.strip("$"), display=False, macros=macros)
    return html.escape(math)


def expand_macros(math: str, macros: dict[str, str]) -> str:
    expanded = math
    for name in sorted(macros, key=len, reverse=True):
        expanded = re.sub(rf"\\{name}\b", lambda _match, value=macros[name]: value, expanded)
    return expanded


class SvgMathAssets:
    def __init__(self, asset_dir: Path, url_prefix: str = "assets") -> None:
        self.asset_dir = asset_dir
        self.url_prefix = url_prefix.strip("/")
        self.counter = 0
        self.pending: list[dict[str, object]] = []
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        for stale in self.asset_dir.glob("eq_*.svg"):
            stale.unlink()

    def render_image(self, math: str, display: bool, macros: dict[str, str]) -> str:
        expanded = normalize_math_for_svg(expand_macros(math, macros))
        filename = self.reserve_svg(expanded, display=display)
        src = f"{self.url_prefix}/{filename}"
        alt = html.escape(math, quote=True)
        if display:
            return f'<figure class="math-display"><img src="{src}" alt="{alt}"></figure>'
        return f'<img class="math-inline" src="{src}" alt="{alt}">'

    def reserve_svg(self, math: str, display: bool) -> str:
        self.counter += 1
        filename = f"eq_{self.counter:03d}.svg"
        self.pending.append({"id": filename.removesuffix(".svg"), "filename": filename, "math": math, "display": display})
        return filename

    def render_pending(self) -> None:
        if not self.pending:
            return
        try:
            self.render_with_mathjax()
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            print(f"Warning: MathJax SVG render failed; using text fallback: {error}")
            for item in self.pending:
                self.write_text_svg(
                    filename=str(item["filename"]),
                    math=str(item["math"]),
                    display=bool(item["display"]),
                )

    def render_with_mathjax(self) -> None:
        script = Path(__file__).resolve().parents[2] / "scripts" / "render_math_svg.mjs"
        payload = {
            "items": [
                {"id": item["id"], "math": item["math"], "display": item["display"]}
                for item in self.pending
            ]
        }
        result = subprocess.run(
            ["node", str(script)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=True,
        )
        rendered_items = json.loads(result.stdout)
        by_id = {item["id"]: item["svg"] for item in rendered_items}
        for item in self.pending:
            svg = by_id[str(item["id"])]
            (self.asset_dir / str(item["filename"])).write_text(svg, encoding="utf-8")

    def write_text_svg(self, filename: str, math: str, display: bool) -> None:
        path = self.asset_dir / filename
        lines = math.splitlines() or [math]
        font_size = 18 if display else 16
        line_height = int(font_size * 1.55)
        padding_x = 14 if display else 4
        padding_y = 12 if display else 4
        text_width = max((len(line) for line in lines), default=1) * int(font_size * 0.62)
        width = min(max(text_width + padding_x * 2, 64), 1800)
        height = max(len(lines) * line_height + padding_y * 2, font_size + padding_y * 2)
        tspans = []
        y = padding_y + font_size
        for line in lines:
            tspans.append(
                f'<tspan x="{padding_x}" y="{y}">{html.escape(line) or " "}</tspan>'
            )
            y += line_height
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">
  <rect width="100%" height="100%" fill="white"/>
  <text font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace" font-size="{font_size}" fill="#1c1f24">
    {''.join(tspans)}
  </text>
</svg>
'''
        path.write_text(svg, encoding="utf-8")


def normalize_math_for_svg(math: str) -> str:
    replacements = {
        r"\left": "",
        r"\right": "",
        r"\;": " ",
        r"\,": " ",
        r"\!": "",
        r"\quad": "    ",
        r"\qquad": "        ",
    }
    normalized = math
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized.strip()


def replace_text_command(
    text: str, command: str, tag: str, keep_token: Callable[[str], str]
) -> str:
    pattern = re.compile(rf"\\{command}\{{([^{{}}]*)\}}")
    while True:
        replaced = pattern.sub(
            lambda m: keep_token(f"<{tag}>{html.escape(m.group(1))}</{tag}>"), text
        )
        if replaced == text:
            return text
        text = replaced


def strip_commands(text: str) -> str:
    text = re.sub(r"\\[A-Za-z]+\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+", "", text)
    return text


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "section"


if __name__ == "__main__":
    main()
