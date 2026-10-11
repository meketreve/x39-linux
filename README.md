# x39-linux — configura o mouse X-39 no Linux

Port experimental do app Windows `X-39 Gaming Mouse` (Holtek **04d9:fc55**)
para Linux, via HID Feature Reports. Nenhuma ferramenta existente
(libratbag/Piper/OpenRazer) suporta esse mouse — o protocolo foi extraído
por engenharia reversa do `hid.exe` original (ver `PROTOCOL.md`).

## Estado

- ✅ `profiles` — lê seus 5 `RSProfile*.pfd` e mostra DPI/LED/botões (sem USB, sem risco)
- ✅ `probe` — só **lê** o mouse (GET_FEATURE). Seguro.
- ✅ `readmem` — lê a memória do mouse (polling, botões, LED, macros mapeados; ver `PROTOCOL.md`)
- ⚠️ `dry-run` / `apply` — escrita no hardware, **experimental**.
  Pacotes e ordem vieram do disassembly, mas cada mouse/firmware pode variar.
  Use `dry-run` primeiro, aplique com `--yes` e confira no uso.

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
