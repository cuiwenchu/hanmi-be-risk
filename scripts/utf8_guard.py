#!/usr/bin/env python3
from pathlib import Path
import sys

targets=[
 '/data/pipeline58-local/pipeline58_local/app.py',
 '/data/pipeline58-local/pipeline58_local/users_admin.html',
 '/data/pipeline58-local/pipeline58_local/pksim_page.html',
]
errors=[]
for f in targets:
    p=Path(f)
    if not p.exists():
        errors.append(f'missing file: {f}')
        continue
    try:
        t=p.read_text(encoding='utf-8',errors='strict')
    except Exception as e:
        errors.append(f'utf8 decode failed: {f}: {e}')
        continue
    if '\ufffd' in t:
        errors.append(f'U+FFFD found: {f}')
    if '?/h1>' in t:
        errors.append(f'broken h1 tag: {f}')

app=Path('/data/pipeline58-local/pipeline58_local/app.py')
if app.exists():
    a=app.read_text(encoding='utf-8',errors='strict')
    for tok in ['DASHBOARD_HTML','analyze-form','open-history-btn','logout-btn','action="/auth/web-login"','/api/v1/pipeline58/analyze']:
        if tok not in a:
            errors.append(f'app.py missing token: {tok}')

if errors:
    print('UTF8_GUARD_FAIL')
    for e in errors:
        print(' -',e)
    sys.exit(1)
print('UTF8_GUARD_OK')
