#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Chris, HB9HJI – https://www.funkwelt.net
# Teil von icom-icf-tools. Nutzt CHIRP (https://github.com/kk7ds/chirp, GPLv3).
"""
build_icf.py – Erzeugt ein Icom-Cloning-File (.icf) aus einer Kanalliste (CSV).
Unterstützt: ID-51 (Original) und ID-31 (Original, am Gerät getestet). Modell wird erkannt.

Basis ist immer ein Original-ICF des Zielgeräts (MY CALL, Einstellungen,
D-STAR-Repeaterliste bleiben unangetastet). Nur die 500 Speicherkanäle und
die Banknamen werden aus der CSV neu geschrieben.

Aufruf:
    python3 build_icf.py --base Original.icf \
                         --csv  examples/kanaele.csv \
                         --banks examples/banken.csv \
                         --out  Set20260101_02.icf

    --mycall CALL[/TAG],...   MY CALL 1–6 setzen, z. B. HB9XYZ oder HB9XYZ/ID51,HB9ABC
                      (nicht genannte Plätze werden geleert)
    --keep-existing   vorhandene Kanäle behalten, CSV nur drüberlegen
                      (Standard: alle 500 Kanäle vorher leeren)
    --dump            Kanäle eines ICF als CSV auf stdout ausgeben

CSV-Spalten (Kopfzeile Pflicht, Reihenfolge egal, Trenner , oder ; wird erkannt):
    Ch        Kanalnummer 0–499 (leer = nächste freie)
    Name      max. 16 Zeichen ASCII
    RX        Empfangsfrequenz in MHz, z. B. 439.325
    Shift     +, - oder leer (Simplex)
    Offset    Ablage in MHz; leer = 7.6 (70 cm) bzw. 0.6 (2 m)
    Mode      FM | NFM | AM | DV
    Tone      leer | Tone | TSQL | DTCS | TSQL-R | DTCS-R
    RTone     CTCSS Sendeton in Hz, z. B. 88.5 (Standard 88.5)
    CTone     CTCSS Empfangston (Standard = RTone)
    DTCS      DCS-Code (Standard 023)
    URCALL    D-STAR UR (Standard CQCQCQ)
    RPT1      D-STAR RPT1, z. B. "HB9EAS B"
    RPT2      D-STAR RPT2, z. B. "HB9EAS G"
    Bank      Bank-Buchstabe A–Z (leer = keine Bank)
    Skip      leer | S | P
    Step      Tuning-Step kHz (Standard 12.5)

banken.csv (optional):  Bank,Name   →  A,Ostschweiz
"""
import argparse
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# CHIRP-Quellen: $CHIRP_SRC, sonst chirp-src/ im Repo-Hauptordner oder neben dem Script
for CHIRP in (os.environ.get("CHIRP_SRC", ""), os.path.join(HERE, "..", "chirp-src"), os.path.join(HERE, "chirp-src")):
    if CHIRP and os.path.isdir(CHIRP):
        sys.path.insert(0, os.path.abspath(CHIRP))
        break

import logging  # noqa: E402
logging.basicConfig(level=logging.ERROR)
from chirp import chirp_common, directory  # noqa: E402
directory.import_drivers()
from chirp.drivers import id51, id31  # noqa: E402


class ID51Radio(id51.ID51Radio):
    """ID-51 (Original) – Bank-Byte wie vom Gerät geschrieben.

    CHIRPs ID-51-Treiber erbt vom ID-31 (0xFF = keine Bank). Ein vom ID-51
    selbst gespeichertes ICF nutzt aber das 5-Bit-Schema des ID-51 Plus:
      Bits 0-4 = Bank (0-25 = A-Z, 0x1F = keine Bank), Bits 5-7 = unbekannt.
    Beobachtet im Original-File:  leerer Kanal 0x9F, Kanal ohne Bank 0x1F,
    Kanal in Bank A 0x20.  Wir schreiben exakt diese Muster.
    """

    def _get_bank(self, loc):
        v = int(self._memobj.banks[loc].bank) & 0x1F
        return None if v == 0x1F else v

    def _set_bank(self, loc, bank):
        _b = self._memobj.banks[loc]
        if bank is None:
            _b.bank = 0x1F
        else:
            _b.bank = 0x20 | int(bank)

    def set_mycalls(self, calls):
        """calls: Liste bis 6 Einträge 'CALL' oder 'CALL/TAG'; Rest wird geleert."""
        if len(calls) > 6:
            raise ValueError("maximal 6 MY CALL")
        for i in range(6):
            call, tag = "", ""
            if i < len(calls):
                call, _, tag = calls[i].upper().partition("/")
            if len(call) > 8 or len(tag) > 4:
                raise ValueError(f"MY CALL «{calls[i]}»: Call max. 8, Tag max. 4 Zeichen")
            self._memobj.mycall[i].call = call.ljust(8)
            self._memobj.mycall[i].tag = tag.ljust(4)

    def clear_memory(self, number):
        m = chirp_common.Memory()
        m.number = number
        m.empty = True
        self.set_memory(m)
        self._memobj.banks[number].bank = 0x9F   # wie ein nie benutzter Kanal
        self._memobj.banks[number].index = 0

class ID31Radio(id31.ID31Radio):
    """ID-31 (Original) – Bank-Byte wie CHIRP-Treiber und Werks-ICF: 0xFF = keine Bank, sonst 0-25.
    Am Gerät bestätigt."""

    set_mycalls = ID51Radio.set_mycalls

    def clear_memory(self, number):
        m = chirp_common.Memory()
        m.number = number
        m.empty = True
        self.set_memory(m)
        self._memobj.banks[number].bank = 0xFF   # wie im Werks-ICF
        self._memobj.banks[number].index = 0


MODELS = {"33900001": (ID51Radio, ("2m", "70cm")), "33220001": (ID31Radio, ("70cm",))}
BANDS = ("2m", "70cm")


def radio_class(path):
    """Modell aus der ersten Zeile des ICF erkennen."""
    with open(path, encoding="ascii", errors="replace") as f:
        mid = f.readline().strip()
    if mid not in MODELS:
        sys.exit(f"Modell-ID {mid} nicht unterstützt (bekannt: {', '.join(MODELS)})")
    global BANDS
    cls, BANDS = MODELS[mid]
    return cls


DEFAULT_OFFSET = {"2m": 0.6, "70cm": 7.6}
VALID_MODES = ["FM", "NFM", "AM", "DV"]
VALID_TMODES = ["", "Tone", "TSQL", "DTCS", "TSQL-R", "DTCS-R"]


def band(freq_hz):
    b = "2m" if 108e6 <= freq_hz <= 174e6 else "70cm" if 400e6 <= freq_hz <= 479e6 else None
    if b not in BANDS:
        raise ValueError(f"Frequenz {freq_hz/1e6:.4f} MHz ausserhalb des Geräts ({' / '.join(BANDS)})")
    return b


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        rows = list(csv.DictReader(f, dialect=dialect))
    # Spaltennamen normalisieren (case-insensitive, Whitespace weg)
    out = []
    for r in rows:
        out.append({(k or "").strip().lower(): (v or "").strip() for k, v in r.items()})
    return out


def g(row, key, default=""):
    return row.get(key.lower(), default) or default


def mem_from_row(row, number, errors):
    mode = g(row, "Mode", "FM").upper()
    if mode not in VALID_MODES:
        errors.append(f"Ch {number}: ungültiger Mode «{mode}»")
        mode = "FM"
    mem = chirp_common.DVMemory() if mode == "DV" else chirp_common.Memory()
    mem.number = number
    mem.name = g(row, "Name")[:16]
    try:
        mem.freq = int(round(float(g(row, "RX").replace(",", ".")) * 1e6))
        b = band(mem.freq)
    except ValueError as e:
        errors.append(f"Ch {number} «{mem.name}»: {e}")
        return None
    mem.mode = mode
    shift = g(row, "Shift")
    if shift in ("+", "-"):
        mem.duplex = shift
        off = g(row, "Offset")
        mem.offset = int(round((float(off.replace(",", ".")) if off else DEFAULT_OFFSET[b]) * 1e6))
    else:
        mem.duplex = ""
        mem.offset = 0
    tmode = g(row, "Tone")
    tmode = {"": "", "tone": "Tone", "tsql": "TSQL", "dtcs": "DTCS",
             "tsql-r": "TSQL-R", "dtcs-r": "DTCS-R"}.get(tmode.lower(), None)
    if tmode is None:
        errors.append(f"Ch {number} «{mem.name}»: ungültiger Tone-Modus «{g(row, 'Tone')}»")
        tmode = ""
    mem.tmode = tmode
    rtone = float(g(row, "RTone", "88.5").replace(",", "."))
    ctone = float(g(row, "CTone", str(rtone)).replace(",", "."))
    for t in (rtone, ctone):
        if t not in chirp_common.TONES:
            errors.append(f"Ch {number} «{mem.name}»: CTCSS {t} Hz nicht gültig")
    mem.rtone = rtone if rtone in chirp_common.TONES else 88.5
    mem.ctone = ctone if ctone in chirp_common.TONES else mem.rtone
    dtcs = int(g(row, "DTCS", "23"))
    mem.dtcs = dtcs if dtcs in chirp_common.DTCS_CODES else 23
    step = float(g(row, "Step", "12.5").replace(",", "."))
    mem.tuning_step = step if step in (5.0, 6.25, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0, 125.0, 200.0) else 12.5
    skip = g(row, "Skip").upper()
    mem.skip = skip if skip in ("S", "P") else ""
    if mode == "DV":
        mem.dv_urcall = g(row, "URCALL", "CQCQCQ").upper()[:8]
        mem.dv_rpt1call = g(row, "RPT1").upper()[:8]
        mem.dv_rpt2call = g(row, "RPT2").upper()[:8]
        mem.dv_code = 0
        for c in (mem.dv_rpt1call, mem.dv_rpt2call):
            if c and len(c) == 8 and c[7] not in "ABCDEFG ":
                errors.append(f"Ch {number} «{mem.name}»: RPT-Rufzeichen «{c}» – 8. Zeichen sollte Modul (A–G) sein")
    return mem


def fix_header(path):
    """CHIRP schreibt #EtcData klein (1c0011), CS-51/Gerät gross (1C0011) – angleichen."""
    with open(path, "rb") as f:
        data = f.read()
    head, sep, rest = data.partition(b"\r\n#EtcData=")
    if sep:
        val, nl, tail = rest.partition(b"\r\n")
        data = head + sep + val.upper() + nl + tail
        with open(path, "wb") as f:
            f.write(data)


def dump(radio):
    rf = radio.get_features()
    bm = radio.get_bank_model()
    w = csv.writer(sys.stdout)
    w.writerow(["Ch", "Name", "RX", "Shift", "Offset", "Mode", "Tone", "RTone", "CTone",
                "DTCS", "URCALL", "RPT1", "RPT2", "Bank", "Skip", "Step"])
    for i in range(rf.memory_bounds[0], rf.memory_bounds[1] + 1):
        m = radio.get_memory(i)
        if m.empty:
            continue
        maps = bm.get_memory_mappings(m)
        bank = chr(ord("A") + maps[0].index) if maps else ""
        w.writerow([i, m.name, f"{m.freq/1e6:.4f}", m.duplex,
                    f"{m.offset/1e6:.3f}" if m.duplex else "", m.mode, m.tmode,
                    m.rtone, m.ctone, f"{m.dtcs:03d}",
                    getattr(m, "dv_urcall", ""), getattr(m, "dv_rpt1call", ""),
                    getattr(m, "dv_rpt2call", ""), bank, m.skip, m.tuning_step])
    print("# Banken:", {chr(ord("A") + b.index): b.get_name() for b in bm.get_mappings() if b.get_name()}, file=sys.stderr)
    print("# MYCALL:", [c.strip() for c in radio.get_mycall_list() if c.strip()], file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="Original-ICF des Geräts")
    ap.add_argument("--csv", help="Kanalliste CSV")
    ap.add_argument("--banks", help="Banknamen CSV (Bank,Name)")
    ap.add_argument("--out", help="Ziel-ICF")
    ap.add_argument("--mycall", help="MY CALL 1-6, kommagetrennt, CALL oder CALL/TAG")
    ap.add_argument("--keep-existing", action="store_true")
    ap.add_argument("--dump", action="store_true", help="Kanäle des --base als CSV ausgeben")
    a = ap.parse_args()

    cls = radio_class(a.base)
    radio = cls(a.base)
    if a.dump:
        dump(radio)
        return 0
    if not (a.csv and a.out):
        ap.error("--csv und --out sind nötig (oder --dump)")

    rf = radio.get_features()
    lo, hi = rf.memory_bounds
    errors = []

    if a.mycall:
        try:
            radio.set_mycalls([c.strip() for c in a.mycall.split(",") if c.strip()])
        except ValueError as e:
            errors.append(str(e))

    if not a.keep_existing:
        for i in range(lo, hi + 1):
            radio.clear_memory(i)

    bm = radio.get_bank_model()
    bank_list = bm.get_mappings()
    if a.banks:
        for r in read_csv(a.banks):
            letter = g(r, "Bank").upper()
            if len(letter) == 1 and "A" <= letter <= "Z":
                bank_list[ord(letter) - 65].set_name(g(r, "Name")[:16])
            else:
                errors.append(f"banken.csv: ungültige Bank «{letter}»")

    rows = read_csv(a.csv)
    used = set()
    if a.keep_existing:
        used = {i for i in range(lo, hi + 1) if not radio.get_memory(i).empty}
    next_free = lo
    bank_index = {}
    written = 0
    for n, row in enumerate(rows, start=2):
        if not g(row, "RX"):
            continue  # Leerzeile / Kommentar
        ch = g(row, "Ch")
        if ch:
            number = int(ch)
            if not lo <= number <= hi:
                errors.append(f"Zeile {n}: Kanal {number} ausserhalb {lo}-{hi}")
                continue
            if number in used:
                errors.append(f"Zeile {n}: Kanal {number} doppelt belegt")
                continue
        else:
            while next_free in used:
                next_free += 1
            number = next_free
        mem = mem_from_row(row, number, errors)
        if mem is None:
            continue
        radio.set_memory(mem)
        used.add(number)
        written += 1
        bank = g(row, "Bank").upper()
        if bank:
            if len(bank) != 1 or not "A" <= bank <= "Z":
                errors.append(f"Zeile {n}: ungültige Bank «{bank}»")
            else:
                b = bank_list[ord(bank) - 65]
                bm.add_memory_to_mapping(mem, b)
                idx = bank_index.get(bank, 0)
                bm.set_memory_index(mem, b, idx)
                bank_index[bank] = idx + 1

    if errors:
        print("FEHLER – kein File geschrieben:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 1

    radio.save_mmap(a.out)
    fix_header(a.out)
    # Rücklesen zur Kontrolle
    check = cls(a.out)
    n_check = sum(1 for i in range(lo, hi + 1) if not check.get_memory(i).empty)
    print(f"OK: {written} Kanäle geschrieben, {n_check} beim Rücklesen gefunden → {a.out}")
    print("Banken:", ", ".join(f"{k}={v}" for k, v in sorted(bank_index.items())) or "keine")
    print("MY CALL:", [c.strip() for c in check.get_mycall_list() if c.strip()])
    return 0 if n_check == written else 2


if __name__ == "__main__":
    sys.exit(main())
