# icom-icf-tools

Werkzeuge und Dokumentation, um Icom-D-STAR-Geräte **ohne Windows und ohne Kabel** über die
SD-Karte zu programmieren: Speicherkanäle und DR-Repeaterliste für den Original-**ID-51**
direkt im ICF-Cloning-File, und importfertige Repeaterlisten-CSV für **ID-52, IC-705,
ID-5100 und IC-9700**.

*English summary:* Tools and notes for programming Icom D-STAR radios via SD card. Includes
a writer for the D-STAR repeater list of the original ID-51 (which has no CSV import) –
the memory layout is documented in `docs/ID-51_Repeaterliste.md` – and a generator for
device-specific repeater-list CSV files (ID-52, IC-705, ID-5100, IC-9700). GPLv3, uses CHIRP.

Hintergrund: [Ein ID-51, eine SD-Karte und keine Windows-Kiste](https://www.funkwelt.net/ein-id-51-eine-sd-karte-und-keine-windows-kiste-wie-ein-alter-d-star-handfunk-wieder-aktuell-wurde/) auf Funkwelt.net.

## Inhalt

| Datei | Zweck |
|---|---|
| `tools/build_icf.py` | ID-51: Speicherkanäle, Banknamen und MY CALL aus einer CSV in ein ICF schreiben (Basis: ICF vom eigenen Gerät) |
| `tools/build_rptlist.py` | ID-51: D-STAR-Repeaterliste (bis 750 Einträge, 25 Gruppen) aus Icom-CSV ins ICF schreiben; `--dump` zeigt die Liste eines ICF |
| `tools/make_device_lists.py` | Aus einer Master-Repeaterliste die Import-CSV für ID-52E, IC-705, ID-5100 und IC-9700 erzeugen – im jeweiligen Geräteformat und so normalisiert, dass der Import ohne «data was corrected» durchläuft |
| `docs/ID-51_Repeaterliste.md` | Speicherlayout der ID-51-Repeaterliste (reverse engineered, am Gerät verifiziert) |
| `docs/Icom-CSV-Formate.md` | CSV-Formate der Geräte, was das Gerät beim Import anpasst, bewährter Ablauf |
| `docs/ICF-Format.md` | ICF-Grundlagen, Stolpersteine auf der SD-Karte (Dateiname, macOS `._`-Dateien) |
| `examples/` | Beispiel-Kanalliste, Banknamen, Repeaterliste, Master |
| `LICENSE`, `LICENSE-docs.md` | GPLv3 für den Code, CC BY 4.0 für Doku und Beispiele |

## Installation (macOS / Linux)

```bash
git clone https://github.com/christianmueller1970-oss/icom-icf-tools.git
cd icom-icf-tools
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git clone https://github.com/kk7ds/chirp.git chirp-src      # nur für die ID-51-Tools
pip install future pyserial requests
```

Die ID-51-Tools finden CHIRP im Unterordner `chirp-src` oder über die Umgebungsvariable `CHIRP_SRC`.

## Beispiele

```bash
# ID-51: Kanäle eines ICF ansehen
python3 tools/build_icf.py --base MeinID51.icf --dump

# ID-51: Kanäle + Banken + MY CALL schreiben
python3 tools/build_icf.py --base MeinID51.icf --csv examples/kanaele.csv \
    --banks examples/banken.csv --mycall HB9XYZ --out Set20260101_02.icf

# ID-51: Repeaterliste ersetzen (Gruppen aus einem ID-52-Export übernehmen, Gruppe 1 ersetzen)
python3 tools/build_rptlist.py --base Set20260101_02.icf --csv Rpt_Export_ID52.csv \
    --groups "1:DV Schweiz,2:DV Deutschland" --replace 1=examples/repeater_dv_schweiz.csv \
    --out Set20260101_03.icf

# Repeaterlisten für ID-52E, IC-705, ID-5100, IC-9700
python3 tools/make_device_lists.py examples/master.csv out/
```

Ablauf am Gerät (ID-51): ICF auf die SD nach `ID-51/Setting/`, am Mac `dot_clean -m /Volumes/<SD>`,
dann MENU › SD Card › Load Setting. **Vorher immer ein eigenes Backup speichern** (Save Setting).

## Wichtig

- Immer ein ICF **des eigenen Geräts** als Basis verwenden und das Original aufbewahren.
- Getestet mit: ID-51 (Original, Modell `33900001`), ID-52E, IC-705 (Repeaterliste + Speicherkanäle
  per CSV). ID-5100 und IC-9700: Formate aus Geräte-Exporten, Import noch nicht getestet.
- Keine Gewähr – das Laden fremder Daten ins Gerät geschieht auf eigenes Risiko.
- Die Repeaterdaten in `examples/` sind Beispiele und keine gepflegte Relaisliste.

## Lizenz

- **Code** (`tools/`): GPL-3.0-or-later, siehe `LICENSE`. Die ID-51-Tools nutzen [CHIRP](https://github.com/kk7ds/chirp) (GPLv3).
- **Dokumentation** (`docs/`, dieses README) und **Beispieldaten** (`examples/`):
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.de), siehe `LICENSE-docs.md`. Frei verwendbar,
  auch in eigenen Projekten mit anderer Lizenz, mit Quellenangabe «icom-icf-tools, HB9HJI».

73 de Chris, HB9HJI – [funkwelt.net](https://www.funkwelt.net)
