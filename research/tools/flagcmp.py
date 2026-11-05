import parse,re,collections,sys
ICED=sys.argv[1] if len(sys.argv)>1 else 'InstructionDefs.txt'  # iced: src/csharp/Intel/Generator/Tables/InstructionDefs.txt
FL={'of':'o','sf':'s','zf':'z','af':'a','pf':'p','cf':'c','df':'d','if':'i','ac':'A','fc0':'0','fc1':'1','fc2':'2','fc3':'3'}
def xnorm(ic):
    ic=re.sub(r'^(REP|REPE|REPNE)_','',ic); ic=re.sub(r'_LOCK$','',ic)
    return ic.lower()
X=collections.defaultdict(lambda: collections.defaultdict(set))
xsrc={}
for r in parse.records():
    f=r.get('FLAGS')
    if not f: continue
    if 'APX' in r.get('EXCEPTIONS','') : continue  # skip APX variants
    m=xnorm(r['ICLASS'])
    for tok in re.findall(r'([a-zA-Z0-9]+)-([a-zA-Z0-9]+)',f):
        fl,act=tok[0].lower(),tok[1].lower()
        if fl not in FL: continue
        c=FL[fl]
        k={'tst':'r','mod':'w','u':'u','0':'0','1':'1','pop':'w','ah':'w'}[act]
        X[m][k].add(c)
    xsrc.setdefault(m,(r['_file'],r['_line']))
I=collections.defaultdict(lambda: collections.defaultdict(set))
cur=None
for line in open(ICED):
    if line.startswith('INSTRUCTION:'):
        p=line.split('|'); 
        cur=p[1].strip().split()[0].lower() if len(p)>1 else None
        if cur and cur.startswith('<'): cur=None
        if cur: I[cur]
    elif cur and line.strip().startswith('rflags:'):
        for t in line.split(':',1)[1].split():
            if '=' in t:
                k,v=t.split('=',1)
                for c in v: I[cur][k].add(c)
# normalization for iced 'w' includes 0/1? keep separate
out=[]
for m in sorted(set(X)|set(I)):
    if m not in I or m not in X: continue
    xs={k:set(v) for k,v in X[m].items()}; is_={k:set(v) for k,v in I[m].items()}
    # compare written-total and read
    xw=xs.get('w',set())|xs.get('u',set())|xs.get('0',set())|xs.get('1',set())
    iw=is_.get('w',set())|is_.get('u',set())|is_.get('0',set())|is_.get('1',set())
    xr=xs.get('r',set()); ir=is_.get('r',set())
    xw-= {'A'}; iw-={'A','u'}  # ignore AC/UIF
    d=[]
    if xr!=ir: d.append('read X=%s I=%s'%(''.join(sorted(xr)),''.join(sorted(ir))))
    if xw!=iw: d.append('write X=%s I=%s'%(''.join(sorted(xw)),''.join(sorted(iw))))
    xu=xs.get('u',set()); iu=is_.get('u',set())
    if xu!=iu: d.append('undef X=%s I=%s'%(''.join(sorted(xu)),''.join(sorted(iu))))
    if d: out.append((m,xsrc[m],d))
for m,s,d in out: print(m, '%s:%d'%s, ' | '.join(d))
print(len(out),'diffs; X mnems',len(X),'common',len(set(X)&set(I)),file=sys.stderr)
print('XED-flagged not in iced:',sorted(set(X)-set(I)),file=sys.stderr)
allx=collections.defaultdict(list)
for r in parse.records():
    if 'APX' in r.get('EXCEPTIONS',''): continue
    allx[xnorm(r['ICLASS'])].append(r)
miss=[]
for m,rs in sorted(allx.items()):
    if m in X: continue
    if m in I and any(I[m].values()):
        miss.append((m, rs[0]['_file'], {k:''.join(sorted(v)) for k,v in I[m].items()}))
print('\n# iced has rflags, XED has no FLAGS:',file=sys.stderr)
for x in miss: print('NOFLAGS',x)
