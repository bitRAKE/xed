# XED datafile gap analysis

Snapshot: XED `v2026.08.23` (commit `0bcb623`), `datafiles/` only.

Method:
1. Static parse of all 9,149 instruction records (1,995 ICLASSes) with
   `research/tools/parse.py`.
2. Internal consistency checks.
3. Flags cross-check against iced (`research/tools/flagcmp.py`).
4. **Round 2:** tables and per-instruction text extracted from the vendor
   manuals committed in `research/`, used as the documented source of truth.
   See §7 for the datasets and §8 for the tools.

XED itself was not built (see *Limitations*).

Findings fall into four classes:

| Class | Meaning |
|---|---|
| **S** – Structure | The record format has no field or syntax that can hold the fact. |
| **E** – Enumeration | The format could hold it, but an enum value, register, chip or instruction is missing. |
| **X** – Potential error | The data says something that disagrees with vendor docs, another database, or XED's own data. |
| **A** – Alternate perspective | XED made a legitimate modelling choice that differs from other sources; consumers need to know. |

Evidence tags (strongest first). Page numbers are **PDF page numbers** of the committed files.
- **[SDM p.N]**: Intel SDM 325462-093US (Sep 2026), `research/325462-093-sdm-vol-1-2abcd-3abcd-4.pdf`.
- **[APM p.N]**: AMD APM 40332 rev 4.11, `research/40332_4.11_APM_Vol1-5.pdf`.
- **[internal]**: XED contradicts itself. Verified directly in the datafiles.
- **[iced]**: XED disagrees with iced's `InstructionDefs.txt` only.
- **[knowledge]**: not found stated in either manual. Treat it as a hypothesis.

Manual versions inside the bundles:

| Doc | Revision |
|---|---|
| SDM Vol. 1–4 combined | 325462-093US, Sep 2026 |
| APM Vol. 1 (24592) | 3.25, May 2026 |
| APM Vol. 2 (24593) | 3.46, Oct 2026 |
| APM Vol. 3 (24594) | 3.39, Oct 2026 |
| APM Vol. 4 (26568) | 3.27, Jul 2026 |
| APM Vol. 5 (26569) | **3.16, Nov 2021**: the x87 volume is five years older than the rest. |

---

## 0. What changed with the manuals (round 2 summary)

- **14 of the 22 round-1 "potential errors" are now confirmed** by a manual
  citation (X1–X12, X14, X20). Previously they rested on iced, on XED
  itself or on knowledge; X5, X6, X14 and X20 had rested partly or wholly
  on knowledge. X22 is confirmed but re-classified as an alternate
  perspective. X21 is re-classified because ENCLV is no longer documented
  at all. X13/X15 remain XED-internal, and X16–X19 still lack a manual
  source. None was refuted.
- **New XED errors found:** INT1 flags (X23), ERETS/ERETU VM (X24),
  AVX512_BF16 VL CPUID (X25), VP2INTERSECT AVX512F CPUID (X26),
  SYSCALL/SYSRET CPUID bit (X27), stale or missing AMD CPUID entries (X28).
- **New vendor divergences** (cases where the SDM and the APM disagree with
  each other) are listed in §5.1. The largest:
  - SDM rev 093 **redefined BSF/BSR**: flags are now defined, and the
    destination is unmodified when the source is zero.
  - Serialization lists differ: AMD counts MFENCE and WBNOINVD as serializing,
    and Intel exempts MOV to CR8.
- **Structural gaps now have data**:
  - ENCLS has one XED record, but the SDM documents 16 leaves with at least
    5 different flag behaviours (S2).
  - 59 instructions VM-exit conditionally, each with a named control (S4).
  - The serializing and ordering lists are in machine-readable form (S10).
- **Positive result:** 64-bit-mode validity in XED agrees with the SDM for
  every legacy-encoded mnemonic (0 disagreements).
- **The manuals themselves are imperfect.** See §5.2:
  - SDM Vol. 1 Table A-2 is stale (66 disagreements with the Vol. 2 pages).
  - AMD Table F-1 omits instructions that its own pages show affecting flags.

---

## 1. What a record can hold (baseline)

Fields seen across all records (counts out of 9,149):

```
ICLASS CPL CATEGORY EXTENSION PATTERN OPERANDS   9149
ISA_SET 8113  ATTRIBUTES 8090  EXCEPTIONS 7961  IFORM 7361
REAL_OPCODE 7159  FLAGS 2581  DISASM 176  COMMENT 167  UNAME 91
```

Per-ISA-set CPUID lives in separate `cpuid*.xed.txt` files. Their syntax is
`ISA, GROUP: name.leaf.sub.reg.bit …`: records inside a group are AND-ed,
groups are OR-ed (`pysrc/cpuid_rdr.py:197`). Chips are defined in
`*chips*.txt` as sets of ISA_SETs.

---

## 2. S – Structure not sufficient to represent

| # | Missing concept | Evidence | Manual evidence |
|---|---|---|---|
| S1 | **Run-time-value-dependent flags.** The only qualifiers are `IMM0/IMM1/IMMx/REP/NOREP` (`pysrc/flag_gen.py:129`). `IMM0` is implemented but never used by any datafile. | Shift-by-CL forms fall back to `MAY`. | SAL/SAR/SHL/SHR [SDM p.1895]: "If the count is 0, the flags are not affected." CF "is undefined for SHL and SHR instructions where the count is greater than or equal to the size". SHLD/SHRD [SDM p.1930, 1933]: "If the count is greater than the operand size, the flags are undefined." The extractor files these clauses under `conditional` in `flags_parse.py` output. |
| S2 | **Leaf-/selector-dependent behaviour.** One record per opcode. | ENCLS/ENCLU/GETSEC/VMFUNC have no or one FLAGS line. | `data/leaf_flags_sdm_vs_xed.csv`: 33 leaf pages. ENCLS leaves alone cover 5 flag patterns: none (EADD), ZF (EREMOVE), CF+ZF (EBLOCK, EWB), ZF + rest cleared (EINIT, EDBGRD), CF=1 + ZF (EUPDATESVN) [SDM p.4559–4615]. VMFUNC: "Depends on the VM function specified in EAX" [SDM p.4353]. |
| S3 | **Conditional privilege.** CPL is only `0` or `3`. | 84 / 9,065 records. | RDTSC operation: `IF (CR4.TSD = 0) or (CPL = 0) or (CR0.PE = 0) THEN … ELSE #GP(0)` [SDM p.1850]. RDPRU: #UD if "CPL>0 and …" [APM p.1635]. |
| S4 | **Operating-mode / virtualization context.** No SMM, VMX non-root, SVM guest, enclave or SEAM state. | RSM `CPL 3` with only `rIP`. VMCALL `CPL 0`. | 16 instructions VM-exit unconditionally in VMX non-root [SDM §28.1.2 p.4204]. 59 do so conditionally, each gated by a named VM-execution control [SDM §28.1.3 p.4204–4206]. See `data/ordering_vmexit_lists.csv`. VMMCALL/VMGEXIT "are allowed in all modes and at all privilege levels" [APM p.1831]. |
| S5 | **Vendor-divergent semantics.** `AMDONLY` exists, but there is no per-vendor operand/flag/decode dimension. Divergences live in `COMMENT` or as split ICLASSes. | `xed-isa.txt:6431` MOVSXD, `:9319`/`:9332` SYSENTER/SYSEXIT, `SYSCALL_AMD`/`SYSRET_AMD`. | §5.1 lists 7 manual-documented divergences: BSF/BSR, BT ZF, FCOMI OF/SF/AF, serialization, SYSCALL CPUID, AltMovCr8 and others. |
| S6 | **Mode- or generation-dependent CPUID and behaviour.** A CPUID bit attaches to an ISA_SET, not to a mode or a processor generation. | `XED_ISA_SET_LAHF` applies in all modes. `P4PRESCOTT_NOLAHF` drops LAHF from 32-bit mode too. | BSF/BSR footnote 2: "On some older processors, the CF, OF, SF, AF, and PF flags are unmodified" [SDM p.811, 813]. UIRET loads UIF only `IF CPUID.07H.01H:EDX.UIRET_UIF[17] = 1` [SDM p.2027]: behaviour gated by a CPUID bit. |
| S7 | **Variable / multiple memory footprints** (ENTER nesting, XSAVE*, REP strings, PUSHA). | `MEM0`/`MEM1` only. | — |
| S8 | **State bundles as attributes** (`xmm_state_r`, …), not operands. | FXSAVE. | — |
| S9 | **Exception detail.** `EXCEPTIONS` is a class name only; 1,188 records have none. **`xed-exceptions.txt` also has no error-code column.** | — | Table 7-1 "Error Code" column (#DF/#TS/#NP/#SS/#GP/#PF/#AC/#CP = Yes) [SDM p.3352–3353]. Per-instruction exception text for 864 entries is in `data/sdm_instructions.json` (`exceptions`). |
| S10 | **Ordering / serialization.** No `SERIALIZING`/`FENCE` attribute. | 100 attribute values, none of them about ordering. | Intel list [SDM §11.3 p.3480]; AMD list [APM §7.6.4 p.675]; both in `data/ordering_vmexit_lists.csv`. The lists **differ by vendor** (§5.1 A-V5). AMD LFENCE is dispatch-serializing when `CPUID Fn8000_0021_EAX[2]=1`. |
| S11 | **Semantics, timing, encoding preference.** | — | Operation pseudo-code for 864 SDM entries is now in `data/sdm_instructions.json` (`operation`). Timing remains unsourced: uops.info is blocked. |
| S12 | **x87/MXCSR sub-field effects.** | `X87STATUS` as one register. | SDM pages carry a separate "FPU Flags Affected" section (C0–C3 per instruction), captured as `fpu_flags_affected`. |
| S13 | **CPUID-gated *behaviour* (new).** Not just availability: a CPUID bit changes what the instruction does. | — | UIRET/UIF [SDM p.2027]. AMD LFENCE serialization [APM §7.6.4 p.675]. |

---

## 3. E – Enumerations missing or incomplete

| # | Enum / table | Gap | Evidence |
|---|---|---|---|
| E1 | `xed-exceptions.txt` | Vectors 20–31 all "reserved". Missing: **#VE (20)** and **#CP (21)** [SDM p.3353]; **#CP (21), #HV (28), #VC (29), #SX (30)** [APM p.710]. Vector 20 is #VE on Intel but reserved on AMD. XED's name for vector 19 is `#XF` (AMD); Intel names it `#XM`. | `data/exception_vectors.csv` (3-way) |
| E2 | `xed-flag-enum.txt` | No **UIF** flag. The SDM documents UIF effects (TESTUI/UIRET/CLUI/STUI) separately from "Flags Affected". | [SDM p.2012, 2027] |
| E3 | `xed-flag-action-enum.txt` | No "unchanged", "vendor-defined" or "masked by MSR" action. SYSCALL `RFLAGS := RFLAGS AND NOT(IA32_FMASK)` [SDM p.1990]. | — |
| E4 | Element types | No E8M0, TF32 or INT4. `FLOAT8` declared but unused. `INT`/`INT8` duplicated. `2bf16` defined twice. `HFLOAT8` comment wrong. | datafiles |
| E5 | Registers | Missing PKRU, IA32_XSS, VMCS, TR3–TR7, GIF, UINTR state, FRED MSRs. | datafiles |
| E6 | AMD chips | Last real model is Zen2. No Zen3–Zen5. | `amd/xed-amd-chips.txt` |
| E7 | Intel chips | No RPL/MTL/LNL/GRR names. | datafiles |
| E8 | AMD instructions | Missing **RMPCHKD**, **RMPOPT**, **RMPQUERY**, **RMPREAD**, **VMGEXIT**, all with published CPUID bits: RMPCHKD `8000_0025 EDX[2]`, RMPOPT `8000_0025 EDX[0]`, RMPQUERY `8000_001F EAX[6]`, RMPREAD `8000_001F EAX[21]`, VMGEXIT `8000_001F EAX[3]` [APM Table 4-1 p.1703]. RMPCHKD/RMPOPT/RMPQUERY/RMPREAD flags are in [APM Table F-1 p.2011]. Geode PFRCPV/PFRSQRTV also missing. | `data/cpuid_amd_vs_xed.csv`, `data/amd_rflags_tableF1.csv` |
| E9 | Legacy / other vendors | LOADALL, UMOV, Cyrix, NEC, POP CS, 8086 aliases, JMPE. | — |
| E10 | x87 undocumented aliases | **Present** (positive). | — |
| E11 | **CPUID entries (new)** | `n/a` or missing where the APM publishes a bit:<br>• `AMD_INVLPGB: n/a ### … 2020-04-29 not published yet`, now published as `8000_0008 EBX[3]`;<br>• `SVM: n/a`, now `8000_0001 ECX[2]`;<br>• `CLZERO` has no line, now `8000_0008 EBX[0]`;<br>• `3DNOW: n/a`, now `8000_0001 EDX[31]` [APM Table D-1 p.1947]; INVLPGB/SVM/CLZERO bits from [APM Table 3-1 p.1406, Table 4-1 p.1703]. | `datafiles/amd/cpuid-amd.xed.txt`, `data/cpuid_amd_vs_xed.csv` |

---

## 4. X – Potential errors

Status column: **confirmed** = the manual says so; **XED-internal** = XED contradicts itself.

### 4.1 Flags

| # | ICLASS | XED says | Manual says | Evidence | Status |
|---|---|---|---|---|---|
| X1 | **SBB** (+ `_LOCK`, APX) | `af-u` | AF set from result ("The OF, SF, ZF, AF, CF, and PF flags are set according to the result") | [SDM p.1903] [SDM A-2 p.539] [APM F-1 p.2011] | **confirmed ×3** |
| X2 | **BEXTR** (VEX + APX) | `of-u cf-u` | "ZF is updated … AF, SF, and PF are undefined. All other flags are cleared." | [SDM p.781]; XED `BEXTR_XOP` has `cf-0 of-0` [internal] | **confirmed** |
| X3 | **VPTEST / VTESTPS / VTESTPD** | `zf cf` only | "The OF, AF, PF, SF flags are cleared and the ZF, CF flags are set according to the operation." | [SDM p.1788, 2829] | **confirmed** |
| X4 | **TESTUI** | `cf-mod` | "The ZF, OF, AF, PF, SF flags are cleared and the CF flags to the value of the user interrupt flag." | [SDM p.2012] | **confirmed** |
| X5 | **UIRET** | `mod` on 6 flags | Operation: "update in RFLAGS only CF, PF, AF, ZF, SF, TF, DF, OF, NT, RF, AC, and ID". DF/TF/NT/RF/AC/ID are missing, and the action should be `pop`. | [SDM p.2027] | **confirmed** |
| X6 | **Shift/rotate imm8** | `IMMx MUST` | Count 0 leaves flags unaffected. The masked count governs OF. | [SDM p.1826, 1895, 1930] | **confirmed** |
| X7 | **CLRSSBSY, RSTORSSP** | no FLAGS | CF result, ZF/PF/AF/OF/SF cleared | [SDM p.854, 1888] | **confirmed** |
| X8 | **PBNDKB** | no FLAGS | ZF result, others cleared | [SDM p.1527] | **confirmed** |
| X9 | **RDPRU** (AMD) | no FLAGS | OF/SF/ZF/AF/PF = 0, CF = M | [APM p.1635] | **confirmed** |
| X10 | **MCOMMIT** (AMD) | `cf-mod` only | OF/SF/ZF/AF/PF = 0, CF = M | [APM p.1563] | **confirmed** |
| X11 | **MOV CRn / DRn** | no FLAGS | OF, SF, ZF, AF, PF, CF undefined | [SDM p.1322, 1324] [SDM A-2 p.539] | **confirmed** |
| X12 | **SYSCALL** | no RFLAGS read | `R11 := RFLAGS` | [SDM p.1990] | **confirmed** |
| X12b | **INT n/INT3/INTO** | no RFLAGS read | "The EFLAGS register is pushed onto the stack." | [SDM p.1183] | **confirmed** |
| X23 | **INT1** (new) | **no FLAGS** | Same SDM entry as INT n/INTO/INT3: "The IF, TF, NT, AC, RF, and VM flags may be cleared". XED's INT/INT3/INTO records have these flags; INT1 has none. | [SDM p.1183] [internal] | **confirmed** |
| X24 | **ERETS / ERETU** (new) | `vm-pop` | "All defined flags … are potentially modified **except for the VM flag**." | [SDM p.1003, 1007] | **confirmed** |

### 4.2 Operands / registers

| # | Item | Issue | Evidence | Status |
|---|---|---|---|---|
| X13 | FADD m32/m64 | `ST0` `SUPP` vs `IMPL` on siblings | `xed-isa.txt:21, 985` | XED-internal |
| X14 | `XED_REG_TSC` | `pseudo 32` | RDTSC: `EDX:EAX := TimeStampCounter` (64-bit) [SDM p.1850] | **confirmed** |
| X15 | Attribute casing | `FIXED_BASE0`/`fixed_base0` etc. | datafiles | XED-internal |

### 4.3 ISA_SET / chip / CPL / CPUID

| # | Item | Issue | Evidence | Status |
|---|---|---|---|---|
| X16 | MOV_CR, MOV_DR | `ISA_SET: I86` | not stated in either manual | knowledge |
| X17 | JCXZ | `ISA_SET: I386` | not stated in either manual | knowledge |
| X18 | AMD_K10 | inherits SSSE3/SSE4.x/AES/VTX/SMX from WESTMERE | chip lineage is not in the APM | knowledge |
| X19 | AMD_ZEN | keeps TBM; MONITORX placed under ZEN2 | chip lineage is not in the APM | knowledge |
| X20 | **CLGI, STGI, VMRUN, VMLOAD, VMSAVE, SKINIT** | `CPL 3` | "#GP: CPL was not 0" for each | [APM p.1708, 1809, 1836, 1829, 1837, 1801] | **confirmed** |
| X21 | ENCLV | `CPL 3` | **ENCLV and its leaves are absent from SDM rev 093** (0 occurrences). Re-classified as A10. | [SDM] | re-classified |
| X22 | VMCALL | `CPL 0` | VMCALL VM-exits unconditionally in VMX non-root | [SDM §28.1.2 p.4204] | confirmed → A |
| X25 | **AVX512_BF16_128/256** (new) | CPUID `bf16.7.1.eax.5` only | SDM: `(AVX512_BF16 AND AVX512VL) OR AVX10.1`. XED's own `AVX512F_128` and `AVX512_VP2INTERSECT_128` do include `avx512vl`. | [SDM p.2088, 2094, 2216] [internal] | **confirmed** |
| X26 | **AVX512_VP2INTERSECT_*** (new) | no `avx512f` | SDM: `AVX512_VP2INTERSECT AND AVX512F` (+VL) | [SDM p.2489] | **confirmed** (minor) |
| X27 | **SYSCALL / SYSRET** (new) | CPUID via `LONGMODE`: `intel64.80000001.0.edx.29` (LM) | `SysCallSysRet` = `8000_0001 EDX[11]` | [APM Table 4-1 p.1703] | **confirmed** |
| X28 | **AMD CPUID entries** (new) | INVLPGB/TLBSYNC, SVM, CLZERO, 3DNOW unresolvable | see E11 | [APM Tables 3-1 p.1406, 4-1 p.1703, D-1 p.1947] | **confirmed** |

---

## 5. A – Alternate perspectives

| # | Choice in XED | Other view |
|---|---|---|
| A1 | FNSTSW/FNSTENV/FNSAVE: C0–C3 via `X87STATUS`, not flags | iced lists C0–C3 as read |
| A2 | VMCALL/VMLAUNCH/VMRESUME FLAGS include DF/IF | VMfail-only view (iced). SDM: "See the operation section and Section 33.2" [SDM p.4350] |
| A3 | REP/LOCK forms are separate ICLASSes | Most databases use one mnemonic + attributes |
| A4 | SYSCALL_AMD / SYSRET_AMD split | Uneven vendor modelling |
| A5 | Undocumented aliases carry `UNDOCUMENTED` | sandpile names them |
| A6 | 99 blank ISA_SETs | — |
| A7 | Binary CPL | — |
| A8 | UD0 modelled as chips | Pattern reusable for S5 |
| A9 | **PREFETCHW (new)**: all records use `ISA_SET: PREFETCH_NOP` (`n/a`). `XED_ISA_SET_PREFETCHW` (`prefetchw.80000001.0.ecx.8`) is defined and listed by chips but **used by no instruction** (`xed-chips.txt:101`: "not subject to chip-check because of prior implementation as NOP"). | SDM: CPUID `PREFETCHW` [SDM p.1705]. APM: `3DNowPrefetch 8000_0001 ECX[8]` [APM Table 3-1 p.1407]. XED's CPUID query for PREFETCHW returns nothing. |
| A10 | **ENCLV (new)**: XED models ENCLV (`sgx-enclv/`). | Removed from SDM rev 093. Its only documentation is now older SDMs. |
| A11 | **WAIT-prefixed x87 (new)**: XED decodes `9B` as a separate FWAIT. | The SDM lists FINIT/FCLEX/FSAVE/FSTCW/FSTENV/FSTSW as instructions (`data/coverage_sdm_vs_xed.csv`). |
| A12 | **Instructions ahead of the SDM (new)**: AVX10.2 (VADDBF16…, VCVT*BF8/HF8, VMINMAX*), avx10-2-aux (BF4/BF6/HF6), MOVRS, RAO-INT, AMX-DMR, APX, IBHF are in XED but not in SDM 093. | Source of truth is the ISE / AVX10.2 / APX specs, not committed here. 153 rows in `data/coverage_sdm_vs_xed.csv`. |

### 5.1 Vendor divergences documented by the manuals (feed S5)

| # | Instruction | Intel | AMD | XED follows |
|---|---|---|---|---|
| A-V1 | **BSF/BSR** | Rev 093: PF defined, CF/OF/SF/AF cleared. Destination **unmodified** when the source is 0. Footnotes: older processors leave flags unmodified, and some may clear the upper 32 bits [SDM p.811, 813]. | OF/SF/AF/PF/CF undefined [APM F-1 p.2009] | AMD and earlier SDMs (`u`) |
| A-V2 | **BT/BTS/BTR/BTC** ZF | "The ZF flag is unaffected." [SDM p.817] | ZF undefined [APM F-1 p.2009] | Intel |
| A-V3 | **FCOMI/FCOMIP/FUCOMI/FUCOMIP** OF/SF/AF | "set the OF, SF, and AF flags to zero" [SDM p.1031] | rFLAGS box lists only ZF/PF/CF [APM p.4254, Vol. 5 rev 3.16] | Intel |
| A-V4 | **SYSRET** VM | "All." [SDM p.2000] | VM not affected [APM F-1 p.2012] | AMD |
| A-V5 | **Serializing** | + SERIALIZE, INVEPT, INVVPID; MOV to CR **except CR8** [SDM §11.3 p.3480] | + MFENCE, WBNOINVD; "MOV CRn" without the CR8 exception; WRMSR not serializing for SPEC_CTRL/PRED_CMD/x2APIC MSRs [APM §7.6.4 p.675] | neither (no attribute) |
| A-V6 | **SYSCALL CPUID** | — | `SysCallSysRet` EDX[11] [APM Table 4-1 p.1703] | LM bit (X27) |
| A-V7 | **Vector 20 / 19 names** | #VE / #XM | reserved / #XF | AMD names, no #VE |

### 5.2 Defects in the manuals themselves (so "source of truth" is used with care)

| # | Where | Defect |
|---|---|---|
| M1 | SDM Vol. 1 Table A-2 (EFLAGS cross-reference) [SDM p.537–540] | Disagrees with the Vol. 2 pages in **66** (ICLASS, flag) cells: CLI/STI IF, INT/INTO VIF/AC/RF, IRET/POPF AC/ID/VIF/VIP, SAHF "R" vs AH, BSF/BSR. It omits BMI, POPCNT, LZCNT and SYSCALL. Typo "VERR/VERRW". Treat it as stale. |
| M2 | APM Table F-1 [APM p.2009–2012] | Claims "The table includes all instructions that affect the flags", but omits MCOMMIT and RDPRU, whose own pages show flags (X9/X10). It also omits the CF read of CMC and the ZF read of REPE/REPNE CMPS/SCAS (17 read-only diffs). |
| M3 | APM Vol. 5 | Revision 3.16 (2021) inside a 2026 bundle. |
| M4 | SDM | SSE/AVX compare instructions (COMISD, UCOMISS, PCMPxSTRx…) have no "Flags Affected" section. Their effects exist only in Operation (`ZF,PF,CF := 111;`) or Description text. The extractor falls back to Operation. |
| M5 | SDM rev 093 | Generation caveats sit in page footnotes, not in a structured field. 148 footnotes captured; BSF/BSR are the only "older processors" flag notes. |

---

## 6. Sources

| Source | Used for | Accessed? |
|---|---|---|
| XED repo `datafiles/`, `pysrc/flag_gen.py`, `pysrc/cpuid_rdr.py` @ `0bcb623` | Primary subject | yes |
| **Intel SDM 325462-093US**, combined Vol. 1–4, Sep 2026 (sha256 prefix `a4a62e6a7ba11a76`) | Vol. 2 instruction pages (opcode/CPUID/mode tables, Flags Affected, Operation, exceptions, footnotes); Vol. 1 Table A-2; Vol. 3A Table 7-1 (p.3352), §11.3 (p.3480); Vol. 3C §28.1.2–28.1.3 (p.4204); VMX/SMX/SGX/TDX chapters | **yes (committed)** |
| **AMD APM 40332 rev 4.11**, Vol. 1–5 (sha256 prefix `8512b8fd936fe290`) | Vol. 3 Tables 3-1 (p.1406), 4-1 (p.1703), D-1 (p.1947), F-1 (p.2009) and per-instruction rFLAGS / exception boxes; Vol. 2 Table 8-1 (p.710), §7.6.4 (p.675) | **yes (committed)** |
| iced `InstructionDefs.txt` @ `86210d465112` | Round-1 cross-check | yes |
| sandpile.org | Undocumented opcodes | knowledge |
| uops.info | Timing (S11) | blocked |

---

## 7. Manual-derived datasets (`research/data/`)

These are the extracted "documented behaviour" tables, ready to be joined
with XED datafiles. Every row carries a PDF page number so it can be checked
against the source.

| File | Rows | Content | Use for XED |
|---|---|---|---|
| `sdm_instructions.json` | 864 entries, 4,274 opcode rows, 148 footnotes | Per SDM entry: mnemonics, page range, opcode/instruction/op-en/64-bit/compat/CPUID rows, Flags Affected (raw), FPU Flags Affected, Operation, exception sections, footnotes, leaf (GETSEC/ENCLS/ENCLU) | Ground truth for FLAGS, CPUID, mode validity and EXCEPTIONS |
| `sdm_eflags_tableA2.csv` | 150 | SDM Vol. 1 Table A-2, normalised to XED actions | Secondary only (M1) |
| `amd_rflags_tableF1.csv` | 108 | APM Table F-1, all 17 RFLAGS bits, normalised to XED actions | AMD-side FLAGS |
| `amd_cpuid_tables.csv` | 151 | APM Tables 3-1, 4-1, D-1: instruction → CPUID function, register[bit], feature name | AMD CPUID bits (E11, X27, E8) |
| `exception_vectors.csv` | 32 | Vectors 0–31: SDM vs APM vs XED (mnemonic, type, error code) | E1, S9 |
| `ordering_vmexit_lists.csv` | 110 | Serializing (priv / non-priv), memory-ordering, dispatch-serializing, VM-exit unconditional / conditional (with controlling VM-execution control) | Proposed new attributes (S4, S10) |
| `flags_manual_vs_xed.csv` | 174 | Per (ICLASS, flag): XED vs SDM prose vs SDM A-2 vs AMD F-1, with verdict and pages | X1–X12, X23–X24, §5.1, M1/M2 |
| `leaf_flags_sdm_vs_xed.csv` | 33 | Per leaf: EAX selector, documented flags, XED flags | S2 |
| `cpuid_sdm_vs_xed.csv` | 86 | SDM CPUID column vs XED cpuid features (name-normalised; most rows are benign: MMX forms, APX re-encodings) | X25, X26 |
| `cpuid_amd_vs_xed.csv` | 20 | AMD CPUID (leaf, sub, reg, bit) vs XED, bit-exact | E8, E11, X27 |
| `coverage_sdm_vs_xed.csv` | 260 | SDM mnemonics with no XED ICLASS (aliases, umbrella titles) and the reverse (instructions not in SDM 093) | A10–A12 |
| `mode64_sdm_vs_xed.csv` | 0 | 64-bit validity disagreements, legacy encodings | Positive result |

Verdict values in `flags_manual_vs_xed.csv`:

| Verdict | Meaning |
|---|---|
| `XED-differs-from-vendors` | Candidate XED error |
| `XED-matches-AMD-not-SDM` / `XED-matches-SDM-not-AMD` | Vendor divergence |
| `SDM-TableA2-stale` | Only the Vol. 1 summary disagrees |
| `mixed:*` | Mixed sources disagree |
| `read-only-diff` | Only flag reads differ |

Parsed flag actions use XED's vocabulary (`mod 0 1 u pop ah tst`), plus
`mod/u` (value-dependent) and `-` (explicitly unaffected).

---

## 8. Reproduce

The PDFs are in `research/`. Tools need poppler `pdftotext` and `pip install pdfplumber`.

```bash
python3 research/tools/extract_flag_tables.py research/40332_4.11_APM_Vol1-5.pdf research/325462-093-sdm-vol-1-2abcd-3abcd-4.pdf research/data
```

```bash
python3 research/tools/extract_sdm_vol2.py research/325462-093-sdm-vol-1-2abcd-3abcd-4.pdf research/data/sdm_instructions.json 1 5364
```

```bash
python3 research/tools/sdm_footnotes.py research/325462-093-sdm-vol-1-2abcd-3abcd-4.pdf research/data/sdm_instructions.json
```

```bash
python3 research/tools/extract_exception_vectors.py research/325462-093-sdm-vol-1-2abcd-3abcd-4.pdf research/40332_4.11_APM_Vol1-5.pdf datafiles/xed-exceptions.txt research/data/exception_vectors.csv
```

```bash
python3 research/tools/extract_amd_cpuid.py research/40332_4.11_APM_Vol1-5.pdf . research/data
```

```bash
python3 research/tools/extract_ordering_vmexit.py research/325462-093-sdm-vol-1-2abcd-3abcd-4.pdf research/40332_4.11_APM_Vol1-5.pdf . research/data/ordering_vmexit_lists.csv
```

```bash
python3 research/tools/compare_manuals.py
```

`extract_sdm_vol2.py` takes about 10 minutes over the full document; the
others take under a minute each. Round-1 tools: `parse.py`, `flagcmp.py`.

## 9. Limitations / next steps

- **XED was not built.** The `mbuild` clone was declined, so findings are
  against raw datafiles, not the merged `obj/dgen` view.
- Flag prose is parsed by rules (`flags_parse.py`). Every row keeps the raw
  text, and rows with conditional clauses are marked. Spot-check before
  filing anything upstream.
- The SDM CPUID comparison is name-based (fuzzy). The AMD comparison is
  bit-exact. A bit-exact Intel comparison needs the SDM CPUID leaf tables
  (Vol. 2A CPUID instruction pages), which are not extracted yet.
- Not yet extracted:
  - AMD per-instruction rFLAGS boxes for instructions outside Table F-1
    (only spot-checked: MCOMMIT, RDPRU, CLZERO, MONITORX);
  - per-instruction exception tables (both vendors);
  - SVM instruction-intercept table [APM Table 15-7, p.~998–999];
  - the ISE / AVX10.2 / APX specs, needed for A12.
- Chip lineage claims (X18/X19) and ISA_SET-era claims (X16/X17) still lack a
  manual source. Neither manual documents processor-model feature sets.
