#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Chris, HB9HJI – https://www.funkwelt.net
# Teil von icom-icf-tools. Nutzt CHIRP (https://github.com/kk7ds/chirp, GPLv3).
"""
build_rptlist.py – schreibt eine D-STAR-Repeater-Liste direkt in ein ID-51-ICF.

Der Original-ID-51 (nicht Plus) hat keinen CSV-Import; die Liste muss daher
im Cloning-File stehen. Struktur reverse-engineered aus einem Werks-ICF, einem
CS-51-File und einem ID-52-ICF (siehe docs/ID-51_Repeaterliste.md).

Aufruf:
    python3 build_rptlist.py --base Set20260101_02.icf \
        --csv Rpt_Export_ID52.csv --groups "1:DV Schweiz,2:DV Deutschland" \
        --replace 1=examples/repeater_dv_schweiz.csv \
        --out Set20260101_03.icf

    --csv       Icom-Repeaterlisten-CSV (ID-52-Export: Komma; CS-51: Semikolon – wird erkannt)
    --groups    welche Gruppen-Nummern aus --csv übernommen werden, mit neuem Namen
                (Reihenfolge = Reihenfolge im Gerät). Ohne --groups: alle DV-Gruppen.
    --replace   N=datei.csv  ersetzt den Inhalt der Gruppe N durch die Einträge der Datei
    --dump      Repeater-Liste eines ICF ausgeben

Limits ID-51: 750 Einträge, 25 Gruppen, Name 16 / Sub 8 Zeichen ASCII, nur 2 m / 70 cm.
"""
import argparse
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# CHIRP-Quellen: $CHIRP_SRC, sonst chirp-src/ im Repo-Hauptordner oder neben dem Script
for CHIRP in (os.environ.get("CHIRP_SRC", ""), os.path.join(HERE, "..", "chirp-src"), os.path.join(HERE, "chirp-src")):
    if CHIRP and os.path.isdir(CHIRP):
        sys.path.insert(0, os.path.abspath(CHIRP))
        break
import logging  # noqa: E402
logging.basicConfig(level=logging.ERROR)
from chirp import directory  # noqa: E402
directory.import_drivers()
from chirp.drivers.id51 import ID51Radio  # noqa: E402
from chirp.drivers.id31 import _encode_call, _decode_call  # noqa: E402

# ---- Layout ID-51 (Offsets im 0x1FB40-Byte-Image) ----
RPT_OFF, RPT_N, RPT_LEN = 0xA8C0, 750, 49
RPTCALL_OFF = 0x1384E                    # 750 × 7 Byte Gateway-Call (nur beim Site-Ersteintrag)
GROUP_NAMES_OFF, GROUP_N = 0x14CD0, 25   # 25 × 16 Zeichen
GROUP_START_OFF = 0x19BDC                # 25 × u16 BE Startindex, unbenutzt 0xFFFF
SORT_A_OFF = 0x19600                     # 750 × u16 BE Index (Identität), unbenutzt 0xFFFF
EMPTY_ENTRY = bytes.fromhex("0000000000ffff00870664ca7263ce" + "20" * 24 + "0000004e000000457fff")
EMPTY_CALL = bytes(_encode_call(" " * 8))
FLAG_DUP = {"DUP-": 0x40, "DUP+": 0x80, "OFF": 0x00, "": 0x00}
FLAG_POS = {"Exact": 0x08, "Approximate": 0x04, "None": 0x00, "": 0x00}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        head = f.readline()
        f.seek(0)
        delim = ";" if head.count(";") > head.count(",") else ","
        rows = list(csv.DictReader(f, delimiter=delim))
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def num(s):
    return float(s.replace(",", "."))


def enc_freq(freq_mhz, offset_mhz):
    f = int(round(freq_mhz * 1e6)); o = int(round(offset_mhz * 1e6))
    if f % 5000 == 0 and o % 5000 == 0:
        return (f // 5000).to_bytes(3, "big"), (o // 5000).to_bytes(2, "big")
    if f % 6250 == 0 and o % 6250 == 0:
        return ((f // 6250) | 0xC00000).to_bytes(3, "big"), (o // 6250).to_bytes(2, "big")
    raise ValueError(f"{freq_mhz} / {offset_mhz} nicht im 5- oder 6.25-kHz-Raster")


def enc_coord(val, pos_c, neg_c):
    c = pos_c if val >= 0 else neg_c
    v = abs(val); deg = int(v); minutes = int(round((v - deg) * 60 * 1000))
    if minutes >= 60000:
        deg += 1; minutes -= 60000
    return bytes([deg]) + minutes.to_bytes(2, "big") + c.encode()


def enc_utc(s):
    s = s.strip()
    if not s or s.startswith("--"):
        return (0x7FFF).to_bytes(2, "big")
    sign = -1 if s[0] == "-" else 1
    h, m = s.lstrip("+-").split(":")
    return (sign * (int(h) * 60 + int(m))).to_bytes(2, "big", signed=True)


def ascii_pad(s, n):
    s = "".join(c for c in s if 32 <= ord(c) < 127)
    return s[:n].ljust(n).encode()


def norm_call(rc):
    """'HB9HD  C' / 'HB9HD C ' / 'HB9HD' → ('HB9HD', 'C')"""
    t = rc.split()
    if not t:
        return "", ""
    call = t[0].upper()
    mod = t[1].upper() if len(t) > 1 else ""
    return call, mod


def build_entries(rows, errors, src):
    """CSV-Zeilen → Liste von dicts (bereits gefiltert auf DV, 2 m/70 cm)."""
    out = []
    for n, r in enumerate(rows, 2):
        if r.get("Mode", "DV").upper() != "DV":
            continue
        try:
            f = num(r["Frequency"]); o = num(r.get("Offset", "0") or "0")
        except ValueError:
            errors.append(f"{src} Z{n}: Frequenz/Offset unlesbar"); continue
        if not (144 <= f <= 148 or 430 <= f <= 440):
            continue
        call, mod = norm_call(r["Repeater Call Sign"])
        if call == "CALLSIGN":
            errors.append(f"{src} Z{n}: Platzhalter CALLSIGN ({r['Name']}) – übersprungen")
            continue
        if not mod:
            errors.append(f"{src} Z{n}: {call} ohne Modulbuchstaben"); continue
        gw = f"{call:<7}G"
        try:
            lat = num(r.get("Latitude", "0") or "0"); lon = num(r.get("Longitude", "0") or "0")
        except ValueError:
            lat = lon = 0.0
        pos = r.get("Position", "Approximate") or "Approximate"
        if lat == 0 and lon == 0:
            pos = "None"
        out.append(dict(call=call, mod=mod, rpt=f"{call:<7}{mod}", gw=gw, freq=f, off=o,
                        dup=r.get("Dup", "DUP-").upper() or "DUP-", pos=pos,
                        name=r["Name"], sub=r.get("Sub Name", ""), lat=lat, lon=lon,
                        utc=r.get("UTC Offset", "+1:00")))
    return out


def entry_bytes(e, site):
    fb, ob = enc_freq(e["freq"], e["off"] if e["dup"] != "OFF" else 0.0)
    flag = FLAG_DUP.get(e["dup"], 0x40) | FLAG_POS.get(e["pos"], 0x04)
    b = fb + ob + site.to_bytes(2, "big") + bytes([flag]) + bytes(_encode_call(e["rpt"]))
    b += ascii_pad(e["name"], 16) + ascii_pad(e["sub"], 8)
    if e["pos"] == "None":
        b += b"\x00\x00\x00N\x00\x00\x00E"
    else:
        b += enc_coord(e["lat"], "N", "S") + enc_coord(e["lon"], "E", "W")
    b += enc_utc(e["utc"])
    assert len(b) == RPT_LEN, len(b)
    return b


def dump(mm):
    starts = struct.unpack(">25H", mm[GROUP_START_OFF:GROUP_START_OFF + 50])
    names = [mm[GROUP_NAMES_OFF + 16 * i:GROUP_NAMES_OFF + 16 * (i + 1)].decode("latin1").rstrip() for i in range(GROUP_N)]
    valid = [(s, names[i]) for i, s in enumerate(starts) if s != 0xFFFF]
    print("Gruppen:", valid)
    for i in range(RPT_N):
        b = mm[RPT_OFF + i * RPT_LEN:RPT_OFF + (i + 1) * RPT_LEN]
        if b[15:31] == b" " * 16:
            break
        raw = int.from_bytes(b[0:3], "big"); mult = 6.25 if raw & 0xC00000 else 5.0
        f = (raw & 0x3FFFF) * mult / 1000; o = int.from_bytes(b[3:5], "big") * mult / 1000
        g = max(k for k, (s, _) in enumerate(valid) if s <= i)
        gw = _decode_call(list(mm[RPTCALL_OFF + i * 7:RPTCALL_OFF + (i + 1) * 7]))
        print(f"{i:3d} G{g + 1:<2} {_decode_call(list(b[8:15]))} {b[15:31].decode('latin1').rstrip():<16} {b[31:39].decode('latin1').rstrip():<8} {f:9.4f} {o:6.3f} flag {b[7]:02x} site {int.from_bytes(b[5:7], 'big'):3d} gw '{gw}' {b[39]:02d}{int.from_bytes(b[40:42], 'big') / 1000:06.3f}{chr(b[42])} {b[43]:03d}{int.from_bytes(b[44:46], 'big') / 1000:06.3f}{chr(b[46])} utc {int.from_bytes(b[47:49], 'big', signed=True)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--csv")
    ap.add_argument("--groups", help='z. B. "1:DV Schweiz,2:DV Deutschland"')
    ap.add_argument("--replace", action="append", default=[], help="N=datei.csv")
    ap.add_argument("--out")
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    radio = ID51Radio(a.base)
    mm = bytearray(radio._mmap.get_packed())
    if a.dump:
        dump(mm); return 0
    if not (a.csv and a.out):
        ap.error("--csv und --out nötig (oder --dump)")

    errors = []
    rows = read_csv(a.csv)
    groups = []   # [(name, [entries])]
    if a.groups:
        spec = [(g.split(":", 1)[0].strip(), g.split(":", 1)[1].strip()) for g in a.groups.split(",")]
    else:
        seen = []
        for r in rows:
            if r["Group No"] not in [s[0] for s in seen]:
                seen.append((r["Group No"], r["Group Name"]))
        spec = seen
    repl = {x.split("=", 1)[0].strip(): x.split("=", 1)[1].strip() for x in a.replace}
    for gno, gname in spec:
        if gno in repl:
            ents = build_entries(read_csv(repl[gno]), errors, os.path.basename(repl[gno]))
        else:
            ents = build_entries([r for r in rows if r["Group No"] == gno], errors, f"Gruppe {gno}")
        ents.sort(key=lambda e: (e["rpt"], e["freq"]))
        groups.append((gname, ents))

    total = sum(len(e) for _, e in groups)
    if len(groups) > GROUP_N:
        errors.append(f"{len(groups)} Gruppen > {GROUP_N}")
    if total > RPT_N:
        errors.append(f"{total} Einträge > {RPT_N}")
    fatal = [e for e in errors if "übersprungen" not in e]
    if errors:
        print("Hinweise:", *errors, sep="\n  ")
    if fatal:
        print("FEHLER – nichts geschrieben"); return 1

    # --- schreiben ---
    flat = [e for _, ents in groups for e in ents]
    site_of = {}
    for i, e in enumerate(flat):
        key = (e["call"], round(e["lat"], 4), round(e["lon"], 4))
        site_of.setdefault(key, i)
    for i in range(RPT_N):
        p = RPT_OFF + i * RPT_LEN; q = RPTCALL_OFF + i * 7
        if i < len(flat):
            e = flat[i]; site = site_of[(e["call"], round(e["lat"], 4), round(e["lon"], 4))]
            mm[p:p + RPT_LEN] = entry_bytes(e, site)
            mm[q:q + 7] = bytes(_encode_call(e["gw"])) if site == i else EMPTY_CALL
        else:
            mm[p:p + RPT_LEN] = EMPTY_ENTRY; mm[q:q + 7] = EMPTY_CALL
    starts = []; idx = 0
    for gname, ents in groups:
        starts.append(idx); idx += len(ents)
    for g in range(GROUP_N):
        mm[GROUP_NAMES_OFF + 16 * g:GROUP_NAMES_OFF + 16 * (g + 1)] = ascii_pad(groups[g][0] if g < len(groups) else "", 16)
        mm[GROUP_START_OFF + 2 * g:GROUP_START_OFF + 2 * g + 2] = (starts[g] if g < len(groups) else 0xFFFF).to_bytes(2, "big")
    for i in range(RPT_N):
        mm[SORT_A_OFF + 2 * i:SORT_A_OFF + 2 * i + 2] = (i if i < total else 0xFFFF).to_bytes(2, "big")

    radio._mmap[0] = bytes(mm)
    radio.save_mmap(a.out)
    # #EtcData gross schreiben wie build_icf.py
    with open(a.out, "rb") as f:
        data = f.read()
    head, sep, rest = data.partition(b"\r\n#EtcData=")
    if sep:
        val, nl, tail = rest.partition(b"\r\n")
        with open(a.out, "wb") as f:
            f.write(head + sep + val.upper() + nl + tail)
    print(f"OK: {total} Repeater in {len(groups)} Gruppen → {a.out}")
    for (gname, ents), s in zip(groups, starts):
        print(f"   {gname:<16} {len(ents):3d}  ab Index {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
