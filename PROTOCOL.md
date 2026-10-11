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
- Área lida em `411f10/412840`: base **`0x478`**, 20 grupos × 4 chunks
  de 50 B (passo `0x32`), cobrindo `0x478–0x1418` = **20 slots de macro**
  (200 B cada), não DPI — ver mapa de memória abaixo.

## Resposta do GET ID3 (confirmado em hardware, `readmem`)

40 bytes: `[ID, 0x08, off_lo, off_hi+0x60, 0x20, 0x00, 0xFA, 0xFA, dados(32B)]`
(bytes 2–3 = offset pedido + `0x6000`, ex. off `0x40` → `40 60`).

Bloco por perfil (dado+2, i.e. byte 10 da resposta) = **índice DPI ativo**:
fábrica P0=1, P1–P4=3, e o hardware retorna `01, 03, 03, 03, 03`. ✔
Mapa completo abaixo; dump cru em `dumps/2026-10-11-readmem.txt`.

## Mapa de memória (readmem 0x0000–0x0600, confirmado em hardware 2026-10-11)

Tudo casado byte a byte com os 5 `RSProfile*.pfd`. Leitura: `./x39.py readmem OFF…`
(cada GET traz 32 B a partir de OFF).

| Endereço | Conteúdo | Confirmação |
|---|---|---|
| `0x1E` | `68 79` | ? (assinatura/versão?) |
| `0x20–0x2B` | `01 00` ×6 | ? |
| `0x2C` | `00` → `01` na 1ª troca de DPI pelo botão; não muda na 2ª | flag "alterado no mouse"? |
| `0x2F–0x31` | `dc 05 c0` (`0x05DC`=1500) | ? |
| `0x32` | **polling por perfil**, LE16 ×5: `1,2,2,2,2` | = `PollingRate` ✔ |
| `0x3C` | `ff` | ? |
| bases `0x40, 0x100, 0x1B0, 0x260, 0x310` | **bloco de perfil** (0xB0 B; P0 tem folga até 0x100) | |
| `base+0` | nº de estágios DPI (`05`) | = `DPIStageNum` ✔ |
| `base+2` | estágio DPI ativo, 0-based (máx = `DPIStageNum-1` = 4); o botão de DPI grava aqui na hora | = `DPI` ✔; bancada 2026-10-11: perfil 2 `03`→`04` (máx)→`02` ✔ |
| `base+4` | 5 × 6 B `[EN, V, B2, 00, 00, 00]`: **V = valor do estágio** (linear), B2 = ? (`00,00,00,01,04`) | bancada ✔: V `5a`→`2d` no estágio 2 deixou igual ao estágio 1 |
| `base+0x22` | `01` em +0x22, +0x28, +0x2E | ? |
| `base+0x40` | `14 00` (=20) + **tabela de botões**, 4 B/botão | ✔ (abaixo) |
| fim do bloco | `ff ff ff ff` | terminador |
| `0x400`, `0x420` | `ff 00 00 00 00 ff 00 ff 00 ff 00 ff ff ff 00 00 ff ff ff ff ff` (idênticos) | cores dos estágios DPI? |
| `0x448` | **LED por perfil**, 8 B × 5 | ✔ (abaixo) |
| `0x478+` | **macros**, 200 B/slot | formato = `MacroDB` ✔ |

### Tabela de botões (`base+0x42`, 4 B por botão, mesma ordem do `.pfd`)

| Código no mouse | Significado | `ButtonFunc` no .pfd |
|---|---|---|
| `81 00 00 00` / `82` / `83` | clique esq / dir / meio | 1 / 2 / 3 |
| `84 00 00 00` | botão 4 (voltar) | 5 |
| `85 00 00 00` | botão 5 (avançar) | 4 |
| `90 00 KK 00` | tecla HID `KK` (ex. `47` ScrollLock, `5C–62` keypad, `1E–27` 1–0) | 6 (antes rotulado "DPI" por engano) |
| `8E 01 CD 00` / `E9` / `EA` | consumer: play/pause / vol+ / vol− | 39 / 43 / 44 |
| `99 81 03 00`, `8A`, `89` | ? | 12, 48, 49 |
| `8B`, `8C`, `8D` | provavelmente perfil±/DPI (no fim da tabela) | 52/53? |

A tabela tem 24 posições até o `ff ff ff ff`, mas o contador diz 20; as 4 a
mais (`00`, `00`, `8B`, `8C`) não estão casadas com o `.pfd` ainda.

### LED (`0x448 + 8*perfil`)

`80 B G R MODO VELOC 01 ESTADO` — cor em **BGR**: `#FF0C79` → `79 0C FF`.
`MODO=3` (`LedMode`), `VELOC=5` (`FlashState`/`BreathState`),
`ESTADO` = `LedState` (P0=3, P1–4=2). ✔ nos 5 perfis.

### Macros (`0x478+`)

Eventos de 6 B: `84|04 KK 00 06 DD 00` — `84`=aperta, `04`=solta, `KK`=tecla HID,
`DD` = atraso. Slots com passo 200 B (`0x478`, `0x540`, `0x608`, …).

## Escrita bulk ID3 (confirmado em bancada 2026-10-11)

`03 F3 off_lo off_hi LEN 00 00 00 dados[LEN]` — o byte 4 é o **tamanho** (também na
leitura: `03 F2 off LEN` devolve exatamente LEN bytes). Após a escrita, o GET ID3
devolve o ponteiro já avançado (`off+LEN`) e `fe ff` no campo de tamanho.
Grava direto na config; o mouse aplica na hora.

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

## Codificação de DPI — parcialmente confirmada

**Bancada 2026-10-11:** gravar `V=2d` (valor do estágio 1) no estágio 2 do perfil
ativo (`w3 0x110 012d00000000 --grp 0xF3 --flag 0x06`) deixou os dois estágios com
a mesma velocidade, sem commit nem resselecionar — vale na hora. Restaurado para `5a`.

Com os CPI do `.pfd`: `V = 0x16, 0x2D, 0x5A` ↔ 500 / 1000 / 2000 → **CPI ≈ V × 22,2**
(`V ≈ CPI × 9/200`). Estágios 3 e 4 (`5C 01`, `7C 04` ↔ 3600 / 5350) não seguem isso só
com V: o papel de **B2** está em aberto (multiplicador/faixa do sensor?).

Antigo (abaixo), mantido como histórico:

Nos `.pfd`, `DPIStageValue` (LE32 `[X, Y, en]` ×5) traz `(9,9) (19,19) (39,39)
(71,71) (106,106)`, que pela fórmula da família LUOM (`CPI = (reg+1)*50`) dá
500 / 1000 / 2000 / 3600 / 5350 CPI. **No mouse esses bytes não aparecem**:
`base+4` traz `0x16, 0x2D, 0x5A, 0x15C, 0x47C`. Ou a codificação no fio é outra,
ou os estágios ficam em outro endereço. `apply --dpi` está bloqueado até fechar.

A suposição antiga de que `0x478` (passo `0x32`, `411f40`) era a tabela DPI
estava errada: é a área de macros.

## Arquivos de perfil `.pfd` (INI)

`[GROUPn]`: `PollingRate`, `LIFT` (1–3), `ANGLE`, `MouseSensitivity`,
`DPI` (índice ativo), `DPICurrentX/Y`, `DPIStageNum`, `DPIStageValue`
(hex LE32, 409 B), `LedMode1/State1/FlashState1/BreathState1/LedColor1`
(int RGB), `ButtonAssigned0_N` (hex 190 B, byte0 espelha o último) +
seções `[ButtonAssigned0_N]` com `ButtonFunc` (ver "Tabela de botões").

Macros: `MacroDB/*.MSMACRO` (`MacroSetting_0` hex) + `MacroSet.MSDB`
(índice). Upload via `04 F3` 1024 B.

## O que falta confirmar em bancada

1. **DPI**: índice ativo (`base+2`) e valor V (`base+4+6i+1`) confirmados. Falta o
   papel do byte B2 e a escala exata — medir contagens via evdev com V/B2 variados.
2. Pacote de **escrita** do polling (o valor mora em `0x32`; falta o SET).
3. Pacote de escrita do LED (o valor mora em `0x448`; falta o SET).
4. Ordem exata da sequência de apply (selects → stages → bulk → F3 → F1).
5. Significado dos códigos `99 81 03`, `89`, `8A`, `8B`–`8D` e dos campos `?` do mapa.

~~`GET ID3/ID4/ID5` — o firmware responde?~~ Sim (2026-10-11): ID2–ID6 respondem
via hidraw e pyusb; `readmem` faz o backup do estado atual.

Procedimento: `./x39.py probe` e `readmem` (só leitura), depois `dry-run`;
escrita só depois do item correspondente acima estar confirmado.
