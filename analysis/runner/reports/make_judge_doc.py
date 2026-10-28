"""Build the judge analysis and recommendations document (Word) from harness.judge_tables and harness.recommendations output."""
import argparse
import json
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from docx_helpers import set_font, add_runs, add_page_number  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--runs', required=True, type=Path, help='run records folder (data_dir in config/paths.local.yaml)')
ap.add_argument('--out', default=Path('.'), type=Path, help='folder for the output')
ARGS = ap.parse_args()

A = ARGS.runs / 'judge/judge_v1-20261026T053102Z/analysis/20261026T055439Z/judge_analysis.json'
OUT = ARGS.out / 'Pilot_Results_Judge_Analysis_2026-10-26.docx'
LATIN = EAST = 'Times New Roman'
BODY = 10.5
a = json.loads(A.read_text(encoding='utf-8'))
G, Q = a['judges']['gpt-5-5'], a['judges']['qwen3p8-2p4t-a95b']
PROMPTS = {'p1_bare_v1': 'Bare', 'p2_reader_v1': 'Reader instructions', 'p3_criteria_v1': 'Reader + criteria'}
TYPES = {'Technical': 'C5†, C6', 'Technical/mixed': 'C4, C7†', 'Mixed': 'C2', 'Taste/mixed': 'C1, C3, C8'}


def res(j, which, level, scope='all pairs'):
    return j['results'][f'{which}|{level}|{scope}']


def two(get, j, level, scope='all pairs', whiches=('lower', 'higher')):
    """'lo–hi' share in % across the code readings, with n."""
    rs = [get(res(j, w, level, scope)) for w in whiches]
    if any(r['share'] is None for r in rs):
        return '–'
    s = sorted(round(r['share'] * 100) for r in rs)
    n = sorted(r['n'] for r in rs)
    sh = f'{s[0]}' if s[0] == s[-1] else f'{s[0]}–{s[-1]}'
    nn = f'{n[0]}' if n[0] == n[-1] else f'{n[0]}–{n[-1]}'
    return f'{sh} (n {nn})'


def ci(get, j, level, scope='all pairs', whiches=('lower', 'higher')):
    rs = [get(res(j, w, level, scope)) for w in whiches]
    lo = min(r['ci95'][0] for r in rs); hi = max(r['ci95'][1] for r in rs)
    return f'{lo * 100:.0f}–{hi * 100:.0f}'


def band(get, j, level, scope='all pairs', whiches=('lower', 'higher')):
    def b(x):
        return 'largely tracks' if x >= 0.8 else 'weak guide' if x <= 0.6 else 'mixed'
    bs = {b(get(res(j, w, level, scope))['share']) for w in whiches}
    return bs.pop() if len(bs) == 1 else 'between bands'


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    tcPr.append(shd)


doc = Document()
sec = doc.sections[0]
sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
sec.left_margin = sec.right_margin = Cm(2.2); sec.top_margin = sec.bottom_margin = Cm(2.0)
normal = doc.styles['Normal']; set_font(normal, LATIN, EAST, BODY)
normal.paragraph_format.space_after = Pt(5); normal.paragraph_format.line_spacing = 1.12
h = doc.styles['Heading 1']; set_font(h, LATIN, EAST, BODY + 1.5, bold=True); h.font.italic = False
h.paragraph_format.space_before = Pt(10); h.paragraph_format.space_after = Pt(4); h.paragraph_format.keep_with_next = True
add_page_number(sec)


def P(text, size=None, after=None, keep=False):
    p = doc.add_paragraph(); add_runs(p, text, LATIN, EAST)
    for r in p.runs:
        if size:
            r.font.size = Pt(size)
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    if keep:
        p.paragraph_format.keep_with_next = True
    return p


def table(rows, widths, size=8.5, center_from=1):
    tb = doc.add_table(rows=len(rows), cols=len(rows[0])); tb.style = 'Table Grid'
    tb.alignment = WD_TABLE_ALIGNMENT.CENTER; tb.autofit = False
    mar = OxmlElement('w:tblCellMar')
    for side in ('left', 'right'):
        el = OxmlElement(f'w:{side}'); el.set(qn('w:w'), '60'); el.set(qn('w:type'), 'dxa'); mar.append(el)
    tb._tbl.tblPr.append(mar)
    for j, w in enumerate(widths):
        tb.columns[j].width = Cm(w)
    for i, row in enumerate(rows):
        tb.rows[i]._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for j, val in enumerate(row):
            cell = tb.cell(i, j); cell.width = Cm(widths[j])
            p = cell.paragraphs[0]; p.paragraph_format.space_after = Pt(0); p.paragraph_format.line_spacing = 1.0
            if j >= center_from:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if i < len(rows) - 1:
                p.paragraph_format.keep_with_next = True
            add_runs(p, str(val), LATIN, EAST)
            for r in p.runs:
                r.font.size = Pt(size)
                if i == 0:
                    r.bold = True
            if i == 0:
                shade(cell, 'E7E7E7')
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def caption(text):
    P(text, size=BODY - 0.5, after=3, keep=True)


def note(text):
    P(text, size=BODY - 2, after=8)


o1 = lambda r: r['agreement']['all 8 concerns']
o1r = lambda r: r['agreement']['reliably coded only']
o3 = lambda r: r['raised_on_clean']['all 8 concerns']
VARIANTS = (('GPT-5.5, all pairs', G, 'all pairs', ('lower', 'higher')),
            ('GPT-5.5, without OpenAI pairs', G, 'no OpenAI pairs', ('lower', 'higher')),
            ('Qwen3.8, all pairs', Q, 'all pairs', ('lower', 'higher')),
            ('Qwen3.8, without OpenAI pairs', Q, 'no OpenAI pairs', ('lower', 'higher')),
            ('Qwen3.8, Sonnet’s codes only', Q, 'all pairs', ('sonnet',)))


def what(text):
    P('*What it shows:* ' + text, size=BODY - 1, after=3, keep=True)


def share_only(cell):
    return cell.split(' (')[0]


p = doc.add_paragraph(); r = p.add_run('Pilot Results: Judge Analysis and Recommendations'); set_font(r, LATIN, EAST, BODY + 5, bold=True)
p.paragraph_format.space_after = Pt(2)
P('Investigator 1, 26 October 2026', after=8)
P('This analysis is exploratory. We added it after the coding sheet was frozen (run plan, section 8). We paired the 480 '
  'main reviews into 240 pairs, each with the same version and prompt but two different models. GPT-5.5 at maximum effort '
  'and Qwen3.8 judged every pair twice, once in each order, with King and Worthington’s pairwise prompt. A pair counts as '
  f'decided when the same review wins both times. GPT-5.5 decided {G["decided"]} of the 240 pairs and Qwen3.8 '
  f'{Q["decided"]}. The review shown first won {G["share_first_position_wins"]:.0%} and {Q["share_first_position_wins"]:.0%} '
  'of the time, so the order did not matter much.')
P('**How to read the tables.** Whether a review caught a problem comes from the final LLM codes, as in the coding results. '
  'F means the review raised a planted problem with its reason; “F or P” means it raised it at all. A range like 82–83 '
  'shows the result with the lower and the higher code. n is the number of decided pairs behind a result. For Table J1 '
  'we set the bands before seeing any results: 80% or more means the judge’s preference largely tracks detection, 60% or '
  'less means it is a weak guide, and anything in between is mixed.')

doc.add_heading('Summary', level=1)
p3 = lambda r: r['agreement_by_prompt']['p3_criteria_v1']
mins = lambda j: min(round(res(j, w, 'F')['preferred_but_missed'][c]['share'] * 100) for w in ('lower', 'higher') for c in ('C1', 'C2', 'C3', 'C4', 'C5', 'C8'))
maxs = lambda j: max(round(res(j, w, 'F')['preferred_but_missed'][c]['share'] * 100) for w in ('lower', 'higher') for c in ('C1', 'C2', 'C3', 'C4', 'C5', 'C8'))
RC = json.loads((ARGS.runs / 'recommendations/20261026T195856Z/tables/20261026T200718Z/recommendations.json').read_text(encoding='utf-8'))
pl, cl = RC['prompts_2_3']['flawed'], RC['prompts_2_3']['clean']
same = [m for m, d in RC['by_model_prompts_2_3'].items() if d['flawed']['Major revision'] == d['flawed']['n'] and d['clean']['Major revision'] == d['clean']['n']]
summary = [
    f'When two reviews of the planted version differ in how many planted problems they catch, GPT-5.5 picks the one that '
    f'catches more in {share_only(two(o1, G, "F"))}% of decided pairs. By our bands, its preference largely tracks detection. '
    f'Qwen3.8 does so in {share_only(two(o1, Q, "F"))}%, which is mixed (Table J1).',
    f'It is lowest among the Reader + criteria reviews: {share_only(two(p3, G, "F"))}% for GPT-5.5 and '
    f'{share_only(two(p3, Q, "F"))}% for Qwen3.8 (Table J2).',
    f'When only one review catches C6 or C7, neither judge ever picked the review that missed it. For the other problems, '
    f'GPT-5.5 picked the review that missed the problem in {mins(G)}–{maxs(G)}% of such pairs, and Qwen3.8 in '
    f'{mins(Q)}–{maxs(Q)}% (Table J3).',
    f'On the clean version, GPT-5.5 picks the review that raises more of these problems in {share_only(two(o3, G, "F"))}% '
    f'of pairs, and Qwen3.8 in {share_only(two(o3, Q, "F"))}% (Table J4).',
    f'Most reviews recommend major revision on both versions: {pl["Major revision"]} of 160 on each. '
    f'{["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"][len(same)]} of the 8 models recommended '
    f'major revision in all their prompt 2 and 3 reviews (Tables R1 and R2).',
]
for g in summary:
    P('• ' + g, after=3)

doc.add_heading('1. Does the judge prefer the review that catches more?', level=1)
caption('**Table J1.** Planted version: % of decided pairs in which the judge picks the review that catches more planted problems')
what('Whether the judge’s preference follows detection. Pairs where both reviews catch the same number are left out.')
rows = [['Judge and pairs', 'F', 'F or P', 'Band (F)']]
for lab, j, scope, wh in VARIANTS:
    rows.append([lab, two(o1, j, 'F', scope, wh), two(o1, j, 'FP', scope, wh), band(o1, j, 'F', scope, wh)])
table(rows, [6.0, 3.2, 3.2, 2.6])
note('Without OpenAI pairs: pairs with a GPT-6 Astra or Luna review are left out, because GPT-5.5 is also an OpenAI '
     'model. Sonnet’s codes only: Qwen is also one of our coders, so we also check its judgments against the other coder. '
     f'Leaving out C5 and C7, which are not reliably coded, gives {share_only(two(o1r, G, "F"))}% for GPT-5.5 and '
     f'{share_only(two(o1r, Q, "F"))}% for Qwen3.8 (F, all pairs).')

caption('**Table J2.** The same, by prompt and by problem type (F, all pairs)')
what('Whether the link between preference and detection holds for each prompt and each kind of problem.')
rows = [['', 'GPT-5.5', 'Qwen3.8']]
for pk, lab in PROMPTS.items():
    get = lambda r, pk=pk: r['agreement_by_prompt'][pk]
    rows.append([f'Prompt: {lab}', two(get, G, 'F'), two(get, Q, 'F')])
for ty, cs in TYPES.items():
    get = lambda r, ty=ty: r['agreement_by_type'][ty]
    rows.append([f'Type: {ty} ({cs})', two(get, G, 'F'), two(get, Q, 'F')])
table(rows, [6.2, 3.6, 3.6])
note('For a problem type, only the problems of that type are counted.')

doc.add_heading('2. Is a review that misses a problem still preferred?', level=1)
caption('**Table J3.** Planted version: % of decided pairs in which the judge picks the review that misses the problem')
what('For each problem, among pairs where only one review catches it, how often the judge picks the one that misses it. '
     'Lower is better.')
rows = [['Concern', 'GPT-5.5: F', 'GPT-5.5: F or P', 'Qwen3.8: F', 'Qwen3.8: F or P']]
for c in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8'):
    get = lambda r, c=c: r['preferred_but_missed'][c]
    rows.append([c + ('†' if c in ('C5', 'C7') else ''), two(get, G, 'F'), two(get, G, 'FP'), two(get, Q, 'F'), two(get, Q, 'FP')])
table(rows, [2.2, 3.0, 3.0, 3.0, 3.0])
note('–: too few pairs. Almost every planted-version review raises C6 at all, so with F or P there is at most one such pair.')

doc.add_heading('3. On the clean version, is the review that raises more preferred?', level=1)
caption('**Table J4.** Clean version: % of decided pairs in which the judge picks the review that raises more of the planted problems')
what('On the clean version the planted problems are fixed. This shows whether the judge prefers the review that still '
     'raises more of them.')
rows = [['Judge and pairs', 'F', 'F or P']]
for lab, j, scope, wh in VARIANTS:
    rows.append([lab, two(o3, j, 'F', scope, wh), two(o3, j, 'FP', scope, wh)])
table(rows, [6.0, 3.6, 3.6])
note('The other variants of Tables J2 and J3 (without OpenAI pairs, and Qwen against Sonnet’s codes) are in the data files.')

# ---------------- recommendations ----------------
OPT = ['Reject', 'Major revision', 'Minor revision', 'Accept', 'none stated']
LAB = {'claude-fable-5-1': 'Claude Fable 5.1', 'claude-haiku-5-5': 'Claude Haiku 5.5', 'gpt-6-astra': 'GPT-6 Astra',
       'gpt-6-luna': 'GPT-6 Luna', 'gemini-4-argon': 'Gemini 4 Argon', 'gemini-3-5-flash-lite': 'Gemini 3.5 Flash-Lite',
       'deepseek-v4p1-flash': 'DeepSeek V4.1 Flash', 'kimi-k3': 'Kimi K3'}
VER = {'flawed': 'Planted', 'clean': 'Clean'}
doc.add_heading('4. Recommendations', level=1)
P('Prompts 2 and 3 asked each reviewer to recommend reject, major revision, minor revision or accept. We read the '
  'recommendation from the text after “recommend…” or “verdict”. When a review named two options (24 reviews, for example '
  '“Minor revision (or Accept, at the Editor’s discretion)”), we took the first one, and counted “accept with minor/major '
  'revisions” as minor/major revision. Prompt 1 did not ask for a recommendation, so those reviews count only when they '
  'give one, and are shown apart. No new model calls were needed.')
caption('**Table R1.** Recommendations by prompt and version (number of reviews)')
what('Whether the reviews recommend something different for the planted and the clean version.')
rows = [['Prompt', 'Version'] + OPT[:4] + ['None stated', 'n']]
for pk, lab in (('p2_reader_v1', 'Reader instructions'), ('p3_criteria_v1', 'Reader + criteria')):
    for v in ('flawed', 'clean'):
        d = RC['by_prompt'][pk][v]
        rows.append([lab, VER[v]] + [d[o] for o in OPT] + [d['n']])
for v in ('flawed', 'clean'):
    d = RC['prompts_2_3'][v]
    rows.append(['Prompts 2 and 3', VER[v]] + [d[o] for o in OPT] + [d['n']])
for v in ('flawed', 'clean'):
    d = RC['by_prompt']['p1_bare_v1'][v]
    rows.append(['Bare (not asked)', VER[v]] + [d[o] for o in OPT] + [d['n']])
table(rows, [3.6, 1.6, 1.4, 2.0, 2.0, 1.4, 1.8, 1.0], size=8.5, center_from=2)
caption('**Table R2.** Recommendations by model, prompts 2 and 3 (number of reviews; 20 per model and version)')
what('Which models change their recommendation between the two versions.')
rows = [['Model', 'Version'] + OPT[:4]]
for m, lab in LAB.items():
    for v in ('flawed', 'clean'):
        d = RC['by_model_prompts_2_3'][m][v]
        rows.append([lab if v == 'flawed' else '', VER[v]] + [d[o] for o in OPT[:4]])
table(rows, [4.2, 1.8, 1.6, 2.2, 2.2, 1.6], size=8.5, center_from=2)
note('Every prompt 2 and 3 review gives a recommendation. Reader recommendations are not included.')

doc.save(OUT)
print(OUT)
