#!/usr/bin/env python3
"""Extract AMD APM CPUID instruction-support tables and compare bit positions with XED.

  APM Vol.3 Table 3-1  "Instruction Support Indicated by CPUID Feature Bits"   (general purpose)
  APM Vol.3 Table 4-1  "System Instruction Support Indicated by CPUID Feature Bits"
  APM Vol.3 Table D-1  "Feature Flags for Instruction / Instruction Subset Support"

XED's cpuid*.xed.txt give 'name.leaf.subleaf.reg.bit', so the comparison is on the exact
(leaf, subleaf, register, bit) tuple, not on feature names.

usage: extract_amd_cpuid.py <apm.pdf> <repo_root> <out_dir>
"""
import sys, os, re, csv, subprocess, collections
import pdfplumber

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse as xedparse  # noqa: E402


def page_texts(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True,
                          errors='replace').stdout.split('\f')


def tables_on(pdf, pages, want_hdr):
    rows = []
    for pg in pages:
        p = pdf.pages[pg]
        try:
            T = p.extract_tables()
        finally:
            p.close()
        for t in T:
            if not t or not t[0]: continue
            hdr = [re.sub(r'\s+', ' ', (c or '')).strip() for c in t[0]]
            if not any(want_hdr in h for h in hdr): continue
            for r in t[1:]:
                rows.append([re.sub(r'\s+', ' ', (c or '').replace('\n', ' ')).strip() for c in r] + [pg + 1])
    return rows


def text_table_41(P, pages):
    """Table 4-1 is not ruled: parse layout text. A value line is '<name?>  <function>  <REG[bit]>';
    name-only lines attach to the adjacent value line that has no name."""
    rows = []
    for pg in pages:
        t = P[pg]
        k = t.find('Table 4-1.')
        body = t[k:].split('\n')[2:]
        lines = []
        for l in body:
            if re.search(r'System Instruction Reference\s+\d+', l): break
            if not l.strip(): continue
            m = re.match(r'^\s*(.*?)\s{2,}(\S+(?:\[[^\]]*\])?)\s{2,}(E[ABCD]X\[\d+\])\s*$', l)
            m2 = re.match(r'^\s{10,}(\S+(?:\[[^\]]*\])?)\s{2,}(E[ABCD]X\[\d+\])\s*$', l)
            if m2: lines.append(['', m2.group(1), m2.group(2)])
            elif m: lines.append([m.group(1).strip(), m.group(2), m.group(3)])
            else: lines.append([l.strip(), None, None])
        for i, (n, f, b) in enumerate(lines):
            if f is None: continue
            name = n
            if not name:
                if i > 0 and lines[i - 1][1] is None: name = lines[i - 1][0]
            if i + 1 < len(lines) and lines[i + 1][1] is None and (not n or name.endswith(',') or name.endswith('and')):
                name = (name + ' ' + lines[i + 1][0]).strip()
            rows.append([name, f, b, '', pg + 1])
    return rows


def leaf_of(fn):
    """'0000_0007h (ECX=0)' / '0000_0007_0' / '8000_0001h' / 'standard' / 'extended' -> [(leaf, subleaf)]"""
    fn = fn.replace(' ', '')
    out = []
    if 'standard' in fn or fn.startswith('both'): out.append((0x1, 0))
    if 'extended' in fn or fn.startswith('both'): out.append((0x80000001, 0))
    for m in re.finditer(r'([0-9A-Fa-f]{4})_([0-9A-Fa-f]{4})(?:_(\d+)(?![0-9A-Fa-f_])|h(?:\(ECX=(\d+)\))?)?', fn):
        sub = m.group(3) or m.group(4) or '0'
        out.append((int(m.group(1) + m.group(2), 16), int(sub)))
    return out


def bits_of(rb):
    return [(m.group(1).lower(), int(m.group(2))) for m in re.finditer(r'(E[ABCD]X)\[(\d+)\]', rb)]


def xed_cpuid():
    import xed_cpuid as xc
    spec = collections.defaultdict(set)
    for isa, groups in xc.read(ROOT).items():
        for g, recs in groups.items():
            for r in recs:
                spec[isa].add((r['leaf'], r['sub'], r['reg'], r['bit'], r['name']))
    return spec


def main(apm, root, outdir):
    global ROOT
    ROOT = root
    P = page_texts(apm)
    def find(rx): return [i for i, t in enumerate(P) if re.search(rx, t) and not re.search(rx + r'.*\. \. \.', t)]
    p31 = find(r'Table 3-1\.\s+Instruction Support Indicated by CPUID Feature Bits')
    p41 = find(r'Table 4-1\.\s+System Instruction Support Indicated by CPUID Feature Bits')
    pd1 = find(r'Table D-1\.\s+Feature Flags for Instruction')
    with pdfplumber.open(apm) as pdf:
        r31 = tables_on(pdf, p31, 'Instruction')
        r41 = text_table_41(P, p41)
        rd1 = tables_on(pdf, pd1, 'Feature Flag')
    os.makedirs(outdir, exist_ok=True)
    amd = []
    for src, rows in (('APM-Vol3-Table3-1', r31), ('APM-Vol3-Table4-1', r41)):
        for r in rows:
            if len(r) < 5 or not r[0] or r[0].startswith(('Instruction', 'Notes')): continue
            ff = r[3] or (re.search(r'\[([^\]]+)\]', r[1]).group(1) if re.search(r'\[([^\]]+)\]', r[1]) else '')
            amd.append({'source': src, 'instructions': r[0], 'cpuid_function': r[1], 'register_bit': r[2],
                        'feature_flag': ff, 'pdf_page': r[-1]})
    for r in rd1:
        if len(r) < 5 or not r[0] or r[0].startswith('Feature'): continue
        amd.append({'source': 'APM-Vol3-TableD-1', 'instructions': r[1], 'cpuid_function': r[2],
                    'register_bit': r[3], 'feature_flag': r[0], 'pdf_page': r[-1]})
    with open(os.path.join(outdir, 'amd_cpuid_tables.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(amd[0])); w.writeheader(); w.writerows(amd)
    print('amd_cpuid_tables.csv', len(amd), 'rows', file=sys.stderr)

    # ------------- compare with XED: instruction names -> ISA_SET -> (leaf,sub,reg,bit)
    spec = xed_cpuid()
    by_ic = collections.defaultdict(set)
    for r in xedparse.records():
        by_ic[r['ICLASS']].add(r.get('ISA_SET') or r['EXTENSION'])
    out = []
    for a in amd:
        if a['source'] == 'APM-Vol3-TableD-1': continue      # subset names, not mnemonics
        names = [n.strip().upper() for n in re.split(r',|/| and |\s+(?=[A-Z]{4,}\b)', a['instructions']) if n.strip()]
        names = [re.sub(r'\s*\(.*\)$', '', n) for n in names]
        names = [re.sub(r'(?<=[A-Z])\d$', '', n) if not re.search(r'(8B|16B|32|64|128|256|512)$', n) else n
                 for n in names]          # strip footnote markers MOVD1, PREFETCHW2
        leaves = leaf_of(a['cpuid_function']); bits = bits_of(a['register_bit'])
        want = {(lf, sl, rg, b) for (lf, sl) in leaves for (rg, b) in bits}
        for n in names:
            ics = [ic for ic in by_ic if ic == n or ic.startswith(n + '_') or re.sub(r'^(REP|REPE|REPNE)_', '', ic) == n]
            if not ics:
                if re.fullmatch(r'[A-Z][A-Z0-9]+', n):
                    out.append({'instruction': n, 'amd_feature': a['feature_flag'], 'amd_cpuid': '%s %s' % (a['cpuid_function'], a['register_bit']),
                                'xed_cpuid': '', 'verdict': 'no XED ICLASS', 'xed_isa_sets': '', 'amd_page': a['pdf_page']})
                continue
            isas = set().union(*(by_ic[ic] for ic in ics))
            have = {(s[0], s[1], s[2], s[3]) for i in isas for s in spec.get(i, ())}
            names_x = sorted({'%s(%x.%x.%s.%d)' % (s[4], s[0], s[1], s[2], s[3]) for i in isas for s in spec.get(i, ())})
            if not want:
                continue
            if want & have:
                continue
            verdict = 'XED has no CPUID for ISA_SET' if not have else 'bit mismatch'
            out.append({'instruction': n, 'amd_feature': a['feature_flag'],
                        'amd_cpuid': '%s %s' % (a['cpuid_function'], a['register_bit']),
                        'xed_cpuid': ' '.join(names_x), 'verdict': verdict, 'xed_isa_sets': ' '.join(sorted(isas)),
                        'amd_page': a['pdf_page']})
    with open(os.path.join(outdir, 'cpuid_amd_vs_xed.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, list(out[0]) if out else ['instruction']); w.writeheader(); w.writerows(out)
    print('cpuid_amd_vs_xed.csv', len(out), 'rows', collections.Counter(o['verdict'] for o in out), file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:4])
