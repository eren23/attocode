"""Record a guided walkthrough of the calibration page."""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8932/calibration-demo/calibration.html")
parser.add_argument("--output-dir", type=Path, default=Path(".playwright-mcp/new-recording"))
args = parser.parse_args()
OUT = args.output_dir
OUT.mkdir(exist_ok=True, parents=True)
W, H = 1280, 820

def glide(page, selector, block="start"):
    page.evaluate(
        """([sel, block]) => {
            const el = document.querySelector(sel);
            if (el) el.scrollIntoView({behavior:'smooth', block});
        }""", [selector, block])

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(
        viewport={"width": W, "height": H},
        record_video_dir=str(OUT), record_video_size={"width": W, "height": H},
        device_scale_factor=1, color_scheme="light",
    )
    page = ctx.new_page()
    page.goto(args.url, wait_until="load")
    page.wait_for_timeout(400)
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(2600)                     # title + standfirst

    glide(page, ".strip")                            # the three ECEs
    page.wait_for_timeout(3200)

    glide(page, ".codeframe")                        # the scanner flagging itself
    page.wait_for_timeout(4200)
    glide(page, ".verdicts")
    page.wait_for_timeout(3600)
    glide(page, ".said")
    page.wait_for_timeout(3400)

    glide(page, ".explorer")                         # explore real findings
    page.wait_for_timeout(2400)
    def tap(sel, nth=0):
        page.evaluate("""([s, n]) => {
            const el = document.querySelectorAll(s)[n];
            if (el) el.click();
        }""", [sel, nth])

    for k, hold in (("split", 2600), ("declined", 2400)):
        tap(f".filters button[data-k='{k}']")
        page.wait_for_timeout(hold)
    for n in (0, 1):
        tap(".exrow", n)
        page.wait_for_timeout(2800)
    tap(".filters button[data-k='sec']")
    page.wait_for_timeout(1400)
    tap(".exrow", 0)
    page.wait_for_timeout(3000)

    glide(page, ".racebox")                          # the real-time race
    page.wait_for_timeout(1000)
    page.evaluate("document.getElementById('replay').click()")
    page.wait_for_timeout(7200)

    glide(page, "figure:has(svg)", "center")         # reliability
    page.wait_for_timeout(1200)
    page.evaluate("""() => {
        const h = [...document.querySelectorAll('h2')]
          .find(e => e.textContent.includes('same question'));
        if (h) h.scrollIntoView({behavior:'smooth', block:'start'});
    }""")
    page.wait_for_timeout(4200)
    page.evaluate("""() => {
        const h = [...document.querySelectorAll('h2')]
          .find(e => e.textContent.includes('part company'));
        if (h) h.scrollIntoView({behavior:'smooth', block:'start'});
    }""")
    page.wait_for_timeout(3600)
    page.evaluate("""() => {
        const h = [...document.querySelectorAll('h2')]
          .find(e => e.textContent.includes('wrong question'));
        if (h) h.scrollIntoView({behavior:'smooth', block:'start'});
    }""")
    page.wait_for_timeout(4000)
    page.evaluate("""() => {
        const h = [...document.querySelectorAll('h2')]
          .find(e => e.textContent.includes('Monday'));
        if (h) h.scrollIntoView({behavior:'smooth', block:'start'});
    }""")
    page.wait_for_timeout(4200)

    ctx.close()
    src = Path(page.video.path())
    browser.close()

print("raw:", src, src.stat().st_size, "bytes")
