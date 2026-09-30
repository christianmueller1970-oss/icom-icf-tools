# Icom ID-51 (Original): Aufbau der D-STAR-Repeaterliste im ICF

Der Original-ID-51 hat im Gegensatz zum ID-51 Plus **keinen CSV-Import/-Export**. Die
DR-Repeaterliste kann nur über CS-51 (Windows, Kabel) oder direkt im Cloning-File (ICF)
geändert werden. Dieses Dokument beschreibt die Struktur, wie sie `tools/build_rptlist.py`
schreibt. Sie wurde aus drei Files abgeleitet:

- ein vom Gerät selbst gespeichertes ICF mit der Werksliste (725 Einträge)
- ein älteres ICF desselben Gerätetyps mit einer in CS-51 erstellten Liste (267 Einträge)
- ein ICF und ein CSV-Export eines ID-52 (bekannte Werte je Eintrag)

**Prüfung:** Der Writer reproduziert die 267 Einträge des CS-51-Files und alle
688 Werkseinträge mit Rufzeichen **byte-identisch**. Ein so erzeugtes ICF wurde am Gerät
geladen (MENU › SD Card › Load Setting) und im DR-Modus mit Relais-QSO getestet.

Modell-ID im ICF-Kopf: `33900001`. Speicherabbild: 0x1FB40 Byte. Alle Werte Big Endian.

## Repeater-Einträge

`repeaters[750]` ab **0xA8C0**, je **49 Byte**:

| Offset | Länge | Inhalt |
|---|---|---|
| 0 | 3 | Frequenz. Bit 23+22 gesetzt (`0xC00000`) = Einheit 6.25 kHz, sonst 5 kHz. Wert = `raw & 0x3FFFF` × Einheit |
| 3 | 2 | Ablage, gleiche Einheit wie die Frequenz |
| 5 | 2 | Site-Index = Index des ersten Eintrags desselben Standorts (gleiches Rufzeichen + Koordinaten) |
| 7 | 1 | Flags: `0x40` DUP−, `0x80` DUP+, `0x08` Position «Exact», `0x04` «Approximate» |
| 8 | 7 | Repeater-Rufzeichen, 8 Zeichen à 7 Bit gepackt (wie CHIRP `id31._encode_call`), Modul an Stelle 8 |
| 15 | 16 | Name, ASCII, mit Leerzeichen aufgefüllt |
| 31 | 8 | Sub-Name, ASCII |
| 39 | 4 | Breite: Grad (1 Byte), Minuten × 1000 (u16), `N`/`S` |
| 43 | 4 | Länge: Grad (1 Byte), Minuten × 1000 (u16), `E`/`W` |
| 47 | 2 | UTC-Offset in Minuten, signed; `0x7FFF` = kein Offset |

Leerer Eintrag (so im Werks-ICF):
`0000000000ffff00870664ca7263ce` + 24 × `0x20` + `0000004e000000457fff`

## Weitere Tabellen

| Adresse | Inhalt |
|---|---|
| **0x1384E** | `rptcall[750]` × 7 Byte: Gateway-Rufzeichen (gepackt). Nur beim **ersten** Eintrag eines Standorts gefüllt, sonst 8 Leerzeichen gepackt |
| **0x14CD0** | 25 Gruppennamen × 16 Zeichen ASCII |
| **0x19BDC** | 25 × u16: Startindex jeder Gruppe in `repeaters[]`, unbenutzt `0xFFFF`. Gruppen liegen lückenlos hintereinander |
| **0x19600** | 750 × u16: Sortierindex, bei uns Identität (0, 1, 2 …), unbenutzt `0xFFFF` |
| 0x19C0E | 250 Byte, gehört **nicht** zur Liste – nicht anfassen |

Limits: 750 Einträge, 25 Gruppen, nur 2 m / 70 cm.

## Unterschied zum ID-52

Im ID-52-ICF sind die Repeater-Einträge 50 Byte lang, und dieselben Flag-Bits stehen
um 2 nach rechts verschoben: `0x10` DUP−, `0x20` DUP+, `0x01` Approximate, `0x02` Exact.
Der ID-52 (und ID-51 Plus, IC-705, IC-9700, ID-5100) kann die Liste aber ohnehin per
CSV importieren – siehe `Icom-CSV-Formate.md`.

## Speicherkanäle ID-51: Bank-Byte

CHIRPs ID-51-Treiber erbt vom ID-31 (Bank `0xFF` = keine). Ein vom ID-51 gespeichertes ICF
nutzt aber ein 5-Bit-Feld: Bits 0–4 = Bank (0–25 = A–Z, `0x1F` = keine Bank), beobachtet
`0x9F` = nie benutzter Kanal, `0x1F` = Kanal ohne Bank, `0x20 | n` = Kanal in Bank n.
`tools/build_icf.py` schreibt genau diese Muster (am Gerät verifiziert).
6.25-kHz-Frequenzen in Speicherkanälen: CHIRP-Flag `0x200000` funktioniert am Gerät.
