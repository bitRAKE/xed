#!/usr/bin/env python3
"""Extract the vendor RFLAGS cross-reference tables into CSV.

  AMD APM 24594 (in 40332 combined vol 1-5) Table F-1 "Instruction Effects on RFLAGS"
  Intel SDM 325462 Vol.1 Table A-2 "EFLAGS Cross-Reference"

Output codes are normalised to XED flag-action vocabulary:
  tst mod 0 1 u pop ah  (multiple actions joined with '+', e.g. 'tst+mod')
  SDM 'R' (restores prior value) -> pop ; SDM '—' (undefined) -> u ; SDM 'TM' -> tst+mod
usage: extract_flag_tables.py <apm.pdf> <sdm.pdf> <outdir>
"""
import sys,csv,re,os,pdfplumber

import subprocess
_TXT={}
def page_texts(path):
    """Per-page text via poppler pdftotext (low memory); index 0 = PDF page 1."""
    if path not in _TXT:
        _TXT[path]=subprocess.run(['pdftotext','-layout',path,'-'],capture_output=True,
                                   text=True,errors='replace').stdout.split('\f')
    return _TXT[path]
def find_pages(path,pattern):
    rx=re.compile(pattern)
    return [i for i,t in enumerate(page_texts(path)) if rx.search(t)]

AMDMAP={'tst':'tst','mod':'mod','0':'0','1':'1','u':'u','pop':'pop','ah':'ah'}
def norm_amd(cell):
    if not cell: return ''
    toks=[t.strip().lower() for t in re.split(r'[\n ]+',cell) if t.strip()]
    return '+'.join(AMDMAP.get(t,'?'+t) for t in toks)
def norm_sdm(cell):
    if not cell: return ''
    c=cell.replace(' ','').replace('\n','')
    out=[]
    for ch in c:
        out.append({'T':'tst','M':'mod','0':'0','1':'1','—':'u','-':'u','R':'pop'}.get(ch,'?'+ch))
    return '+'.join(out)

def split_label(label):
    """'RCL/RCR 1' -> ['RCL 1','RCR 1'];  'SHL\\nSAL count' -> ['SHL count','SAL count'];
    'MOV control, debug, test' kept as one row (it is one SDM row)."""
    lab=label.replace('\n','/').strip()
    if lab.startswith('MOV control'): return ['MOV control/debug/test']
    parts=[x.strip() for x in re.split(r'/|, *',lab) if x.strip()]
    m=re.match(r'^(.*\S)\s+(1|count)$',parts[-1]) if parts else None
    if m and len(parts)>1:
        q=m.group(2); parts=[x if re.search(r'\s(1|count)$',x) else x+' '+q for x in parts]
    return parts

def extract(pdf,pages,norm,src):
    rows=[];hdr=None
    for pi in pages:
        page=pdf.pages[pi]
        tables=page.extract_tables(); page.close()
        for t in tables:
            for r in t:
                if r and r[0] and r[0].replace('\n',' ').strip().startswith('Instruction') and any(r[1:]):
                    hdr=[ (c or '').split('\n')[0].strip() for c in r[1:]]; continue
                if r and r[0] is None and r[1] and 'ID' in (r[1] or ''):
                    hdr=[ (c or '').split('\n')[0].strip() for c in r[1:]]; continue
                if not hdr or not r or not r[0]: continue
                if 'RFLAGS Mnemonic' in ''.join(c or '' for c in r): continue
                mn=r[0]
                vals=r[1:1+len(hdr)]
                for m in split_label(mn):
                    d={'mnemonic':m,'row_label':mn.replace('\n','/'),'source':src,'pdf_page':pi+1}
                    for h,v in zip(hdr,vals): d[h]=norm(v)
                    rows.append(d)
    return rows

def main(apm,sdm,out):
    os.makedirs(out,exist_ok=True)
    pages=[p for p in find_pages(apm,r'Table F-1\.\s+Instruction Effects on RFLAGS') if p>1500]
    with pdfplumber.open(apm) as pdf:
        amd=extract(pdf,pages,norm_amd,'APM24594-TableF-1')
    pages=[p for p in find_pages(sdm,r'Table A-2\. EFLAGS Cross-Reference') if p<1000]
    with pdfplumber.open(sdm) as pdf:
        intel=extract(pdf,pages,norm_sdm,'SDM325462-Vol1-TableA-2')
    for name,rows in (('amd_rflags_tableF1.csv',amd),('sdm_eflags_tableA2.csv',intel)):
        cols=['mnemonic','row_label','source','pdf_page']+sorted({k for r in rows for k in r}-{'mnemonic','row_label','source','pdf_page'})
        with open(os.path.join(out,name),'w',newline='') as f:
            w=csv.DictWriter(f,cols); w.writeheader(); w.writerows(rows)
        print(name,len(rows),'rows; pages',sorted({r['pdf_page'] for r in rows}))
if __name__=='__main__': main(*sys.argv[1:4])
