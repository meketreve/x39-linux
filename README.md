# x39-linux — configura o mouse X-39 no Linux

Port experimental do app Windows `X-39 Gaming Mouse` (Holtek **04d9:fc55**)
para Linux, via HID Feature Reports. Nenhuma ferramenta existente
(libratbag/Piper/OpenRazer) suporta esse mouse — o protocolo foi extraído
por engenharia reversa do `hid.exe` original (ver `PROTOCOL.md`).

## Estado

- ✅ `profiles` — lê seus 5 `RSProfile*.pfd` e mostra DPI/LED/botões (sem USB, sem risco)
- ✅ `probe` — só **lê** o mouse (GET_FEATURE). Seguro.
- ✅ `readmem` — lê a memória do mouse (polling, botões, LED, macros mapeados; ver `PROTOCOL.md`)
- ✅ `w3` — escrita crua no canal bulk (`03 F3 off LEN dados`); vale na hora.
  Testado em bancada mudando o valor de um estágio de DPI e restaurando.
- ⚠️ `dry-run` / `apply` — **experimental**; pacotes vieram do disassembly.
  `apply --dpi` está bloqueado (o caminho antigo gravava em cima das macros).

### O que já se sabe do mouse (detalhes em `PROTOCOL.md`)

| Item | Onde | Situação |
|---|---|---|
| Polling por perfil | `0x32` | leitura ✔, escrita a testar |
| Estágio DPI ativo | `base+2` (0–4) | ✔ confirmado com o botão |
| Valor de cada estágio | `base+4+6i+1` | ✔ linear, CPI ≈ V × 22,2 (estágios baixos) |
| Byte extra dos estágios altos | `base+4+6i+2` | ❓ em aberto |
| Botões | `base+0x42`, 4 B cada | leitura ✔ |
| LED (BGR, modo, velocidade) | `0x448 + 8·perfil` | leitura ✔, escrita a testar |
| Macros | `0x478+`, 200 B/slot | leitura ✔ |

Bases dos perfis: `0x40, 0x100, 0x1B0, 0x260, 0x310`.

## Instalação

```bash
git clone https://github.com/meketreve/x39-linux && cd x39-linux
pip install --break-system-packages pyusb   # só p/ fallback pyusb; hidraw não precisa
sudo cp 99-x39-gaming-mouse.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
# desplugue e plugue o mouse (ou rode tudo com sudo)
```

## Uso

```bash
./x39.py profiles --dir "/mnt/SSD/OneDrive-Linux/Documents/X-39 Gaming Mouse"
./x39.py probe
./x39.py dry-run --dpi 500 1000 2000 3600 5350
./x39.py readmem 0x40 0x448      # perfil 1 e LED (só leitura)
```

`apply --dpi` está **bloqueado**: a codificação de DPI no mouse ainda não fecha e o
caminho antigo gravava em cima das macros (ver `PROTOCOL.md`).

## Arquivos

- `x39.py` — CLI
- `x39proto.py` — transporte (hidraw/pyusb) + pacotes + parser `.pfd`
- `PROTOCOL.md` — protocolo reverso e o que falta confirmar
- `99-x39-gaming-mouse.rules` — udev (acesso sem sudo)

## Ajuda a fechar o protocolo

Rode `sudo ./x39.py probe` e me mande a saída + o que mudou no mouse
após cada `apply`. Com 2–3 iterações dá pra cravar polling, LED e botões.
