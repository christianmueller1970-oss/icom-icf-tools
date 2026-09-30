# Icom-CSV-Formate für Repeaterliste und Speicherkanäle (SD-Karte)

Stand: Exporte aus den Geräten im September 2026. Alle Dateien UTF-8 **ohne BOM**, Zeilenende CRLF.
Trennzeichen und Dezimalzeichen hängen von der CSV-Einstellung im Gerät ab – am sichersten
ist, genau das Format zu schreiben, das das jeweilige Gerät selbst exportiert.

## Repeaterliste (`Csv/RptList/`)

| Gerät | Trenner / Dezimal (so exportiert von unseren Geräten) | Spalten |
|---|---|---|
| ID-52E | `,` / `.` | 17 |
| IC-705 | `;` / `,` | 17 |
| ID-5100 | `;` / `,` | 17 |
| IC-9700 | `;` / `,` | **18** – zusätzlich `Gateway IP Address` nach `Gateway Call Sign` |

Kapazität laut Hersteller: ID-5100 1500 Einträge in 50 Gruppen. Für die übrigen Geräte bitte
im Handbuch nachsehen – `make_device_lists.py` rechnet mit 2500 und bricht bei Überschreitung ab.

17 Spalten: `Group No, Group Name, Name, Sub Name, Repeater Call Sign, Gateway Call Sign,
Frequency, Dup, Offset, Mode, TONE, Repeater Tone, RPT1USE, Position, Latitude, Longitude, UTC Offset`

### Was das Gerät beim Import «korrigiert»

Ein ID-52E meldete nach dem Import *«Completed – some data was corrected»*. Der Vergleich
mit einem anschliessenden Export zeigte drei Anpassungen. Schreibt man die Werte gleich
so, ist der Export danach **byte-identisch** mit der Importdatei (am ID-52E und IC-705 geprüft):

1. **Koordinaten** werden auf Grad + Minuten mit 3 Nachkommastellen gerundet
   (47.495690 → 47.495683).
2. **DTCS** gibt es in der Repeaterliste nicht – `TONE` wird `OFF`, `Repeater Tone` `88.5Hz`.
   DTCS-Relais gehören in die Speicherkanäle.
3. **FM-Simplex** (Dup `OFF`): Das Gerät löscht `Repeater Call Sign`.

`tools/make_device_lists.py` macht das in der Funktion `normalize()`.

Weitere Beobachtungen:
- `UTC Offset` darf `--:--` sein (so exportiert das Gerät selbst).
- `Repeater Tone` hat bei DV/OFF den Platzhalter `88.5Hz`.
- Der Export des IC-9700 enthielt nur `DV`/`DD`-Einträge. Ob er FM in der Repeaterliste
  annimmt, ist noch nicht getestet.

## Speicherkanäle (`Csv/MemoryCh/`)

| Gerät | Trenner | Spalten |
|---|---|---|
| ID-52E | `,` | 20: `Group No, Group Name, CH No, Name, Frequency, Dup, Offset, TS, Mode, SKIP, TONE, Repeater Tone, TSQL Frequency, DTCS Code, DTCS Polarity, DV SQL, DV CSQL Code, Your Call Sign, RPT1 Call Sign, RPT2 Call Sign` |
| IC-705 | `;` | 38: wie oben ohne `TS/SKIP`, dafür `SEL, DATA, Filter`, plus Split-Block (`Split`, `Frequency(2)` …) |
| IC-9700, ID-5100 | – | auf unseren SD-Karten kein Ordner `Csv/MemoryCh` – Speicherkanäle dort über ICF/Programmiersoftware |

Hinweise aus der Praxis:
- `TONE` kennt u. a. `OFF`, `TONE`, `TSQL`, `TONE(T)/TSQL(R)`, `DTCS`.
- D-STAR-Kanäle ohne `RPT1/RPT2`: Ohne RPT1 im Kopf der Aussendung wiederholt ein D-STAR-Relais
  normalerweise nicht. Im DR-Modus fällt das nicht auf, weil das Gerät die Werte aus der
  Repeaterliste nimmt. (Nicht separat getestet – wir haben die Felder einfach gefüllt.)
- `DV SQL = DSQL` öffnet nur bei Rufen an das eigene Rufzeichen.
- Ein Import mit unveränderten Zeilen (byte-genau aus dem Export übernommen) plus neuen Zeilen
  lief an ID-52E und IC-705 durch; der Export danach war byte-identisch mit der Importdatei.

## Ablauf, der sich bewährt hat

1. Gerät: Export (Backup und Formatvorlage).
2. Datei erzeugen – exakt im Format des Exports.
3. Auf die SD nach `Csv/RptList/` bzw. `Csv/MemoryCh/`, am Mac danach `dot_clean -m /Volumes/<SD>`.
4. Gerät: Import.
5. Gerät: erneut Export und mit der Importdatei vergleichen (`cmp`).
