from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import json,re
root=Path(__file__).resolve().parents[1]/'docs'
errors=[]
def check(source,value):
    parsed=urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path:return
    if parsed.path.startswith('/'):
        errors.append(f'{source}: root-absolute path breaks project Pages: {value}');return
    target=(source.parent/unquote(parsed.path)).resolve()
    if not target.is_relative_to(root):errors.append(f'{source}: outside published root: {value}')
    elif not target.exists():errors.append(f'{source}: missing {value}')
class Links(HTMLParser):
    def handle_starttag(self,tag,attrs):
        for k,v in attrs:
            if k in ('href','src') and v:check(self.source,v)
for file in root.rglob('*.html'):
    parser=Links();parser.source=file;parser.feed(file.read_text())
for file in root.rglob('*.css'):
    for v in re.findall(r'url\([\'"]?([^\)\'"]+)',file.read_text()):check(file,v)
variants=json.loads((root/'variants.json').read_text());ids=set()
for v in variants:
    if v['id'] in ids:errors.append('Duplicate variant id: '+v['id'])
    ids.add(v['id'])
    for key in ('path','image'):check(root/'index.html',v[key])
    if not (root/v['path']/'index.html').is_file():errors.append('Missing variant index '+v['id'])
if errors:raise SystemExit('\n'.join(errors))
print(f'OK: {len(list(root.rglob("*.html")))} HTML pages, {len(variants)} variants, all local asset and CSS links resolve.')
