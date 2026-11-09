# x86-xed.inc

The x86 instruction set for fasmg, with the instruction forms of Intel's
XED (v2026.08.23). It covers:
- legacy, x87, MMX/SSE and system instructions;
- VEX, XOP and AVX-512 (masks, broadcast, rounding, VSIB);
- AMX;
- APX: r16-r31, REX2, NDD, `{nf}`, `{zu}`, ccmp/ctest.

10,859 of XED's 10,998 forms are available. Most of the rest is XED's
`shl /6`, an alias of `shl /4`. Every encoding decodes back with XED to
what the line says.

## Usage

### With fasm2

`fasm2-xed.cmd` is `fasm2.cmd` with x86-xed.inc in place of x86-2.inc. It
loads `include/fasm2-xed.inc`. The formats, win32/win64 headers, `proc`,
`if` and the other fasm2 includes work unchanged:

```
fasm2-xed program.asm
```

### Alone

x86-xed.inc includes `xcalm.inc`, so the `include` directory must be on
fasmg's include path:

```
set include=C:\git\fasm2\include
fasmg program.asm
```

```
include 'x86-xed.inc'
use64
	mov	rax, [rbx+8]
	vaddps	zmm1{k1}{z}, zmm2, [rax]{1to16}
	{nf} add rax, rbx
	ret
```

Without `dd.inc`, relocatable values are plain emitters. With `dd.inc`
(and a format that redefines `word?`, `dword?`, `qword?`), they record
relocations, as with x86-2.inc.

### Modes

`use16` (the default), `use32` and `use64` set the mode; fasm2's
`use 64` and `bits64` mean `use64`. A form that the mode cannot encode is
an error ("this form is not available in this mode"). So is a register
that needs long mode.

### Syntax

Intel operand order and fasm's conventions:
- **Sizes:** `byte word dword fword pword qword tbyte tword dqword
  xword oword qqword yword dqqword zword`, before an operand.
- **Memory:** `[base+index*scale+disp]`, with a segment written inside
  (`[ds:ebp+4]`).
- **Branches:** `short` and `near` before a target. `far` covers
  `jmp far seg:off` and `far [mem]`. In use64 a label in brackets
  (`[label]`) is RIP-relative.
- **x87:** `st0`-`st7` or `st(i)`. `fld st1` is written without st0, as
  Intel writes it.
- **AVX-512:**
  - a mask on operand 1: `{k1}`, `{k1}{z}`;
  - a broadcast on memory: `[rax]{1to16}`;
  - rounding or SAE as the last operand: `{rn-sae}`, `{rd-sae}`,
    `{ru-sae}`, `{rz-sae}`, `{sae}`;
  - register groups: `zmm4+3`.
- **Lists:** `push rax r16 r31` and `pop rbx rax` assemble one
  instruction per register. So do pushw/popw, pushd/popd and pushq/popq.
- **Fixed registers** may be written out: `blendvps xmm1,xmm2,xmm0`,
  `pvalidate rax,ecx,edx`.
- **Names:**
  - XED's iclass names;
  - fasm2's condition-code aliases (`je`, `ja`, `cmove`, `setnc` ...);
  - fasm2's other spellings: `retn`, `xlatb`, `icebp`, `wait`, the
    `retw`/`retd`/`retq` and `retfw`/`retfd`/`retfq` families, and
    `pushf`/`popf`/`pusha`/`popa`/`iret` (at the mode's size);
  - the predicate pseudo-ops: `cmpltps`, `vcmpneq_oqps`, `vpcomltb`,
    `vpcmpltd`, `pclmullqlqdq`.

### What a line means

Every byte follows from what the line says. Nothing is added behind the
line's back, and when the line leaves a choice, the shortest encoding
wins.

Addresses:
- The first register written is the base, and its default segment is the
  address's segment. `[ebp+ebp+7Fh]` is an SS access; `[ds:ebp+ebp+7Fh]`
  stores the 3E prefix.
- Among encodings with the same meaning (the written order, base and
  index exchanged, or the base-less `[r*2+disp32]`), the shortest is
  taken. An override equal to the default segment is not stored.
- Long mode only cares about fs: and gs:. There, a direct address is
  absolute and uses the moffs forms where they exist.

| Line | Bytes |
|---|---|
| `inc dword [ebp+ebp+7Fh]` | `FF 44 2D 7F` (base ebp: SS) |
| `inc dword [ds:ebp+ebp+7Fh]` | `3E FF 44 2D 7F` |
| `inc dword [ds:ebp+ebp+80h]` | `FF 04 6D 80 00 00 00` (base-less: DS) |
| `mov eax,[ds:ebp+ecx]` | `8B 04 29` (exchanged: DS, no prefix) |
| `inc dword [eax*2]` | `FF 04 00` (`[eax+eax]`, no disp32) |
| `mov eax,[12345678h]` (use32) | `A1 78 56 34 12` |
| use64 `mov eax,[gs:30h]` | `65 67 A1 30 00 00 00` |

Two rules keep the choice of operand size from changing what a line
means:
- An operand size that no operand shows (`push 1`, `ret`) is the mode's
  default.
- An unsized memory operand takes its size from the other operands, never
  from a request. With neither, the line is an error ("operand size not
  specified").

Ties go as XED's encoder breaks them, with one exception:
- **The usual rule:** the form whose first operand is the r/m wins, so
  `mov eax,ecx` is `89 C8`.
- **The exception:** a register move into a register that is not a
  general one (mm, xmm, ymm, zmm, k, bnd ...) takes the load form, as
  x86-2.inc does. `movaps xmm0,xmm1` is `0F 28 C1`.

Length still comes first. In use64, `vmovaps xmm0,xmm8` is the two-byte
VEX of the store form, `C5 78 29 C0`. The same source always gives the same bytes.

### Encoding requests

A request comes before the mnemonic, and a line may carry several
(`{imm32}{disp32} add dword [ebx+4],1`). A request is met, or the line is
an error. It never changes what the line means: it cannot pick an operand
size or a segment.

| Request | Asks for |
|---|---|
| `{imm8}`, `{imm32}` | an immediate of that size: `{imm32} add ecx,1` is `81 C1 01 00 00 00` |
| `{disp8}`, `{disp32}` | a displacement of that size (EVEX: disp8 must be a multiple of the scale) |
| `{vex2}`, `{vex3}` | the two- or three-byte VEX prefix |
| `{evex}` | the EVEX form: `{evex} add rax,rbx` is the APX-promoted form |
| `{nf}` | APX no-flags form; it may also stand before the operands |
| `{zu}` | APX zero-upper form (setzu, imul ...) |
| `{dfv=of,sf,zf,cf}` | ccmp/ctest default flags |
| `lock`, `rep`, `repe`/`repz`, `repne`/`repnz` | the prefix, where the form takes it. Alone on a line it is just the byte |

A fasm2 setting in braces applies for one line only: `{AVX512BW} kshiftlq
k6,k6,1`. See "Choosing instruction sets" below.

### Choosing instruction sets

Every instruction form belongs to an XED ISA set, and by default all sets
are enabled.
`use` narrows or widens them:

| Line | Enables |
|---|---|
| `use everything`, `use all` | every set (the default) |
| `use AMD64, AVX2, BMI2` | fasm2's presets, levels and extensions, as x86-2.inc reads them. The CPU, FPU and SIMD levels are assigned; extensions are added. `AVX2` brings SSE3 to AVX too |
| `use SKYLAKE` | adds every ISA set of an XED chip (73 chips) |
| `use I386, CMOV` | adds ISA sets by XED name (284 sets) |
| `use none` | clears everything; then add what you need |

```
use none
use PENTIUMPRO		; or: use I86, CMOV
cmovz eax,ecx		; without CMOV: "instruction needs ISA set CMOV (enable it with use)"
```

A VEX form whose set is off falls back to its EVEX form if that set is
enabled. fasm2's encoding preferences (`use imm8`, `use rip`, `use vex2`
...) are accepted; to get those encodings, write the request on the line.

### Errors

An error names what is wrong with the line. For example:
- `operand size not specified`
- `this instruction cannot take that prefix (lock: a memory destination of a lockable form; rep: string forms)`
- `{imm8}/{imm32} cannot be honoured: no form of this instruction has that immediate for these operands`
- `registers 16-31 need REX2 or EVEX; this instruction has neither for these operands`
- `this form is not available in this mode`
- `esp/rsp cannot be an index register`
- `a register in an expression is an address: write it in [ ]`
- `short jump out of range`
- `unknown setting, XED chip or ISA set: NAME`

### Macros over mnemonics

A macro defined over a mnemonic stays in charge: `macro push? regs& ...`
can call `push` inside itself, and fasm2's `proc` redefines `ret` this
way. Each mnemonic's encoder lives under a hidden name in `xed.`, so
setting it up on first use never replaces a macro of yours.

### Names it takes

At root:
- the registers;
- `use16`, `use32`, `use64` and `use`;
- `lock`, `rep`, `repe`, `repz`, `repne`, `repnz`;
- the mnemonics;
- the `??` handler for lines that start with `{`;
- fasm2's compatibility symbols (`x86.mode`, `x86.<size>`,
  `x86.parse_operand@...`, `SSE.parse_operand@...`).

Everything else is under `xed.`.

### Differences from x86-2.inc

Of fasm2's 1,086 reference lines with expected bytes:

| Result | Lines |
|---|---:|
| same bytes | 1,040 |
| different bytes | 21 |
| an error here | 8 |
| under requests not taken yet | 17 |

Where the bytes differ:

| Line | x86-2.inc | x86-xed.inc | Why |
|---|---|---|---|
| `urdmsr rax,rcx` (and its EVEX forms) | `F2 0F 38 F8 C1` | `F2 0F 38 F8 C8` | The SDM's `11:rrr:bbb` puts the destination in r/m |
| FMA4 `vfmaddps xmm0,xmm1,xmm2,xmm3` ... | `C4 E3 F1 68 C3 20` (W1) | `C4 E3 71 68 C2 30` (W0) | A tie, settled as XED settles it |
| `cfcmovb rax,rbx`, `xchg r16,r17` | | | A tie, settled as XED settles it |
| `vpdpbusd xmm1,xmm2,xmm3`, `vcvtneps2bf16 xmm1,ymm2` | EVEX | VEX (AVX-VNNI, AVX-NE-CONVERT) | Shorter. With those sets turned off by `use`, the EVEX form |
| use64 `vmovaps xmm0,xmm8` | `C4 C1 78 28 C0` | `C5 78 29 C0` | Shorter |
| `use vex3` before a line | three-byte VEX | the shortest | Block preferences are accepted but not applied yet; `{vex3}` on the line is |
| use64 `jmp near [ebx]` | `67 48 FF 23` | `67 FF 23` | REX.W adds nothing |
| use32 `jmp far dword [bx]` | `67 66 FF 2F` | `66 67 FF 2F` | The order of the prefixes |

Lines that are errors in one and not the other:
- **Errors here:** instructions XED lacks (`rmpquery`, `vmgexit`),
  fasm2's `[r16,rax]` sibmem syntax, and `{rex2}`, `{sib}`,
  `{load}`/`{store}` and `use rex2`, which are not taken yet.
- **Errors in x86-2.inc only:** use64 `jmp [ebx]`, `retw` and
  `jmp dword [ebx]`, which are XED forms.

## How it works

### Encodings are chosen ahead of time

Each encoding is decided before you assemble anything:
- for every mnemonic, combination of operand classes, mode and request,
  the best form: the shortest, prefixes counted, with XED's order
  breaking ties;
- for every address shape, displacement size and segment, the best
  address encoding.

When a line is assembled, its operands are classified (register file and
size, memory size, the range an immediate fits, how far a branch
reaches), and the classes and requests make a key. fasmg's symbol search
finds the answer, so a line costs the same however many forms its
mnemonic has. The same source always gives the same bytes.

### Common instructions take a fast path

These mnemonics decide the usual register, value and memory shapes
directly, with the same bytes as the general path:
- add, or, adc, sbb, and, sub, xor, cmp;
- mov, test, lea;
- inc, dec, push, pop.

Anything else takes the general path, which also gives every error:
- a request or a prefix;
- r16-r31;
- a relocatable or out-of-range value;
- instruction sets narrowed by `use`.

Instructions without operands (`ret`, `cdq`, `rep movsb`) emit their
bytes directly.

### A program pays for what it uses

A mnemonic's encoder and its table of forms are set up the first time
the mnemonic is used in a pass. A program that uses forty mnemonics sets
up forty, not two thousand. The include assembles in one pass of its
own: it adds no passes to a program.

### Cost

Assembling the include alone takes about 0.037 s a pass, against 0.020
s for x86-2.inc. Lines are faster. Each figure below is the time with
x86-xed.inc as a fraction of the time with x86-2.inc:

| Line or mix | x86-xed.inc / x86-2.inc |
|---|---:|
| 160k-line 32-bit mix | 0.54 |
| 160k-line 64-bit mix | 0.61 |
| `add ecx,1` | 0.40 |
| `mov [ebx+ecx*4+8],edx` | 0.63 |
| `ret`, `rep movsb` | about 2.5 |

The include costs about 0.017 s more than x86-2.inc on every pass. Lines
save about 2 µs each, so a program of about 8,000 lines breaks even.
