fetch('variants.json').then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}).then(items=>{
  const list=document.querySelector('#varianten');
  items.sort((a,b)=>b.sequence-a.sequence);
  const el=(tag,text,className)=>{const node=document.createElement(tag);if(text)node.textContent=text;if(className)node.className=className;return node;};
  for(const [i,v] of items.entries()){
    const row=el('li',null,'review-item');const img=el('img');img.src=v.image;img.alt='Vorschau '+v.title;
    const body=el('div');const meta=el('div',null,'review-meta');meta.append(el('span','VARIANTE '+v.version,'card-number'));
    const date=el('time',new Intl.DateTimeFormat('de-AT',{day:'2-digit',month:'long',year:'numeric'}).format(new Date(v.date+'T12:00:00')));date.dateTime=v.date;meta.append(date);
    if(i===0)meta.append(el('span','Aktuellster Entwurf','latest'));
    const changes=el('ul');for(const change of v.changes)changes.append(el('li',change));
    const link=el('a','Variante '+v.version+' öffnen →','button');link.href=v.path;
    body.append(meta,el('h2',v.title),el('p',v.description),changes,link);row.append(img,body);list.append(row);
  }
}).catch(()=>{document.querySelector('#status').textContent='Variantenliste konnte nicht geladen werden.';const li=document.createElement('li');const a=document.createElement('a');a.href='variants/01-natur/';a.textContent='Ersten Entwurf direkt öffnen';li.append(a);document.querySelector('#varianten').append(li);});
