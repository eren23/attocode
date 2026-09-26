import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description="Rebuild the historical demo without model calls.")
parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
parser.add_argument("--output-dir", type=Path, default=Path(".playwright-mcp/calibration-demo"))
args = parser.parse_args()
S = args.data_dir
args.output_dir.mkdir(parents=True, exist_ok=True)
data = json.loads((S / "compact.json").read_text())
stats = json.loads((S / "stats.json").read_text())

HTML = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Can You Trust 0.85?</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{
  --paper:#F5F7F8; --raised:#FFFFFF; --ink:#131B22; --slate:#5A6672; --faint:#8494A0;
  --rule:#DCE2E6; --hair:#E8EDF0;
  --constants:#98A2AB; --jev:#0F6E63; --llm:#C15A2B;
  --grid:#E2E8EC; --band:#EDF1F3;
  --measure:66ch;
}
:root:not([data-theme="light"]){ @media (prefers-color-scheme: dark){
  --paper:#0F151A; --raised:#161E25; --ink:#E4E9ED; --slate:#9BA8B3; --faint:#71808C;
  --rule:#25303A; --hair:#1D262E;
  --constants:#7D8892; --jev:#3FA694; --llm:#E0824F;
  --grid:#222C35; --band:#182128;
}}
:root[data-theme="dark"]{
  --paper:#0F151A; --raised:#161E25; --ink:#E4E9ED; --slate:#9BA8B3; --faint:#71808C;
  --rule:#25303A; --hair:#1D262E;
  --constants:#7D8892; --jev:#3FA694; --llm:#E0824F;
  --grid:#222C35; --band:#182128;
}
*{box-sizing:border-box}
body{
  background:var(--paper); color:var(--ink);
  font-family:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
  font-size:16px; line-height:1.62; margin:0;
  padding-block:0 5rem; padding-left:20px; padding-right:20px;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:var(--measure); margin:0 auto}
.wide{max-width:920px; margin:0 auto}
h1,h2,h3{font-family:Newsreader,Georgia,serif; font-weight:500; text-wrap:balance; margin:0}
h1{font-size:clamp(2.4rem,7vw,3.9rem); line-height:1.04; letter-spacing:-.018em}
h2{font-size:clamp(1.5rem,3.6vw,2rem); line-height:1.16; letter-spacing:-.012em}
h3{font-size:1.12rem; font-weight:600; line-height:1.3}
p{margin:0}
a{color:var(--jev)}
.eyebrow{
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.69rem;
  letter-spacing:.15em; text-transform:uppercase; color:var(--faint);
}
code,.mono{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.86em}
.num{font-variant-numeric:tabular-nums}

header{padding-block:4.5rem 3rem; border-bottom:1px solid var(--rule)}
.standfirst{font-size:1.16rem; color:var(--slate); margin-top:1.5rem; max-width:58ch}
.byline{margin-top:2rem; display:flex; flex-wrap:wrap; gap:.5rem 1.6rem}
.byline span{font-family:"IBM Plex Mono",monospace; font-size:.74rem; color:var(--faint)}

section{padding-block:3.4rem; border-bottom:1px solid var(--hair)}
.stack{display:flex; flex-direction:column; gap:1.15rem}
.lede{font-size:1.07rem}

/* verdict strip: three scorers, the one number that matters */
.strip{display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--rule);
  border:1px solid var(--rule); margin-block:2.2rem}
.cell{background:var(--raised); padding:1.15rem 1.15rem 1.25rem; display:flex; flex-direction:column; gap:.3rem}
.cell .who{font-family:"IBM Plex Mono",monospace; font-size:.74rem; letter-spacing:.06em;
  display:flex; align-items:center; gap:.45rem}
.swatch{width:9px; height:9px; flex:none; border-radius:1px}
.cell .ece{font-family:Newsreader,serif; font-size:2.3rem; line-height:1; font-variant-numeric:tabular-nums}
.cell .note{font-size:.78rem; color:var(--faint); line-height:1.45}

figure{margin:2.4rem 0 0}
figcaption{font-size:.83rem; color:var(--slate); margin-top:1rem; line-height:1.55; max-width:62ch}
.chartbox{background:var(--raised); border:1px solid var(--rule); padding:1.1rem .85rem .6rem}
svg{display:block; width:100%; height:auto; max-width:100%}
.legend{display:flex; flex-wrap:wrap; gap:.4rem 1.3rem; padding:.5rem .35rem 0;
  font-family:"IBM Plex Mono",monospace; font-size:.73rem; color:var(--slate)}
.legend i{display:inline-flex; align-items:center; gap:.4rem; font-style:normal}

table{border-collapse:collapse; width:100%; font-size:.85rem}
.scroll{overflow-x:auto; margin-top:1.6rem}
th,td{text-align:right; padding:.5rem .7rem; border-bottom:1px solid var(--hair); white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{font-family:"IBM Plex Mono",monospace; font-size:.7rem; letter-spacing:.07em;
  text-transform:uppercase; color:var(--faint); border-bottom:1px solid var(--rule)}
tbody td{font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:none}

.pull{border-left:2px solid var(--jev); padding:.15rem 0 .15rem 1.15rem; margin-block:.4rem;
  font-family:Newsreader,serif; font-size:1.25rem; line-height:1.4}
.finding{display:flex; gap:.7rem; align-items:baseline; margin-top:.5rem}
.finding .tag{font-family:"IBM Plex Mono",monospace; font-size:.68rem; letter-spacing:.1em;
  text-transform:uppercase; color:var(--llm); flex:none; padding-top:.28rem}

.readout{min-height:3.6rem; margin-top:.5rem; padding:.55rem .7rem; background:var(--band);
  border:1px solid var(--hair); font-family:"IBM Plex Mono",monospace; font-size:.76rem;
  line-height:1.5; color:var(--slate)}
.readout b{color:var(--ink); font-weight:500}
.dot{cursor:pointer}
.dot:focus{outline:2px solid var(--ink); outline-offset:2px}

.split{display:grid; grid-template-columns:1fr 1fr; gap:1px; background:var(--rule);
  border:1px solid var(--rule); margin-top:1.8rem}
.half{background:var(--raised); padding:1.1rem}
.half h3{margin-bottom:.55rem}
.half p{font-size:.86rem; color:var(--slate)}
.half .big{font-family:Newsreader,serif; font-size:1.9rem; line-height:1.1; font-variant-numeric:tabular-nums}

ol.steps{margin:1.3rem 0 0; padding-left:0; list-style:none; counter-reset:s;
  display:flex; flex-direction:column; gap:.95rem}
ol.steps li{counter-increment:s; display:flex; gap:.85rem; align-items:baseline}
ol.steps li::before{content:counter(s); font-family:"IBM Plex Mono",monospace; font-size:.72rem;
  color:var(--faint); flex:none; width:1.1rem}
footer{padding-top:2.6rem; font-size:.8rem; color:var(--faint); line-height:1.6}

@media (max-width:620px){
  .strip{grid-template-columns:1fr}
  .split{grid-template-columns:1fr}
  header{padding-block:3rem 2.2rem}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}

.codeframe{background:var(--raised); border:1px solid var(--rule)}
.codehead{display:flex; flex-wrap:wrap; gap:.5rem 1rem; justify-content:space-between;
  align-items:center; padding:.6rem .9rem; border-bottom:1px solid var(--hair); font-size:.72rem;
  color:var(--faint)}
.rulechip{color:var(--ink); border:1px solid var(--rule); padding:.1rem .45rem}
pre.code{margin:0; padding:1.1rem .9rem; overflow-x:auto; font-family:"IBM Plex Mono",monospace;
  font-size:.83rem; line-height:1.85; color:var(--ink)}
pre.code .ln{color:var(--faint); user-select:none; padding-right:.7rem}
pre.code .kw{color:var(--llm)}
pre.code .str{color:var(--jev)}
pre.code .mark{display:inline-block; width:100%; box-shadow:inset 0 -2px 0 0 var(--jev); opacity:.5}
.codenote{padding:.75rem .9rem 1rem; border-top:1px solid var(--hair); font-size:.82rem;
  color:var(--slate); line-height:1.6}
.codenote b{color:var(--ink); font-weight:600}
.verdicts{display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--rule);
  border:1px solid var(--rule); border-top:none}
.v{background:var(--raised); padding:1.05rem .95rem 1.15rem; display:flex; flex-direction:column; gap:.25rem}
.v .score{font-family:Newsreader,serif; font-size:2.5rem; line-height:1; font-variant-numeric:tabular-nums}
.v .act{font-family:"IBM Plex Mono",monospace; font-size:.7rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--faint); margin-bottom:.4rem}
.v p{font-size:.83rem; color:var(--slate); line-height:1.6}
.v p b{color:var(--ink); font-weight:600}
.said{margin:1.8rem 0 0; padding:1.2rem 1.3rem; background:var(--band); border:1px solid var(--hair)}
.said p{font-family:Newsreader,serif; font-size:1.2rem; line-height:1.5}
.said cite{display:block; margin-top:.7rem; font-style:normal; font-family:"IBM Plex Mono",monospace;
  font-size:.72rem; color:var(--faint)}

.racebox{padding:1rem .95rem 1rem}
.racehead{display:flex; align-items:center; justify-content:space-between; gap:1rem;
  padding-bottom:.9rem; border-bottom:1px solid var(--hair)}
#replay{font-family:"IBM Plex Mono",monospace; font-size:.76rem; letter-spacing:.04em;
  background:var(--ink); color:var(--paper); border:none; padding:.55rem 1rem; cursor:pointer}
#replay:hover{opacity:.87}
#replay:focus-visible{outline:2px solid var(--jev); outline-offset:2px}
.clock{font-size:1.5rem; color:var(--ink)}
.lane{padding:1rem 0 .3rem; border-bottom:1px solid var(--hair)}
.lane:last-of-type{border-bottom:none}
.lanehead{display:flex; justify-content:space-between; align-items:baseline; gap:1rem; flex-wrap:wrap}
.lanehead .who{font-family:"IBM Plex Mono",monospace; font-size:.76rem; letter-spacing:.05em;
  display:flex; align-items:center; gap:.45rem}
.wk{color:var(--faint); letter-spacing:.02em; margin-left:.3rem}
.tally{font-size:.8rem; color:var(--slate)}
.track{height:3px; background:var(--grid); margin:.6rem 0 .55rem}
.fill{height:100%; width:100%}
.chips{display:flex; flex-wrap:wrap; gap:3px}
.chips b{display:block; width:11px; height:11px; background:var(--grid); border-radius:1px}
.chips b.flight{background:var(--faint); opacity:.45}
.chips b.done{background:var(--jev)}
.chips b.doneM{background:var(--llm)}
.chips b.abst{background:transparent; border:1px solid var(--llm)}
@media (max-width:620px){ .verdicts{grid-template-columns:1fr} }
pre.code .hit{display:block; background:var(--band); box-shadow:inset 2px 0 0 0 var(--jev);
  margin:0 -.9rem; padding:0 .9rem}
.explorer{margin-top:2rem; border:1px solid var(--rule); background:var(--raised)}
.filters{display:flex; flex-wrap:wrap; border-bottom:1px solid var(--rule)}
.filters button{font-family:"IBM Plex Mono",monospace; font-size:.71rem; letter-spacing:.03em;
  background:none; border:none; border-right:1px solid var(--hair); color:var(--slate);
  padding:.65rem .8rem; cursor:pointer}
.filters button[aria-selected="true"]{background:var(--band); color:var(--ink); font-weight:500;
  box-shadow:inset 0 -2px 0 0 var(--jev)}
.filters button:focus-visible{outline:2px solid var(--jev); outline-offset:-2px}
.exgrid{display:grid; grid-template-columns:minmax(0,300px) minmax(0,1fr)}
.exlist{border-right:1px solid var(--rule); max-height:580px; overflow-y:auto}
.exrow{display:block; width:100%; text-align:left; background:none; border:none;
  border-bottom:1px solid var(--hair); padding:.6rem .8rem; cursor:pointer; color:inherit}
.exrow:hover{background:var(--band)}
.exrow[aria-selected="true"]{background:var(--band); box-shadow:inset 3px 0 0 0 var(--jev)}
.exrow:focus-visible{outline:2px solid var(--jev); outline-offset:-2px}
.exrow .rid{font-family:"IBM Plex Mono",monospace; font-size:.71rem; color:var(--ink);
  display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.exrow .loc{font-family:"IBM Plex Mono",monospace; font-size:.65rem; color:var(--faint);
  display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-top:.1rem}
.bars{display:flex; gap:2px; margin-top:.4rem; align-items:flex-end; height:14px}
.bars span{width:22px; border-radius:1px; min-height:1px; display:block}
.exdetail{padding:1rem 1.1rem 1.2rem; min-width:0}
.dhead{display:flex; flex-wrap:wrap; gap:.3rem .9rem; align-items:baseline;
  border-bottom:1px solid var(--hair); padding-bottom:.7rem}
.dhead .rid{font-family:"IBM Plex Mono",monospace; font-size:.84rem; font-weight:500}
.dhead .loc{font-family:"IBM Plex Mono",monospace; font-size:.68rem; color:var(--faint);
  overflow-wrap:anywhere}
.dscores{display:grid; grid-template-columns:repeat(3,1fr); gap:.65rem; margin:.9rem 0}
.ds{border:1px solid var(--hair); padding:.5rem .6rem}
.ds em{font-style:normal; font-family:"IBM Plex Mono",monospace; font-size:.63rem;
  letter-spacing:.09em; color:var(--faint); display:block}
.ds strong{font-family:Newsreader,serif; font-size:1.5rem; font-weight:500; line-height:1.25;
  font-variant-numeric:tabular-nums; display:block}
.ds small{font-size:.65rem; color:var(--faint); font-family:"IBM Plex Mono",monospace}
.dcode{background:var(--paper); border:1px solid var(--hair); overflow-x:auto; margin:.2rem 0 .85rem}
.dcode pre{margin:0; padding:.7rem 0; font-family:"IBM Plex Mono",monospace; font-size:.73rem;
  line-height:1.72}
.dcode i{display:block; font-style:normal; padding:0 .8rem; white-space:pre}
.dcode i.on{background:var(--band); box-shadow:inset 2px 0 0 0 var(--jev)}
.dcode i b{color:var(--faint); font-weight:400; user-select:none; display:inline-block;
  width:3.4em; text-align:right; padding-right:.9em}
.dwhy{font-size:.81rem; line-height:1.6; color:var(--slate); border-left:2px solid var(--llm);
  padding-left:.8rem}
.dwhy b{color:var(--ink); font-weight:600; display:block; font-family:"IBM Plex Mono",monospace;
  font-size:.65rem; letter-spacing:.08em; margin-bottom:.25rem}
.dflag{font-family:"IBM Plex Mono",monospace; font-size:.67rem; color:var(--llm);
  margin-top:.65rem; display:block; line-height:1.5}
@media (max-width:760px){
  .exgrid{grid-template-columns:1fr}
  .exlist{border-right:none; border-bottom:1px solid var(--rule); max-height:260px}
  .dscores{grid-template-columns:1fr}
}
.film{display:block; width:100%; height:auto; background:var(--band);
  border:1px solid var(--rule)}.ddesc{font-size:.82rem; color:var(--slate); margin-bottom:.5rem; line-height:1.55;
  overflow-wrap:anywhere}
</style>

<header class="wrap">
  <p class="eyebrow">Calibration audit &middot; historical recording: September 20, 2026</p>
  <p>Archived scores and media describe that recorded run. Current source review and live scans are reported separately.</p>
  <h1>Can you trust 0.85?</h1>
  <p class="standfirst">Every finding this static-analysis pipeline reports carries a confidence
  number. Until last week every one of those numbers was a literal somebody typed. This is what
  happened when we measured them against 82 findings with known answers &mdash; and what two
  models said when asked the same question.</p>
  <div class="byline">
    <span>82 findings &middot; 60 true / 22 false</span>
    <span>46 files &middot; 6 languages</span>
    <span>eval/rule_accuracy corpus</span>
  </div>
</header>

<section class="wrap stack">
  <p class="eyebrow">The claim under test</p>
  <p class="lede">A confidence of 0.85 is a promise: <em>of the findings I label this way, roughly
  85&nbsp;out of 100 are real.</em> The pipeline takes that promise literally &mdash; it drops
  anything below <code>min_confidence</code>, so the threshold is only as good as the number it
  filters on.</p>
  <p>The measure for whether a promise like that holds is Expected Calibration Error. Bucket every
  finding by what it claimed, compare each bucket to how often it was actually right, and average
  the gaps by bucket size. The archived implementation compares accuracy to bin midpoints,
  so these values are a legacy calibration proxy rather than mean-confidence ECE.</p>
  <div class="strip" role="list">
    <div class="cell" role="listitem">
      <span class="who"><span class="swatch" style="background:var(--constants)"></span>CONSTANTS</span>
      <span class="ece" style="color:var(--constants)">__ECE_C__</span>
      <span class="note">Hand-set literals. The shipped behaviour.</span>
    </div>
    <div class="cell" role="listitem">
      <span class="who"><span class="swatch" style="background:var(--jev)"></span>JEV</span>
      <span class="ece" style="color:var(--jev)">__ECE_J__</span>
      <span class="note">A probability head. Answered all 82.</span>
    </div>
    <div class="cell" role="listitem">
      <span class="who"><span class="swatch" style="background:var(--llm)"></span>CLASSIFIER</span>
      <span class="ece" style="color:var(--llm)">__ECE_M__</span>
      <span class="note">Haiku, prompted as a reviewer. Declined 14.</span>
    </div>
  </div>
  <p>One of those clears the bar. The one that reads worst is not the constants.</p>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Sixty seconds</p>
    <h2>Watch it decide</h2>
    <p>The September 20 recording: the finding up close, the explorer, and the two scorers racing
    through 82 findings at real speed. Silent screen recording; later text corrections are not in this video.</p>
  </div>
  <figure>
    <video class="film" controls preload="none" poster="../poster.jpg"
           aria-label="Sixty-second walkthrough of the calibration findings">
      <source src="../calibration-walkthrough.mp4" type="video/mp4">
      Your browser cannot play this video. It is a 60-second screen recording of this page.
    </video>
    <figcaption>Recorded at 1&times; against the live page. The race section is an unedited
    replay of a real scoring run.</figcaption>
  </figure>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">One decision &middot; this repo&rsquo;s own source</p>
    <h2>The scanner flags its own detector</h2>
    <p>Line 476 of <code>security/patterns.py</code> is the regular expression that finds security
    TODOs. The unresolved-TODO rule matched it. Here is what the pipeline decided to do.</p>
  </div>

  <figure>
    <div class="codeframe">
      <div class="codehead">
        <span class="mono">packages/code-intel/&hellip;/integrations/security/patterns.py</span>
        <span class="mono rulechip">bug/unresolved-todo/fixme-marker &middot; info</span>
      </div>
      <pre class="code"><span class="ln">474</span>     [], False),
<span class="ln">475</span>    (<span class="str">"todo_fixme_security"</span>,
<span class="hit"><span class="ln">476</span>     r<span class="str">&quot;&quot;&quot;(?:#|//|/\\*)\\s*(?:TODO|FIXME|HACK|XXX)\\s*.*?(?:security|auth|&hellip;&quot;&quot;&quot;</span></span>
<span class="ln">477</span>     <span class="str">"info"</span>, <span class="str">"CWE-546"</span>,
<span class="ln">478</span>     <span class="str">"Security-related TODO/FIXME comment"</span>,
<span class="ln">479</span>     <span class="str">"Address the security concern before deploying to production"</span>,
<span class="ln">480</span>     [], True),</pre>
      <p class="codenote"><b>What fired:</b> the unresolved-TODO rule, on the pattern that defines
      the unresolved-TODO rule. There is no TODO here to resolve &mdash; only a detector for them.
      The same rule fires on three more of its own definitions a few lines away.</p>
    </div>

    <div class="verdicts">
      <div class="v">
        <span class="who"><span class="swatch" style="background:var(--constants)"></span>CONSTANTS</span>
        <span class="score" style="color:var(--constants)">0.95</span>
        <span class="act">kept &mdash; near certain</span>
        <p>A literal in the rule file, and among the highest confidences anywhere in the pipeline.
        It is asserted before anything has looked at the line. Cost: nothing. Time: none.</p>
      </div>
      <div class="v">
        <span class="who"><span class="swatch" style="background:var(--jev)"></span>JEV</span>
        <span class="score" style="color:var(--jev)">0.15</span>
        <span class="act">dropped</span>
        <p>A probability in <b>371&nbsp;ms</b>. No prose, and none offered &mdash; the number is
        the whole output, and the number is what the threshold consumes.</p>
      </div>
      <div class="v">
        <span class="who"><span class="swatch" style="background:var(--llm)"></span>CLASSIFIER</span>
        <span class="score" style="color:var(--llm)">0.05</span>
        <span class="act">dropped</span>
        <p>Also dropped it, in <b>1,582&nbsp;ms</b>, and said why. On this finding the extra
        second and a half buys an audit trail.</p>
      </div>
    </div>

    <blockquote class="said">
      <p>&ldquo;This is a regex pattern string used for security scanning purposes to detect
      TODO/FIXME markers&hellip; not an actual unresolved TODO/FIXME marker in the codebase
      itself.&rdquo;</p>
      <cite>&mdash; the classifier, correctly</cite>
    </blockquote>
    <figcaption>Both models agree the constant is wrong, and here they are right. 0.95 is a
    near-certainty asserted about a line no rule author ever saw. Note also what the fast answer
    costs you: jev gives you 0.15 and nothing to argue with.</figcaption>
  </figure>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Explore &middot; 82 findings &middot; 31 rules &middot; real source</p>
    <h2>Pick any finding and see all three answers</h2>
    <p>These come from running the rules over this repository&rsquo;s own
    <code>attocode_intel</code> package &mdash; real functions in real files, no test fixtures.
    At recording time they had <b>no reviewed labels</b>, so this historical panel does not establish who was
    right. It shows what each scorer does, and where they part company.</p>
  </div>

  <div class="explorer">
    <div class="filters" id="filters" role="tablist"></div>
    <div class="exgrid">
      <div class="exlist" id="exlist" role="listbox" aria-label="Findings"></div>
      <div class="exdetail" id="exdetail"></div>
    </div>
  </div>
  <p class="wrap" style="font-size:.8rem;color:var(--faint);margin-top:.9rem;line-height:1.6">
    Bars on each row are constant / jev / classifier, tallest is most confident. A flat grey bar
    means the classifier declined &mdash; and a declined finding keeps its constant.</p>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Throughput &middot; recorded run</p>
    <h2>The same 82 findings, both scorers, real time</h2>
    <p>A replay of one actual scoring run, at 1&times; speed, using the per-call start and finish
    times recorded during it. Each tick is one finding. Both lanes run at the worker count they
    use in production.</p>
  </div>

  <figure>
    <div class="chartbox racebox">
      <div class="racehead">
        <button id="replay" type="button">&#9654;&nbsp; Replay in real time</button>
        <span class="clock mono num" id="clock">0.00 s</span>
      </div>
      <div class="lane" id="lane-jev">
        <div class="lanehead">
          <span class="who"><span class="swatch" style="background:var(--jev)"></span>JEV
            <span class="wk">16 workers</span></span>
          <span class="mono num tally" id="tally-jev">82 / 82 &middot; 2.58 s</span>
        </div>
        <div class="track"><div class="fill" id="fill-jev" style="background:var(--jev)"></div></div>
        <div class="chips" id="chips-jev"></div>
      </div>
      <div class="lane" id="lane-llm">
        <div class="lanehead">
          <span class="who"><span class="swatch" style="background:var(--llm)"></span>CLASSIFIER
            <span class="wk">32 workers</span></span>
          <span class="mono num tally" id="tally-llm">82 / 82 &middot; 5.57 s</span>
        </div>
        <div class="track"><div class="fill" id="fill-llm" style="background:var(--llm)"></div></div>
        <div class="chips" id="chips-llm"></div>
      </div>
      <div class="legend">
        <i><span class="swatch" style="background:var(--jev)"></span>answered</i>
        <i><span class="swatch" style="background:var(--faint);opacity:.45"></span>in flight</i>
        <i><span class="swatch" style="background:transparent;border:1px solid var(--llm)"></span>declined &mdash; reverts to the constant</i>
      </div>
    </div>
    <figcaption>Jev finished in <b>2.58&nbsp;s</b>, the classifier in <b>5.57&nbsp;s</b> &mdash; with
    twice the workers. Per call the gap is wider: a median of <b>395&nbsp;ms</b> against
    <b>1,714&nbsp;ms</b>. The classifier is buying deliberation you cannot threshold on; jev is
    returning the one number the pipeline actually consumes.</figcaption>
  </figure>

  <div class="wrap scroll">
    <table style="margin-top:1.4rem">
      <thead><tr><th>&nbsp;</th><th>Per call, median</th><th>Slowest call</th><th>Wall clock, 82</th><th>Workers</th><th>Declined</th></tr></thead>
      <tbody>
        <tr><td><span class="mono" style="color:var(--jev)">jev</span></td><td>395 ms</td><td>752 ms</td><td>2.58 s</td><td>16</td><td>0</td></tr>
        <tr><td><span class="mono" style="color:var(--llm)">classifier</span></td><td>1,714 ms</td><td>2,618 ms</td><td>5.57 s</td><td>32</td><td>14</td></tr>
      </tbody>
    </table>
  </div>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Reliability &middot; all 82</p>
    <h2>Now the same question, 82 times over</h2>
    <p>Each mark is a bucket of findings. Horizontal position is what the bucket claimed; vertical
    is how often it was right. The diagonal is a kept promise. Mark area is how many findings sit
    in that bucket &mdash; the big ones are where the error actually costs you.</p>
  </div>
  <figure>
    <div class="chartbox">__RELIABILITY__
      <div class="legend">
        <i><span class="swatch" style="background:var(--constants)"></span>constants</i>
        <i><span class="swatch" style="background:var(--jev)"></span>jev</i>
        <i><span class="swatch" style="background:var(--llm)"></span>classifier</i>
        <i>&#9679; area &prop; findings in bucket</i>
      </div>
    </div>
    <figcaption>Above the diagonal is underconfidence &mdash; the finding was better than advertised.
    Below is overconfidence, which is the direction that hurts: it means a threshold is keeping
    findings it should drop.</figcaption>
  </figure>
  <div class="wrap stack" style="margin-top:2.4rem">
    <div class="pull">The constants&rsquo; largest bucket holds 38 of 82 findings. It promises 85%.
    It delivers 63%.</div>
    <p>That single bucket is most of the pipeline&rsquo;s output, and it is overconfident by 22
    points. Worse, the constants have buckets in the other direction too &mdash; a group claiming
    0.4&ndash;0.5 turned out 86% true. The numbers are not merely wrong, they are wrong
    inconsistently, which is why no amount of moving <code>min_confidence</code> fixes them.</p>
    <p>The classifier fails differently, and more interestingly. It barely uses the middle of the
    range at all.</p>
  </div>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Distribution</p>
    <h2>A confident instrument with two settings</h2>
    <p>Where each scorer puts its findings along the 0&ndash;1 range. A useful probability spreads
    out; a verdict machine piles up at the ends.</p>
  </div>
  <figure>
    <div class="chartbox">__HIST__</div>
    <figcaption>The classifier put 40 findings in the top bucket and 15 in the bottom. Of those
    15 it was nearly certain were false, <b>7 were real</b>. Jev spreads across the range and its
    buckets land near the line.</figcaption>
  </figure>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Disagreement</p>
    <h2>Where the two models part company</h2>
    <p>Every finding both models scored, placed by what each one said. Along the rising diagonal
    they agree. The lower-right corner is the interesting one: jev says real, the classifier says
    no. Filled marks are findings that were genuinely real.</p>
  </div>
  <figure>
    <div class="chartbox">__SCATTER__
      <div class="legend">
        <i><span class="swatch" style="background:var(--jev);border-radius:50%"></span>truly a real finding</i>
        <i><span class="swatch" style="background:transparent;border:1.5px solid var(--faint);border-radius:50%"></span>truly a false positive</i>
        <i>hover or tab a mark</i>
      </div>
      <div class="readout" id="readout" aria-live="polite">Pick a mark to see the rule, the file and both scores.</div>
    </div>
    <figcaption>The 14 findings the classifier declined to score sit in the strip on the right.
    A declined finding keeps its hand-set constant, so an abstention is not neutral &mdash; it
    hands the decision back to the number we already know is miscalibrated.</figcaption>
  </figure>
</section>

<section class="wrap stack">
  <p class="eyebrow">The cause</p>
  <h2>It was asked the wrong question</h2>
  <p>The lower-right cluster is not random. Split the corpus by what kind of rule fired, and the
  classifier&rsquo;s behaviour separates cleanly:</p>
  <div class="split">
    <div class="half">
      <h3>Security rules</h3>
      <p class="big" style="color:var(--llm)">0.84</p>
      <p>mean score across 50 findings, of which 68% are real. Confident, and roughly right to be.</p>
    </div>
    <div class="half">
      <h3>Style, performance, correctness</h3>
      <p class="big" style="color:var(--llm)">0.51</p>
      <p>mean score across 32 findings, of which <b>81%</b> are real &mdash; a higher hit rate, scored
      far lower.</p>
    </div>
  </div>
  <div class="finding" style="margin-top:1.6rem">
    <span class="tag">Cause</span>
    <p>The prompt opens <em>&ldquo;You are a security code reviewer&hellip; is this a real security
    issue?&rdquo;</em> The corpus asks something else: <em>did this rule fire correctly?</em> On a
    <code>console.log</code> left in production or a <code>clone()</code> inside a loop, the honest
    answer to the first question is no, and the honest answer to the second is yes.</p>
  </div>
  <p>Seven of the eight real findings it scored below 0.20 are non-security rules. Its 0.25
  calibration error is consistent with a scope mismatch. Testing a rule-focused prompt is follow-up work; these observations do not establish the cause.</p>
  <p>The eighth is worth naming: <code>security/aws_access_key</code>, scored 0.05, genuinely real.
  Both scorers send source context to a third-party API, so credentials are stripped on the way
  out and it saw <code>AWS_KEY = &quot;[REDACTED:20 chars]&quot;</code>. Redaction removed the very
  evidence the rule fired on. Jev scored the same redacted line 0.77.</p>
</section>

<section class="wide">
  <div class="wrap stack">
    <p class="eyebrow">Consequence</p>
    <h2>What the threshold actually keeps</h2>
    <p>Filtering at a given confidence, of the findings kept, how many are real &mdash; and of all
    the real ones, how many survive.</p>
  </div>
  <div class="scroll wrap">
    <table>
      <thead><tr><th>Scorer</th><th>Kept at 0.5</th><th>Precision</th><th>Recall</th><th>F1</th><th>ECE</th></tr></thead>
      <tbody>__SWEEPROWS__</tbody>
    </table>
  </div>
  <div class="wrap stack" style="margin-top:1.8rem">
    <p>Jev keeps 75 of 82 findings and still holds precision, recovering almost every real one.
    The constants throw away real findings to reach a precision they never actually gain. The
    classifier keeps the fewest, and its 14 abstentions quietly revert to the constants.</p>
  </div>
</section>

<section class="wrap stack">
  <p class="eyebrow">What follows</p>
  <h2>What to do on Monday</h2>
  <ol class="steps">
    <li><span>Run the rules scorer in shadow for a week.
      <code>ATTOCODE_FLAG_CONFIDENCE=jev</code>, <code>ATTOCODE_FLAG_CONFIDENCE_MODE=shadow</code>. It logs a
      probability beside every constant and changes nothing.</span></li>
    <li><span>Label twenty rows a day. At recording time the notes reported ~3,600 logged decisions and zero labels,
      so those decisions do not establish real-world calibration. Local live use is an opt-in; source review remains necessary.</span></li>
    <li><span>Fix the classifier&rsquo;s prompt before writing it off. Ask whether the rule fired
      correctly, not whether it found a vulnerability, then re-run this page&rsquo;s numbers.</span></li>
    <li><span>Leave redaction alone. Losing one finding to a stripped credential is the correct
      trade against sending live keys to a third party.</span></li>
  </ol>
  <p style="margin-top:1.6rem">The constants were never audited because nothing made auditing cheap.
  The corpus, the labels and the calibration report were all sitting in the repo already; they had
  simply never been pointed at each other.</p>
</section>

<footer class="wrap">
  <p>Archived figures combine a scoring snapshot and a separate timing replay over the 46-file <code>eval/rule_accuracy</code> corpus,
  82 findings after dedup, 60 true positives established by the corpus&rsquo; own line annotations.
  Precision and recall here are finding-level at the stated threshold, which is not identical to
  the benchmark&rsquo;s rule-matching metric. Model scores may vary between runs; these data do not establish a variability bound. The constants are deterministic.</p>
</footer>

<script>

const REAL = __REAL__;
const BUCKETS = [
  ["all", "all", () => true],
  ["agree", "both agree", r => r.m !== null && r.j !== null && Math.abs(r.j - r.m) < .25],
  ["split", "jev keeps, classifier drops", r => r.m !== null && r.j !== null && r.j >= .5 && r.m < .5],
  ["declined", "classifier declined", r => r.m === null],
  ["sec", "security rules", r => r.rule.indexOf("security/") === 0],
];
const esc = t => String(t).replace(/[<>&]/g, c => ({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]));
const fmt = v => (v === null || v === undefined) ? "—" : v.toFixed(2);
const filtersEl = document.getElementById("filters");
const listEl = document.getElementById("exlist");
const detailEl = document.getElementById("exdetail");
let active = "all", chosen = 0;

BUCKETS.forEach(([key, label, fn]) => {
  const b = document.createElement("button");
  b.type = "button"; b.setAttribute("role","tab"); b.dataset.k = key;
  b.textContent = label + " (" + REAL.filter(fn).length + ")";
  b.setAttribute("aria-selected", String(key === "all"));
  b.addEventListener("click", () => { active = key; renderList(); });
  filtersEl.appendChild(b);
});

function bar(v, col){
  const h = v === null ? 2 : Math.max(2, Math.round(v * 14));
  return '<span style="height:' + h + 'px;background:' + (v === null ? "var(--grid)" : col) + '"></span>';
}
function renderList(){
  const fn = BUCKETS.find(b => b[0] === active)[2];
  const rows = REAL.map((r, i) => [r, i]).filter(pair => fn(pair[0]));
  filtersEl.querySelectorAll("button").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.k === active)));
  if (rows.length && !rows.some(pair => pair[1] === chosen)) chosen = rows[0][1];
  listEl.innerHTML = rows.map(pair => {
    const r = pair[0], i = pair[1];
    return '<button class="exrow" type="button" role="option" data-i="' + i +
      '" aria-selected="' + (i === chosen) + '">' +
      '<span class="rid">' + esc(r.rule) + '</span>' +
      '<span class="loc">' + esc(r.file.split("/").pop()) + ':' + r.line + '</span>' +
      '<span class="bars">' + bar(r.c,"var(--constants)") + bar(r.j,"var(--jev)") +
      bar(r.m,"var(--llm)") + '</span></button>';
  }).join("");
  listEl.querySelectorAll(".exrow").forEach(el =>
    el.addEventListener("click", () => { chosen = +el.dataset.i; renderList(); renderDetail(); }));
  renderDetail();
}
function renderDetail(){
  const r = REAL[chosen];
  if (!r) return;
  const code = r.lines.map(l =>
    '<i class="' + (l.n === r.line ? "on" : "") + '"><b>' + l.n + '</b>' +
    esc(l.t).slice(0, 240) + '</i>').join("");
  detailEl.innerHTML =
    '<div class="dhead"><span class="rid">' + esc(r.rule) + '</span>' +
    '<span class="loc">' + esc(r.file) + ':' + r.line + ' · ' + esc(r.sev) +
    (r.cwe ? ' · ' + esc(r.cwe) : '') + '</span></div>' +
    '<div class="dscores">' +
      '<div class="ds"><em>CONSTANT</em><strong style="color:var(--constants)">' + fmt(r.c) +
        '</strong><small>typed in the rule file</small></div>' +
      '<div class="ds"><em>JEV</em><strong style="color:var(--jev)">' + fmt(r.j) +
        '</strong><small>' + r.jms + ' ms</small></div>' +
      '<div class="ds"><em>CLASSIFIER</em><strong style="color:var(--llm)">' +
        (r.m === null ? "—" : fmt(r.m)) + '</strong><small>' +
        (r.m === null ? "declined · " : "") + r.mms + ' ms</small></div>' +
    '</div>' +
    '<p class="ddesc">' + esc(r.desc.length > 200 ? r.desc.slice(0,200).trim() + "\u2026" : r.desc) + '</p>' +
    '<div class="dcode"><pre>' + code + '</pre></div>' +
    '<p class="dwhy"><b>CLASSIFIER SAID</b>' + esc(r.why) + '</p>' +
    (r.redacted ? '<span class="dflag">⚠ a credential-shaped literal in this context was ' +
      'redacted before either model saw it</span>' : '');
}
chosen = REAL.findIndex(r => r.file.indexOf("security/patterns.py") >= 0 &&
                             r.rule.indexOf("bug/unresolved") === 0);
if (chosen < 0) chosen = 0;
renderList();

const RACE = __RACE__;
const JEV_WALL = 2578, LLM_WALL = 5571;
const lanes = {
  jev:{chips:document.getElementById("chips-jev"), fill:document.getElementById("fill-jev"),
       tally:document.getElementById("tally-jev"), s:"js", e:"je", p:"jp", wall:JEV_WALL, cls:"done"},
  llm:{chips:document.getElementById("chips-llm"), fill:document.getElementById("fill-llm"),
       tally:document.getElementById("tally-llm"), s:"ms", e:"me", p:"mp", wall:LLM_WALL, cls:"doneM"},
};
for (const k in lanes){
  const L = lanes[k];
  L.nodes = RACE.map(()=>{ const b=document.createElement("b"); L.chips.appendChild(b); return b; });
}
const clock = document.getElementById("clock");
function paint(t){          // t = ms into the run; null = finished state
  let slowest = 0;
  for (const k in lanes){
    const L = lanes[k];
    let done = 0, flight = 0;
    RACE.forEach((d,i)=>{
      const node = L.nodes[i];
      const fin = t === null || t >= d[L.e];
      const started = t === null || t >= d[L.s];
      let cls = "";
      if (fin){ done++; cls = d[L.p] === null ? "abst" : L.cls; }
      else if (started){ flight++; cls = "flight"; }
      if (node.className !== cls) node.className = cls;
    });
    const el = t === null ? L.wall : Math.min(t, L.wall);
    L.fill.style.width = (t === null ? 100 : Math.min(100, 100*t/L.wall)) + "%";
    L.tally.textContent = `${done} / ${RACE.length} · ${(el/1000).toFixed(2)} s`
      + (flight ? ` · ${flight} in flight` : "");
    slowest = Math.max(slowest, L.wall);
  }
  clock.textContent = ((t === null ? slowest : t)/1000).toFixed(2) + " s";
}
let raf = null;
function run(){
  if (raf) cancelAnimationFrame(raf);
  const t0 = performance.now(), total = Math.max(JEV_WALL, LLM_WALL) + 220;
  (function step(now){
    const t = now - t0;
    if (t >= total){ paint(null); raf = null; return; }
    paint(t);
    raf = requestAnimationFrame(step);
  })(t0);
}
paint(null);                                  // at rest: the finished run
document.getElementById("replay").addEventListener("click", run);
if (!matchMedia("(prefers-reduced-motion: reduce)").matches) setTimeout(run, 900);

const DATA = __DATA__;
const readout = document.getElementById("readout");
function show(d){
  readout.innerHTML = d
    ? `<b>${d.r}</b> &nbsp;${d.f}:${d.l}<br>jev <b>${d.j.toFixed(2)}</b> &nbsp; classifier <b>${d.m===null?"declined":d.m.toFixed(2)}</b> &nbsp; constant <b>${d.c.toFixed(2)}</b> &nbsp; truth <b>${d.tp?"real":"false positive"}</b><br><span style="opacity:.75">${d.s.replace(/[<>&]/g,c=>({"<":"&lt;",">":"&gt;","&":"&amp;"}[c]))}</span>`
    : "Pick a mark to see the rule, the file and both scores.";
}
document.querySelectorAll(".dot").forEach(el=>{
  const d = DATA[+el.dataset.i];
  const on = ()=>show(d), off = ()=>show(null);
  el.addEventListener("mouseenter",on); el.addEventListener("focus",on);
  el.addEventListener("mouseleave",off); el.addEventListener("blur",off);
});
</script>
"""

# ---------------------------------------------------------------- charts
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

SER = [("constant", "var(--constants)"), ("jev", "var(--jev)"), ("llm", "var(--llm)")]

def reliability_svg():
    width, height, padding = 620, 470, 52
    def x(v):
        return padding + v * (width - padding - 22)
    def y(v):
        return (height - padding) - v * (height - padding - 26)
    o = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Reliability diagram: claimed confidence against observed accuracy for three scorers">']
    o.append(f'<rect x="{padding}" y="{y(1)}" width="{width-padding-22}" height="{y(0)-y(1)}" fill="var(--band)"/>')
    for t in [0, .2, .4, .6, .8, 1]:
        o.append(f'<line x1="{padding}" y1="{y(t):.1f}" x2="{width-22}" y2="{y(t):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<line x1="{x(t):.1f}" y1="{y(0):.1f}" x2="{x(t):.1f}" y2="{y(1):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<text x="{padding-9}" y="{y(t)+4:.1f}" text-anchor="end" fill="var(--faint)" font-size="11" font-family="IBM Plex Mono, monospace">{t:.1f}</text>')
        o.append(f'<text x="{x(t):.1f}" y="{y(0)+19:.1f}" text-anchor="middle" fill="var(--faint)" font-size="11" font-family="IBM Plex Mono, monospace">{t:.1f}</text>')
    o.append(f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" stroke="var(--faint)" stroke-width="1" stroke-dasharray="4 4"/>')
    o.append(f'<text x="{x(.62):.1f}" y="{y(.70):.1f}" fill="var(--faint)" font-size="11" font-style="italic" font-family="Newsreader, serif" transform="rotate(-34 {x(.62):.1f} {y(.70):.1f})">promise kept</text>')
    for key, col in SER:
        bins = stats[key]["reliability"]
        pts = " ".join(f"{x(b['expected']):.1f},{y(b['observed']):.1f}" for b in bins)
        o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" opacity=".55"/>')
        for b in bins:
            r = 3.2 + (b["n"] ** 0.5) * 1.55
            o.append(f'<circle cx="{x(b["expected"]):.1f}" cy="{y(b["observed"]):.1f}" r="{r:.1f}" fill="{col}" opacity=".78"/>')
    big = max(stats["constant"]["reliability"], key=lambda b: b["n"])
    o.append(f'<text x="{x(big["expected"]):.1f}" y="{y(big["observed"])+26:.1f}" text-anchor="middle" fill="var(--ink)" font-size="11.5" font-family="IBM Plex Mono, monospace">{big["n"]} findings, off by 22 pts</text>')
    o.append(f'<text x="{padding-38}" y="{y(.5):.1f}" fill="var(--slate)" font-size="11" font-family="IBM Plex Mono, monospace" text-anchor="middle" transform="rotate(-90 {padding-38} {y(.5):.1f})">observed accuracy</text>')
    o.append(f'<text x="{(padding+width-22)/2:.1f}" y="{height-8}" fill="var(--slate)" font-size="11" font-family="IBM Plex Mono, monospace" text-anchor="middle">confidence claimed</text>')
    o.append("</svg>")
    return "".join(o)

def hist_svg():
    width, height, padding, gap = 620, 300, 52, 26
    lanes = [("constant", "var(--constants)", "constants"), ("jev", "var(--jev)", "jev"), ("llm", "var(--llm)", "classifier")]
    lane_h = (height - padding - gap) / 3
    o = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Distribution of scores across the range for each scorer">']
    def x(v):
        return padding + v * (width - padding - 22)
    for t in [0, .2, .4, .6, .8, 1]:
        o.append(f'<line x1="{x(t):.1f}" y1="14" x2="{x(t):.1f}" y2="{height-padding+8}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<text x="{x(t):.1f}" y="{height-padding+24:.1f}" text-anchor="middle" fill="var(--faint)" font-size="11" font-family="IBM Plex Mono, monospace">{t:.1f}</text>')
    for li, (key, col, label) in enumerate(lanes):
        top = 18 + li * lane_h
        base = top + lane_h - 12
        counts = {int(b["lo"] * 10): b["n"] for b in stats[key]["reliability"]}
        mx = max(counts.values())
        o.append(f'<text x="{padding-9}" y="{base:.1f}" text-anchor="end" fill="{col}" font-size="11" font-family="IBM Plex Mono, monospace">{label}</text>')
        o.append(f'<line x1="{padding}" y1="{base:.1f}" x2="{width-22}" y2="{base:.1f}" stroke="var(--rule)" stroke-width="1"/>')
        bw = (width - padding - 22) / 10
        for b in range(10):
            n = counts.get(b, 0)
            if not n:
                continue
            h = (n / mx) * (lane_h - 26)
            o.append(f'<rect x="{padding + b*bw + 1.6:.1f}" y="{base-h:.1f}" width="{bw-3.2:.1f}" height="{h:.1f}" fill="{col}" opacity=".8"/>')
            o.append(f'<text x="{padding + b*bw + bw/2:.1f}" y="{base-h-4:.1f}" text-anchor="middle" fill="var(--slate)" font-size="10" font-family="IBM Plex Mono, monospace">{n}</text>')
    o.append(f'<text x="{(padding+width-22)/2:.1f}" y="{height-6}" fill="var(--slate)" font-size="11" font-family="IBM Plex Mono, monospace" text-anchor="middle">score assigned</text>')
    o.append("</svg>")
    return "".join(o)

def scatter_svg():
    width, height, padding, lane = 620, 560, 56, 74
    plot_w = width - padding - 22 - lane
    def x(v):
        return padding + v * plot_w
    def y(v):
        return (height - padding) - v * (height - padding - 30)
    o = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Scatter of jev score against classifier score for each finding">']
    o.append(f'<rect x="{padding}" y="{y(1)}" width="{plot_w}" height="{y(0)-y(1)}" fill="var(--band)"/>')
    for t in [0, .2, .4, .6, .8, 1]:
        o.append(f'<line x1="{padding}" y1="{y(t):.1f}" x2="{padding+plot_w:.1f}" y2="{y(t):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<line x1="{x(t):.1f}" y1="{y(0):.1f}" x2="{x(t):.1f}" y2="{y(1):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        o.append(f'<text x="{padding-9}" y="{y(t)+4:.1f}" text-anchor="end" fill="var(--faint)" font-size="11" font-family="IBM Plex Mono, monospace">{t:.1f}</text>')
        o.append(f'<text x="{x(t):.1f}" y="{y(0)+19:.1f}" text-anchor="middle" fill="var(--faint)" font-size="11" font-family="IBM Plex Mono, monospace">{t:.1f}</text>')
    o.append(f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(1)}" y2="{y(1)}" stroke="var(--faint)" stroke-width="1" stroke-dasharray="4 4"/>')
    o.append(f'<text x="{x(.5):.1f}" y="{y(.18):.1f}" text-anchor="middle" fill="var(--ink)" font-size="11.5" font-family="IBM Plex Mono, monospace">jev says real, classifier says no</text>')
    for i, d in enumerate(DATA_IDX):
        if d["m"] is None:
            continue
        fill = "var(--jev)" if d["tp"] else "none"
        o.append(
            f'<circle class="dot" tabindex="0" data-i="{i}" cx="{x(d["j"]):.1f}" cy="{y(d["m"]):.1f}" r="5" '
            f'fill="{fill}" stroke="{"var(--jev)" if d["tp"] else "var(--faint)"}" stroke-width="1.4" opacity=".85">'
            f'<title>{esc(d["r"])} — jev {d["j"]:.2f}, classifier {d["m"]:.2f}</title></circle>'
        )
    lx = padding + plot_w + 30
    o.append(f'<line x1="{lx-13:.1f}" y1="{y(1):.1f}" x2="{lx-13:.1f}" y2="{y(0):.1f}" stroke="var(--rule)" stroke-width="1"/>')
    o.append(f'<text x="{lx+10:.1f}" y="{y(1)-9:.1f}" text-anchor="middle" fill="var(--faint)" font-size="10.5" font-family="IBM Plex Mono, monospace">declined</text>')
    for i, d in enumerate(DATA_IDX):
        if d["m"] is not None:
            continue
        fill = "var(--jev)" if d["tp"] else "none"
        jitter = ((i * 37) % 5 - 2) * 8
        o.append(
            f'<circle class="dot" tabindex="0" data-i="{i}" cx="{lx+jitter:.1f}" cy="{y(d["j"]):.1f}" r="5" '
            f'fill="{fill}" stroke="{"var(--jev)" if d["tp"] else "var(--faint)"}" stroke-width="1.4" '
            f'stroke-dasharray="2 1.6" opacity=".85">'
            f'<title>{esc(d["r"])} — jev {d["j"]:.2f}, classifier declined</title></circle>'
        )
    o.append(f'<text x="{padding-40}" y="{y(.5):.1f}" fill="var(--slate)" font-size="11" font-family="IBM Plex Mono, monospace" text-anchor="middle" transform="rotate(-90 {padding-40} {y(.5):.1f})">classifier score</text>')
    o.append(f'<text x="{(padding+plot_w)/2+10:.1f}" y="{height-8}" fill="var(--slate)" font-size="11" font-family="IBM Plex Mono, monospace" text-anchor="middle">jev score</text>')
    o.append("</svg>")
    return "".join(o)

DATA_IDX = data

rows_html = []
label = {"constant": "constants", "jev": "jev", "llm": "classifier"}
for key, col in SER:
    h = stats[key]["at_half"]
    rows_html.append(
        f'<tr><td><span class="mono" style="color:{col}">{label[key]}</span></td>'
        f'<td>{h["kept"]}</td><td>{h["precision"]:.2f}</td><td>{h["recall"]:.2f}</td>'
        f'<td>{h["f1"]:.2f}</td><td>{stats[key]["ece"]:.4f}</td></tr>'
    )

html = (HTML
    .replace("__ECE_C__", f'{stats["constant"]["ece"]:.3f}')
    .replace("__ECE_J__", f'{stats["jev"]["ece"]:.3f}')
    .replace("__ECE_M__", f'{stats["llm"]["ece"]:.3f}')
    .replace("__RELIABILITY__", reliability_svg())
    .replace("__HIST__", hist_svg())
    .replace("__SCATTER__", scatter_svg())
    .replace("__SWEEPROWS__", "".join(rows_html))
    .replace("__DATA__", json.dumps(data, separators=(",", ":")))
    .replace("__RACE__", (S / "race.json").read_text())
    .replace("__REAL__", (S / "real.json").read_text())
)
(args.output_dir / "calibration.html").write_text(html + "\n</html>", encoding="utf-8")
print("wrote calibration.html", len(html), "bytes")
