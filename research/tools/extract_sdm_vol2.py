#!/usr/bin/env python3
"""Extract per-instruction data from the Intel SDM (325462) instruction-reference pages
(Vol. 2, plus the VMX / SMX / SGX / TDX instruction chapters of Vol. 2D and Vol. 3).

For every "MNEMONIC—Title" entry it records:
  - pdf page range
  - opcode-table rows (opcode, instruction, op/en, 64-bit / compat mode, CPUID flag)
  - raw text of "Flags Affected" (+ a parsed per-flag action, see flags_parse.py)
  - the names of exception sections present

usage: extract_sdm_vol2.py <sdm.pdf> <out.json> [first_page last_page]
Text segmentation uses poppler pdftotext; tables use pdfplumber (opened page by page
to stay within memory).
"""
import sys, re, json, subprocess
import pdfplumber

TITLE = re.compile(r'^([A-Z][A-Za-z0-9/ ,\[\]]*?[A-Za-z0-9\]])\s*—\s*(\S.*)?$')
FOOTER = re.compile(r'(Vol\. 2[A-D]\s+\d+-\d+|\d+-\d+\s+Vol\. 2[A-D]|INSTRUCTION SET REFERENCE|^\s*Vol\. 2)')
SECTIONS = ['Description', 'Operation', 'Flags Affected', 'Intel C/C++ Compiler Intrinsic Equivalent',
            'Intel C/C++ Compiler Intrinsic Equivalents', 'Floating-Point Exceptions', 'FPU Flags Affected',
            'SIMD Floating-Point Exceptions', 'Numeric Exceptions', 'Protected Mode Exceptions',
            'Real-Address Mode Exceptions', 'Virtual-8086 Mode Exceptions', 'Compatibility Mode Exceptions',
            '64-Bit Mode Exceptions', 'Exceptions (All Operating Modes)', 'Other Exceptions',
            'IA-32 Architecture Compatibility', 'Instruction Operand Encoding', 'VM-exit Condition',
            'Exceptions', 'Flags Affected:', 'Operation in a Uni-Processor Platform', 'Use of Prefixes',
            'Concurrency Restrictions', 'Leaf Function Concurrency Restrictions', 'Instruction Operand Encoding',
            'EADD Memory Parameter Semantics', 'Temp Variables in EINIT Operational Flow',
            'Intel C/C++ Compiler Intrinsic Equivalent', 'Concurrency Table', 'SGX Exceptions']
SEC_RX = re.compile(r'^(%s)\s*$' % '|'.join(re.escape(s) for s in sorted(SECTIONS, key=len, reverse=True)))


def page_texts(path):
    out = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True,
                         errors='replace').stdout
    return out.split('\f')


def expand(name):
    """'VF[,N]MADD[132,213,231]PH' -> all combinations; 'A/B' -> [A,B]."""
    res = []
    for part in name.split('/'):
        part = part.strip()
        m = re.search(r'\[([^\]]*)\]', part)
        if m and re.fullmatch(r'[A-Z][A-Z0-9_]{2,}', m.group(1)):   # GETSEC[SENTER]: a leaf, not alternatives
            res.append(part); continue
        if not m:
            if part: res.append(part)
            continue
        for alt in m.group(1).split(','):
            res.extend(expand(part[:m.start()] + alt + part[m.end():]))
    return res


RUNHDR = re.compile(r'^[A-Z0-9 ,.&()®™\-]+$')   # running page header, e.g. "SAFER MODE EXTENSIONS REFERENCE"
MAXPAGES = 30                                     # bound an entry that would run across a chapter boundary


def segment(P, first, last):
    entries = []
    for i in range(first - 1, last):
        L = [l for l in P[i].split('\n') if l.strip()]
        if len(L) < 2: continue
        k = 0
        while k < 2 and k < len(L) - 1 and RUNHDR.match(L[k].strip()) and '—' not in L[k]:
            k += 1
        head = L[k].strip()
        if 'Vol.' in head: continue
        m = TITLE.match(head)
        if not m: continue
        title = (m.group(2) or '').strip()
        if not title or not any('Opcode' in l for l in L[k + 1:k + 3]):
            # title wrapped onto the next line
            if any('Opcode' in l for l in L[k + 2:k + 4]):
                title = (title + ' ' + L[k + 1].strip()).strip()
            else:
                continue
        name = m.group(1).strip()
        if name.lower().startswith(('chapter', 'table', 'figure')): continue
        ent = {'name': name, 'title': title, 'start': i + 1}
        lm = re.match(r'^([A-Z][A-Z0-9]+)\[([A-Z][A-Z0-9_]+)\]$', name)
        if lm: ent['leaf_of'], ent['leaf'] = lm.group(1), lm.group(2)
        entries.append(ent)
    for a, b in zip(entries, entries[1:] + [None]):
        a['end'] = min((b['start'] - 1) if b else last, a['start'] + MAXPAGES)
    return entries


def body_lines(P, e):
    out = []
    for pg in range(e['start'], e['end'] + 1):
        for l in P[pg - 1].split('\n'):
            if FOOTER.search(l): continue
            out.append((pg, l.rstrip()))
    return out


def sections(lines):
    secs = {}; cur = None; order = []
    for pg, l in lines:
        s = l.strip()
        m = SEC_RX.match(s)
        if m and not l.startswith('    '):
            cur = m.group(1).rstrip(':'); order.append(cur)
            secs.setdefault(cur, {'page': pg, 'text': []})
            continue
        if cur: secs[cur]['text'].append(s)
    for k in secs:
        secs[k]['text'] = re.sub(r'\s+', ' ', ' '.join(secs[k]['text'])).strip()
    return secs, order


HEXB = re.compile(r'^[0-9A-F]{2}(\+r[bwdo]|\+i|\+cc)?$')
OPC_TOKENS = re.compile(r'^(REX(\.W|2)?|REX\.R|NP|NFx|VEX\.|EVEX\.|XOP\.|/[0-7r]|i[bwdo]|c[bwdpot]|m64|\+|o16|o32|o64|a16|a32|66|F2|F3|NDS|NDD|DDS|PREFIX|\d+H)')
MNEM = re.compile(r'^[A-Z][A-Z0-9]*(cc|CC|x)?[A-Z0-9]*$')


def split_opcode_instruction(cell):
    """Return (opcode, instruction) from a combined 'Opcode/Instruction' cell."""
    lines = [l.strip() for l in (cell or '').split('\n') if l.strip()]
    for k, l in enumerate(lines):
        tok = l.split()[0].rstrip(',')
        if MNEM.match(tok) and not HEXB.match(tok) and not OPC_TOKENS.match(tok) and k > 0:
            return ' '.join(lines[:k]), ' '.join(lines[k:])
    # fallback: token scan on a single line
    toks = ' '.join(lines).split()
    for k, t in enumerate(toks):
        if k and MNEM.match(t) and not HEXB.match(t) and not OPC_TOKENS.match(t) and len(t) > 1:
            return ' '.join(toks[:k]), ' '.join(toks[k:])
    return ' '.join(lines), ''


def norm_hdr(h):
    h = re.sub(r'\s+', ' ', (h or '').replace('\n', ' ')).strip().lower()
    if h.startswith('opcode') and 'instruction' in h: return 'opcode_instruction'
    if h.startswith('opcode'): return 'opcode'
    if h.startswith('instruction'): return 'instruction'
    if re.match(r'^op ?/ ?e ?n', h) or h == 'op en': return 'op_en'
    if h.startswith('64/32') or '64/32' in h: return 'mode_64_32'
    if h.startswith('64-bit') or h.startswith('64-bit mode'): return 'mode64'
    if h.startswith('compat'): return 'compat_leg'
    if h.startswith('cpuid'): return 'cpuid'
    if h.startswith('description'): return 'description'
    return h


def opcode_rows(pdf, e):
    rows = []
    for pg in range(e['start'], min(e['end'], e['start'] + 7) + 1):
        page = pdf.pages[pg - 1]
        try:
            tables = page.extract_tables()
        finally:
            page.close()
        found = False
        for t in tables:
            if not t or not t[0]: continue
            hdr = [norm_hdr(c) for c in t[0]]
            if not ('opcode' in hdr or 'opcode_instruction' in hdr): continue
            found = True
            for r in t[1:]:
                d = {h: re.sub(r'\s+', ' ', (c or '').replace('\n', ' ')).strip() for h, c in zip(hdr, r)}
                if 'opcode_instruction' in hdr:
                    raw = r[hdr.index('opcode_instruction')]
                    d['opcode'], d['instruction'] = split_opcode_instruction(raw)
                    d.pop('opcode_instruction', None)
                if not d.get('opcode') and not d.get('instruction'): continue
                if (d.get('opcode') or '').startswith('NOTES'): continue
                d.pop('', None)
                d.pop('description', None)
                d['pdf_page'] = pg
                rows.append(d)
        if rows and not found:
            break  # table finished on an earlier page
    return rows


def main(pdfpath, out, first=None, last=None):
    P = page_texts(pdfpath)
    first = int(first) if first else 1
    last = int(last) if last else len(P)
    E = segment(P, first, last)
    print('entries', len(E), file=sys.stderr)
    with pdfplumber.open(pdfpath) as pdf:
        for n, e in enumerate(E):
            secs, order = sections(body_lines(P, e))
            e['mnemonics'] = [e['leaf_of']] if 'leaf_of' in e else expand(e['name'])
            e['flags_affected'] = secs.get('Flags Affected', {}).get('text')
            e['flags_affected_page'] = secs.get('Flags Affected', {}).get('page')
            e['fpu_flags_affected'] = secs.get('FPU Flags Affected', {}).get('text')
            e['sections'] = order
            # SSE/AVX compare pages (COMISD, PTEST, ...) put flag effects only in Operation
            e['operation'] = secs.get('Operation', {}).get('text')
            e['exceptions'] = {k: secs[k]['text'] for k in secs if 'Exception' in k}
            e['opcodes'] = opcode_rows(pdf, e)
            # SGX leaf pages (EADD, EINIT ...) are titled by leaf; rows read 'ENCLS[EADD]'
            if 'leaf_of' not in e:
                for r in e['opcodes']:
                    lm = re.search(r'\b(ENCL[SUV]|GETSEC|PCONFIG|SEAMOPS|TDCALL)\[([A-Z0-9_]+)\]', r.get('instruction', '') + ' ' + r.get('opcode', ''))
                    if lm:
                        e['leaf_of'], e['leaf'] = lm.group(1), lm.group(2)
                        e['mnemonics'] = [lm.group(1)]
                        break
            if n % 50 == 0:
                print(n, e['name'], e['start'], file=sys.stderr, flush=True)
    json.dump({'source': 'Intel SDM 325462-093 (combined volumes), Vol. 2 instruction pages',
               'pdf_page_range': [first, last], 'entries': E}, open(out, 'w'), indent=1)
    print('wrote', out, len(E), 'entries', sum(len(e['opcodes']) for e in E), 'opcode rows', file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:])
