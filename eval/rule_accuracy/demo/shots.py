"""Tight element screenshots of the things worth showing."""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8932/calibration-demo/calibration.html")
parser.add_argument("--output-dir", type=Path, default=Path(".playwright-mcp/new-shots"))
args = parser.parse_args()
OUT = args.output_dir
OUT.mkdir(exist_ok=True, parents=True)

PICK = """([rule, file]) => {
  const rows = [...document.querySelectorAll('.exrow')];
  const hit = rows.find(r =>
    r.querySelector('.rid').textContent.includes(rule) &&
    r.querySelector('.loc').textContent.includes(file));
  if (hit) { hit.click(); return true; }
  return false;
}"""

with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900},
                        device_scale_factor=2, color_scheme="light")
    page = ctx.new_page()
    page.goto(args.url, wait_until="load")
    page.wait_for_timeout(1800)          # let the autoplay race finish

    def shot(sel, name, pad=True):
        el = page.query_selector(sel)
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(350)
        el.screenshot(path=str(OUT / name))
        print("  ", name)

    # 1 — speed, caught mid-race: jev done, classifier still working
    page.evaluate("document.getElementById('replay').click()")
    page.wait_for_timeout(3300)
    shot(".racebox", "01-speed-mid-race.png")

    # 2 — the speed numbers
    page.wait_for_timeout(3000)
    shot("section.wide:has(.racebox) table", "02-speed-numbers.png")

    # 3 — case: the scanner flags its own detector (both models beat the constant)
    shot("figure:has(.codeframe)", "03-case-scanner-flags-itself.png")

    # 4 — case: jev keeps, classifier drops (CLI usage print)
    page.evaluate("document.querySelector(\"[data-k='split']\").click()")
    page.wait_for_timeout(500)
    page.evaluate(PICK, ["py-debug-print-leftover", "cli.py"])
    page.wait_for_timeout(500)
    shot(".explorer", "04-case-jev-keeps-classifier-drops.png")

    # 5 — case: declined because redaction removed the evidence
    page.evaluate("document.querySelector(\"[data-k='declined']\").click()")
    page.wait_for_timeout(500)
    page.evaluate(PICK, ["password_assignment", "cli.py"])
    page.wait_for_timeout(500)
    shot(".explorer", "05-case-declined-after-redaction.png")

    # 6 — a SQL pattern match; its table-name origin needs source review
    page.evaluate("document.querySelector(\"[data-k='sec']\").click()")
    page.wait_for_timeout(500)
    ok = page.evaluate(PICK, ["python_sql_fstring", "maintenance_tools.py"])
    page.wait_for_timeout(500)
    shot(".explorer", "06-case-real-sql-fstring.png")
    print("   sql row found:", ok)

    # 7 — the one chart that carries the argument
    shot("figure:has(svg[aria-label*='Reliability'])", "07-calibration.png")

    shot("figure:has(.codeframe)", "08-case-both-beat-the-constant.png")
    ctx.close()
    b.close()
