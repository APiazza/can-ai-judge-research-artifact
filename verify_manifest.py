"""Verify release file fingerprints with Python's standard library."""
from pathlib import Path
import hashlib,json,sys

root=Path(__file__).resolve().parent
manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
failed=[]
for item in manifest['files']:
 path=(root/item['path']).resolve()
 if not path.is_relative_to(root):
  failed.append(item['path']+': unsafe path');continue
 if not path.is_file():
  failed.append(item['path']+': missing');continue
 raw=path.read_bytes()
 if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
  failed.append(item['path']+': changed')
print(json.dumps({'status':'FAIL' if failed else 'PASS','files_checked':len(manifest['files']),'failures':failed},indent=2))
sys.exit(1 if failed else 0)
