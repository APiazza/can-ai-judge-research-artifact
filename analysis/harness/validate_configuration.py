"""New offline consistency check of exported records; not the historical runner."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
config = json.loads((BASE / 'recorded_configuration.json').read_text(encoding='utf-8'))
manifest = json.loads((BASE / 'input_hash_manifest.json').read_text(encoding='utf-8'))
checks = 0

def check(condition, label):
    global checks
    if not condition:
        raise AssertionError(label)
    checks += 1

for name, info in config['review_prompts'].items():
    data = (BASE / 'prompts' / 'review' / (name + '.txt')).read_bytes()
    check(hashlib.sha256(data).hexdigest() == info['sha256'], name + ' request string')
    check(hashlib.sha256(data + b'\n').hexdigest() == info['recorded_template_sha256'], name + ' template newline')

expected = {'main_v1-20261018T210504Z': 483, 'effort_v1-20261018T221245Z': 40,
            'format_v1-20261018T215347Z': 20, 'coding_v1-20261024T191027Z': 1087,
            'judge_v1-20261026T053102Z': 960}
for batch in config['batches']:
    check(batch['recorded_calls'] == expected[batch['batch_id']], batch['batch_id'] + ' call count')
    if 'isolation' in batch:
        check(batch['isolation']['passed'] is True, 'recorded isolation passed')
        check(batch['isolation']['key_path_available_to_review_runner'] is False, 'recorded key path unavailable')
    if 'recovered_judge_system_prompt_sha256' in batch:
        data = (BASE / 'prompts/judge/kw_pairwise_reviews_only_v1.txt').read_bytes()
        check(hashlib.sha256(data).hexdigest() == batch['recovered_judge_system_prompt_sha256'], 'judge request instructions')

inputs = [x for x in manifest if x.get('matches_review_batch')]
check(len(inputs) == 20, 'twenty verified model input files')
check(all(x['matches_review_batch'] for x in inputs), 'input hashes matched retained run record')
main = next(x for x in config['batches'] if x['batch_id'].startswith('main_v1'))
key_hashes = {x['sha256'] for x in manifest if '-key.' in x['file']}
check(key_hashes == set(main['isolation']['key_sha256_checked']), 'restricted key hashes match recorded isolation check')
print('PASS: ' + str(checks) + ' offline recorded-configuration checks; no API calls made.')
