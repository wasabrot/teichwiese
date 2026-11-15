"""Verify the deployed Pages index, variants and shared assets."""
import sys,time
from urllib.request import urlopen, Request
from urllib.parse import urljoin
base=sys.argv[1].rstrip('/')+'/'
checks={'':b'TW-ROUNDTRIP-001','variants/01-natur/':b'01-natur','variants/02-architektur/':b'02-architektur','assets/brand/teichwiese.svg':b'TEICHWIESE','assets/fonts/NunitoSans-ExtraBold.ttf':b'\x00\x01\x00\x00','assets/images/ansicht-01.jpg':b'\xff\xd8\xff'}
for attempt in range(12):
    try:
        for path,expected in checks.items():
            with urlopen(Request(urljoin(base,path),headers={'User-Agent':'Teichwiese-Pages-Smoke-Test'}),timeout=20) as res:
                data=res.read()
                assert res.status==200 and expected in data, f'Unexpected content: {path}'
        print(f'PASS: {base} – index marker, both variants, SVG, font and image verified.');break
    except Exception as error:
        if attempt==11:raise
        print(f'Waiting for deployed content ({attempt+1}/12): {error}');time.sleep(10)
