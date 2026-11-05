#!/usr/bin/env python3
"""Three-way exception-vector table: Intel SDM Table 7-1, AMD APM Vol.2 Table 8-1,
XED datafiles/xed-exceptions.txt.

usage: extract_exception_vectors.py <sdm.pdf> <apm.pdf> <xed-exceptions.txt> <out.csv>
"""
import sys, re, csv, subprocess


def pages(path):
    return subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True,
                          text=True, errors='replace').stdout.split('\f')


def vec_range(tok):
    tok = tok.replace('–', '-')
    if '-' in tok:
        a, b = tok.split('-'); return list(range(int(a), int(b) + 1))
    return [int(tok)]


def table_text(P, title_rx, stop_rx):
    for i, p in enumerate(P):
        m = re.search(title_rx, p)
        if m and not re.search(r'\.\s\.\s\.', p[m.start():m.start() + 200]):
            txt = p[m.start():]
            if i + 1 < len(P) and re.search(title_rx, P[i + 1]):  # continued on next page
                txt += P[i + 1][re.search(title_rx, P[i + 1]).start():]
            return i + 1, txt[:re.search(stop_rx, txt).start()] if re.search(stop_rx, txt) else txt
    raise SystemExit('table not found: ' + title_rx)


def parse_intel(txt):
    out = {}
    for l in txt.split('\n'):
        m = re.match(r'^\s*(\d+(?:\s*-\s*\d+)?)\s+(#\w+|—)?\s*(.*?)\s{2,}(Fault/ Trap|Fault|Trap|Abort|Interrupt)?\s*(Yes|No)?', l)
        if not m or int(re.match(r'\d+', m.group(1)).group()) > 255: continue
        for v in vec_range(m.group(1).replace(' ', '')):
            if v > 31: continue
            out[v] = {'mnemonic': (m.group(2) or '').replace('—', ''),
                      'name': m.group(3).strip(), 'type': (m.group(4) or '').replace(' ', ''),
                      'error_code': m.group(5) or ''}
    return out


def parse_amd(txt):
    out = {}
    for l in txt.split('\n'):
        m = re.match(r'^\s*(\d+(?:[–-]\d+)?)\s+(.*?)\s{2,}(#\w+|—)?\s*(.*)$', l)
        if not m: continue
        rng = vec_range(m.group(1))
        if len(rng) > 32: continue  # 0-255 external / software rows
        for v in rng:
            out[v] = {'mnemonic': (m.group(3) or '').replace('—', ''), 'name': m.group(2).strip(),
                      'cause': m.group(4).strip()}
    return out


def parse_xed(path):
    out = {}
    for l in open(path):
        m = re.match(r'^\s*(\d+)\s+(#?\w+)\s+"([^"]*)"\s+(\S+)', l)
        if m and int(m.group(1)) < 32:
            out[int(m.group(1))] = {'mnemonic': m.group(2), 'name': m.group(3), 'type': m.group(4)}
    return out


def main(sdm, apm, xedf, outp):
    ip, it = table_text(pages(sdm), r'Table 7-1\. Protected-Mode Exceptions and Interrupts', r'NOTES:')
    ap, at = table_text(pages(apm), r'Table 8-1\. Interrupt Vector Source and Cause', r'Table 8-2 on page')
    I, A, X = parse_intel(it), parse_amd(at), parse_xed(xedf)
    with open(outp, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['vector', 'sdm_mnemonic', 'sdm_name', 'sdm_type', 'sdm_error_code',
                    'apm_mnemonic', 'apm_name', 'xed_mnemonic', 'xed_name', 'xed_type', 'finding',
                    'sdm_pdf_page', 'apm_pdf_page'])
        for v in range(32):
            i, a, x = I.get(v, {}), A.get(v, {}), X.get(v, {})
            vendor = {m for m in (i.get('mnemonic'), a.get('mnemonic')) if m}
            xm = x.get('mnemonic', '')
            finding = ''
            if vendor and x.get('type') == 'reserved':
                finding = 'XED marks reserved; vendor defines ' + '/'.join(sorted(vendor))
            elif vendor and xm not in vendor:
                finding = 'mnemonic differs'
            w.writerow([v, i.get('mnemonic', ''), i.get('name', ''), i.get('type', ''), i.get('error_code', ''),
                        a.get('mnemonic', ''), a.get('name', ''), xm, x.get('name', ''), x.get('type', ''),
                        finding, ip, ap])


if __name__ == '__main__':
    main(*sys.argv[1:5])
