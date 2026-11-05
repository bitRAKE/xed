#!/usr/bin/env python3
"""Parse SDM "Flags Affected" prose into per-flag actions in XED vocabulary.

Actions:  mod  0  1  u  pop  tst  -  (- = explicitly unaffected)
Every result carries 'unparsed' clauses; a result is 'complete' only when no clause
mentioning a flag was left unclassified.  Raw text is always kept by the caller --
this is a triage aid, not a replacement for reading the manual.
"""
import re

ARITH = ['OF', 'SF', 'ZF', 'AF', 'PF', 'CF']
ALLF = ARITH + ['DF', 'IF', 'TF', 'AC', 'NT', 'RF', 'VM', 'VIF', 'VIP', 'ID', 'IOPL', 'UIF']
FLAG_RX = re.compile(r'\b(OF|SF|ZF|AF|PF|CF|DF|IF|TF|AC|NT|RF|VM|VIF|VIP|ID|IOPL|UIF)\b(?![- ](?:function|exit|entry|execution|instruction|control))')

UNAFF = re.compile(r'unaffected|unmodified|not affected|unchanged|not modified|preserved|no flags are affected|are not changed')
UNDEF = re.compile(r'undefined')
COND = re.compile(r'\bif\b|otherwise|according|based on|updated|contains|reflect|as specified|depending|depends|to the value|filled with|'
                  r'indicate|result|modified|affected|set or cleared|loaded with|set accordingly')
CLR = re.compile(r'cleared|set to 0|reset|are all cleared|is cleared|are cleared|zeroed|forced to 0')
SET = re.compile(r'set to 1|\bis set\b|are set\b|forced to 1|^\w+ set\.?$')
POP = re.compile(r'popped|restored|loaded from|from the stack')


# Clauses that describe an exceptional run-time path (count==0, count>=size, task switch).
# They are recorded in 'conditional' and NOT applied: XED has no way to express them (gap S1).
SKIPCOND = re.compile(r'count( operand)? is 0|masked count is 0|zero-bit rotate|greater than( or equal to)? the '
                      r'(operand )?size|task gate|task switch|nested task|previous task', re.I)
# Clauses that are conditional but describe the normal path: applied, and also recorded.
MAINCOND = re.compile(r'^(if the count is 1 or greater|for a non-zero count|if a shift occurs|for a 1-bit shift|'
                      r'for shifts greater than 1|if the masked count is 1|for all instructions|for rcl and rcr|'
                      r'for rol and ror)', re.I)


def _clauses(text):
    text = re.sub(r'(\w)- (\w)', r'\1\2', text)                  # join hyphenation "unde- fined"
    text = re.sub(r'\s+(?:C/C\+\+ )?Compiler Intrinsic Equivalent.*$', '', text)
    text = re.sub(r'(\w)\.(\d)(\s|$)', r'\1.\3', text)          # strip footnote markers "cleared.2"
    text = re.sub(r'\s+\d\.\s+(Further|On some|With|See|Software).*$', '', text)  # trailing footnotes
    parts = re.split(r'(?<=[.;])\s+|;\s*|\s+and (?=the (?:[A-Z]{2,4}, )*[A-Z]{2,4} flags? )', text)
    return [p.strip() for p in parts if p.strip()]


def classify(clause):
    c = clause.lower()
    if UNDEF.search(c) and re.search(r'affected|is set|otherwise', c) and not re.search(r'flags are undefined', c):
        return 'mod/u'          # "affected for 1-bit shifts; otherwise undefined" -> value dependent
    if UNDEF.search(c): return 'u'
    if UNAFF.search(c): return '-'
    if re.search(r'from the ah register|values from ah', c): return 'ah'
    if POP.search(c): return 'pop'
    cond = bool(COND.search(c))
    clr, st = bool(CLR.search(c)), bool(SET.search(c))
    if cond or (clr and st): return 'mod'
    if clr: return '0'
    if st: return '1'
    return None


def parse(text):
    res = {'actions': {}, 'unparsed': [], 'conditional': [], 'complete': True, 'none': False, 'note': ''}
    if text is None:
        res['complete'] = False; return res
    t = text.strip()
    if re.match(r'^none\b', t, re.I) or re.match(r'^no flags', t, re.I):
        res['none'] = True; return res
    m = re.match(r'^all (defined )?flags( and fields)?.*?(potentially )?modified,? except (for )?the ([A-Z]+) flag', t, re.I)
    if m:
        for f in ARITH + ['DF', 'IF', 'TF', 'AC', 'NT', 'RF', 'VIF', 'VIP', 'ID', 'IOPL', 'VM']:
            A_ = res['actions']; A_[f] = '-' if f == m.group(5).upper() else 'mod'
        res['note'] = 'all-except-' + m.group(5).upper(); return res
    if re.match(r'^depends on the .* specified in E[ABCD]X', t, re.I):
        res['note'] = 'leaf-dependent'; res['complete'] = False; return res
    if re.match(r'^all\.?$', t, re.I):
        res['note'] = 'all-flags'; return res
    if re.search(r'see the operation section', t, re.I) and len(t) < 90:
        res['note'] = 'see-operation'; res['complete'] = False; return res
    A = res['actions']
    last = []
    for cl in _clauses(t):
        if re.match(r'^otherwise,? (it is|they are) undefined', cl, re.I) and last:
            for f in last: A[f] = 'mod/u'
            continue
        if SKIPCOND.search(cl):
            res['conditional'].append(cl); continue
        maincond = bool(MAINCOND.match(cl))
        if maincond:
            res['conditional'].append(cl)
        flags = FLAG_RX.findall(cl)
        low = cl.lower()
        rest_arith = bool(re.search(r'(all )?other (arithmetic |status )?flags|all other flags|remaining flags|'
                                    r'other flags in the eflags|other flags in rflags', low))
        all_arith = bool(re.search(r'all (arithmetic|status) flags|the arithmetic flags', low)) and not flags
        if not flags and not rest_arith and not all_arith:
            if re.search(r'flag', low) and not re.search(r'^\d', low): res['unparsed'].append(cl)
            continue
        act = classify(cl)
        if act is None:
            res['unparsed'].append(cl); res['complete'] = False; continue
        if rest_arith or all_arith:
            for f in ARITH:
                A.setdefault(f, act)
        for f in flags:
            if maincond and f in A and A[f] != act and 'u' in (A[f], act):
                A[f] = 'mod/u'
            else:
                A[f] = act
        last = flags
    return res


if __name__ == '__main__':
    import sys
    for line in sys.stdin:
        name, _, txt = line.partition('::')
        r = parse(txt)
        print(name.strip(), r['actions'], 'NONE' if r['none'] else '', '' if r['complete'] else 'INCOMPLETE', r['unparsed'][:2])
