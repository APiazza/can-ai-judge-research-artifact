"""Workflow figure for the run plan, drawn in millimetres with matplotlib.

Version of 24 Oct 2026: coding sheet frozen as v1.0, human sample and final scores as in its section 5, and the
exploratory judge analysis added after the freeze."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch

HERE = Path(__file__).resolve().parent
W, H = 165, 226          # canvas, mm
MM = 1 / 25.4
PT = 0.3528              # mm per point

INK, GRID = '#222222', '#8A8A8A'
FILL, BAND, GATE = '#FFFFFF', '#F2F2F2', '#FCE9C8'

TEXT = {
    'en': {
        'font': ['Times New Roman'],
        'stages': ['Prepare', 'Run', 'Code', 'Analyze'],
        'materials': ('Materials', 'AI copies of pilot-v6 and clean-matched-v6\n(PDF and text versions)'),
        'prompts': ('Three prompts', 'Bare · Reader instructions · Reader + criteria'),
        'checks': ('Checks before running', 'model IDs · PDF input · default effort · tokens'),
        'gate': 'Plan approved',
        'settings': ('Every run', 'new API request · manuscript\nfirst, prompt after · no tools\n· default temperature'),
        'practice': ('20 practice runs', 'spread across models'),
        'main': ('540 runs', '480 main: 8 models × 3 prompts × 2 versions × 10\n40 effort: GPT-6 Astra at low and max · 20 format: Gemini 4 Argon'),
        'record': ('Run record', 'model ID · construction tag ·\ndate · effort · tokens ·\nstop reason'),
        'sheet': ('Coding sheet', 'drafted on the practice\nreviews, reviewed and\nrevised, frozen as v1.0\non 23 Oct, before any\nmain review is read'),
        'key': ('Answer key (pilot-v6)', 'stored apart; used only\nfor coding; never sent to\na model under review'),
        'keylabel': 'answer key',
        'blind': ('Blinding', 'labels removed · random IDs · shuffled'),
        'llm': ('Two LLM coders: every review', 'Claude Sonnet 5.5 and Qwen3.8 (open weights)\nF / P / – per concern · criticism count'),
        'human': ('Human sample (40)', 'drawn at blinding;\ncore 24 coded first,\nthe other 16 if time allows;\ntwo investigators code\nindependently, before\nseeing the LLM codes'),
        'agree': ('Agreement and final scores', 'LLM–LLM · human–human · human–LLM · provider check\nLLM coders differ → results with the lower and the higher code\nagreed human codes check each LLM coder (5 in 6)\ncriticisms: average of the two LLM counts'),
        'judge': ('Judge analysis', 'exploratory; added 24 Oct,\nafter the sheet was frozen\n240 pairs of main reviews\n(same version and prompt)\nboth orders · K&W prompt\nGPT-5.5 (maximum effort)\nand Qwen3.8'),
        'join': ('Unblind', 'join the codes and judge verdicts to the run records'),
        'tables': ('Results tables', 'by concern · pilot vs clean gap · by prompt · effort\nsplit by construction tag · criticism counts\nexploratory: does judge preference track detection?'),
        'readers': ('Reader reports', 'after IRB approval;\nLLM coders only if\nthe reader permits'),
    },
}


def box(ax, x0, y0, x1, y1, title, body='', fill=FILL, dashed=False, tsize=8.2, bsize=7.0):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle='round,pad=0,rounding_size=1.6',
                                linewidth=0.8, edgecolor=INK, facecolor=fill,
                                linestyle=(0, (3, 2)) if dashed else '-', zorder=3))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if not body:
        ax.text(cx, cy, title, ha='center', va='center', fontsize=tsize, weight='bold', color=INK, zorder=4)
        return (x0, y0, x1, y1)
    th, lh, gap = tsize * PT * 1.2, bsize * PT * 1.3, 1.0
    n = body.count('\n') + 1
    top = cy + (th + gap + n * lh) / 2
    ax.text(cx, top - th / 2, title, ha='center', va='center', fontsize=tsize, weight='bold', color=INK, zorder=4)
    ax.text(cx, top - th - gap - n * lh / 2, body, ha='center', va='center', fontsize=bsize, color=INK,
            linespacing=1.3, zorder=4)
    return (x0, y0, x1, y1)


def arrow(ax, p, q, dashed=False):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle='-|>', mutation_scale=8, linewidth=0.8, color=INK,
                                 linestyle=(0, (3, 2)) if dashed else '-', shrinkA=0, shrinkB=0, zorder=2))


def path(ax, pts, dashed=False):
    """Orthogonal polyline whose last segment ends in an arrowhead."""
    for a, b in zip(pts[:-2], pts[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=INK, lw=0.8, ls=(0, (3, 2)) if dashed else '-', zorder=2)
    arrow(ax, pts[-2], pts[-1], dashed=dashed)


def draw(lang):
    T = TEXT[lang]
    plt.rcParams['font.family'] = T['font']
    fig = plt.figure(figsize=(W * MM, H * MM))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis('off')

    for (y0, y1), name in zip([(177, 225), (125, 175), (65, 123), (1, 63)], T['stages']):
        ax.add_patch(Rectangle((0, y0), W, y1 - y0, facecolor=BAND, edgecolor='none', zorder=0))
        ax.text(2.2, y1 - 3.2, name, ha='left', va='center', fontsize=8.6, weight='bold', color=GRID, zorder=1)

    cx0, cx1, rx0, rx1 = 46, 119, 124, 160
    mid = (cx0 + cx1) / 2

    # Prepare
    m = box(ax, cx0, 210, cx1, 223, *T['materials'])
    p = box(ax, cx0, 194.5, cx1, 205.5, *T['prompts'])
    c = box(ax, cx0, 179, cx1, 190, *T['checks'])
    k = box(ax, rx0, 184, rx1, 206, *T['key'], dashed=True)
    arrow(ax, (mid, m[1]), (mid, p[3])); arrow(ax, (mid, p[1]), (mid, c[3]))

    # Run
    g = box(ax, cx0 + 8, 164, cx1 - 8, 171.5, T['gate'], fill=GATE)
    pr = box(ax, cx0, 148, cx1, 159, *T['practice'])
    mn = box(ax, cx0, 128, cx1, 144, *T['main'])
    box(ax, 3, 129, 40, 150, *T['settings'])
    rec = box(ax, rx0, 128, rx1, 146, *T['record'])
    arrow(ax, (mid, c[1]), (mid, g[3]))
    arrow(ax, (mid, g[1]), (mid, pr[3]))
    arrow(ax, (mid, pr[1]), (mid, mn[3]))
    arrow(ax, (mn[2], 136), (rec[0], 136))

    # Code
    bl = box(ax, cx0, 109, cx1, 119, *T['blind'])
    sh = box(ax, 3, 86, 40, 110, *T['sheet'])
    llm = box(ax, cx0, 91, cx1, 104, *T['llm'])
    hu = box(ax, rx0, 81, rx1, 108.5, *T['human'])
    ag = box(ax, cx0, 67, cx1, 87, *T['agree'])
    arrow(ax, (mid, mn[1]), (mid, bl[3]))
    arrow(ax, (mid, bl[1]), (mid, llm[3]))
    arrow(ax, (mid, llm[1]), (mid, ag[3]))
    path(ax, [(pr[0], 153.5), (42, 153.5), (42, 117), (21.5, 117), (21.5, sh[3])])     # practice reviews -> sheet
    arrow(ax, (sh[2], 97.5), (llm[0], 97.5))                                           # frozen sheet -> LLM coders
    path(ax, [(cx1, 114), (142, 114), (142, hu[3])])                                   # blinded reviews -> human sample
    path(ax, [(142, hu[1]), (142, 77), (cx1, 77)])                                     # human codes -> agreement
    # answer key -> both coders (dashed), labelled
    kx = 121.5
    path(ax, [(rx0 + 5, k[1]), (rx0 + 5, 176), (kx, 176), (kx, 99.5), (llm[2], 99.5)], dashed=True)
    path(ax, [(kx, 111), (129, 111), (129, hu[3])], dashed=True)
    ax.text(kx, 154, T['keylabel'], rotation=90, ha='center', va='center', fontsize=6.6, style='italic',
            color=INK, bbox=dict(facecolor=BAND, edgecolor='none', pad=0.8), zorder=5)

    # Analyze
    jn = box(ax, cx0, 45, cx1, 56, *T['join'])
    jd = box(ax, 3, 24, 40, 54, *T['judge'])
    tb = box(ax, 3, 3, cx1, 20.5, *T['tables'], tsize=8.6, bsize=7.2)
    rd = box(ax, rx0, 3, rx1, 20.5, *T['readers'], dashed=True)
    arrow(ax, (mid, ag[1]), (mid, jn[3]))
    arrow(ax, (mid, jn[1]), (mid, tb[3]))
    # blinded main reviews -> judge; gap where it passes under the sheet -> LLM arrow
    ax.plot([cx0, 44, 44], [111.5, 111.5, 98.7], color=INK, lw=0.8, zorder=2)
    path(ax, [(44, 96.3), (44, 60), (21.5, 60), (21.5, jd[3])])
    arrow(ax, (jd[2], 50.5), (jn[0], 50.5))                                            # verdicts -> unblind
    path(ax, [(rx1, 136), (163, 136), (163, 50.5), (cx1, 50.5)])                       # run records -> unblind
    arrow(ax, (rd[0], 11.75), (tb[2], 11.75), dashed=True)

    out = ARGS.out / 'workflow_2026-10-24.png'
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(out)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=Path('.'), type=Path, help='folder for the PNG')
    ARGS = ap.parse_args()
    draw('en')
