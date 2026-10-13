# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Chris, HB9HJI – https://www.funkwelt.net
# Teil von icom-icf-tools. Braucht CHIRP wie build_rptlist.py (chirp-src/ oder CHIRP_SRC).
#   python3 -m unittest discover tests
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
try:
    import build_rptlist as br
except ImportError as exc:      # CHIRP oder pyserial fehlt
    raise unittest.SkipTest(f"CHIRP nicht verfügbar: {exc}")


def entry(call, mod, freq, lat=47.5, lon=9.3):
    return dict(call=call, mod=mod, rpt=f"{call:<7}{mod}", gw=f"{call:<7}G", freq=freq, off=0.6 if freq < 200 else 7.6,
                dup="DUP-", pos="Approximate", name=call, sub="", lat=lat, lon=lon, utc="+1:00")


def site(L, mm, i):
    p = L["rpt"] + i * br.RPT_LEN
    return int.from_bytes(mm[p + 5:p + 7], "big")


def gw(L, mm, i):
    return br._decode_call(list(mm[L["rptcall"] + i * 7:L["rptcall"] + (i + 1) * 7]))


class KeepTest(unittest.TestCase):
    """@keep: Standortverweise und Gateway-Call, Schlüssel für die Deduplizierung."""

    def base(self, L):
        mm = bytearray(0x1A000)
        # Gruppe 1: HB9AA C/B am selben Standort (Kopf = Index 0), Gruppe 2: HB9BB B
        br.write_list(L, mm, [("Eins", [entry("HB9AA", "C", 145.6), entry("HB9AA", "B", 439.4)]),
                              ("Zwei", [entry("HB9BB", "B", 439.1, lat=46.9)])])
        return mm

    def test_keep_all_is_identical(self):
        for L in br.LAYOUTS.values():
            mm = self.base(L)
            out = bytearray(mm)
            groups = [(n, br.kept_entries(L, mm, s, e)) for n, s, e in br.groups_of(L, mm)]
            br.write_list(L, out, groups)
            self.assertEqual(out, mm, L["model"])

    def test_keep_keeps_site_reference(self):
        for L in br.LAYOUTS.values():
            mm = self.base(L)
            out = bytearray(mm)
            br.write_list(L, out, [("Zwei", br.kept_entries(L, mm, 2, 3)), ("Eins", br.kept_entries(L, mm, 0, 2))])
            self.assertEqual([site(L, out, i) for i in range(3)], [0, 1, 1], L["model"])
            self.assertEqual([gw(L, out, i).strip() for i in range(3)], ["HB9BB  G", "HB9AA  G", ""], L["model"])

    def test_keep_without_site_head_takes_gateway(self):
        for L in br.LAYOUTS.values():
            mm = self.base(L)
            out = bytearray(mm)
            br.write_list(L, out, [("B", br.kept_entries(L, mm, 1, 2))])    # nur HB9AA B, Kopf HB9AA C fehlt
            self.assertEqual(site(L, out, 0), 0, L["model"])
            self.assertEqual(gw(L, out, 0), "HB9AA  G", L["model"])

    def test_raw_key_matches_csv_key(self):
        L = br.LAYOUTS["33220001"]
        mm = self.base(L)
        keys = [br.raw_key(x[1]) for x in br.kept_entries(L, mm, 0, 3)]
        self.assertEqual(keys, ["HB9AA  C", "HB9AA  B", "HB9BB  B"])
        self.assertEqual(br.raw_key(br.EMPTY_ENTRY), "")


if __name__ == "__main__":
    unittest.main()
