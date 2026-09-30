# Icom ICF-Cloning-File – Grundlagen

Ein `.icf` ist ein Textfile mit CRLF-Zeilenenden:

```
33900001            ← Modell-ID (hier ID-51 Original)
#Comment=
#MapRev=1
#EtcData=1C0011     ← CS-51 und das Gerät schreiben Grossbuchstaben
0000000020015739…   ← Datenzeilen: Adresse (8 Hex) + Länge (2 Hex, hier 0x20) + Daten (Hex)
…
#CD=9D896A75…       ← Prüfsumme über den Inhalt (32 Hex), schreibt CHIRP selbst
```

Die Datenzeilen ergeben zusammen das komplette Speicherabbild des Geräts. CHIRP
(`chirp.drivers.icf`) liest und schreibt das Format; `tools/build_icf.py` und
`tools/build_rptlist.py` nutzen dafür CHIRP.

Beobachtete Modell-IDs: ID-51 `33900001`, ID-52E `38670001`, IC-705 `40750001`,
IC-9700 `39130001`, ID-5100 `34840001`.

## Stolpersteine beim Laden über die SD-Karte (ID-51)

- Ordner: `ID-51/Setting/`, Menü: MENU › SD Card › Load Setting › Datei › ALL.
- **Dateiname kurz halten** wie vom Gerät vergeben (`Set20260101_01.icf`, 14 Zeichen + Endung). Ein längerer Name wurde vom Gerät nicht angezeigt; die genaue Grenze ist nicht ausgetestet.
- macOS legt auf FAT-Karten `._Dateiname` an; das Gerät listet diese und meldet beim Laden
  «Data error». Abhilfe: `dot_clean -m /Volumes/<Kartenname>`.
- CHIRP schreibt `#EtcData` klein; `build_icf.py` korrigiert das auf Grossbuchstaben wie CS-51.
- Immer ein vom Gerät selbst gespeichertes ICF als Basis nehmen (MY CALL, Einstellungen bleiben).

## Unterstützung durch CHIRP (geprüfter Stand: kk7ds/chirp, Commit b28df6b vom 18.09.2026)

| Gerät | ICF-Datei in CHIRP | Alternative |
|---|---|---|
| ID-51 (Original) | ja (`id51.py`), Repeaterliste nein → `build_rptlist.py` | – |
| ID-5100 | ja (`id5100.py`) | Repeaterliste per CSV |
| IC-9700 | nein (nur live über CI-V/USB) | Repeaterliste per CSV |
| IC-705 | nein (auch kein Live-Treiber im geprüften Stand) | Repeaterliste und Speicherkanäle per CSV |
| ID-52 | nein | Repeaterliste und Speicherkanäle per CSV |
