#!/usr/bin/env python3
"""X-39 Gaming Mouse (Holtek 04d9:fc55) — protocolo reverso + transporte Linux.

Transporte: HID Feature Reports na interface 2 (Usage Page 0xFFA0).
  Report ID 2 -> 16 bytes | ID 3 -> 64 bytes | ID 4 -> 256 bytes
  ID 5 -> 1024 bytes | ID 6 -> 2048 bytes

Pode usar hidraw (ioctl HIDIOCGFEATURE/HIDIOCSFEATURE, sem detach de driver)
ou pyusb (ctrl_transfer SET/GET_REPORT, precisa detach do usbhid).

Protocolo extraído por engenharia reversa de hid.exe (app Windows):
  hid_send_feature_report / hid_get_feature_report sobre esses reports.
"""

import array
import fcntl
import glob
import os
import struct

VID = 0x04D9
PID = 0xFC55

# tamanhos totais (inclui byte 0 = Report ID)
REPORT_LEN = {2: 16, 3: 64, 4: 256, 5: 1024, 6: 2048}

IFACE_NUM = 2  # interface de controle (hidraw3 no setup atual)

# ioctl hidraw (linux/hidraw.h): _IOC(dir,type,nr,len);
# os dois usam _IOC_WRITE|_IOC_READ = 3 (hidraw.h)
_HIDIOCGFEATURE = lambda l: (3 << 30) | (l << 16) | (ord('H') << 8) | 0x07
_HIDIOCSFEATURE = lambda l: (3 << 30) | (l << 16) | (ord('H') << 8) | 0x06


# ---------------------------------------------------------------- transporte

def find_all_mouse_hidraw():
    """Todos os nós hidraw do 04d9:fc55: [(path, phys)]."""
    found = []
    for path in sorted(glob.glob('/dev/hidraw*')):
        uevent = f'/sys/class/hidraw/{os.path.basename(path)}/device/uevent'
        try:
            with open(uevent) as f:
                txt = f.read()
        except OSError:
            continue
        if '04D9' in txt and 'FC55' in txt:
            phys = ''
            for line in txt.splitlines():
                if line.startswith('HID_PHYS='):
                    phys = line
            found.append((path, phys))
    return found


def find_control_hidraw():
    """Localiza o nó hidraw da interface 2 do mouse (a de controle)."""
    found = find_all_mouse_hidraw()
    # interface 2 = .../input2
    for path, phys in found:
        if 'input2' in phys:
            return path
    return found[0][0] if found else None


class HidrawTransport:
    """Transporte via /dev/hidraw + ioctl (recomendado: não mexe no driver)."""

    def __init__(self, path=None):
        self.path = path or find_control_hidraw()
        if not self.path:
            raise RuntimeError('mouse 04d9:fc55 não encontrado em /dev/hidraw*')
        self.fd = os.open(self.path, os.O_RDWR)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def get_feature(self, report_id, length=None):
        length = length or REPORT_LEN[report_id]
        buf = array.array('B', [report_id] + [0] * (length - 1))
        fcntl.ioctl(self.fd, _HIDIOCGFEATURE(length), buf, True)
        return bytes(buf)

    def send_feature(self, data):
        buf = array.array('B', bytes(data))
        fcntl.ioctl(self.fd, _HIDIOCSFEATURE(len(buf)), buf, True)


class PyusbTransport:
    """Transporte via pyusb (fallback; faz detach do kernel driver).

    Só toca na interface 2 (controle vendor). As interfaces 0 (mouse) e
    1 (teclado) NUNCA são detached — senão o desktop perde input e
    parece que o PC travou.
    """

    def __init__(self):
        import usb.core
        import usb.util
        self.usb = usb
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        if self.dev is None:
            raise RuntimeError('mouse 04d9:fc55 não encontrado via libusb')
        self.detached = []
        try:
            if self.dev.is_kernel_driver_active(IFACE_NUM):
                self.dev.detach_kernel_driver(IFACE_NUM)
                self.detached.append(IFACE_NUM)
        except usb.core.USBError:
            pass
        try:
            cfg = self.dev.get_active_configuration()
            if cfg.bConfigurationValue != 1:
                self.dev.set_configuration()
        except usb.core.USBError:
            pass

    def close(self):
        import usb.util
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
        for i in self.detached:
            try:
                self.dev.attach_kernel_driver(i)
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def get_feature(self, report_id, length=None):
        length = length or REPORT_LEN[report_id]
        return bytes(self.dev.ctrl_transfer(
            0xA1, 0x01, 0x0300 | report_id, IFACE_NUM, length, timeout=3000))

    def send_feature(self, data):
        rid = data[0]
        self.dev.ctrl_transfer(
            0x21, 0x09, 0x0300 | rid, IFACE_NUM, bytes(data), timeout=3000)


def open_transport(prefer='hidraw', path=None):
    if prefer == 'hidraw':
        return HidrawTransport(path)
    return PyusbTransport()


# ---------------------------------------------------------------- pacotes
# Todos os pacotes abaixo foram extraídos do disassembly de hid.exe.
# Formato ID2 (16B): [02, F2|F3|F1, SUB, p3, p4, 00, 00, 00, ...]
# Formato ID3 (64B): [03, F2|F3, off_lo, off_hi, 0x32|0x20, 00.., dados]

def r2(sub, p3=0, p4=0, group=0xF2, extra=None):
    """Monta pacote de 16B (Report ID 2)."""
    pkt = bytearray(16)
    pkt[0] = 0x02
    pkt[1] = group
    pkt[2] = sub
    pkt[3] = p3
    pkt[4] = p4
    if extra:
        pkt[5:5 + len(extra)] = bytes(extra)
    return bytes(pkt)


def r3_bulk(off, data, group=0xF2, flag=0x32):
    """Monta pacote de 64B (Report ID 3): offset + até 50B de dados."""
    pkt = bytearray(64)
    pkt[0] = 0x03
    pkt[1] = group
    pkt[2] = off & 0xFF
    pkt[3] = (off >> 8) & 0xFF
    pkt[4] = flag
    pkt[8:8 + min(len(data), 50)] = bytes(data[:50])
    return bytes(pkt)


def r3_read_req(off, group=0xF2, flag=0x20):
    """Pedido de leitura bulk (igual ao app: payload zero + GET ID3)."""
    return r3_bulk(off, bytes(50), group, flag)


# bases por perfil (tabela em hid.exe:0x47e58c) + área de config geral
PROFILE_BASES = [64, 256, 432, 608, 784]
PROFILE_SUB = [0x49, 0x51, 0x59, 0x61, 0x69]  # 0x49 + 8*i (select por perfil)


# --- seleção/leitura de registradores (padrão send-then-get do hid.exe) ---
# Cada "select" é um SET ID2 seguido de um GET ID2; o valor vem num byte do GET.
REG_SELECT = {
    # nome: (SUB, p4)  — p3 é 0 nesses selects
    'reg_2c': (0x2C, 0x01),
    'reg_32': (0x32, 0x05),
    'reg_38': (0x38, 0x03),
    'reg_3d': (0x3D, 0x01),
}


def select_packet(name):
    sub, p4 = REG_SELECT[name]
    return r2(sub, p3=0, p4=p4)


# --- DPI: escrita por estágio (loop de 5 no hid.exe, 40f640) ---
# cmd = 0x49 + idx*8, p3=0x04, p4=0x07
def dpi_stage_packet(idx, value_reg=None):
    pkt = bytearray(r2(0x49 + idx * 8, p3=0x04, p4=0x07))
    if value_reg is not None:
        pkt[5] = value_reg & 0xFF
    return bytes(pkt)


# --- DPI: tabela bulk (ID3, offset base 0x478, passo 0x32, 4 chunks) ---
DPI_BULK_BASE = 0x478
DPI_BULK_STEP = 0x32


# --- LED por perfil (loop de 5 perfis no hid.exe, 40fce4) ---
def led_profile_packet(offset_word, color_byte):
    """ID2 F3 genérico de LED; offset_word varia por perfil/campo."""
    pkt = bytearray(r2(0x00, group=0xF3))
    pkt[2] = offset_word & 0xFF
    pkt[3] = (offset_word >> 8) & 0xFF
    pkt[4] = 0x02
    pkt[7] = color_byte & 0xFF
    return bytes(pkt)


# --- commits / apply (sequência final do hid.exe) ---
COMMIT_PACKETS = [
    r2(0x02, p3=0x02, group=0xF1),
    r2(0x02, p3=0x10, group=0xF1),
    r2(0x3E, group=0xF3),
    bytes(bytearray([0x02, 0xF3, 0x46, 0x04, 0x02] + [0] * 11)),
]


# ---------------------------------------------------------------- perfis .pfd

import configparser  # noqa: E402


def load_pfd(path):
    cp = configparser.ConfigParser()
    cp.optionxform = str
    cp.read(path, encoding='latin1')
    return cp


def _le32_list(hexstr):
    raw = bytes.fromhex(hexstr)
    n = len(raw) // 4
    return list(struct.unpack('<%dI' % n, raw[:n * 4]))


def decode_dpi_stages(cp, group='GROUP0'):
    """Retorna [(x_reg, y_reg, en)] por estágio. CPI = (reg+1)*50."""
    vals = _le32_list(cp[group]['DPIStageValue'])
    n = int(cp[group].get('DPIStageNum', '5'))
    stages = []
    for i in range(n):
        base = 1 + i * 4
        stages.append((vals[base], vals[base + 1], vals[base + 2]))
    return stages


def reg_to_cpi(reg):
    return (reg + 1) * 50


def cpi_to_reg(cpi):
    return max(0, (int(cpi) // 50) - 1)


BUTTON_FUNC_NAMES = {
    1: 'clique-esq', 2: 'clique-dir', 3: 'clique-meio',
    4: 'voltar', 5: 'avançar', 6: 'DPI',
    39: 'tecla', 43: 'tecla', 44: 'tecla',
    52: 'perfil?', 53: 'perfil?',
}


def decode_buttons(cp, group='GROUP0'):
    """Retorna {n: (func_id, func_nome, blob_hex)} para os 20 botões."""
    out = {}
    for i in range(1, 21):
        sec = cp['ButtonAssigned%d_%d' % (int(group[-1]), i)]
        func = int(sec.get('ButtonFunc', '0'))
        blob = cp[group].get('ButtonAssigned%d_%d' % (int(group[-1]), i), '')
        out[i] = (func, BUTTON_FUNC_NAMES.get(func, 'func_%d' % func), blob)
    return out


def decode_led(cp, group='GROUP0'):
    g = cp[group]
    color = int(g.get('LedColor1', '0'))
    return {
        'mode': g.get('LedMode1'),
        'state': g.get('LedState1'),
        'flash': g.get('FlashState1'),
        'breath': g.get('BreathState1'),
        'color_int': color,
        'color_hex': '#%06X' % (color & 0xFFFFFF),
    }


def profile_summary(path):
    cp = load_pfd(path)
    groups = [s for s in cp.sections() if s.startswith('GROUP')]
    lines = ['perfil: %s' % os.path.basename(path)]
    for grp in groups:
        g = cp[grp]
        lines.append('  [%s] polling=%s lift=%s angle=%s sens=%s' % (
            grp, g.get('PollingRate'), g.get('LIFT'), g.get('ANGLE'),
            g.get('MouseSensitivity')))
        lines.append('  DPI ativo: idx=%s (X=%s Y=%s)  estágios=%s' % (
            g.get('DPI'), g.get('DPICurrentX'), g.get('DPICurrentY'),
            g.get('DPIStageNum')))
        for i, (x, y, en) in enumerate(decode_dpi_stages(cp, grp)):
            lines.append('    estágio %d: X=%d (%d CPI)  Y=%d (%d CPI)  en=%d' % (
                i, x, reg_to_cpi(x), y, reg_to_cpi(y), en))
        led = decode_led(cp, grp)
        lines.append('  LED: mode=%s state=%s flash=%s breath=%s cor=%s' % (
            led['mode'], led['state'], led['flash'], led['breath'],
            led['color_hex']))
        lines.append('  botões:')
        for n, (f, nome, blob) in decode_buttons(cp, grp).items():
            if not blob or blob[:2] == '00':
                tag = ''
            else:
                tag = ' tecla/macro 0x%s' % blob[:2]
            lines.append('    %2d: func=%d (%s)%s' % (n, f, nome, tag))
    return '\n'.join(lines)
