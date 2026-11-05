#!/usr/bin/env python3
"""Extract instruction-property lists that XED has no field for (gaps S4 / S10):

  Intel SDM Vol.3A 11.3  "Serializing Instructions"   (privileged / non-privileged / memory-ordering)
  AMD APM Vol.2 7.6.4    "Serializing Instructions"   (+ dispatch-serializing LFENCE)
  Intel SDM Vol.3C 28.1.2 "Instructions That Cause VM Exits Unconditionally"
  Intel SDM Vol.3C 28.1.3 "Instructions That Cause VM Exits Conditionally" (+ controlling VM-execution control)

usage: extract_ordering_vmexit.py <sdm.pdf> <apm.pdf> <repo_root> <out.csv>
"""
import sys, os, re, csv, subprocess, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse as xedparse  # noqa: E402


def pages(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True,
                          errors='replace').stdout.split('\f')


def find_body(P, head_rx, stop_rx, skip_toc=True):
    for i, p in enumerate(P):
        m = re.search(head_rx, p, re.M)
        if not m: continue
        if skip_toc and re.search(r'\. \. \.', p[m.start():m.start() + 300]): continue
        txt = ''.join(P[i:i + 6])[m.start():]
        s = re.search(stop_rx, txt[len(m.group(0)):], re.M)
        return i + 1, txt[:len(m.group(0)) + (s.start() if s else 20000)]
    raise SystemExit('not found: ' + head_rx)


def names(s):
    s = re.sub(r'\(([^)]*)\)', lambda m: '(' + m.group(1).replace(',', ';') + ')', s)
    out = []
    for t in re.split(r',\s*|\s+and\s+', s):
        t = re.sub(r'^and\s+', '', t.strip())
        t = re.sub(r'^\d+\s+', '', t)                              # footnote marker before the item
        t = re.sub(r'(?<=[A-Za-z])\d$', '', t.rstrip('.'))          # footnote marker after the item
        t = t.replace('MOV CR8)', 'MOV CR8)').replace('CR81)', 'CR8)')
        if t: out.append(t)
    return out


def main(sdm, apm, root, outp):
    S, A = pages(sdm), pages(apm)
    rows = []
    pg, t = find_body(S, r'^11\.3\s+SERIALIZING INSTRUCTIONS', r'^11\.4\s')
    t1 = ' '.join(t.split())
    m = re.search(r'Privileged serializing instructions — (.*?)\.\s+•', t1)
    for n in names(m.group(1)): rows.append(('Intel', 'serializing-privileged', n, '', 'SDM 11.3', pg))
    m = re.search(r'Non-privileged serializing instructions — (.*?)\.\s+When', t1)
    for n in names(m.group(1)): rows.append(('Intel', 'serializing-nonprivileged', n, '', 'SDM 11.3', pg))
    m = re.search(r'Non-privileged memory-ordering instructions — (.*?)\.\s', t1)
    for n in names(m.group(1)): rows.append(('Intel', 'memory-ordering', n, '', 'SDM 11.3', pg))

    pg, t = find_body(A, r'^7\.6\.4 Serializing Instructions', r'^7\.6\.5 ')
    sect = None
    for l in t.split('\n'):
        s = l.strip()
        if s.startswith('•   Non-Privileged'): sect = 'serializing-nonprivileged'; continue
        if s.startswith('•   Privileged'): sect = 'serializing-privileged'; continue
        if sect and s.startswith('-'):
            item = s.lstrip('- ').strip()
            cond = 'see note 1: writes to SPEC_CTRL, PRED_CMD, x2APIC MSRs are not serializing' if 'note 1' in item else ''
            item = re.sub(r'\(see note 1\)', '', item).strip()
            for n in names(item): rows.append(('AMD', sect, n, cond, 'APM24593 7.6.4', pg))
        elif sect and s and not s.startswith('-') and not s.startswith('•'):
            sect = None
    if re.search(r'LFenceAlwaysSerializing', ' '.join(t.split())):
        rows.append(('AMD', 'dispatch-serializing', 'LFENCE',
                     'always when CPUID Fn8000_0021_EAX[LFenceAlwaysSerializing](bit 2)=1; otherwise configurable',
                     'APM24593 7.6.4', pg))

    pg, t = find_body(S, r'^28\.1\.2\s+Instructions That Cause VM Exits Unconditionally', r'^28\.1\.3')
    t1 = ' '.join(t.split())
    m = re.search(r'operation: (.*?)\. This is also true of instructions introduced with VMX: (.*?)\.', t1)
    for n in names(m.group(1)) + names(m.group(2)):
        rows.append(('Intel', 'vmexit-unconditional', n, 'in VMX non-root operation', 'SDM 28.1.2', pg))

    pg, t = find_body(S, r'^28\.1\.3\s+Instructions That Cause VM Exits Conditionally', r'^28\.2\s')
    for b in re.finditer(r'^•\s+([A-Z][A-Za-z0-9/ ,]+?(?: from CR\d| to CR\d| DR)?)\.\s+(.*?)(?=^•|\Z)', t, re.M | re.S):
        body = ' '.join(b.group(2).split())
        ctl = '; '.join(sorted(set(re.findall(r'“([^”]+)” VM-execution control', body))))
        head = b.group(1).strip()
        mm = re.match(r'^MOV (from|to) (CR\d)$|^MOV (DR)$', head)
        for n in ([head] if mm else names(head.replace('/', ', '))):
            rows.append(('Intel', 'vmexit-conditional', n, ctl or body[:160], 'SDM 28.1.3', pg))

    # ---- join with XED
    X = collections.defaultdict(set)
    attrs = collections.defaultdict(set)
    for r in xedparse.records():
        X[r['ICLASS']].add(r['_file'])
        attrs[r['ICLASS']] |= set(r.get('ATTRIBUTES', '').split())

    def xed_for(n):
        k = n.upper().replace(' ', '')
        if k.startswith('MOV(TOCONTROLREGISTER') or k.startswith('MOVTOCR') or k.startswith('MOVFROMCR') or k == 'MOVCRN':
            return ['MOV_CR']
        if k.startswith('MOV(TODEBUGREGISTER') or k in ('MOVDR', 'MOVDRN'): return ['MOV_DR']
        k = re.sub(r'\(.*$', '', k)
        if k in X: return [k]
        return sorted(ic for ic in X if re.sub(r'^(REP|REPE|REPNE)_', '', ic) == k or ic.startswith(k + '_'))

    with open(outp, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['vendor', 'property', 'instruction', 'condition', 'source', 'pdf_page', 'xed_iclasses',
                    'xed_has_property_attribute'])
        for v, prop, n, cond, src, pg in rows:
            ics = xed_for(n)
            has = ''
            if prop.startswith('serializ') or prop == 'dispatch-serializing':
                has = 'no (no SERIALIZING attribute exists)'
            elif prop == 'memory-ordering':
                has = 'no (no FENCE/ORDERING attribute exists)'
            elif prop.startswith('vmexit'):
                has = 'no (no VM-exit attribute exists)'
            w.writerow([v, prop, n, cond, src, pg, ' '.join(ics) or '(no ICLASS)', has])
    print(outp, len(rows), 'rows', collections.Counter((r[0], r[1]) for r in rows), file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:5])
