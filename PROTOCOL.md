# X-39 — protocolo USB (engenharia reversa)

Mouse: **Holtek 04d9:fc55 "Venus MMO Gaming Mouse"** (app Windows: `X-39 Gaming
Mouse_20231103(2535 HT560+P3327).exe`, instalador Inno Setup 5.6).

Sensor P3327 + MCU Holtek HT560 (pelo nome do instalador e `2535_3327` no
pdb do app: `d:\work\ET\2535_3327_newdriver_X-39\razerhid\Release\mousehid.pdb`).

## Descritores

3 interfaces HID; a de controle é a **interface 2** (Usage Page vendor
`0xFFA0`), 1 endpoint IN (`0x83`). Tudo host→mouse vai por **control
SET_REPORT (Feature)**; não há endpoint OUT.

| Report ID | Tamanho (c/ ID) | Uso no app |
|---|---|---|
| 2 | 16 B | comandos curtos: `02 F2/F3/F1 SUB …` |
| 3 | 64 B | bulk: `03 F2/F3 off_lo off_hi flag …` (até 50 B/chunk) |
| 4 | 256 B | upload de macro (`04 F3 …`, 1024 B via hidapi — firmware tolera) |
| 5 | 1024 B | blob grande |
| 6 | 2048 B | blob grande |

Transporte Windows original: `hidapi.dll` (`hid_send_feature_report`,
`hid_get_feature_report`, `hid_open_path`, …) chamado por `hid.exe`.

## Família `02 F2` — registradores / DPI (grupo `0xF2`)

Padrão do código: **SET `02 F2 SUB 00 P4 …` → GET `02 F2` → lê byte** do GET.

| SUB | P4 | Contexto (função em hid.exe) | Papel provável |
|---|---|---|---|
| `0x2C` | `0x01` | `40ef00` | select registrador genérico |
| `0x32` | `0x05` | `40f9a0` | select registrador |
| `0x38` | `0x03` | `40fa??` | select registrador |
| `0x3D` | `0x01` | `40f740` | select registrador |
| `0x49+8*i` i=0..4 | `0x07` (p3=`0x04`) | `40f5d0` loop 5 perfis | **select do perfil i** (payload zero; o valor vai no GET seguinte) |

## Canal bulk ID3 — `03 F2 off_lo off_hi flag …`

- Leitura (o que o app faz): SET `03 F2 off flag=0x20|0x32` com payload zero → GET ID3 traz 50 B.
- Escrita: mesmo formato com payload (flag exata em confirmação).
- Offsets-base por perfil, tabela em `hid.exe:0x47e58c`: **64, 256, 432, 608, 784**
  (na chamada soma +2 → 66, 258, 434, 610, 786; chunks internos de 6 B, passo 0x10).
- Área de config geral lida em `411f10/412840`: base **`0x478`**, 20 grupos × 4 chunks
  de 50 B (passo `0x32`), cobrindo `0x478–0x1418`.

## Resposta do GET ID3 (confirmado em hardware, `readmem`)

40 bytes: `[ID, 0x08, off_lo, off_hi+0x60, 0x20, 0x00, 0xFA, 0xFA, dados(32B)]`
(bytes 2–3 = offset pedido + `0x6000`, ex. off `0x40` → `40 60`).

Bloco por perfil (dado+2, i.e. byte 10 da resposta) = **índice DPI ativo**:
fábrica P0=1, P1–P4=3, e o hardware retorna `01, 03, 03, 03, 03`. ✔
Bytes esparsos 00/01 ao redor = flags (enable/modo) — mapa completo via `readmem`
varrendo `base, base+16, …`.

## Família `02 F3` — escrita de campos (grupo `0xF3`)

Template (extraído automaticamente dos 37 sends do hid.exe):
`02 F3 SUB 00 P4 00 00 00 VALOR…` (+ commit `02 F1 02 01` em seguida).

| SUB | P4 | Valor (origem no app) | Papel provável |
|---|---|---|---|
| `0x2C` | `0x02` | 1 byte (obj+0x58) | campo 0x2C |
| `0x32` | `0x06` | vários bytes | campo 0x32 (multi-byte) |
| `0x38` | `0x04` | vários bytes | campo 0x38 (multi-byte) |
| `0x3E` | dinâmico | dinâmico | LED/apply |
| `0x46` | `0x04` | — | commit |
| `0x4F` | `0x04`+`0x01` | 1 byte | campo 0x4F |

Bulk ID3: `03 F3 20 00 0A …` + 1 byte/campo × 5 perfis (campo obj+0x68).
Commits: `02 F1 02 01|02|08|10`, `02 F3 46 04 02`, `02 F5 XX`.

Ferramentas de bancada: `w2 GRP SUB P3 P4 [extra] --yes`,
`w3 OFF [payload] --grp --flag --yes` (sempre com readback automático).

| Pacote | Contexto | Papel provável |
|---|---|---|
| `02 F3 off_lo off_hi 02 00 00 00 cor` (loop 5 perfis) | `40fc70` | LED por perfil (5 = nº de RSProfiles) |
| `02 F3 3E …` | commit | parte do apply |
| `02 F3 46 04 02 …` | commit | parte do apply |
| `02 F3 2C …` | `4101b6/4101f8` | campo de perfil |
| `02 F3 32 …` (p4=`0x06`) | `4102c5/41032a` | campo de perfil |

## Família `02 F1` — commit/apply (grupo `0xF1`)

`02 F1 02 02`, `02 F1 02 10`, `02 F1 xx 04`, `02 F1 xx 08`, `02 F5 …`
(enviados no fim da sequência de gravação).

## Bulk ID3 — `03 F2 off_lo off_hi 0x32 …`

Offset base **`0x478`**, passo **`0x32` (50)**, 4 chunks (`411f40`): tabela DPI.
Offset/limites irmãos com `03 F3 … 0x20 …` (dados de perfil/botão).

## Codificação de DPI (confirmada via .pfd + LUOM da mesma família)

```
reg = CPI // 50 - 1        (vai no fio)
CPI = (reg + 1) * 50
```

Estágios de fábrica (`RSProfile1.pfd`, `DPIStageValue` como LE32
`[X, Y, en]` ×5): `(9,9) (19,19) (39,39) (71,71) (106,106)` →
**500 / 1000 / 2000 / 3600 / 5350 CPI**. `DPICurrentX/Y=14` → 750 CPI.

## Arquivos de perfil `.pfd` (INI)

`[GROUPn]`: `PollingRate`, `LIFT` (1–3), `ANGLE`, `MouseSensitivity`,
`DPI` (índice ativo), `DPICurrentX/Y`, `DPIStageNum`, `DPIStageValue`
(hex LE32, 409 B), `LedMode1/State1/FlashState1/BreathState1/LedColor1`
(int RGB), `ButtonAssigned0_N` (hex 190 B, byte0 espelha o último) +
seções `[ButtonAssigned0_N]` com `ButtonFunc` (1=esq, 2=dir, 3=meio,
4=voltar, 5=avançar, 6=DPI, 39/43/44=tecla, 52/53=perfil?).

Macros: `MacroDB/*.MSMACRO` (`MacroSetting_0` hex) + `MacroSet.MSDB`
(índice). Upload via `04 F3` 1024 B.

## O que falta confirmar em bancada (com sudo)

1. Qual SUB `F2` = polling rate (candidatos `0x2C/0x32/0x38/0x3D`) e seus valores.
2. Byte exato da cor no pacote `02 F3` de LED + `LedMode` (1–3?).
3. Ordem exata da sequência de apply (selects → stages → bulk → F3 → F1).
4. `GET ID3/ID4/ID5` — o firmware responde? (permite backup do estado atual).

Procedimento: `sudo ./x39.py probe` (só leituras), depois `dry-run`,
depois `apply --dpi … --yes` conferindo o DPI no uso real.
