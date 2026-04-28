from __future__ import annotations

import argparse
import html
import re
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
        "--canonical-url",
        default="",
        help="Optional public GitHub Pages URL for canonical links and Medium import.",
    )
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    tex = source.read_text(encoding="utf-8")
    html_page = render_article(tex, canonical_url=args.canonical_url)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_page, encoding="utf-8")
    print(f"Wrote {output}")


def render_article(tex: str, canonical_url: str = "") -> str:
    metadata = extract_metadata(tex)
    macros = extract_macros(tex)
    body = extract_document_body(tex)
    body = strip_maketitle(body)
    content = TexRenderer().render(body)
    canonical_tag = (
        f'<link rel="canonical" href="{html.escape(canonical_url, quote=True)}">\n'
        if canonical_url
        else ""
    )
    mathjax_macros = ",\n".join(
        f"        {name}: {macro_to_js_array(definition)}" for name, definition in macros.items()
    )
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
    def __init__(self) -> None:
        self.env_stack: list[str] = []
        self.paragraph: list[str] = []
        self.section_index = 0

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
                output.append(render_display_math("\n".join(block)))
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
                output.append(render_table(table_lines))
                i += 1
                continue

            if section := re.match(r"\\section\{(.+)\}", stripped):
                self.flush_paragraph(output)
                self.section_index += 1
                title = convert_inline(section.group(1))
                output.append(f'<h2 id="{slugify(strip_commands(section.group(1)))}">{title}</h2>')
                i += 1
                continue

            if paragraph := re.match(r"\\paragraph\{(.+)\}\.?", stripped):
                self.flush_paragraph(output)
                title = convert_inline(paragraph.group(1))
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
                output.append(f"<li>{convert_inline(item.group(1))}</li>")
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
            output.append(f"<p>{convert_inline(text)}</p>")
        self.paragraph.clear()


def render_env_start(env: str, title: str | None) -> str:
    if env == "abstract":
        return '<section class="abstract"><div class="statement-title">Abstract</div>'
    if env == "proof":
        return '<section class="proof"><div class="proof-title">Proof</div>'
    label = BLOCK_ENVS[env].title()
    if title:
        label += f": {html.escape(strip_commands(title))}"
    return f'<section class="statement {env}"><div class="statement-title">{label}</div>'


def render_display_math(content: str) -> str:
    escaped = html.escape(content.strip())
    return f'<div class="math-display">\\[\n{escaped}\n\\]</div>'


def render_table(lines: list[str]) -> str:
    rows: list[list[str]] = []
    for line in lines:
        if not line or line == r"\hline":
            continue
        line = line.replace(r"\\", "").strip()
        if not line:
            continue
        rows.append([convert_inline(cell.strip()) for cell in line.split("&")])
    if not rows:
        return ""
    html_rows = []
    for index, row in enumerate(rows):
        tag = "th" if index == 0 else "td"
        cells = "".join(f"<{tag}>{cell}</{tag}>" for cell in row)
        html_rows.append(f"<tr>{cells}</tr>")
    return "<table>\n" + "\n".join(html_rows) + "\n</table>"


def convert_inline(text: str) -> str:
    tokens: list[str] = []

    def keep_token(rendered: str) -> str:
        tokens.append(rendered)
        return f"@@TOKEN{len(tokens) - 1}@@"

    text = re.sub(r"\$[^$]+\$", lambda m: keep_token(html.escape(m.group(0))), text)
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
