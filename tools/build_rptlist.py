#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Chris, HB9HJI – https://www.funkwelt.net
# Teil von icom-icf-tools. Nutzt CHIRP (https://github.com/kk7ds/chirp, GPLv3).
"""
build_rptlist.py – schreibt eine D-STAR-Repeaterliste (DR-Modus) direkt in ein Icom-ICF.

Für Geräte ohne CSV-Import der Repeaterliste: ID-51 (Original) und ID-31 (Original).
Das Modell wird aus der ersten Zeile des ICF erkannt. Struktur reverse-engineered aus
vom Gerät gespeicherten ICF-Files (siehe docs/ID-51_Repeaterliste.md).
ID-31: am Gerät getestet (Laden, Bänke, DR-Liste, Scan).

Aufruf (neue Form, Gruppen in der Reihenfolge im Gerät):
    python3 build_rptlist.py --base MeinID31.icf --out Set20260101_02.icf \\
        --group "DV Schweiz=examples/repeater_dv_schweiz.csv" \\
        --group "DV Deutschland=Rpt_Export.csv#2" \\
        --group "Europa West=Rpt_Export.csv#8+9" \\
        --group "Simplex=@keep"

    --group NAME=DATEI[#N+M]   Gruppe NAME aus Icom-Repeater-CSV; #N+M = nur Gruppen N und M der Datei
    --group NAME=@keep         Gruppe NAME unverändert aus --base übernehmen (z. B. «Simplex»)
    --no-dedupe                Repeater (Rufzeichen+Modul), die schon in einer früheren Gruppe stehen,
                               NICHT weglassen (Standard bei --group: weglassen; alte Form: nie)
    --dump                     Repeaterliste eines ICF ausgeben (Spalte scan/SKIP)
    --fix-skip --out X         nur das Skip-Bitfeld einer vorhandenen Liste korrigieren

Alte Form (ID-51, weiterhin gültig):
    --csv DATEI --groups "1:DV Schweiz,2:DV Deutschland" [--replace 1=andere.csv]

Es werden nur DV-Einträge im Frequenzbereich des Geräts übernommen (ID-51: 2 m/70 cm, ID-31: 70 cm).
"""
import argparse
import csv
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.environ.get("CHIRP_SRC", ""), os.path.join(HERE, "chirp-src"),
             os.path.join(HERE, "..", "chirp-src")):
    if cand and os.path.isdir(cand):
        sys.path.insert(0, cand)
        break
import logging  # noqa: E402
logging.basicConfig(level=logging.ERROR)
from chirp import directory  # noqa: E402
directory.import_drivers()
from chirp.drivers.id51 import ID51Radio  # noqa: E402
from chirp.drivers.id31 import ID31Radio, _encode_call, _decode_call  # noqa: E402

# ---- Layouts (Offsets im Speicherabbild) ----
# freq_flags: (Flag Frequenz 6.25 kHz, Flag Ablage 6.25 kHz) im 24-Bit-Frequenzfeld
LAYOUTS = {
    "33900001": dict(model="ID-51", radio=ID51Radio, rpt=0xA8C0, n=750, rptcall=0x1384E,
                     gnames=0x14CD0, ng=25, gstart=0x19BDC, sort=0x19600, scan=None,   # Kandidat 0x19D94, am Gerät nicht geprüft
                     flags=(0xC00000, None), bands=((144, 148), (430, 440))),
    "33220001": dict(model="ID-31", radio=ID31Radio, rpt=0x74C0, n=700, rptcall=0xFABC,
                     gnames=0x10DE0, ng=20, gstart=0x14AF8, sort=0x14580, scan=0x14C92,
                     flags=(0x200000, 0x040000), bands=((430, 440),)),
}
# scan: Bitfeld 1 Bit je Eintrag (LSB zuerst): 1 = beim DR-Scan dabei, 0 = SKIP bzw. leer.
#       Werkslisten: 1 bei allen Funk-Einträgen, 0 bei Einträgen ohne Frequenz und bei leeren.
RPT_LEN = 49
EMPTY_ENTRY = bytes.fromhex("0000000000ffff00870664ca7263ce" + "20" * 24 + "0000004e000000457fff")
EMPTY_CALL = bytes(_encode_call(" " * 8))
FLAG_DUP = {"DUP-": 0x40, "DUP+": 0x80, "OFF": 0x00, "": 0x00}
FLAG_POS = {"Exact": 0x08, "Approximate": 0x04, "None": 0x00, "": 0x00}


def model_of(path):
    with open(path, encoding="ascii", errors="replace") as f:
        mid = f.readline().strip()
    if mid not in LAYOUTS:
        sys.exit(f"Modell-ID {mid} nicht unterstützt (bekannt: {', '.join(LAYOUTS)})")
    return LAYOUTS[mid]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        head = f.readline()
        f.seek(0)
        delim = ";" if head.count(";") > head.count(",") else ","
        rows = list(csv.DictReader(f, delimiter=delim))
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def num(s):
    return float(s.replace(",", "."))


def enc_freq(L, freq_mhz, offset_mhz):
    f = int(round(freq_mhz * 1e6)); o = int(round(offset_mhz * 1e6))
    ff, of = L["flags"]
    if f % 5000 == 0 and o % 5000 == 0:
        return (f // 5000).to_bytes(3, "big"), (o // 5000).to_bytes(2, "big")
    if f % 6250 == 0 and o % 6250 == 0:
        return ((f // 6250) | ff | (of or 0)).to_bytes(3, "big"), (o // 6250).to_bytes(2, "big")
    raise ValueError(f"{freq_mhz} / {offset_mhz} nicht im 5- oder 6.25-kHz-Raster")


def dec_freq(L, b):
    raw = int.from_bytes(b[0:3], "big"); ff, of = L["flags"]
    fm = 6.25 if raw & ff else 5.0
    om = (6.25 if raw & of else 5.0) if of else fm
    return (raw & 0x3FFFF) * fm / 1000, int.from_bytes(b[3:5], "big") * om / 1000


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
    s = (s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("Ä", "Ae")
          .replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss"))
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


def in_band(L, f):
    return any(lo <= f <= hi for lo, hi in L["bands"])


def build_entries(L, rows, errors, src):
    """CSV-Zeilen → Liste von dicts (gefiltert auf DV im Band des Geräts)."""
    out = []
    for n, r in enumerate(rows, 2):
        if r.get("Mode", "DV").upper() != "DV":
            continue
        try:
            f = num(r["Frequency"]); o = num(r.get("Offset", "0") or "0")
        except ValueError:
            errors.append(f"{src} Z{n}: Frequenz/Offset unlesbar"); continue
        if not in_band(L, f):
            continue
        call, mod = norm_call(r["Repeater Call Sign"])
        if call == "CALLSIGN":
            errors.append(f"{src} Z{n}: Platzhalter CALLSIGN ({r['Name']}) – übersprungen")
            continue
        if not mod:
            errors.append(f"{src} Z{n}: {call} ohne Modulbuchstaben – übersprungen"); continue
        gwc, _ = norm_call(r.get("Gateway Call Sign", ""))
        gw = f"{(gwc or call):<7}G"
        try:
            lat = num(r.get("Latitude", "0") or "0"); lon = num(r.get("Longitude", "0") or "0")
        except ValueError:
            lat = lon = 0.0
        pos = r.get("Position", "Approximate") or "Approximate"
        if lat == 0 and lon == 0:
            pos = "None"
        dup = (r.get("Dup", "DUP-") or "DUP-").upper()
        out.append(dict(call=call, mod=mod, rpt=f"{call:<7}{mod}", gw=gw, freq=f, off=o,
                        dup=dup, pos=pos, name=r["Name"], sub=r.get("Sub Name", ""),
                        lat=lat, lon=lon, utc=r.get("UTC Offset", "+1:00")))
    return out


def entry_bytes(L, e, site):
    fb, ob = enc_freq(L, e["freq"], e["off"] if e["dup"] != "OFF" else 0.0)
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


def groups_of(L, mm):
    ng = L["ng"]
    starts = struct.unpack(f">{ng}H", mm[L["gstart"]:L["gstart"] + 2 * ng])
    names = [mm[L["gnames"] + 16 * i:L["gnames"] + 16 * (i + 1)].decode("latin1").rstrip() for i in range(ng)]
    total = sum(1 for i in range(L["n"]) if struct.unpack(">H", mm[L["sort"] + 2 * i:L["sort"] + 2 * i + 2])[0] != 0xFFFF)
    valid = [(s, names[i]) for i, s in enumerate(starts) if s != 0xFFFF]
    out = []
    for k, (s, name) in enumerate(valid):
        end = valid[k + 1][0] if k + 1 < len(valid) else total
        out.append((name, s, end))
    return out


def dump(L, mm):
    gs = groups_of(L, mm)
    print(f"Modell {L['model']}, Gruppen:", [(n, s, e - s) for n, s, e in gs])
    for g, (gname, s, e) in enumerate(gs):
        for i in range(s, e):
            b = mm[L["rpt"] + i * RPT_LEN:L["rpt"] + (i + 1) * RPT_LEN]
            f, o = dec_freq(L, b)
            gw = _decode_call(list(mm[L["rptcall"] + i * 7:L["rptcall"] + (i + 1) * 7]))
            print(f"{i:3d} G{g + 1:<2} {_decode_call(list(b[8:15]))} {b[15:31].decode('latin1').rstrip():<16} "
                  f"{b[31:39].decode('latin1').rstrip():<8} {f:9.4f} {o:6.3f} flag {b[7]:02x} "
                  f"site {int.from_bytes(b[5:7], 'big'):3d} gw '{gw}' {b[39]:02d}{int.from_bytes(b[40:42], 'big') / 1000:06.3f}{chr(b[42])} "
                  f"{b[43]:03d}{int.from_bytes(b[44:46], 'big') / 1000:06.3f}{chr(b[46])} utc {int.from_bytes(b[47:49], 'big', signed=True)}"
                  f"{'' if L['scan'] is None or (mm[L['scan'] + i // 8] >> (i % 8)) & 1 else ' SKIP'}")


def write_list(L, mm, groups):
    """groups: [(name, [entry-dict | ('raw', bytes49, bytes7)])] → mm (in place)."""
    flat = [e for _, ents in groups for e in ents]
    site_of = {}
    for i, e in enumerate(flat):
        if isinstance(e, dict):
            site_of.setdefault((e["call"], round(e["lat"], 4), round(e["lon"], 4)), i)
    for i in range(L["n"]):
        p = L["rpt"] + i * RPT_LEN; q = L["rptcall"] + i * 7
        if i < len(flat):
            e = flat[i]
            if isinstance(e, dict):
                site = site_of[(e["call"], round(e["lat"], 4), round(e["lon"], 4))]
                mm[p:p + RPT_LEN] = entry_bytes(L, e, site)
                mm[q:q + 7] = bytes(_encode_call(e["gw"])) if site == i else EMPTY_CALL
            else:      # unverändert übernommener Eintrag (z. B. Simplex), Site-Index neu setzen
                raw = bytearray(e[1])
                if raw[5:7] != b"\xff\xff":
                    raw[5:7] = i.to_bytes(2, "big")
                mm[p:p + RPT_LEN] = bytes(raw); mm[q:q + 7] = e[2]
        else:
            mm[p:p + RPT_LEN] = EMPTY_ENTRY; mm[q:q + 7] = EMPTY_CALL
    starts = []; idx = 0
    for _, ents in groups:
        starts.append(idx); idx += len(ents)
    for g in range(L["ng"]):
        mm[L["gnames"] + 16 * g:L["gnames"] + 16 * (g + 1)] = ascii_pad(groups[g][0] if g < len(groups) else "", 16)
        mm[L["gstart"] + 2 * g:L["gstart"] + 2 * g + 2] = (starts[g] if g < len(groups) else 0xFFFF).to_bytes(2, "big")
    for i in range(L["n"]):
        mm[L["sort"] + 2 * i:L["sort"] + 2 * i + 2] = (i if i < len(flat) else 0xFFFF).to_bytes(2, "big")
    set_scan_bits(L, mm, len(flat))
    return starts


def set_scan_bits(L, mm, total):
    """Skip-Bitfeld passend zur Liste setzen: alle Einträge mit Frequenz scannen, Rest 0.
    Ohne das bleiben die Bits der alten (Werks-)Liste stehen und landen auf fremden Einträgen."""
    if L["scan"] is None:
        return
    for i in range(L["n"]):
        p = L["rpt"] + i * RPT_LEN
        on = i < total and mm[p:p + 3] != b"\x00\x00\x00"
        byte, bit = L["scan"] + i // 8, 1 << (i % 8)
        mm[byte] = (mm[byte] | bit) if on else (mm[byte] & ~bit & 0xFF)


def list_total(L, mm):
    return sum(1 for i in range(L["n"]) if struct.unpack(">H", mm[L["sort"] + 2 * i:L["sort"] + 2 * i + 2])[0] != 0xFFFF)


def save(radio, mm, out):
    radio._mmap[0] = bytes(mm)
    radio.save_mmap(out)
    with open(out, "rb") as f:          # #EtcData gross wie vom Gerät
        data = f.read()
    head, sep, rest = data.partition(b"\r\n#EtcData=")
    if sep:
        val, nl, tail = rest.partition(b"\r\n")
        with open(out, "wb") as f:
            f.write(head + sep + val.upper() + nl + tail)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out")
    ap.add_argument("--group", action="append", default=[], help="NAME=DATEI[#N+M] oder NAME=@keep")
    ap.add_argument("--no-dedupe", action="store_true")
    ap.add_argument("--csv")
    ap.add_argument("--groups", help='alte Form: "1:DV Schweiz,2:DV Deutschland"')
    ap.add_argument("--replace", action="append", default=[], help="alte Form: N=datei.csv")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--fix-skip", action="store_true",
                    help="nur das Skip-Bitfeld der vorhandenen Liste neu setzen (alle Funk-Einträge ohne SKIP)")
    a = ap.parse_args()

    L = model_of(a.base)
    radio = L["radio"](a.base)
    mm = bytearray(radio._mmap.get_packed())
    if a.dump:
        dump(L, mm); return 0
    if a.fix_skip:
        if L["scan"] is None:
            ap.error(f"--fix-skip: Skip-Bitfeld für {L['model']} nicht bekannt")
        if not a.out:
            ap.error("--fix-skip braucht --out")
        set_scan_bits(L, mm, list_total(L, mm))
        save(radio, mm, a.out)
        print(f"OK ({L['model']}): Skip-Bitfeld für {list_total(L, mm)} Einträge gesetzt → {a.out}")
        return 0
    if not a.out or not (a.group or a.csv):
        ap.error("--out und --group (oder --csv) nötig, oder --dump")

    errors = []
    spec = []   # [(name, kind, payload)]
    if a.group:
        for g in a.group:
            name, _, src = g.partition("=")
            if src == "@keep":
                spec.append((name.strip(), "keep", None))
            else:
                path, _, sel = src.partition("#")
                spec.append((name.strip(), "csv", (path, set(sel.split("+")) if sel else None)))
    else:
        rows = read_csv(a.csv)
        repl = {x.split("=", 1)[0].strip(): x.split("=", 1)[1].strip() for x in a.replace}
        if a.groups:
            old = [(g.split(":", 1)[0].strip(), g.split(":", 1)[1].strip()) for g in a.groups.split(",")]
        else:
            old = []
            for r in rows:
                if r["Group No"] not in [s[0] for s in old]:
                    old.append((r["Group No"], r["Group Name"]))
        for gno, gname in old:
            spec.append((gname, "csv", (repl[gno], None) if gno in repl else (a.csv, {gno})))

    base_groups = {n: (s, e) for n, s, e in groups_of(L, mm)}
    groups = []
    seen = set(); dropped = []
    for gname, kind, payload in spec:
        if kind == "keep":
            if gname not in base_groups:
                errors.append(f"Gruppe «{gname}» nicht im Basis-ICF"); continue
            s, e = base_groups[gname]
            ents = [("raw", bytes(mm[L["rpt"] + i * RPT_LEN:L["rpt"] + (i + 1) * RPT_LEN]),
                     bytes(mm[L["rptcall"] + i * 7:L["rptcall"] + (i + 1) * 7])) for i in range(s, e)]
        else:
            path, sel = payload
            rows = [r for r in read_csv(path) if sel is None or r["Group No"] in sel]
            ents = build_entries(L, rows, errors, os.path.basename(path))
            ents.sort(key=lambda e: (e["rpt"], e["freq"]))
            if a.group and not a.no_dedupe:
                keep = []
                for e in ents:
                    k = e["rpt"]
                    if k in seen:
                        dropped.append(f"{e['rpt']} {e['freq']:.4f} in «{gname}» (schon früher)")
                    else:
                        seen.add(k); keep.append(e)
                ents = keep
        groups.append((gname, ents))

    total = sum(len(e) for _, e in groups)
    if len(groups) > L["ng"]:
        errors.append(f"{len(groups)} Gruppen > {L['ng']}")
    if total > L["n"]:
        errors.append(f"{total} Einträge > {L['n']}")
    fatal = [e for e in errors if "übersprungen" not in e]
    if errors:
        print("Hinweise:", *errors, sep="\n  ")
    if dropped:
        print(f"Doppelte weggelassen: {len(dropped)}", *dropped[:30], sep="\n  ")
    if fatal:
        print("FEHLER – nichts geschrieben"); return 1

    starts = write_list(L, mm, groups)
    save(radio, mm, a.out)
    print(f"OK ({L['model']}): {total} Repeater in {len(groups)} Gruppen → {a.out}")
    for (gname, ents), s in zip(groups, starts):
        print(f"   {gname:<16} {len(ents):3d}  ab Index {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
