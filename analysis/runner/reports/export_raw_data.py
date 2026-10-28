"""Raw data behind the pilot result tables, as three CSV files (one row per review x concern, per judged pair, per review)."""
import argparse
import csv
import json
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--runs', required=True, type=Path, help='run records folder (data_dir in config/paths.local.yaml)')
ap.add_argument('--out', default=Path('.'), type=Path, help='folder for the data/ folder')
ARGS = ap.parse_args()
RUNS = ARGS.runs
CODING = RUNS / 'coding/coding_v1-20261024T191027Z'
READ = CODING / 'reads/rules_2026_10_24-20261025T054512Z'
JUDGE = RUNS / 'judge/judge_v1-20261026T053102Z'
RECS = RUNS / 'recommendations/20261026T195856Z'
OUT = ARGS.out / 'data'
OUT.mkdir(parents=True, exist_ok=True)
RANK = {'–': 0, 'P': 1, 'F': 2}
CONCERNS = [f'C{i}' for i in range(1, 9)]
PROMPTS = {'p1_bare_v1': 'Bare', 'p2_reader_v1': 'Reader instructions', 'p3_criteria_v1': 'Reader + criteria'}
VERSIONS = {'flawed': 'planted', 'clean': 'clean'}
jl = lambda p: [json.loads(l) for l in open(p, encoding='utf-8')]

blinding = json.load(open(RUNS / 'coding/blinding/coding_v1/blinding.json', encoding='utf-8'))['reviews']
info = {r['blind_id']: r for r in blinding}

# 1. LLM codes per review and concern, with the human codes for the core 24
sel = {s['run_id'] for s in jl(READ / 'selected.jsonl') if s['run_id']}
codes, counts = {}, {}
for row in jl(READ / 'codes.jsonl'):
    if row['run_id'] in sel:
        k = (row['blind_id'], row['coder_key'])
        codes[k] = {c: row['codes']['concerns'][c]['code'] for c in CONCERNS}
        counts[k] = row['codes']['criticism_count']
hum = json.load(open(CODING / 'human_check/human_codes.json', encoding='utf-8'))
H = {n: {(r['blind_id'], r['concern']): r['code'] for r in hum[n]} for n in ('coder1', 'coder2', 'agreed')}
S, Q = 'claude-sonnet-5-5', 'qwen3p8-2p4t-a95b'
with open(OUT / 'llm_codes_by_review_and_concern.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['blind_id', 'purpose', 'model', 'provider', 'version', 'prompt', 'run', 'concern', 'code_sonnet', 'code_qwen',
                'code_lower', 'code_higher', 'criticisms_sonnet', 'criticisms_qwen', 'human_coder1_CH', 'human_coder2_AP',
                'human_agreed'])
    for b in sorted(info):
        r = info[b]
        for c in CONCERNS:
            a, q = codes[(b, S)][c], codes[(b, Q)][c]
            w.writerow([b, r['review_purpose'], r['model_key'], r['provider'], VERSIONS[r['version']], PROMPTS[r['template_id']],
                        r['rep'], c, a, q, min(a, q, key=RANK.get), max(a, q, key=RANK.get), counts[(b, S)], counts[(b, Q)],
                        H['coder1'].get((b, c), ''), H['coder2'].get((b, c), ''), H['agreed'].get((b, c), '')])

# 2. Judge verdicts per pair and judge
pairs = {p['pair_id']: p for p in json.load(open(RUNS / 'judge/pairs/judge_v1/pairs.json', encoding='utf-8'))['pairs']}
best = {}
for r in jl(JUDGE / 'calls.jsonl'):
    if r['status'] == 'ok' and (r['slot'] not in best or r['attempt'] > best[r['slot']]['attempt']):
        best[r['slot']] = r
v = {}
for r in best.values():
    v.setdefault((r['judge_key'], r['pair_id']), {})[r['order']] = r['winner_blind_id']
with open(OUT / 'judge_verdicts_by_pair.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['pair_id', 'version', 'prompt', 'review_1', 'model_1', 'review_2', 'model_2', 'judge',
                'winner_review_1_shown_first', 'winner_review_2_shown_first', 'decided_winner'])
    for (j, pid), o in sorted(v.items(), key=lambda x: (x[0][1], x[0][0])):
        p = pairs[pid]
        w.writerow([pid, VERSIONS[p['version']], PROMPTS[p['template_id']], p['review_1'], info[p['review_1']]['model_key'],
                    p['review_2'], info[p['review_2']]['model_key'], j, o.get('12', ''), o.get('21', ''),
                    o['12'] if o.get('12') and o.get('12') == o.get('21') else 'undecided'])

# 3. Recommendations per main review
hand = json.load(open(RECS / 'hand.json', encoding='utf-8'))['decisions']
with open(OUT / 'recommendations_by_review.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['blind_id', 'model', 'version', 'prompt', 'recommendation', 'how_read'])
    for r in jl(RECS / 'extraction.jsonl'):
        rec = hand[r['blind_id']] if r['read'] == 'hand' else (r['option'] or 'none stated')
        how = {'auto': 'automatic', 'hand': 'rule for mixed statements, checked by Investigator 1', 'none': 'none stated'}[r['read']]
        w.writerow([r['blind_id'], r['model_key'], VERSIONS[r['version']], PROMPTS[r['template_id']], rec, how])

for p in sorted(OUT.glob('*.csv')):
    print(p.name, sum(1 for _ in open(p, encoding='utf-8-sig')) - 1, 'rows')
