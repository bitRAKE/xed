#!/usr/bin/env python3
"""Read XED cpuid*.xed.txt files.

Line forms (see pysrc/cpuid_rdr.py):
  XED_ISA_SET_<ISA>:            name.LEAF.SUB.REG.BIT  [name.LEAF.SUB.REG.BIT ...]     (group FBIT)
  XED_ISA_SET_<ISA>, <GROUP>:   name.LEAF.SUB.REG[BIT] name.LEAF.SUB.REG[LO:HI]=VAL    (named group)
Records inside one group are AND-ed; groups of one ISA_SET are OR-ed.
"""
import os, re, collections

LINE = re.compile(r'^\s*XED_ISA_SET_(\w+)\s*(?:,\s*(\w+))?\s*:\s*(.*)$')
TOK = re.compile(r'^([a-z0-9_]+)\.([0-9a-fA-F]+)\.([0-9a-fA-F]+)\.(e[abcd]x)(?:\.(\d+)|\[(\d+)(?::(\d+))?\](?:=(\w+))?)$')


def read(root):
    """-> {isa_set: {group: [ {name, leaf, sub, reg, bit, hi, val} ... ]}}"""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for dp, dn, fn in os.walk(os.path.join(root, 'datafiles')):
        for f in fn:
            if not (f.startswith('cpuid') and f.endswith('.txt')) and 'cpuid' not in f: continue
            if not f.endswith('.txt'): continue
            for l in open(os.path.join(dp, f), errors='replace'):
                m = LINE.match(l.split('#')[0])
                if not m: continue
                isa, grp = m.group(1), (m.group(2) or 'FBIT')
                for t in m.group(3).split():
                    tm = TOK.match(t)
                    if not tm: continue
                    lo = tm.group(5) or tm.group(6)
                    out[isa][grp].append({'name': tm.group(1), 'leaf': int(tm.group(2), 16), 'sub': int(tm.group(3), 16),
                                          'reg': tm.group(4), 'bit': int(lo), 'hi': int(tm.group(7)) if tm.group(7) else None,
                                          'val': tm.group(8), 'file': os.path.relpath(os.path.join(dp, f), root)})
    return out
