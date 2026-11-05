#!/usr/bin/env python3
"""Compare XED datafiles against vendor-manual extractions.

Inputs (all produced by the other tools in this directory):
  research/data/sdm_instructions.json   (extract_sdm_vol2.py + sdm_footnotes.py)
  research/data/amd_rflags_tableF1.csv       (extract_flag_tables.py)
  research/data/sdm_eflags_tableA2.csv       (extract_flag_tables.py)

Outputs (research/data/):
  flags_manual_vs_xed.csv     per (XED ICLASS, flag): XED / SDM-prose / SDM-A2 / AMD-F1, verdict
  coverage_sdm_vs_xed.csv     SDM mnemonics with no XED ICLASS and vice versa
  mode64_sdm_vs_xed.csv       64-bit-mode validity disagreements
usage: compare_manuals.py [repo_root]
"""
import sys, os, re, csv, json, collections

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'research', 'tools'))
import parse as xedparse          # noqa: E402
import flags_parse                # noqa: E402

DATA = os.path.join(ROOT, 'research', 'data')
FLAGS = ['OF', 'SF', 'ZF', 'AF', 'PF', 'CF', 'DF', 'IF', 'TF', 'AC', 'NT', 'RF', 'VM', 'VIF', 'VIP', 'ID', 'IOPL']

# ---------------------------------------------------------------- XED side
SPECIAL = {'MOVSD_XMM': 'MOVSD', 'CMPSD_XMM': 'CMPSD', 'SYSCALL_AMD': 'SYSCALL', 'SYSRET_AMD': 'SYSRET',
           'SYSRET64': 'SYSRET', 'CALL_NEAR': 'CALL', 'CALL_FAR': 'CALL', 'JMP_FAR': 'JMP', 'RET_NEAR': 'RET',
           'RET_FAR': 'RET', 'INT1': 'INT1', 'XSTORE': 'XSTORE', 'UDB': 'UD', 'FSTPNCE': 'FSTP',
           'FDISI8087_NOP': 'FNOP', 'FENI8087_NOP': 'FNOP', 'FSETPM287_NOP': 'FNOP', 'BEXTR_XOP': 'BEXTR'}


def xed_mnemonic(ic):
    if ic in SPECIAL: return SPECIAL[ic]
    m = re.sub(r'^(REP|REPE|REPNE)_', '', ic)
    m = re.sub(r'_LOCK$', '', m)
    m = re.sub(r'^NOP\d$', 'NOP', m)
    return m


def xed_db():
    X = collections.defaultdict(lambda: {'recs': [], 'flags': collections.defaultdict(set), 'files': set()})
    for r in xedparse.records():
        if 'APX' in r.get('EXCEPTIONS', ''):  # APX re-encodings; compared separately if needed
            continue
        x = X[r['ICLASS']]
        x['recs'].append(r); x['files'].add('%s:%d' % (r['_file'], r['_line']))
        f = r.get('FLAGS')
        if not f: continue
        for fl, act in re.findall(r'([a-zA-Z0-9]+)-([a-zA-Z0-9]+)', f):
            fl, act = fl.upper(), act.lower()
            if fl.startswith('FC'): continue
            x['flags'][fl].add(act)
    return X


def xed_write_class(acts):
    """Collapse XED actions on one flag to a comparable class (reads are tracked separately)."""
    w = {a for a in acts if a != 'tst'}
    if not w: return '-'
    if w == {'mod', 'u'}: return 'mod/u'
    if len(w) == 1: return next(iter(w))
    return '/'.join(sorted(w))


# ---------------------------------------------------------------- SDM side
OPASSIGN = re.compile(r'((?:[OSZAPC]F\s*(?::=|,)\s*)+)([01]+|[A-Za-z_\[\]\.0-9]+)')


def flags_from_operation(op):
    """Recover flag effects from pseudo code like 'ZF,PF,CF := 111;' 'AF := OF := 0;'."""
    vals = collections.defaultdict(set)
    for m in OPASSIGN.finditer(op or ''):
        names = re.findall(r'[OSZAPC]F', m.group(1)); v = m.group(2)
        if re.fullmatch(r'[01]+', v):
            if len(v) == len(names):
                for n, b in zip(names, v): vals[n].add(b)
            else:
                for n in names: vals[n].add(v[0])
        else:
            for n in names: vals[n].add('expr')
    return {k: (next(iter(v)) if len(v) == 1 and v <= {'0', '1'} else 'mod') for k, v in vals.items()}


def sdm_db():
    d = json.load(open(os.path.join(DATA, 'sdm_instructions.json')))
    M = collections.defaultdict(list)   # mnemonic -> list of (entry, parsed)
    for e in d['entries']:
        if e.get('leaf'):      # leaf pages are compared in leaf_flags.csv, not against the opcode record
            continue
        p = flags_parse.parse(e['flags_affected'])
        src = 'Flags Affected'
        if e['flags_affected'] is None:
            op = flags_from_operation(e.get('operation'))
            if op:
                p = {'actions': op, 'unparsed': [], 'conditional': [], 'complete': True, 'none': False,
                     'note': 'from Operation pseudo-code'}
                src = 'Operation'
        e['_parsed'] = p; e['_src'] = src
        names = set(m.upper() for m in e['mnemonics'])
        for r in e['opcodes']:
            t = (r.get('instruction') or '').split()
            if t: names.add(t[0].rstrip(',').upper())
        e['_names'] = names
        for n in names: M[n].append(e)
    return d['entries'], M


def sdm_flag(e, fl):
    p = e['_parsed']
    if p['none']: return '-'
    if p.get('note') == 'all-flags': return 'mod'
    a = p['actions'].get(fl)
    return a if a else ''          # '' = not mentioned


# ---------------------------------------------------------------- AMD / A-2 tables
AMDX = {'CMPSx': ['CMPSB', 'CMPSW', 'CMPSD', 'CMPSQ'], 'LODSx': ['LODSB', 'LODSW', 'LODSD', 'LODSQ'],
        'MOVSx': ['MOVSB', 'MOVSW', 'MOVSD', 'MOVSQ'], 'SCASx': ['SCASB', 'SCASW', 'SCASD', 'SCASQ'],
        'STOSx': ['STOSB', 'STOSW', 'STOSD', 'STOSQ'], 'INSx': ['INSB', 'INSW', 'INSD'],
        'OUTSx': ['OUTSB', 'OUTSW', 'OUTSD'], 'IRETx': ['IRET', 'IRETD', 'IRETQ'],
        'POPFx': ['POPF', 'POPFD', 'POPFQ'], 'INT 3': ['INT3'], 'CMPS': ['CMPSB', 'CMPSW', 'CMPSD', 'CMPSQ'],
        'SCAS': ['SCASB', 'SCASW', 'SCASD', 'SCASQ'], 'POPF': ['POPF', 'POPFD', 'POPFQ'],
        'IRET': ['IRET', 'IRETD', 'IRETQ'], 'INS': ['INSB', 'INSW', 'INSD'], 'OUTS': ['OUTSB', 'OUTSW', 'OUTSD'],
        'LODS': ['LODSB', 'LODSW', 'LODSD', 'LODSQ'], 'MOVS': ['MOVSB', 'MOVSW', 'MOVSD', 'MOVSQ'],
        'STOS': ['STOSB', 'STOSW', 'STOSD', 'STOSQ'], 'VERRW': ['VERW']}


def table_db(fname):
    T = collections.defaultdict(dict)
    for r in csv.DictReader(open(os.path.join(DATA, fname))):
        mn = r['mnemonic']
        base = re.sub(r'\s+(1|count)$', '', mn)
        qual = mn[len(base):].strip()
        for m in AMDX.get(base, [base]):
            T[m][qual or '*'] = r
    return T


def table_flag(rows, fl):
    """Merge '1'/'count' rows into one class like XED IMM1/IMMx does."""
    if not rows: return None
    vals = set()
    for q, r in rows.items():
        v = r.get(fl, '')
        vals.add(re.sub(r'(^|\+)tst(\+|$)', r'\1\2', v).strip('+') or '-')
    if vals == {'mod', 'u'}: return 'mod/u'
    if len(vals) == 1: return vals.pop()
    return '/'.join(sorted(vals))


def table_reads(rows, fl):
    return any('tst' in (r.get(fl, '') or '') for r in rows.values()) if rows else None


# ---------------------------------------------------------------- comparison
def same(x, m):
    """XED class x vs manual class m."""
    if m is None: return None
    if m == '': return x == '-' or None     # manual silent: unknown
    if m == 'ah': m = 'ah'
    if m == 'pop' and x in ('pop', 'mod'): return True
    if x == 'pop' and m == 'mod': return True        # XED more specific (value from stack)
    if x == m: return True
    if m == 'mod/u' and x in ('mod', 'u', 'mod/u'): return True
    if x == 'mod/u' and m in ('mod', 'u'): return 'partial'
    if m == 'mod' and x in ('0', '1'): return 'partial'   # XED more specific
    return False


def verdict(x, s, a, t):
    rs, ra, rt = same(x, s), same(x, a), same(x, t)
    srcs = {'SDM': rs, 'AMD': ra, 'A-2': rt}
    bad = [k for k, v in srcs.items() if v is False]
    good = [k for k, v in srcs.items() if v is True]
    if not bad: return ''
    if 'SDM' in bad and ('AMD' in bad or a is None):
        return 'XED-differs-from-vendors'
    if 'SDM' in bad and 'AMD' in good:
        return 'XED-matches-AMD-not-SDM'
    if 'AMD' in bad and 'SDM' in good:
        return 'XED-matches-SDM-not-AMD'
    if bad == ['A-2']:
        return 'SDM-TableA2-stale'     # Vol.1 App. A summary disagrees with the Vol.2 page
    return 'mixed:' + ','.join(bad)


def main():
    X = xed_db()
    entries, S = sdm_db()
    A = table_db('amd_rflags_tableF1.csv')
    T = table_db('sdm_eflags_tableA2.csv')
    out = []
    for ic in sorted(X):
        x = X[ic]
        m = xed_mnemonic(ic)
        ents = S.get(m, [])
        if ic == 'MOV_CR': ents = [e for e in S.get('MOV', []) if 'Control' in e['title']]
        elif ic == 'MOV_DR': ents = [e for e in S.get('MOV', []) if 'Debug' in e['title']]
        elif m == 'MOV': ents = [e for e in ents if e['title'] == 'Move']
        elif m in ('MOVSD', 'CMPSD'):
            want = 'Scalar' if ic.endswith('_XMM') else 'String'
            ents = [e for e in ents if (want in e['title']) or (want == 'String' and 'Move Data' in e['title'])
                    or (want == 'String' and 'Compare String' in e['title'])]
        e = ents[0] if ents else None
        nostr = ic.endswith('_XMM')       # SSE scalar MOVSD/CMPSD: not the string instructions
        amd = None if nostr else A.get(m) or ({'*': A['SYSRET']['*']} if m == 'SYSRET' and 'SYSRET' in A else None)
        a2 = None if nostr else T.get(m)
        if e is None and amd is None and a2 is None: continue
        sdm_complete = bool(e and e['_parsed']['complete'] and (e['_parsed']['actions'] or e['_parsed']['none']
                                                                 or e['_parsed'].get('note') == 'all-flags'))
        for fl in FLAGS:
            xc = xed_write_class(x['flags'].get(fl, set()))
            sc = sdm_flag(e, fl) if e else None
            if sc == '' and sdm_complete and e['_parsed']['actions']:
                sc = ''   # mentioned others but not this one
            ac = table_flag(amd, fl)
            tc = table_flag(a2, fl)
            if xc == '-' and not sc and ac in (None, '-') and tc in (None, '-'): continue
            v = verdict(xc, sc if sc != '' else None, ac, tc)
            xr = 'tst' in x['flags'].get(fl, set())
            ar = table_reads(amd, fl)
            read_note = ''
            if ar is not None and ar != xr: read_note = 'read: XED=%s AMD=%s' % (xr, ar)
            if not v and not read_note: continue
            out.append({'iclass': ic, 'flag': fl, 'xed': xc, 'xed_reads': xr, 'sdm_prose': sc, 'sdm_A2': tc,
                        'amd_F1': ac, 'verdict': v or 'read-only-diff', 'read_note': read_note,
                        'sdm_entry': e['name'] if e else '', 'sdm_src': e['_src'] if e else '',
                        'sdm_page': (e.get('flags_affected_page') or e['start']) if e else '',
                        'amd_page': next(iter(amd.values()))['pdf_page'] if amd else '',
                        'xed_where': sorted(x['files'])[0],
                        'sdm_text': (e['flags_affected'] or e['_parsed'].get('note') or '')[:400] if e else ''})
    with open(os.path.join(DATA, 'flags_manual_vs_xed.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    print('flags_manual_vs_xed.csv rows', len(out), collections.Counter(r['verdict'] for r in out), file=sys.stderr)

    # ---------------- coverage
    xm = collections.defaultdict(set)
    for ic, x in X.items():
        xm[xed_mnemonic(ic)].add(ic)
        for r in x['recs']:
            if r.get('DISASM'): xm[r['DISASM'].upper()].add(ic)
    cov = []
    for n, es in sorted(S.items()):
        if n in xm or not re.match(r'^[A-Z][A-Z0-9]+$', n): continue
        cov.append({'direction': 'SDM-not-in-XED', 'mnemonic': n, 'sdm_entry': es[0]['name'],
                    'sdm_page': es[0]['start'], 'xed': ''})
    for m, ics in sorted(xm.items()):
        if m in S: continue
        recs = [r for ic in ics for r in X[ic]['recs']]
        attrs = set(a for r in recs for a in r.get('ATTRIBUTES', '').split())
        if 'AMDONLY' in attrs or 'UNDOCUMENTED' in attrs: continue
        exts = sorted(set(r['EXTENSION'] for r in recs))
        if any(e in ('VIA_PADLOCK', 'XOP', 'FMA4', 'TBM', 'SSE4a', 'SVM', 'AMD', 'PREFETCHW', '3DNOW', 'CLZERO',
                     'MCOMMIT', 'RDPRU', 'MONITORX', 'SNP', 'AMD_INVLPGB', 'ACE', 'KNC') for e in exts): continue
        cov.append({'direction': 'XED-not-in-SDM', 'mnemonic': m, 'sdm_entry': '', 'sdm_page': '',
                    'xed': ' '.join(sorted(ics)) + ' [' + ','.join(exts) + ']'})
    with open(os.path.join(DATA, 'coverage_sdm_vs_xed.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(cov[0])); w.writeheader(); w.writerows(cov)
    print('coverage rows', len(cov), collections.Counter(r['direction'] for r in cov), file=sys.stderr)

    # ---------------- 64-bit validity (mnemonic level, legacy-encoded rows only)
    md = []
    for n, es in sorted(S.items()):
        rows = [r for e in es for r in e['opcodes']
                if (r.get('instruction') or '').split()[:1] and r['instruction'].split()[0].rstrip(',').upper() == n
                and not r.get('opcode', '').startswith(('VEX', 'EVEX', 'XOP'))]
        if not rows or n not in xm: continue

        def v64(r):
            s = (r.get('mode64') or r.get('mode_64_32', '').split('/')[0]).strip().upper().rstrip('*')
            return {'VALID': True, 'V': True, 'INVALID': False, 'I': False, 'N.E.': False, 'NE': False,
                    'N.S.': None, 'N.P.': True}.get(s)
        vals = set(v64(r) for r in rows) - {None}
        if not vals: continue
        recs = [r for ic in xm[n] for r in X[ic]['recs']]
        pats = [p for r in recs for p in r['_pats'] if not re.search(r'\bVV1\b|EVV|VEX', p)]
        if not pats: continue
        xed_64 = any(not re.search(r'\bnot64\b|\bmode16\b|\bmode32\b|\beamode16\b', p) for p in pats)
        sdm_64 = True in vals
        if xed_64 != sdm_64:
            md.append({'mnemonic': n, 'sdm_valid_in_64': sdm_64, 'xed_has_64bit_pattern': xed_64,
                       'sdm_entry': es[0]['name'], 'sdm_page': rows[0]['pdf_page'],
                       'sdm_rows': '; '.join('%s [%s]' % (r['instruction'], r.get('mode64') or r.get('mode_64_32'))
                                             for r in rows[:4]),
                       'xed_iclasses': ' '.join(sorted(xm[n]))})
    with open(os.path.join(DATA, 'mode64_sdm_vs_xed.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(md[0]) if md else ['mnemonic']); w.writeheader(); w.writerows(md)
    print('mode64 rows', len(md), file=sys.stderr)
    cpuid_compare(X, S)
    leaf_table(X)


def leaf_table(X):
    """Per-leaf documented flags for leaf-selected instructions (GETSEC/ENCLS/ENCLU/ENCLV):
    XED has a single record per opcode, so per-leaf effects cannot be represented (gap S2)."""
    d = json.load(open(os.path.join(DATA, 'sdm_instructions.json')))
    out = []
    for e in d['entries']:
        if not e.get('leaf'): continue
        p = flags_parse.parse(e['flags_affected'])
        x = X.get(e['leaf_of'])
        sel = ''
        for r in e['opcodes']:
            m = re.search(r'EAX\s*=\s*([0-9A-Fa-f]+H?)', r.get('opcode', '') + ' ' + r.get('instruction', ''))
            if m: sel = m.group(1); break
        out.append({'instruction': e['leaf_of'], 'leaf': e['leaf'], 'eax': sel, 'sdm_page': e['start'],
                    'sdm_flags': 'none' if p['none'] else ' '.join('%s=%s' % kv for kv in sorted(p['actions'].items())),
                    'xed_flags': ' '.join('%s=%s' % (k, '/'.join(sorted(v))) for k, v in sorted(x['flags'].items())) if x else '(no ICLASS)',
                    'xed_records': len(x['recs']) if x else 0,
                    'sdm_text': (e['flags_affected'] or '')[:300]})
    with open(os.path.join(DATA, 'leaf_flags_sdm_vs_xed.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    print('leaf rows', len(out), file=sys.stderr)


ALIAS = {'adx': 'adoxadcx', 'avx101': 'avx10ver1', 'avx102': 'avx10ver2', 'movbe': 'movebe', 'sse41': 'sse4',
         'clfsh': 'clflush', 'fsgsbase': 'rdwrfsgs', 'ospke': 'ospku', 'avx512bf16': 'bf16', 'kl': 'klsupported',
         'aeskle': 'klenabled', 'widekl': 'klwide', 'prefetchi': 'icacheprefetch', 'intelpt': 'intelpt',
         'tsxldtrk': 'tsxldtrk', 'rdpid': 'rdp', 'hle': 'rtm', 'prfchw': 'prefetchw', '3dnowprefetch': 'prefetchw',
         'avx512vbmi1': 'avx512vbmi', 'lm': 'intel64', 'avx512vp2intersect': 'avx512vp2intersect',
         'avxvnniint8': 'avxvnniint8', 'pclmulqdq': 'pclmulqdq', 'rdtscp': 'rdtscp', 'sse42': 'sse42'}


def cpuid_db():
    import xed_cpuid
    feat = collections.defaultdict(set)
    for isa, groups in xed_cpuid.read(ROOT).items():
        for g, recs in groups.items():
            for r in recs:
                feat[isa].add(re.sub(r'[^a-z0-9]', '', r['name'].lower()))
    return feat


def norm_feat(t):
    t = re.sub(r'[^a-z0-9]', '', t.lower())
    return ALIAS.get(t, t)


def cpuid_compare(X, S):
    F = cpuid_db()
    out = []
    for n, es in sorted(S.items()):
        ics = [ic for ic in X if xed_mnemonic(ic) == n]
        if not ics: continue
        xf = set()
        for ic in ics:
            for r in X[ic]['recs']:
                xf |= F.get(r.get('ISA_SET', r['EXTENSION']), set())
        xf -= {'na', ''}
        rows = [r for e in es for r in e['opcodes'] if r.get('cpuid')
                and (r.get('instruction') or '').split()[:1] and r['instruction'].split()[0].rstrip(',').upper() == n]
        sf = set()
        for r in rows:
            for t in re.split(r'\s+AND\s+|\s+OR\s+|[(),/ ]+', r['cpuid']):
                t = norm_feat(t)
                if t and t not in ('and', 'or', 'na', 'ns', 'ne'): sf.add(t)
        if not sf: continue
        if not xf:
            out.append({'mnemonic': n, 'sdm_cpuid': ' '.join(sorted(sf)), 'xed_cpuid': '(none: ISA_SET has n/a)',
                        'missing_in_xed': ' '.join(sorted(sf)), 'extra_in_xed': '', 'sdm_page': rows[0]['pdf_page'],
                        'xed_iclasses': ' '.join(sorted(ics))})
            continue
        miss = sorted(t for t in sf if t not in xf and not any(t in x or x in t for x in xf))
        extra = sorted(t for t in xf if t not in sf and not any(t in s_ or s_ in t for s_ in sf)
                       and t not in ('osxsave', 'avx10enabled', 'ospku', 'klenabled'))
        if miss or extra:
            out.append({'mnemonic': n, 'sdm_cpuid': ' '.join(sorted(sf)), 'xed_cpuid': ' '.join(sorted(xf)),
                        'missing_in_xed': ' '.join(miss), 'extra_in_xed': ' '.join(extra),
                        'sdm_page': rows[0]['pdf_page'], 'xed_iclasses': ' '.join(sorted(ics))})
    with open(os.path.join(DATA, 'cpuid_sdm_vs_xed.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)
    print('cpuid rows', len(out), file=sys.stderr)


if __name__ == '__main__':
    main()
