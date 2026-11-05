#!/usr/bin/env python3
"""Attach page footnotes to each entry of sdm_vol2_instructions.json (in place).

SDM instruction pages carry behaviour caveats in numbered footnotes at the bottom of the
page ("2. On some older processors, the CF, OF, SF, AF, and PF flags are unmodified.").
These are where generation-dependent behaviour is documented, so they are kept verbatim.

usage: sdm_footnotes.py <sdm.pdf> <sdm_vol2_instructions.json>
"""
import sys, re, json, subprocess

FOOT = re.compile(r'^\s{0,3}(\d{1,2})\.\s+(\S.*)$')
RUNNING = re.compile(r'Vol\. 2[A-D]|INSTRUCTION SET REFERENCE')


def main(pdf, js):
    P = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True,
                       errors='replace').stdout.split('\f')
    d = json.load(open(js))
    n = 0
    for e in d['entries']:
        notes = []
        for pg in range(e['start'], e['end'] + 1):
            lines = P[pg - 1].split('\n')
            # footnotes sit after the last section text, directly above the running footer
            tail = []
            for l in reversed(lines):
                if not l.strip() or RUNNING.search(l):
                    if tail and not l.strip(): tail.append('')
                    continue
                tail.append(l)
                if len(tail) > 14: break
            tail.reverse()
            cur = None
            for l in tail:
                m = FOOT.match(l)
                if m and int(m.group(1)) < 20:
                    cur = {'n': int(m.group(1)), 'page': pg, 'text': m.group(2).strip()}
                    notes.append(cur)
                elif cur and l.startswith('   ') and l.strip():
                    cur['text'] += ' ' + l.strip()
                elif not l.strip():
                    cur = None
        # drop false positives (numbered list items inside Operation pseudo code etc.)
        e['footnotes'] = [x for x in notes if re.match(r'^[A-Z]', x['text']) and len(x['text']) > 15]
        n += len(e['footnotes'])
    json.dump(d, open(js, 'w'), indent=1)
    print('footnotes attached:', n, file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:3])
