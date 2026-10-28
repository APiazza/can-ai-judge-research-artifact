"""Readable tables and a dependency-free SVG from calculated pilot results."""

import csv
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import json
import textwrap


def rounded(value, digits=1):
    quantum = Decimal(1).scaleb(-digits)
    return format(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP), f".{digits}f")


def range_text(low, high, digits=1):
    low, high = sorted((Decimal(str(low)), Decimal(str(high))))
    a, b = rounded(low, digits), rounded(high, digits)
    return a if a == b else a + "–" + b


def count_range(stats, denominator=None, scale=100, digits=1):
    n = stats["n"] if denominator is None else denominator
    if not n:
        return "NA"
    return range_text(Decimal(stats["lower"])*scale/Decimal(n),
                      Decimal(stats["higher"])*scale/Decimal(n), digits)


def integer_range(a, b):
    a, b = sorted((a, b))
    return str(a) if a == b else f"{a}–{b}"


def qualification_label(row):
    if row['sonnet_passes'] and row['qwen_passes']:
        return "Both pass"
    if row['sonnet_passes']:
        return "Sonnet only"
    return "Qwen only" if row['qwen_passes'] else "Neither passes"


def concern_label(concern, register, flag=""):
    info = register.get("concerns", {}).get(concern, {})
    return concern + flag + " " + info.get("short_title", info.get("title", concern))


def build_tables(result, human, register, concerns):
    tables = []

    def add(table_id, title, headers, rows, note=""):
        tables.append({"id": table_id, "title": title, "headers": headers,
                       "rows": [[str(value) for value in row] for row in rows], "note": note})

    add("S3", "Agreement with the investigator reference: original classifications",
        ["Concern", "Initial investigator matches", "Sonnet matches", "Qwen matches", "n", "Original qualification"],
        [[concern_label(r['concern'], register), r['human'], r['sonnet'], r['qwen'], r['n'], qualification_label(r)]
         for r in result['calibration_original']],
        "Qualification uses the original codes and the recorded agreement threshold. It is not recomputed from corrected answers.")
    add("S3a", "Agreement after the targeted quotation check",
        ["Concern", "Sonnet corrected matches", "Qwen corrected matches", "n", "Original qualification retained"],
        [[concern_label(r['concern'], register), r['sonnet'], r['qwen'], r['n'],
          qualification_label(result['calibration_original'][i])]
         for i, r in enumerate(result['calibration_corrected'])],
        "Corrected agreement on selectively checked records does not establish that an originally failing scorer passed.")
    human_lookup = {r['concern']: r for r in human}
    add("S4", "Reader assessments after disclosure",
        ["Concern", "Yes", "Qualified endorsement", "No", "Cannot judge", "Total"],
        [[c, human_lookup[c]['yes'], human_lookup[c]['qualified'], human_lookup[c]['no'], human_lookup[c]['cannot_judge'], human_lookup[c]['n']]
         for c in concerns], "Post-disclosure endorsement is not spontaneous detection.")
    failed = set(result['original_qualification']['excluded'])
    single = result['original_qualification']['single_scorers']

    def marker(c):
        return "†" if c in failed else "‡" if c in single else ""

    add("S5", "Matched criticisms (%)",
        ["Concern", "Full planted", "Full baseline", "Full or partial planted", "Full or partial baseline"],
        [["All eight" if c == 'All' else concern_label(c, register, marker(c)),
          *[count_range(result['primary'][m][c][v]) for m, v in
            [('F', 'planted'), ('F', 'baseline'), ('FP', 'planted'), ('FP', 'baseline')]]]
         for c in concerns + ['All']],
        "† Neither scorer passed the original check; ‡ only one passed. Ranges count both versus either scorer, not confidence intervals.")
    sens_names = [
        ('original_all_eight', 'All eight; original classifications'),
        ('all_eight', 'All eight; after quotation check'),
        ('exclude_C5_C7_Qwen_C3', 'Exclude C5/C7; Qwen-only C3'),
        ('exclude_C2_C5_C7_Qwen_C3', 'Also exclude C2; post hoc')]
    add("S6", "Sensitivity to concern inclusion and scorer choice (%)",
        ["Analysis", "Count per version", "Full planted", "Full baseline", "Full or partial planted", "Full or partial baseline"],
        [[label, result['sensitivities'][key]['F']['planted']['n'],
          *[count_range(result['sensitivities'][key][m][v]) for m, v in
            [('F', 'planted'), ('F', 'baseline'), ('FP', 'planted'), ('FP', 'baseline')]]]
         for key, label in sens_names],
        "The concern/coder restriction follows original qualification. C2 exclusion follows the observed human finding and is explicitly post hoc.")
    models = register.get('model_order', list(result['per_model']))
    model_labels = register.get('model_labels', {})
    add("S7", "Matches per review and repeated-run coverage",
        ["Model", "Full planted /8", "Full baseline /8", "Full or partial planted /8", "Ever fully detected /8"],
        [[model_labels.get(model, model),
          count_range(result['per_model'][model]['planted']['F'], result['per_model'][model]['planted']['reviews'], 1),
          count_range(result['per_model'][model]['baseline']['F'], result['per_model'][model]['baseline']['reviews'], 1),
          count_range(result['per_model'][model]['planted']['FP'], result['per_model'][model]['planted']['reviews'], 1),
          integer_range(result['per_model_ever'][model]['F']['lower'], result['per_model_ever'][model]['F']['higher'])]
         for model in models], "Ever detected combines all planted-version main runs; it is not a practical panel estimate.")
    prompts = register.get('prompt_order', list(result['prompts']))
    add("S8", "Prompt comparisons (%)",
        ["Prompt", "Full planted", "Full baseline", "Full or partial planted", "Full or partial baseline"],
        [[prompt, *[count_range(result['prompts'][prompt][m][v]) for m, v in
                    [('F', 'planted'), ('F', 'baseline'), ('FP', 'planted'), ('FP', 'baseline')]]] for prompt in prompts])
    diagnostic_rows = []
    for kind, levels, prefix in [('effort', ['low', 'default', 'max'], 'Astra'),
                                 ('format', ['PDF', 'Text + figures'], 'Argon')]:
        for level in levels:
            group = result['diagnostics'][kind][level]
            diagnostic_rows.append([f'{prefix}, {level}', *[
                count_range(group[v][m], group[v]['reviews'], 1) for m, v in
                [('F', 'planted'), ('F', 'baseline'), ('FP', 'planted'), ('FP', 'baseline')]]])
    add("S9", "Diagnostic matches per review (out of eight)",
        ["Condition", "Full planted", "Full baseline", "Full or partial planted", "Full or partial baseline"],
        diagnostic_rows, "Default effort and PDF rows reuse corresponding main reviews.")

    def judge_cell(judge, metric, subset, v, bound=None):
        bounds = [bound] if bound else ['lower', 'higher']
        group = 'agreement' if v == 'planted' else 'raised_on_baseline'
        values = [result['judge'][judge]['variants'][f'{b}|{metric}|{subset}'][group]['all 8 concerns'] for b in bounds]
        require_nonempty = all(x['n'] > 0 for x in values)
        if not require_nonempty:
            return 'NA'
        percentages = [Decimal(x['k'])*100/Decimal(x['n']) for x in values]
        return range_text(min(percentages), max(percentages)) + ' (' + integer_range(
            min(x['n'] for x in values), max(x['n'] for x in values)) + ')'

    judge_rows = []
    judges = sorted(result['judge'], key=lambda k: (not k.startswith('gpt-'), k))
    for judge in judges:
        label = 'GPT-5.5' if judge.startswith('gpt-') else 'Qwen3.8'
        for subset, suffix in [('all pairs', 'all'), ('no OpenAI pairs', 'without OpenAI')]:
            judge_rows.append([f'{label}, {suffix}',
                               judge_cell(judge, 'F', subset, 'planted'),
                               judge_cell(judge, 'FP', subset, 'planted'),
                               judge_cell(judge, 'F', subset, 'baseline')])
        if 'qwen' in judge:
            judge_rows.append([f'{label}, Sonnet codes',
                               judge_cell(judge, 'F', 'all pairs', 'planted', 'sonnet'),
                               judge_cell(judge, 'FP', 'all pairs', 'planted', 'sonnet'),
                               judge_cell(judge, 'F', 'all pairs', 'baseline', 'sonnet')])
    add("S10", "Preference for the review with more matched criticisms, % (eligible pairs)",
        ["Judge and analysis", "Full, planted", "Full or partial, planted", "Full, baseline"], judge_rows,
        "Eligible pairs have the same winner in both orders and unequal detection counts. Baseline criticism validity has not been adjudicated.")
    recommendation_rows = []
    requested = [p for p in prompts if p != 'Bare']
    for prompt in requested + ['Both requested prompts'] + (['Bare'] if 'Bare' in prompts else []):
        for v in ('planted', 'baseline'):
            row = result['recommendations'][prompt][v]
            recommendation_rows.append([prompt, v, *[row[c] for c in
                                       ('Reject', 'Major revision', 'Minor revision', 'Accept', 'None', 'n')]])
    add("S11", "Publication recommendations (review counts)",
        ["Prompt", "Version", "Reject", "Major", "Minor", "Accept", "None", "n"], recommendation_rows)
    add("Corrections", "Dated quotation-check overlay",
        ['Review', 'Concern', 'Scorer', 'Original code', 'Corrected code', 'Purpose', 'Version'],
        [[r[k] for k in ('blind_id', 'concern', 'coder', 'old_code', 'recommended_code', 'purpose', 'version')]
         for r in result['applied_corrections']], "Original inputs are never overwritten.")
    return tables


def write_tables(tables, output_dir):
    sections = ['# Reproduced numerical tables', '']
    with (output_dir / 'tables.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['table_id', 'table_title', 'row_number', 'column', 'value'])
        for table in tables:
            sections += [f"## Table {table['id']}. {table['title']}", '',
                         '| ' + ' | '.join(table['headers']) + ' |',
                         '| ' + ' | '.join('---' for _ in table['headers']) + ' |']
            for number, row in enumerate(table['rows'], 1):
                sections.append('| ' + ' | '.join(str(x).replace('|', '\\|') for x in row) + ' |')
                for header, value in zip(table['headers'], row):
                    writer.writerow([table['id'], table['title'], number, header, value])
            if table['note']:
                sections += ['', table['note']]
            sections.append('')
    (output_dir / 'tables.md').write_text('\n'.join(sections), encoding='utf-8')


def write_figure(result, register, concerns, output_dir):
    rows = []
    for c in concerns:
        for v in ('planted', 'baseline'):
            stats = result['primary']['F'][c][v]
            rows.append({'concern': c, 'version': v, 'n': stats['n'],
                         'lower_count': stats['lower'], 'higher_count': stats['higher'],
                         'lower_pct': 100*stats['lower']/stats['n'],
                         'higher_pct': 100*stats['higher']/stats['n']})
    with (output_dir / 'figure_data.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    width, height, left, top, chart_width, row_height = 1120, 700, 505, 76, 570, 64
    blue, orange = '#205f86', '#b34d17'
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<title>Criticisms of baseline and planted-problem versions</title>',
           '<desc>Each segment spans reviews counted by both scorers through those counted by either scorer. These are not confidence intervals.</desc>',
           '<rect width="100%" height="100%" fill="white"/>',
           '<g font-family="Arial, sans-serif" fill="#171717">']
    failed = set(result['original_qualification']['excluded'])
    single = result['original_qualification']['single_scorers']
    for i, c in enumerate(concerns):
        y = top + i*row_height
        if c in failed:
            svg.append(f'<rect x="10" y="{y-23}" width="1095" height="{row_height}" fill="#f0f0f0"/>')
    bottom = top+(len(concerns)-1)*row_height+40
    for tick in range(0, 101, 20):
        x = left + chart_width*tick/100
        svg += [f'<line x1="{x}" y1="{top-25}" x2="{x}" y2="{bottom}" stroke="#dddddd"/>',
                f'<text x="{x}" y="{bottom+28}" text-anchor="middle" font-size="16">{tick}</text>']
    for i, c in enumerate(concerns):
        y = top+i*row_height
        flag = '†' if c in failed else '‡' if c in single else ''
        title = register.get('concerns', {}).get(c, {}).get('title', c)
        wrapped = textwrap.wrap(title, width=43)
        svg.append(f'<text x="15" y="{y+4}" font-size="20">{escape(c+flag)}</text>')
        first_y = y-5 if len(wrapped)>1 else y+4
        for j, line in enumerate(wrapped):
            svg.append(f'<text x="83" y="{first_y+22*j}" font-size="18">{escape(line)}</text>')
        for v, dy, color in [('planted', -3, blue), ('baseline', 19, orange)]:
            stats = result['primary']['F'][c][v]
            x1 = left+chart_width*stats['lower']/stats['n']
            x2 = left+chart_width*stats['higher']/stats['n']
            yy = y+dy
            svg.append(f'<line x1="{x1}" y1="{yy}" x2="{x2}" y2="{yy}" stroke="{color}" stroke-width="4"/>')
            for x in (x1, x2):
                if v == 'planted':
                    svg.append(f'<circle cx="{x}" cy="{yy}" r="5" fill="{color}"/>')
                else:
                    svg.append(f'<rect x="{x-5}" y="{yy-5}" width="10" height="10" fill="{color}"/>')
    for x, label, color, circle in [(650, 'Planted problems', blue, True), (900, 'Baseline', orange, False)]:
        svg.append(f'<line x1="{x-32}" y1="25" x2="{x-6}" y2="25" stroke="{color}" stroke-width="4"/>')
        svg.append(f'<circle cx="{x-19}" cy="25" r="5" fill="{color}"/>' if circle else
                   f'<rect x="{x-24}" y="20" width="10" height="10" fill="{color}"/>')
        svg.append(f'<text x="{x}" y="31" font-size="19">{label}</text>')
    svg += [f'<text x="{left+chart_width/2}" y="{bottom+63}" text-anchor="middle" font-size="17">Reviews raising the concern with the specified reasoning (%)</text>',
            '<text x="15" y="654" font-size="14">† Neither scorer passed the original check; ‡ only one passed. Both scorers contribute to every range.</text>',
            '<text x="15" y="678" font-size="14">Ranges show coder disagreement. Criticisms of the baseline version may be defensible.</text>',
            '</g></svg>']
    (output_dir / 'figure_1.svg').write_text('\n'.join(svg), encoding='utf-8')


def write_report(result, hashes, expected_checks, output_dir):
    scalar = result['scalar_claims']
    full = result['primary']['F']['All']
    original = result['original_primary']['F']['All']
    paragraphs = [
        '# Offline reproduction report', '',
        f"Calculated from {scalar['scoring_rows']:,} concern-level rows, covering {sum(scalar['reviews_by_purpose'].values())} AI reviews. No network or model calls were made.", '',
        '## Main full-match contrast', '',
        '| Version | Original counts | Corrected counts | Denominator | Corrected % |',
        '|---|---|---|---|---|']
    for v in ('planted', 'baseline'):
        paragraphs.append('| ' + ' | '.join([v, integer_range(original[v]['lower'], original[v]['higher']),
                          integer_range(full[v]['lower'], full[v]['higher']), str(full[v]['n']), count_range(full[v])]) + ' |')
    paragraphs += ['', f"Applied {scalar['corrections']} dated classification corrections across {scalar['corrected_review_concern_cases']} review–concern cases. Original data remain unchanged.", '',
                   '## Interpretation', '',
                   'Lower/upper full-match endpoints count both/either scorer for each observation. They are not confidence intervals. Original qualification controls all sensitivity restrictions; corrected calibration does not retroactively pass a scorer. The additional exclusion following observed human rejection is post hoc.', '',
                   'The delivered judge restriction excludes originally unqualified concerns but retains both-scorer bounds for C3. It therefore differs from the six-concern detection sensitivity, which uses the originally passing scorer alone for C3.', '',
                   '## Output files', '',
                   '- results.json: unrounded calculated counts, denominators, comparisons and metadata.',
                   '- scalar_claims.json: calculated scalar claims; supplied provenance metadata is separately labeled in results.json.',
                   '- tables.md and tables.csv: numerical Tables S3–S11, corrected calibration and correction register.',
                   '- figure_data.csv and figure_1.svg: all 16 corrected full-match segments.',
                   '- input_hashes.json: SHA-256 of each package input.',
                   '- expected_checks.json: optional independent expected-value assertions.', '',
                   '## Expected-value checks', '']
    paragraphs.append(f"{sum(c['pass'] for c in expected_checks)}/{len(expected_checks)} supplied assertions passed." if expected_checks else
                      'No expected assertions were supplied. Calculations and schema/invariant checks still ran.')
    paragraphs += ['', '## Input SHA-256', '', '| Package input | SHA-256 |', '|---|---|']
    paragraphs += [f'| {name} | {digest} |' for name, digest in hashes.items()]
    (output_dir / 'report.md').write_text('\n'.join(paragraphs)+'\n', encoding='utf-8')


def dump_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
