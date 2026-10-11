#!/usr/bin/env python3
"""x39 — configura o mouse X-39 (Holtek 04d9:fc55) no Linux.

Uso típico (leitura, sem risco):
  ./x39.py profiles                 mostra os 5 perfis .pfd em CPI legível
  sudo ./x39.py probe               lê registradores do mouse (só GET, seguro)

Escrita (experimental — protocolo reverso, ver PROTOCOL.md):
  sudo ./x39.py dry-run --dpi 800 1600 3200 --polling 1000 --led FF00FF
  sudo ./x39.py apply --dpi 800 1600 3200 --polling 1000 --led FF00FF --yes
"""

import argparse
import glob
import os
import sys

import x39proto as P

DEFAULT_PFD_DIR = '/mnt/SSD/OneDrive-Linux/Documents/X-39 Gaming Mouse'

POLLING_MENU = {125: 0, 250: 1, 500: 2, 1000: 3}  # ver PROTOCOL.md (a confirmar)


def cmd_profiles(args):
    paths = sorted(glob.glob(os.path.join(args.dir, 'RSProfile*.pfd')))
    if not paths:
        print('nenhum RSProfile*.pfd em %s' % args.dir, file=sys.stderr)
        return 1
    for p in paths:
        print(P.profile_summary(p))
        print()
    return 0


def try_transport(t, label):
    print('=== %s ===' % label)
    ok = 0
    for rid, ln in sorted(P.REPORT_LEN.items()):
        try:
            data = t.get_feature(rid, ln)
            print('GET ID%d (%dB) OK: %s' % (rid, ln, data[:16].hex(' ')))
            ok += 1
        except Exception as e:
            print('GET ID%d FALHOU: %s' % (rid, e))
    return ok


def cmd_select(args):
    """Teste seguro de escrita: SET de select + GET (o que o app Win faz p/ ler)."""
    with P.open_transport(args.transport, args.hidraw) as t:
        print('transporte: %s' % getattr(t, 'path', 'pyusb'))
        before = bytes(t.get_feature(2))
        print('GET ID2 antes: %s' % before.hex(' '))
        pkt = P.select_packet(args.reg)
        print('SET %-8s: %s' % (args.reg, pkt.hex(' ')))
        t.send_feature(pkt)
        after = bytes(t.get_feature(2))
        print('GET ID2 depois: %s' % after.hex(' '))
        print('mudou: %s' % (before != after))
    return 0


def cmd_readmem(args):
    """Lê bulk do mouse: SET 03 F2 off (flag 0x20) + GET ID3. Só leitura."""
    offs = []
    if args.off:
        for o in args.off:
            offs.append(int(o, 0))
    else:
        offs = list(P.PROFILE_BASES) + [0x478, 0x4AA]
    with P.open_transport(args.transport, args.hidraw) as t:
        for off in offs:
            try:
                t.send_feature(P.r3_read_req(off))
                data = bytes(t.get_feature(3))
                print('off 0x%04x (%4d): %s' % (off, off, data.hex(' ')))
            except Exception as e:
                print('off 0x%04x FALHOU: %s' % (off, e))
    return 0


def cmd_w2(args):
    """Escrita crua ID2: SET 02 GRP SUB P3 P4 [extra] (+GET ID2 de volta)."""
    if not args.yes:
        print('recusei: passe --yes.', file=sys.stderr)
        return 2
    pkt = bytearray(16)
    pkt[0] = 0x02
    pkt[1] = int(args.grp, 0)
    pkt[2] = int(args.sub, 0)
    pkt[3] = int(args.p3, 0)
    pkt[4] = int(args.p4, 0)
    if args.extra:
        ex = bytes.fromhex(args.extra)
        pkt[5:5 + len(ex)] = ex
    with P.open_transport(args.transport, args.hidraw) as t:
        print('SET: %s' % bytes(pkt).hex(' '))
        t.send_feature(bytes(pkt))
        print('GET ID2: %s' % bytes(t.get_feature(2)).hex(' '))
    return 0


def cmd_w3(args):
    """Escrita crua bulk ID3: SET 03 GRP off flag payload (+GET ID3 de volta)."""
    if not args.yes:
        print('recusei: passe --yes.', file=sys.stderr)
        return 2
    off = int(args.off, 0)
    payload = bytes.fromhex(args.payload) if args.payload else bytes(50)
    pkt = P.r3_bulk(off, payload, group=int(args.grp, 0), flag=int(args.flag, 0))
    with P.open_transport(args.transport, args.hidraw) as t:
        print('SET: %s' % pkt.hex(' '))
        t.send_feature(pkt)
        print('GET ID3: %s' % bytes(t.get_feature(3)).hex(' '))
    return 0


def cmd_probe(args):
    print('--- nós hidraw do mouse ---')
    for path, phys in P.find_all_mouse_hidraw():
        print('%s  %s' % (path, phys))
    print()
    # 1) hidraw em cada nó do mouse
    for path, phys in P.find_all_mouse_hidraw():
        try:
            with P.HidrawTransport(path) as t:
                try_transport(t, 'hidraw %s (%s)' % (path, phys))
        except Exception as e:
            print('hidraw %s FALHOU: %s' % (path, e))
        print()
    # 2) pyusb (control transfer direto, igual ao hidapi do Windows)
    try:
        with P.PyusbTransport() as t:
            try_transport(t, 'pyusb')
    except Exception as e:
        print('pyusb FALHOU: %s' % e)
    return 0


def build_plan(args):
    """Monta a lista de pacotes (SET) a enviar. Retorna [(descr, bytes)]."""
    plan = []
    if args.dpi:
        regs = [P.cpi_to_reg(c) for c in args.dpi]
        while len(regs) < 5:
            regs.append(regs[-1])
        for i, r in enumerate(regs[:5]):
            plan.append(('dpi estágio %d = %d CPI (reg 0x%02x)' % (
                i, P.reg_to_cpi(r), r), P.dpi_stage_packet(i, r)))
        # tabela bulk ID3 (4 chunks de 50B a partir de 0x478)
        bulk = bytearray(200)
        for i, r in enumerate(regs[:5]):
            bulk[i * 2] = r
            bulk[i * 2 + 1] = r
        for c in range(4):
            off = P.DPI_BULK_BASE + c * P.DPI_BULK_STEP
            plan.append(('dpi bulk chunk %d (off 0x%x)' % (c, off),
                         P.r3_bulk(off, bytes(bulk[c * 50:(c + 1) * 50]))))
    if args.polling:
        # NOTA: mapeamento polling<->pacote ainda por confirmar em bancada.
        plan.append(('polling %d Hz (EXPERIMENTAL, ver PROTOCOL.md)' % args.polling,
                     P.r2(0x2C, p3=POLLING_MENU[args.polling], p4=0x01)))
    if args.led is not None:
        rgb = bytes.fromhex(args.led)
        plan.append(('led cor #%s (EXPERIMENTAL)' % args.led.upper(),
                     P.led_profile_packet(0x0000, rgb[0])))
    for i, pkt in enumerate(P.COMMIT_PACKETS):
        plan.append(('commit %d' % i, pkt))
    return plan


def cmd_dry_run(args):
    for descr, pkt in build_plan(args):
        print('%-45s ID=%d len=%d  %s' % (
            descr, pkt[0], len(pkt),
            pkt[:16].hex(' ') + (' ...' if len(pkt) > 16 else '')))
    return 0


def cmd_apply(args):
    if not args.yes:
        print('recusei: passe --yes para enviar ao hardware. '
              'rode dry-run antes.', file=sys.stderr)
        return 2
    plan = build_plan(args)
    t = P.open_transport(args.transport, args.hidraw)
    with t:
        for descr, pkt in plan:
            print('SET %-45s ...' % descr, end=' ', flush=True)
            try:
                t.send_feature(pkt)
                print('ok')
            except Exception as e:
                print('FALHOU: %s' % e)
                return 1
    print('concluído. Confira no uso (DPI/LED) e reporte.')
    return 0


def main():
    ap = argparse.ArgumentParser(prog='x39', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--transport', choices=['hidraw', 'pyusb'], default='pyusb')
    ap.add_argument('--hidraw', default=None, help='ex.: /dev/hidraw3')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('profiles', help='mostra perfis .pfd em formato legível')
    p.add_argument('--dir', default=DEFAULT_PFD_DIR)
    p.set_defaults(fn=cmd_profiles)

    p = sub.add_parser('probe', help='leitura segura do hardware (só GETs)')
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser('select', help='teste de escrita: SET select + GET')
    p.add_argument('reg', choices=sorted(P.REG_SELECT),
                   help='qual registrador selecionar')
    p.set_defaults(fn=cmd_select)

    p = sub.add_parser('readmem', help='lê memória bulk do mouse (só leitura)')
    p.add_argument('off', nargs='*', help='offsets (ex. 64 0x478). Padrão: bases dos 5 perfis + área DPI')
    p.set_defaults(fn=cmd_readmem)

    p = sub.add_parser('w2', help='escrita crua ID2 (debug)')
    p.add_argument('grp', help='grupo ex. 0xF3')
    p.add_argument('sub', help='sub-comando ex. 0x2C')
    p.add_argument('p3', nargs='?', default='0x00')
    p.add_argument('p4', nargs='?', default='0x00')
    p.add_argument('extra', nargs='?', default=None, help='hex p/ bytes 5+')
    p.add_argument('--yes', action='store_true')
    p.set_defaults(fn=cmd_w2)

    p = sub.add_parser('w3', help='escrita crua bulk ID3 (debug)')
    p.add_argument('off', help='offset ex. 0x80')
    p.add_argument('payload', nargs='?', default=None, help='hex até 50B')
    p.add_argument('--grp', default='0xF2')
    p.add_argument('--flag', default='0x20')
    p.add_argument('--yes', action='store_true')
    p.set_defaults(fn=cmd_w3)

    for name, fn, hlp in (('dry-run', cmd_dry_run, 'mostra pacotes sem enviar'),
                          ('apply', cmd_apply, 'envia pacotes (experimental)')):
        p = sub.add_parser(name, help=hlp)
        p.add_argument('--dpi', nargs='+', type=int, default=None,
                       help='até 5 estágios em CPI, ex. --dpi 500 1000 2000 3600 5350')
        p.add_argument('--polling', type=int, choices=[125, 250, 500, 1000],
                       default=None)
        p.add_argument('--led', default=None,
                       help='cor RRGGBB (experimental)')
        if name == 'apply':
            p.add_argument('--yes', action='store_true')
        p.set_defaults(fn=fn)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
