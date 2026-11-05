# XED datafile gap analysis

Snapshot: XED `v2026.08.23` (commit `0bcb623`), `datafiles/` only.
Method: static parse of all 9,149 instruction records (1,995 ICLASSes) with
`research/tools/parse.py`, internal consistency checks, and a flags
cross-check against iced (`research/tools/flagcmp.py`). XED itself was not
built (see *Limitations*).

Findings fall into four classes:

| Class | Meaning |
|---|---|
| **S** – Structure | The record format has no field or syntax that can hold the fact. |
| **E** – Enumeration | The format could hold it, but an enum value, register, chip or instruction is missing. |
| **X** – Potential error | The data says something that disagrees with vendor docs, another database, or XED's own data. |
| **A** – Alternate perspective | XED made a legitimate modelling choice that differs from other sources; consumers need to know. |

Confidence tags on the X items:
- **[internal]**: XED contradicts itself. Verified directly in the datafiles.
- **[iced]**: XED disagrees with iced's `InstructionDefs.txt`. The SDM/APM
  statement quoted is from the manual's "Flags Affected" text as I know it.
  It was **not** re-fetched this session (felixcloutier.com and uops.info were
  blocked by the network policy), so check it against the current SDM before
  you file anything upstream.
- **[knowledge]**: no second database was checked. Based on SDM/APM knowledge only.

---

## 1. What a record can hold (baseline)

Fields seen across all records (counts out of 9,149):

```
ICLASS CPL CATEGORY EXTENSION PATTERN OPERANDS   9149
ISA_SET 8113  ATTRIBUTES 8090  EXCEPTIONS 7961  IFORM 7361
REAL_OPCODE 7159  FLAGS 2581  DISASM 176  COMMENT 167  UNAME 91
```

Per-ISA-set CPUID lives in separate `cpuid.xed.txt` files. Chips are defined
in `*chips*.txt` as sets of ISA_SETs. Everything below is measured against
this schema.

---

## 2. S – Structure not sufficient to represent

| # | Missing concept | Evidence in XED | Examples |
|---|---|---|---|
| S1 | **Run-time-value-dependent flags.** The only flag qualifiers are `IMM0/IMM1/IMMx/REP/NOREP` (`pysrc/flag_gen.py:129`). There is no way to say "count==0 leaves flags unchanged" or "masked count==1". | Shift-by-CL forms fall back to `MAY [...]`. `IMM0` is implemented in the generator but **never used** by any datafile. | SHL/SHR/SAR/ROL/ROR/RCL/RCR/SHLD/SHRD (see X6) |
| S2 | **Leaf-/selector-dependent behaviour.** Operands, flags and CPL are per encoding, not per value in EAX/ECX. | ENCLS/ENCLU/ENCLV, GETSEC, PCONFIG, SEAMOPS, TDCALL have no FLAGS. GETSEC is `CPL 3` even though most leaves need CPL0. XSETBV always writes `XCR0`, even though the target is `XCR[ECX]`. | EACCEPT sets ZF, EINIT sets ZF, GETSEC[SENTER] needs CPL0 |
| S3 | **Conditional privilege.** CPL is only `0` or `3` (84 / 9,065 records). Nothing expresses IOPL-, CR4- or MSR-gated access. | RDTSC/RDTSCP (CR4.TSD), RDPMC (CR4.PCE), SGDT/SIDT/SLDT/STR/SMSW (CR4.UMIP), IN/OUT/INS/OUTS/CLI/STI (IOPL + I/O bitmap), MONITOR/MWAIT (ring-3 enable on some parts), RDPRU (AMD) | — |
| S4 | **Operating-mode context beyond 16/32/64.** No SMM, VMX root/non-root, SVM guest, SGX enclave, TDX/SEAM, or virtual-8086 conditions. | RSM is `CPL 3` with only `rIP` as an operand. VMCALL is `CPL 0`, but in VMX non-root it VM-exits at any CPL. | RSM, VMCALL, VMMCALL/VMGEXIT, ENCLU, TDCALL |
| S5 | **Vendor-divergent semantics.** There is an `AMDONLY` attribute but no vendor dimension for operands or decode. Divergences live only in `COMMENT`, or are split into separate ICLASSes. | `xed-isa.txt:6431` MOVSXD 16-bit memory read size (Prescott/AMD 32b vs Intel 16b). `:9319`/`:9332` SYSENTER/SYSEXIT not in 64-bit on AMD. `SYSCALL_AMD`/`SYSRET_AMD` exist as a split. | Near-branch `66` prefix in 64-bit mode (Intel ignores it via `FORCE64()`/`IMMUNE66_LOOP64()`; AMD truncates to 16 bits). BSF/BSR destination when src=0 (Intel: undefined; AMD: unchanged). LOCK MOV CR0 → CR8 (AMD AltMovCr8): `CR_R()` has no LOCK path. |
| S6 | **Mode-dependent CPUID.** A CPUID bit attaches to an ISA_SET, not to a mode. | `XED_ISA_SET_LAHF: lahf.80000001.0.ecx.0` applies in every mode, but the bit only gates LAHF/SAHF in 64-bit mode. The workaround chip `P4PRESCOTT_NOLAHF: ... NOT(LAHF)` removes LAHF from 16/32-bit mode as well, which is wrong for real hardware. | LAHF/SAHF. Also PREFETCHW (3DNow! bit vs PRFCHW bit). |
| S7 | **Variable or multiple memory footprints.** At most `MEM0`/`MEM1`. Size comes from a width code, with no expression for XCR0-dependent, nesting-dependent or count-dependent size. | ENTER with nesting level > 0 reads up to 31 frame pointers. The record has only `STACKPUSH`. XSAVE* sizes depend on XCR0/XSS. REP string total extent is (r/e)CX × size. | ENTER, XSAVE/XSAVEC/XSAVES/XRSTOR*, REP MOVS/STOS, PUSHA (single `spw8` blob) |
| S8 | **Architectural state bundles.** FXSAVE/XSAVE-type state is carried by lower-case attributes (`xmm_state_r`, `x87_mmx_state_w`, …), not by operands, so it does not show up in operand-based dataflow. | `FXSAVE: OPERANDS MEM0:w:mfpxenv REG0=X87CONTROL:r` and `ATTRIBUTES xmm_state_r x87_mmx_state_r` | FXSAVE/FXRSTOR, XSAVE family, FNSAVE/FRSTOR |
| S9 | **Exception detail.** `EXCEPTIONS` names a class (SSE_TYPE_n, AVX512-En, APX-…). There are no per-instruction #GP/#SS/#PF/#AC/#DE/#UD conditions. 1,188 records (mostly legacy integer, x87, system) have no class at all. | — | DIV/IDIV #DE, CET #CP on RET/ENDBR, alignment #GP for MOVAPS (only `REQUIRES_ALIGNMENT` attribute) |
| S10 | **Ordering, serialization, side effects.** There is no attribute for serializing, fence, ordering class, or "causes VM exit unconditionally". LFENCE/MFENCE/SFENCE records have empty `OPERANDS`. | Attribute set (100 values) has no `SERIALIZING`/`FENCE`. | CPUID, IRET, MOV CR, WRMSR, SERIALIZE, LFENCE/MFENCE/SFENCE |
| S11 | **Semantics, timing, encoding preference.** No operation pseudocode, latency, throughput, port or µop data. No "preferred encoding" flag beyond the encoder's internal ordering. | — | Use uops.info / Agner Fog / vendor optimisation guides |
| S12 | **x87/MXCSR sub-field effects.** Flag enum covers C0–C3 only. TOP, exception flags (IE/DE/ZE/OE/UE/PE/SF/ES/B), MXCSR status bits and the x87 tag word are coarse `X87STATUS`/`X87TAG`/`MXCSR` register operands. | `FADD … REG?=XED_REG_X87STATUS:w:SUPP` | Precise x87/SSE exception-flag dataflow |

---

## 3. E – Enumerations missing or incomplete

| # | Enum / table | Gap | Evidence |
|---|---|---|---|
| E1 | `xed-exceptions.txt` | Vectors 20–31 are all "reserved". Missing: **#VE (20)**, **#CP (21, CET)**, **#HV (28, AMD SEV-SNP)**, **#VC (29, AMD SEV-ES)**, **#SX (30, AMD security)**. #CP matters for XED's own CET data. | file content |
| E2 | `xed-flag-enum.txt` | No **UIF** (user-interrupt flag) as a flag, so CLUI/STUI/TESTUI/UIRET cannot express it. UIF exists only as a register (`UIF UIF 1`). No x87 TOP or exception bits (see S12). | file content |
| E3 | `xed-flag-action-enum.txt` | Only `u tst mod 0 1 pop ah`. No "unchanged", "vendor-defined", or "set from MSR mask" (SYSCALL's RFLAGS &= ~FMASK). | file content |
| E4 | Element types | No **E8M0** (MX scale) for ACE `TOP4MX*`. No TF32. No INT4/UINT4. `FLOAT8` is declared (`avx10-2-element-type-base.txt:19`) but **never used**. `INT`/`INT8` and `UINT`/`UINT8` duplicate the same concept (`i8 INT 8` vs `4i8 INT8 32`). `2bf16` is defined twice (avx-ne-convert, avx10-2). The `HFLOAT8` comment says "hybrid float8", but HF8 is E4M3. | grep of `*element-type*` files |
| E5 | Registers | Missing: **PKRU** (RDPKRU/WRPKRU only show EAX/ECX/EDX), **IA32_XSS** (XSAVES/XRSTORS), VMCS (VMREAD/VMWRITE have no state operand), TR3–TR7 (386/486 `MOV TRn`, `0F 24/26`), GIF (AMD SVM, CLGI/STGI), UINTR state (UIRR/UINV/UPID), FRED MSRs. XCR1/XINUSE exists only as XSAVETRK. | `*regs*.txt` |
| E6 | AMD chips | Last real model is **AMD_ZEN2**. `AMD_FUTURE` = Zen2 + SNP + INVLPGB. No Zen3/Zen4/Zen5, Excavator, Bobcat/Jaguar, Hygon. Zen4 (AVX-512, 2022) and Zen5 cannot be selected as chips. | `amd/xed-amd-chips.txt` |
| E7 | Intel chips | No Raptor Lake, Meteor Lake, Lunar Lake, Grand Ridge. Mostly ISA-identical to neighbours (ADL/ARL), but chip-name lookup fails. | `*chips*.txt` |
| E8 | Instructions, AMD | **RMPQUERY**, **RMPREAD** (SEV-SNP, Zen5-era) are missing. **VMGEXIT** (`F3 0F 01 D9`) has no ICLASS (presumably VMMCALL with an ignored REP). Geode 3DNow! **PFRCPV/PFRSQRTV** are missing. | ICLASS presence check |
| E9 | Instructions, legacy/other vendors | Not modelled: 286 LOADALL (`0F 05`), 386 LOADALL (`0F 07`), UMOV (`0F 10–13` on 386/486), Cyrix SMM/MMX-ext (SMINT, SVDC, RSDC, SVLDT, RSLDT, SVTS, RSTS, RDSHR, WRSHR), NEC V-series, 8086 POP CS (`0F`), 8086 opcode aliasing (`60–6F` → Jcc, `C0/C1/C8/C9` aliases), IA-64 JMPE. | presence check |
| E10 | x87 undocumented aliases | **Present** as `FCOM/FCOMP/FSTP/FXCH … UNDOCUMENTED` (20 records). Recorded here as a positive, so nobody re-adds them as missing. | `ATTRIBUTES UNDOCUMENTED` |

---

## 4. X – Potential errors

### 4.1 Flags

| # | ICLASS | XED says | Expected (source) | Tag | Location |
|---|---|---|---|---|---|
| X1 | **SBB** (legacy + APX) | `af-u` | AF is set from the result. ADC in the same file says `af-mod`. | [iced][internal-asymmetry] | `xed-isa.txt:1679`, `apx-f` |
| X2 | **BEXTR** (BMI1 VEX + APX) | `of-u cf-u` | SDM: "ZF updated; CF and OF cleared; AF, SF, PF undefined". XED's own AMD TBM `BEXTR_XOP` has `cf-0 of-0`. | [iced][internal] | `hswbmi/hsw-bmi-vex-isa.xed.txt:218` |
| X3 | **VPTEST / VTESTPS / VTESTPD** | `zf-mod cf-mod` only | Missing `of-0 af-0 pf-0 sf-0`. The SSE4.1 PTEST record has them. | [iced][internal] | `avx/avx-isa.txt:1236,1256,1276` |
| X4 | **TESTUI** | `cf-mod` | CF←UIF; OF/SF/ZF/AF/PF cleared. | [iced] | `uintr/uintr-isa.xed.txt:71` |
| X5 | **UIRET** | `mod` on 6 arithmetic flags | Pops RFLAGS under a mask that also covers DF, TF, NT, RF, AC, ID (and sets UIF). These should be `pop`, and DF/TF/… are missing. | [iced][knowledge] | `uintr/uintr-isa.xed.txt:86` |
| X6 | **SHL/SHR/SAR/ROL/ROR/RCL/RCR/SHLD/SHRD imm8** | `IMMx MUST [...]`, `IMM1` tested on the raw imm | A count that masks to 0 (`shl eax,0`, `shl eax,32`) leaves flags **unchanged**, so "MUST" is wrong. A count that masks to 1 (`shl eax,33`) defines OF, so "of-u" is wrong. RCL/RCR 8/16-bit use mod 9/17. `IMM0` exists in the generator but is never used. | [internal][knowledge] | `xed-isa.txt:2709–3049`, `13222`, `13249` |
| X7 | **CLRSSBSY, RSTORSSP** | no FLAGS | CF set/cleared, ZF/PF/AF/OF/SF cleared. | [iced] | `cet/cet-isa.xed.txt` |
| X8 | **PBNDKB** | no FLAGS | ZF result; others cleared. | [iced] | `pbndkb/pbndkb-isa.xed.txt` |
| X9 | **RDPRU** (AMD) | no FLAGS | CF=1 on success; others cleared (APM). | [iced] | `amd/xed-amd-rdpru.txt` |
| X10 | **MCOMMIT** (AMD) | `cf-mod` | iced: CF modified, OF/SF/ZF/AF/PF written (cleared per APM). | [iced] — verify against APM | `amd/xed-amd-mcommit.txt:26` |
| X11 | **MOV CRn / MOV DRn** | no FLAGS | SDM: OF, SF, ZF, AF, PF, CF undefined. | [iced] | `xed-isa.txt` MOV_CR/MOV_DR |
| X12 | **SYSCALL, INT/INT3/INTO/INT1** | no `tst` on RFLAGS | SYSCALL copies RFLAGS→R11. INT pushes FLAGS. PUSHF does model the read, so these are inconsistent with it. | [internal] | `xed-isa.txt:8903`, `8431–8453` |

### 4.2 Operands / registers

| # | Item | Issue | Tag | Location |
|---|---|---|---|---|
| X13 | **FADD m32fp / m64fp** | `REG0=XED_REG_ST0:rw:SUPP`. FMUL/FSUB/FSUBR/FDIV/FDIVR/FCOM/FCOMP memory forms use `IMPL`. Disassembly shows `ST0` for every one except FADD. | [internal] | `xed-isa.txt:21`, `:985` |
| X14 | **XED_REG_TSC** | Declared `pseudo 32`. The TSC is 64 bits (RDTSC returns EDX:EAX). | [knowledge] | `xed-regs.txt:264` |
| X15 | Attribute casing | `FIXED_BASE0`/`fixed_base0`, `GATHER`/`gather`, `SIMD_SCALAR`/`simd_scalar`, `MASKOP_EVEX`/`maskop` all appear. Lower-case variants are used by 69/20/8/103/9 records. Distinct enum values with overlapping meaning. | [internal] | `xed-isa.txt`, `avx/avx-isa.txt`, `hswavx/gather-isa.txt` |

### 4.3 ISA_SET / chip / CPL

| # | Item | Issue | Tag |
|---|---|---|---|
| X16 | **MOV_CR, MOV_DR** | `ISA_SET: I86`. They were introduced on the 80386, so the `I86` chip "supports" them. | [knowledge] |
| X17 | **JCXZ** (`E3`, eamode16) | `ISA_SET: I386`. JCXZ is an 8086 instruction. Only JECXZ is 386. | [knowledge] |
| X18 | **AMD_K10** | `ALL_OF(WESTMERE)` pulls in SSSE3, SSE4.1, SSE4.2, AES, PCLMULQDQ, **VTX** and **SMX**. K10 has none of these (it has SVM, SSE4a, POPCNT, LZCNT). | [knowledge] |
| X19 | **AMD_ZEN** | Inherits **TBM** from PILEDRIVER with no `NOT(TBM)`. Zen dropped TBM. MONITORX is listed under ZEN2, but Excavator/Zen1 already had MONITORX/MWAITX. | [knowledge] |
| X20 | **SVM: CLGI, STGI, VMRUN, VMLOAD, VMSAVE, SKINIT** | `CPL 3`. All need CPL0 (#GP otherwise). INVLPGA, in the same file, is correctly `CPL 0`. | [internal][knowledge] |
| X21 | **ENCLV** | `CPL 3`. ENCLV is a VMX-root, CPL0 leaf function. | [knowledge] — verify |
| X22 | **VMCALL** | `CPL 0`. In VMX non-root, its main use, it VM-exits at any CPL. Arguably A, not X. | [knowledge] |

---

## 5. A – Alternate perspectives (not wrong; consumers must know)

| # | Choice in XED | Other view |
|---|---|---|
| A1 | Flags of FNSTSW/FNSTENV/FNSAVE are not listed. C0–C3 are carried through the `X87STATUS` register operand. | iced lists C0–C3 as read. Dataflow tools need both views merged. |
| A2 | VMCALL/VMLAUNCH/VMRESUME `FLAGS` include DF and IF. | iced models only the VMfail result (CF/ZF set, rest cleared). XED covers the VM-entry/exit RFLAGS reload. |
| A3 | `REPE_`/`REPNE_`/`REP_` and `_LOCK` are **separate ICLASSes**. | Most databases (iced, LLVM, Zydis) treat prefixes as attributes of one mnemonic. Joining datasets needs normalisation (see `flagcmp.py:xnorm`). |
| A4 | SYSCALL_AMD / SYSRET_AMD split by vendor, but other divergences (S5) are not. | Uneven vendor modelling. |
| A5 | Undocumented aliases (x87 `D9 D8–DF`, `DC D0–DF`, `F6 /1`, `D0–D3 /6`, `SALC`, `INT1`, `FFREEP`) carry the canonical ICLASS plus `UNDOCUMENTED`. | sandpile.org names them separately (FSTP1, FCOM2, …). |
| A6 | Some ISA_SETs are blank (99 x87 and 64-bit records) and default to EXTENSION. | Chip/ISA filtering on `ISA_SET` alone misses them. |
| A7 | `CPL` means "lowest privilege that can run it" and is binary. | AMD APM/SDM describe CPL1/2 and IOPL interactions that XED folds in. |
| A8 | The UD0 ModRM difference is modelled through `PPRO_UD0_SHORT/LONG` chips. | A good pattern that S5 could reuse. |

---

## 6. Sources

| Source | Used for | Accessed? |
|---|---|---|
| XED repo `datafiles/`, `pysrc/flag_gen.py`, `pysrc/read_xed_db.py` @ `0bcb623` (v2026.08.23) | Primary subject | yes |
| iced `src/csharp/Intel/Generator/Tables/InstructionDefs.txt`, master @ `86210d465112` (sha256 prefix `90db27829720680a`) | Independent flags/mnemonic cross-check (27 flag mismatches, 14 "iced has flags, XED none") | yes, raw.githubusercontent.com |
| Intel 64 and IA-32 SDM, Vol. 2 (order 325462) / Vol. 3 (325384) | "Flags Affected", CPL, exception vectors | from knowledge; mirror fetch blocked |
| Intel ISE (319433), Intel AVX10.2 / APX specs | UINTR, CET, AVX10.2, APX | from knowledge |
| AMD APM Vol. 2 (24593) and Vol. 3 (24594) | SVM CPL, RDPRU/MCOMMIT flags, #VC/#HV/#SX, AltMovCr8, near-branch `66` handling | from knowledge |
| sandpile.org | Undocumented opcodes, chip lineage | from knowledge |
| uops.info | Would supply S11 timing data | blocked (HTTP 403) |

## 7. Reproduce

```bash
python3 research/tools/parse.py
```

```bash
curl -sSLo /tmp/InstructionDefs.txt https://raw.githubusercontent.com/icedland/iced/master/src/csharp/Intel/Generator/Tables/InstructionDefs.txt
```

```bash
python3 research/tools/flagcmp.py /tmp/InstructionDefs.txt
```

## 8. Limitations / next steps

- **XED was not built.** The `mbuild` clone was declined in this session, so
  nothing was checked through XED's decoder or encoder. The merged
  `obj/dgen/all-dec-instructions.txt` would also apply UDELETE/override
  semantics that the raw-file parser ignores.
- SDM/APM statements were not re-fetched. Treat the **[knowledge]** items as
  hypotheses to check against the current manuals.
- Not yet done: CPUID cross-check (XED cpuid files vs iced `cpuid=`),
  operand-width cross-check (e.g. SMSW/MOV Sreg memory size), a full
  LLVM/binutils mnemonic coverage diff, and a uops.info merge for S11.
