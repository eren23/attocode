"""HTML gallery assembly — generates a self-contained visual debug report.

Produces a single ``gallery.html`` file in the session directory with:
- Session metadata header
- Clickable frame filmstrip / timeline
- Exploration graph (Mermaid text + ASCII fallback)
- Per-frame detail view (metadata JSON, annotations, screenshots)

No external dependencies — all CSS and JS are inlined.
"""

from __future__ import annotations

import base64
import html
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from attocode.integrations.recording.exploration_tracker import ExplorationGraph
    from attocode.integrations.recording.recorder import RecordingFrame


def assemble_gallery(
    session_dir: Path,
    frames: list[RecordingFrame],
    exploration: ExplorationGraph,
    session_id: str,
    start_time: float,
) -> Path:
    """Assemble a self-contained HTML gallery for the recording session.

    Args:
        session_dir: Directory containing frame files and sidecars.
        frames: List of captured recording frames.
        exploration: The exploration graph built during the session.
        session_id: Unique session identifier.
        start_time: Epoch timestamp of session start.

    Returns:
        Path to the written ``gallery.html`` file.
    """
    end_time = time.time()
    duration = end_time - start_time

    frame_cards = _build_frame_cards(frames, start_time, session_dir)
    mermaid_text = exploration.to_mermaid() if exploration else ""
    ascii_dag = exploration.to_ascii_dag() if exploration else ""
    agents = sorted({f.agent_id for f in frames}) if frames else []

    gallery_html = _TEMPLATE.format(
        session_id=html.escape(session_id),
        total_frames=len(frames),
        duration=f"{duration:.1f}",
        agents=html.escape(", ".join(agents)) if agents else "none",
        start_time=_fmt_time(start_time),
        frame_cards=frame_cards,
        mermaid_text=html.escape(mermaid_text),
        ascii_dag=html.escape(ascii_dag),
        frame_details=_build_frame_details(frames, start_time, session_dir),
    )

    out_path = session_dir / "gallery.html"
    out_path.write_text(gallery_html, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt_time(ts: float) -> str:
    """Format an epoch timestamp as HH:MM:SS."""
    t = time.localtime(ts)
    return f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"


def _fmt_delta(ts: float, start: float) -> str:
    """Format timestamp delta from start as +Xs or +Xm Ys."""
    delta = max(0.0, ts - start)
    if delta < 60:
        return f"+{delta:.1f}s"
    mins = int(delta) // 60
    secs = delta - mins * 60
    return f"+{mins}m{secs:.0f}s"


def _load_screenshot(path_str: str | None, session_dir: Path) -> str:
    """Load a screenshot as inline content (base64 SVG or <pre> text).

    Returns an HTML snippet.
    """
    if not path_str:
        return '<span class="no-screenshot">no screenshot</span>'

    p = Path(path_str)
    if not p.is_absolute():
        p = session_dir / p

    # Validate resolved path stays within session directory (path traversal guard)
    try:
        p_resolved = p.resolve()
        session_resolved = session_dir.resolve()
        if not str(p_resolved).startswith(str(session_resolved) + "/") and p_resolved != session_resolved:
            return '<span class="no-screenshot">invalid path</span>'
    except (OSError, ValueError):
        return '<span class="no-screenshot">invalid path</span>'

    if not p_resolved.exists():
        return '<span class="no-screenshot">file missing</span>'

    try:
        content = p_resolved.read_text(encoding="utf-8")
    except Exception:
        return '<span class="no-screenshot">read error</span>'

    if p_resolved.suffix == ".svg":
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return f'<img class="frame-svg" src="data:image/svg+xml;base64,{encoded}" alt="frame" />'

    # ASCII / text fallback
    return f"<pre class=\"frame-ascii\">{html.escape(content)}</pre>"


def _build_frame_cards(
    frames: list[RecordingFrame],
    start_time: float,
    session_dir: Path,
) -> str:
    """Build the filmstrip HTML for all frames."""
    if not frames:
        return '<div class="empty">No frames captured</div>'

    parts: list[str] = []
    for f in frames:
        kind_class = "".join(c for c in f.event_kind if c.isalnum() or c in ".-_")
        safe_id = html.escape(f.frame_id, quote=True)
        annotations = html.escape("; ".join(f.annotations)) if f.annotations else ""
        parts.append(
            f'<div class="frame-card {kind_class}" onclick="showDetail(\'{safe_id}\')">'
            f'  <div class="frame-num">#{f.frame_number}</div>'
            f'  <div class="frame-kind">{html.escape(f.event_kind)}</div>'
            f'  <div class="frame-agent">{html.escape(f.agent_id)}</div>'
            f'  <div class="frame-delta">{_fmt_delta(f.timestamp, start_time)}</div>'
            f'  <div class="frame-anno">{annotations}</div>'
            f"</div>"
        )
    return "\n".join(parts)


def _build_frame_details(
    frames: list[RecordingFrame],
    start_time: float,
    session_dir: Path,
) -> str:
    """Build hidden detail panels for each frame."""
    if not frames:
        return ""

    parts: list[str] = []
    for f in frames:
        screenshot_html = _load_screenshot(f.screenshot_path, session_dir)
        meta_json = html.escape(json.dumps(f.metadata, indent=2, default=str))
        annotations_html = "".join(
            f"<li>{html.escape(a)}</li>" for a in f.annotations
        )
        safe_id = html.escape(f.frame_id, quote=True)

        parts.append(
            f'<div class="frame-detail" id="detail-{safe_id}" style="display:none">'
            f'  <h3>Frame #{f.frame_number} — {html.escape(f.event_kind)}</h3>'
            f"  <table>"
            f"    <tr><td>Agent</td><td>{html.escape(f.agent_id)}</td></tr>"
            f"    <tr><td>Time</td><td>{_fmt_delta(f.timestamp, start_time)}</td></tr>"
            f"    <tr><td>Iteration</td><td>{f.iteration}</td></tr>"
            f"  </table>"
            f'  <div class="screenshot-container">{screenshot_html}</div>'
            f"  <h4>Annotations</h4>"
            f"  <ul>{annotations_html or '<li>none</li>'}</ul>"
            f"  <h4>Metadata</h4>"
            f"  <pre class=\"meta-json\">{meta_json}</pre>"
            f"</div>"
        )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Recording: {session_id}</title>
<style>
  :root {{
    --bg: #1a1a2e; --surface: #16213e; --card: #0f3460;
    --accent: #e94560; --text: #eee; --muted: #999;
    --green: #4ade80; --yellow: #facc15; --red: #f87171;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: "SF Mono", "Fira Code", monospace; background: var(--bg); color: var(--text); padding: 1rem; }}
  h1, h2, h3, h4 {{ margin: 0.5rem 0; }}
  h1 {{ color: var(--accent); font-size: 1.3rem; }}
  h2 {{ color: var(--accent); font-size: 1.1rem; border-bottom: 1px solid var(--card); padding-bottom: 0.3rem; }}
  .header {{ background: var(--surface); padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }}
  .header .meta {{ display: flex; gap: 2rem; flex-wrap: wrap; margin-top: 0.5rem; color: var(--muted); font-size: 0.85rem; }}
  .header .meta span {{ color: var(--text); }}

  /* Filmstrip */
  .filmstrip {{ display: flex; gap: 0.5rem; overflow-x: auto; padding: 0.5rem 0; margin-bottom: 1rem; }}
  .frame-card {{
    flex: 0 0 110px; background: var(--card); border-radius: 6px; padding: 0.5rem;
    cursor: pointer; border: 2px solid transparent; transition: border-color 0.15s;
    font-size: 0.75rem;
  }}
  .frame-card:hover {{ border-color: var(--accent); }}
  .frame-card.active {{ border-color: var(--green); }}
  .frame-num {{ font-weight: bold; color: var(--accent); }}
  .frame-kind {{ color: var(--muted); }}
  .frame-agent {{ color: var(--yellow); }}
  .frame-delta {{ color: var(--muted); font-size: 0.7rem; }}
  .frame-anno {{ color: var(--text); font-size: 0.7rem; margin-top: 0.2rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

  /* Sections */
  .section {{ background: var(--surface); padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }}
  pre {{ background: var(--bg); padding: 0.75rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; white-space: pre-wrap; word-break: break-word; }}
  .meta-json {{ max-height: 300px; overflow-y: auto; }}

  /* Frame detail */
  .frame-detail {{ background: var(--surface); padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }}
  .frame-detail table {{ margin: 0.5rem 0; border-collapse: collapse; }}
  .frame-detail td {{ padding: 0.2rem 0.8rem 0.2rem 0; }}
  .frame-detail td:first-child {{ color: var(--muted); }}
  .screenshot-container {{ margin: 0.5rem 0; }}
  .frame-svg {{ max-width: 100%; border-radius: 4px; border: 1px solid var(--card); }}
  .frame-ascii {{ max-height: 400px; overflow: auto; }}
  .no-screenshot {{ color: var(--muted); font-style: italic; }}

  .empty {{ color: var(--muted); font-style: italic; padding: 1rem; }}
  ul {{ list-style: none; padding-left: 0.5rem; }}
  li::before {{ content: "\\2022 "; color: var(--accent); }}
</style>
</head>
<body>

<div class="header">
  <h1>Visual Debug Recording</h1>
  <div class="meta">
    Session: <span>{session_id}</span>
    Frames: <span>{total_frames}</span>
    Duration: <span>{duration}s</span>
    Agents: <span>{agents}</span>
    Started: <span>{start_time}</span>
  </div>
</div>

<div class="section">
  <h2>Frame Timeline</h2>
  <div class="filmstrip" id="filmstrip">
    {frame_cards}
  </div>
</div>

<div class="section">
  <h2>Exploration Graph</h2>
  <pre>{mermaid_text}</pre>
  <details>
    <summary style="cursor:pointer;color:var(--muted);margin-top:0.5rem">ASCII DAG</summary>
    <pre>{ascii_dag}</pre>
  </details>
</div>

<div id="detail-container">
  <h2>Frame Detail</h2>
  <p class="empty" id="detail-placeholder">Click a frame above to view details.</p>
  {frame_details}
</div>

<script>
  let activeCard = null;
  function showDetail(frameId) {{
    // Hide all details
    document.querySelectorAll('.frame-detail').forEach(el => el.style.display = 'none');
    document.getElementById('detail-placeholder').style.display = 'none';
    // Show selected
    const detail = document.getElementById('detail-' + frameId);
    if (detail) detail.style.display = 'block';
    // Highlight card
    if (activeCard) activeCard.classList.remove('active');
    const cards = document.querySelectorAll('.frame-card');
    cards.forEach(c => {{
      if (c.getAttribute('onclick').includes(frameId)) {{
        c.classList.add('active');
        activeCard = c;
      }}
    }});
  }}
</script>

</body>
</html>
"""
