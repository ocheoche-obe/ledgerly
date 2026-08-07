#!/usr/bin/env python3
"""
render.py — render a structured explain-diff spec into a self-contained HTML
explainer page.

Adapted for Ledgerly from Geoffrey Litt's explain-diff recipe
(https://gist.github.com/geoffreylitt/a29df1b5f9865506e8952488eac3d524), via
https://gist.github.com/ankitg12/8e808d387799de4e9839bc393f8e6405.

Why this exists: the CSS, quiz JavaScript, and page scaffolding are identical
across every invocation of the explain-diff skill — only the content (prose,
diagrams, quiz questions) actually changes per diff. Regenerating the full
~250 lines of boilerplate CSS/JS by hand every time wastes tokens and drifts in
quality. This script takes a small JSON spec with just the content and renders
the final page.

Ledgerly changes from the upstream gist:
  1. Default output is <repo>/docs/explainers/YYYY-MM-DD-<slug>.html (git-tracked
     project record) rather than /tmp/. Repo root is found via `git rev-parse`.
  2. Quiz options accept an optional "explanation" so feedback says *why* an
     answer is right or wrong, instead of the upstream's generic "reread the
     section above". Teaching the reader is the whole point of the exercise.
  3. Option text is HTML-escaped (upstream left it raw, so an option mentioning
     `cents < 0` would silently swallow the rest of the button).

Usage:
    python render.py spec.json [-o output.html]

Spec format (JSON):
{
  "title": "Re-enqueueing 153 stranded transactions",
  "subtitle": "Prepared 2026-08-10 · PR #44 · Slice 6 [B-7]",
  "slug": "b7-recategorize-endpoint",
  "sections": [
    {"id": "background", "heading": "Background", "html": "<p>...</p>"},
    {"id": "intuition", "heading": "Intuition", "html": "<p>...</p><div class=\"diagram\">...</div>"},
    {"id": "code", "heading": "Code walkthrough", "html": "<pre><code>...</code></pre>"}
  ],
  "quiz": [
    {
      "question": "Why does re-importing the same CSV not fix the stranded rows?",
      "options": [
        {"text": "The importer only enqueues rows it newly added, and ADR-012 idempotency means a re-import adds none.",
         "correct": true,
         "explanation": "Right — the natural key already matches, so put_transaction is a no-op and nothing reaches the queue."},
        {"text": "The categorizer queue drops duplicate messages.",
         "correct": false,
         "explanation": "No — SQS has no such dedupe here; the messages are never sent in the first place."}
      ]
    }
  ]
}

Option order within each quiz question is randomized by the renderer at render
time — list them in whatever order reads naturally when writing the spec; don't
try to manually vary position to "seem random", the script already guarantees it.

The "html" fields are raw HTML — write real markup (headings, <pre> blocks,
tables, ".diagram"/".callout" divs per the CSS classes below), not markdown.
This keeps the script a pure template renderer; all the writing judgment (what
to explain, which diagrams to draw) belongs to the skill.
"""
import argparse
import datetime
import html
import json
import re
import random
import subprocess
from pathlib import Path

CSS = """
  :root {
    --bg: #fafaf8; --fg: #1a1a1a; --accent: #b5541f; --muted: #6b6b6b;
    --code-bg: #282c34; --code-fg: #e6e6e6; --callout-bg: #fff4e8; --border: #e0ddd6;
  }
  body { font-family: Georgia, 'Times New Roman', serif; background: var(--bg); color: var(--fg);
    max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 6rem; line-height: 1.65; }
  h1 { font-size: 1.9rem; border-bottom: 3px solid var(--accent); padding-bottom: .5rem; }
  h2 { font-size: 1.4rem; margin-top: 3rem; color: var(--accent); }
  h3 { font-size: 1.1rem; margin-top: 1.8rem; }
  code { font-family: 'SF Mono', Consolas, monospace; background: #eee; padding: .1rem .3rem; border-radius: 3px; font-size: .92em; }
  pre { background: var(--code-bg); color: var(--code-fg); padding: 1rem 1.2rem; border-radius: 8px;
    overflow-x: auto; white-space: pre-wrap; font-family: 'SF Mono', Consolas, monospace; font-size: .88rem; line-height: 1.5; }
  pre code { background: none; padding: 0; color: inherit; }
  .callout { background: var(--callout-bg); border-left: 4px solid var(--accent); padding: .9rem 1.2rem;
    border-radius: 0 6px 6px 0; margin: 1.2rem 0; }
  .toc { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.5rem; margin: 1.5rem 0; }
  .toc a { color: var(--accent); text-decoration: none; }
  .toc ul { margin: .3rem 0; }
  .diagram { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem;
    margin: 1.2rem 0; font-family: 'SF Mono', Consolas, monospace; font-size: .85rem; }
  .flow { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; justify-content: center; padding: .5rem 0; }
  .box { border: 2px solid var(--accent); border-radius: 8px; padding: .6rem 1rem; background: #fdf6ee; text-align: center; min-width: 120px; }
  .box.fail { border-color: #b91c1c; background: #fef2f2; }
  .arrow { font-size: 1.4rem; color: var(--muted); }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .92rem; }
  th, td { border: 1px solid var(--border); padding: .5rem .7rem; text-align: left; }
  th { background: #f0ede6; }
  .quiz-q { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem 1.5rem; margin: 1.2rem 0; }
  .quiz-opt { display: block; width: 100%; text-align: left; padding: .6rem 1rem; margin: .4rem 0;
    border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; font-family: inherit; font-size: .95rem; }
  .quiz-opt:hover { background: #f5f2ec; }
  .feedback { display: none; margin-top: .6rem; padding: .6rem 1rem; border-radius: 6px; font-size: .9rem; }
  .feedback.correct { background: #ecfdf3; color: #166534; border-left: 3px solid #16a34a; }
  .feedback.incorrect { background: #fef2f2; color: #991b1b; border-left: 3px solid #dc2626; }
  .badge { display: inline-block; font-size: .75rem; padding: .15rem .5rem; border-radius: 10px; font-family: sans-serif; }
  .badge.new { background: #dcfce7; color: #166534; }
  @media (max-width: 600px) { body { padding: 1rem; } .flow { flex-direction: column; } }
"""

# Feedback text comes from each option's data-explanation when the spec provides
# one, so the reader learns *why* rather than just right/wrong.
QUIZ_JS = """
document.querySelectorAll('.quiz-q').forEach(q => {
  q.querySelectorAll('.quiz-opt').forEach(opt => {
    opt.addEventListener('click', () => {
      const correct = opt.dataset.correct === 'true';
      const why = opt.dataset.explanation || '';
      let fb = opt.nextElementSibling;
      if (!fb || !fb.classList.contains('feedback')) {
        fb = document.createElement('div');
        fb.className = 'feedback';
        opt.insertAdjacentElement('afterend', fb);
      }
      const mark = correct ? '\\u2705 Correct.' : '\\u274c Not quite.';
      fb.textContent = why ? mark + ' ' + why
                           : mark + (correct ? '' : ' Reread the section above.');
      fb.className = 'feedback ' + (correct ? 'correct' : 'incorrect');
      fb.style.display = 'block';
    });
  });
});
"""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def repo_root(fallback: Path) -> Path:
    """Locate the git repo root so explainers land in docs/explainers/."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=fallback, capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return fallback


def render(spec: dict) -> str:
    title = spec["title"]
    subtitle = spec.get("subtitle", "")
    sections = spec.get("sections", [])
    quiz = spec.get("quiz", [])

    toc_items = "\n".join(
        f'  <li><a href="#{s["id"]}">{html.escape(s["heading"])}</a></li>' for s in sections
    )
    if quiz:
        toc_items += '\n  <li><a href="#quiz">Quiz</a></li>'

    body_sections = "\n\n".join(
        f'<h2 id="{s["id"]}">{html.escape(s["heading"])}</h2>\n{s["html"]}' for s in sections
    )

    quiz_html = ""
    if quiz:
        blocks = []
        for q in quiz:
            options = list(q["options"])
            random.shuffle(options)
            opts = "\n".join(
                '<button class="quiz-opt" data-correct="{correct}"{expl}>{text}</button>'.format(
                    correct="true" if o["correct"] else "false",
                    expl=(f' data-explanation="{html.escape(o["explanation"], quote=True)}"'
                          if o.get("explanation") else ""),
                    text=html.escape(o["text"]),
                )
                for o in options
            )
            blocks.append(
                f'<div class="quiz-q">\n<p><strong>{html.escape(q["question"])}</strong></p>\n{opts}\n</div>'
            )
        quiz_html = '<h2 id="quiz">Quiz</h2>\n\n' + "\n\n".join(blocks)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>

<h1>{html.escape(title)}</h1>
{f'<p style="color:var(--muted); margin-top:-.5rem;">{html.escape(subtitle)}</p>' if subtitle else ''}

<div class="toc">
<strong>Contents</strong>
<ul>
{toc_items}
</ul>
</div>

{body_sections}

{quiz_html}

<script>{QUIZ_JS}</script>

</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("spec", type=Path, help="path to the JSON content spec")
    ap.add_argument("-o", "--output", type=Path, default=None, help="output HTML path")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    out_html = render(spec)

    if args.output:
        out_path = args.output
    else:
        date_prefix = datetime.date.today().strftime("%Y-%m-%d")
        slug = spec.get("slug") or slugify(spec["title"])
        out_dir = repo_root(Path(__file__).resolve().parent) / "docs" / "explainers"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_prefix}-{slug}.html"

    out_path.write_text(out_html, encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
