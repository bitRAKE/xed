import os,re,sys,collections,json
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','..','datafiles')
def records():
    for dp,dn,fn in os.walk(ROOT):
        for f in fn:
            if not f.endswith('.txt'): continue
            p=os.path.join(dp,f)
            txt=open(p,errors='replace').read()
            if 'ICLASS' not in txt: continue
            cur=None
            for ln,line in enumerate(txt.split('\n'),1):
                s=line.split('#')[0].rstrip() if not line.lstrip().startswith('#') else ''
                st=s.strip()
                if st=='{': cur={'_file':os.path.relpath(p,ROOT),'_line':ln,'_ops':[], '_pats':[]}; continue
                if st=='}':
                    if cur: yield cur
                    cur=None; continue
                if cur is None: continue
                m=re.match(r'\s*([A-Z_0-9]+)\s*:\s*(.*)',s)
                if m:
                    k,v=m.group(1),m.group(2).strip()
                    if k=='OPERANDS': cur['_ops'].append(v)
                    elif k=='PATTERN': cur['_pats'].append(v)
                    elif k=='IFORM': cur.setdefault('_iforms',[]).append(v)
                    else: cur[k]=v
if __name__=='__main__':
    R=list(records())
    print(len(R))
    c=collections.Counter(k for r in R for k in r)
    print(c)
