# GrowthLedger

## Deutsch

GrowthLedger ist eine lokale Python-3-Terminalanwendung zur Verwaltung und Analyse eines ETF-Sparplans. Phase 1 importiert Trade-Republic-CSV-Dateien, erfasst manuelle Transaktionen, erstellt Berichte und Prognosen, zeichnet ASCII-Diagramme und exportiert Tabellen. Sie verwendet ausschließlich die Python-Standardbibliothek, `Decimal` für Finanzwerte und **keinen Internetzugriff**.

> GrowthLedger ist ein Rechen- und Dokumentationswerkzeug, keine Finanzberatung. Prognosen sind keine Renditegarantie. Märkte schwanken und Verluste sind möglich.

### Voraussetzungen und Einrichtung

- Python 3.10 oder neuer
- Linux-Terminal; keine externen Pakete

Nach dem Klonen ist keine Installation nötig:

```bash
python3 growthledger.py --help
python3 growthledger.py sample-data
python3 growthledger.py list
python3 growthledger.py report
```

Beim ersten Zugriff entstehen `data/transactions.csv` und `data/config.json` automatisch. Mit der globalen Option `--data-dir PFAD` lässt sich ein anderes Datenverzeichnis verwenden. Die lokale Konfiguration enthält nur Phase-2-Metadaten wie ETF-Name, ISIN, Ticker und Börsenplatz; `config.example.json` ist die Vorlage.

### Projektstruktur

```text
growthledger.py                  Modell, Speicherung, Import, Berechnung und CLI
data/transactions.csv           private lokale Daten; automatisch erzeugt
data/config.json                lokale Konfiguration; automatisch erzeugt
export/                         lokale Exporte
examples/trade_republic_sample.csv  anonymisierte Importdatei
tests/test_growthledger.py      unittest-Suite ohne Netzwerkzugriff
config.example.json             Konfigurationsvorlage ohne Geheimnisse
```

Der Ein-Datei-Aufbau ist logisch in Modell, Speicherung, Import, Berechnung, Prognose, Diagramme, Export, CLI und Kursversorgung getrennt. Er kann später ohne Änderung der Berechnungslogik in Module aufgeteilt werden.

### CLI-Befehle

Manuell erfassen; wenn keine Parameter angegeben werden, fragt das Programm interaktiv:

```bash
python3 growthledger.py add
python3 growthledger.py add --date 2026-01-01 --amount 25 --buy-price 100 --market-price 102
python3 growthledger.py add --date 2026-01-01 --transaction-type etf_buy \
  --amount 25 --buy-price 100 --shares 0.25 --name "Beispiel ETF" \
  --identifier IE00B4L5Y983 --currency EUR
```

Eine angegebene tatsächliche Stückzahl hat Vorrang. Nur wenn sie bei einem Kauf fehlt, berechnet GrowthLedger `shares = amount / buy_price`; bei einem Verkauf entsprechend mit `sell_price`. Manuelle Kurse erhalten `price_source=manual`.

Anzeigen und berichten:

```bash
python3 growthledger.py list
python3 growthledger.py report
```

`list` zeigt keine Namen von Gegenparteien oder IBANs. `report` zeigt Zahlungsströme, Käufe, Verkäufe, Bestand, gewichteten Kaufkurs, Gebühren, Steuern, Dividenden, Marktwert und vereinfachte Rendite. Fehlt für eine aktive Position ein `market_price`, wird kein Depotwert vorgetäuscht.

Prognosen und Diagramme:

```bash
python3 growthledger.py forecast --monthly 25 --years 20 --return 5
python3 growthledger.py forecast --monthly 25 --years 20 --returns 3 5 7
python3 growthledger.py forecast --monthly 25 --years 20 --return 5 --start-value 1000
python3 growthledger.py chart
python3 growthledger.py chart --monthly 50 --years 15 --return 6
```

`forecast` verwendet standardmäßig den berechenbaren aktuellen Depotwert als Startwert; `--start-value` überschreibt ihn. `chart` zeigt kumulierte Käufe, verfügbare historische Depotwerte, Investition gegen Depotwert und ein Prognoseszenario.

Export und Beispieldaten:

```bash
python3 growthledger.py export --output export/growthledger.csv
python3 growthledger.py sample-data
```

Beispieldaten sind klar anonymisiert und werden nicht erneut eingespielt oder über bestehende Daten geschrieben.

### Trade-Republic-Import

```bash
python3 growthledger.py import-trade-republic --file traderepublic.csv
python3 growthledger.py import-trade-republic --file traderepublic.csv --preview
python3 growthledger.py import-trade-republic --file traderepublic.csv --dry-run
python3 growthledger.py import-trade-republic --file traderepublic.csv --skip-duplicates --verbose
```

`--preview` prüft und zeigt erkannte Datensätze, `--dry-run` prüft den gesamten Import; beide verändern die Daten nicht. Standardmäßig bricht eine bekannte oder innerhalb der Datei doppelte `transaction_id` den kompletten Import ab. `--skip-duplicates` überspringt sie. Ungültige Zeilen führen nie zu einem Teilimport; erst nach vollständiger Prüfung wird die Zieldatei atomar ersetzt.

Unterstützt werden UTF-8 und UTF-8 mit BOM, leere Felder sowie zusätzliche Spalten. Pflichtspalten sind `date`, `category`, `type` und `transaction_id`. Erwartete Felder sind:

```text
datetime,date,account_type,category,type,asset_class,name,symbol,shares,price,
amount,fee,tax,currency,original_amount,original_currency,fx_rate,description,
transaction_id,counterparty_name,counterparty_iban,payment_reference,mcc_code
```

Gegenpartei, IBAN, Zahlungsreferenz und MCC werden nicht gespeichert oder ausgegeben. Eine vollständige anonymisierte Datei liegt unter `examples/`.

#### Fachliche Zuordnung

- `CASH / CUSTOMER_INPAYMENT` ist eine Einzahlung auf das Verrechnungskonto (`cash_deposit`), kein Wertpapierkauf. Sie erhöht nicht den ETF-Kaufbetrag.
- `TRADING / BUY / FUND` mit Kennung, `shares` und `price` ist ein ETF-Kauf. Broker-Stückzahl und Ausführungskurs werden unverändert übernommen.
- `TRADING / SELL` ist ein Verkauf und reduziert den Bestand.
- Eindeutige Dividenden, Gebühren und Steuern werden getrennt erfasst. Unklare Fälle werden als `unknown` gespeichert, nicht geraten.
- Das Trade-Republic-Feld `symbol` kann eine ISIN wie `IE00B4L5Y983` enthalten; gültige ISINs werden zusätzlich im ISIN-Feld gespeichert.
- Ist `amount` vorhanden, gilt `amount_source=csv`. Fehlt er bei Kauf oder Verkauf, wird exakt `shares * price` mit `Decimal` berechnet und `amount_source=calculated` gesetzt.

`buy_price` beziehungsweise `sell_price` ist der tatsächliche Broker-Ausführungskurs. `market_price` ist ausschließlich ein manueller Bewertungs-, Stichtags- oder Monatsendkurs. Ein Marktpreis überschreibt nie den Kaufkurs. Automatische Marktpreise gibt es in Phase 1 nicht.

### Berechnungen

```text
Bestand = Summe gekaufter Anteile - Summe verkaufter Anteile
Gewichteter Kaufkurs = Summe(shares × buy_price) / Summe gekaufter shares
Depotwert je Position = Bestand × letzter vorhandener market_price
Vereinfachter Gewinn/Verlust = Depotwert + Verkaufserlöse + Dividenden
                               - Kaufbeträge - Gebühren - Steuern
Vereinfachte Rendite = Gewinn/Verlust / (Kaufbeträge + Gebühren + Steuern) × 100
```

Kontoeinzahlungen werden separat berichtet und nie zusätzlich als investierter ETF-Betrag gezählt. Verkäufe reduzieren Stückzahlen und ihre Erlöse fließen in die vereinfachte Gesamtbetrachtung ein. Gebühren und Steuern mindern, Dividenden erhöhen sie. Ohne steuerliche Loszuordnung kann GrowthLedger realisierte und unrealisierte Gewinne nicht belastbar trennen; die Anzeige vermeidet diese falsche Genauigkeit. Bei mehreren Währungen findet keine Umrechnung statt.

Für Prognosen gilt die effektive Monatsrendite

```text
monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
```

Der Startwert verzinst sich monatlich; die Sparrate wird jeweils **am Monatsende** hinzugefügt. Angezeigt werden kumulierte Einzahlungen, Endwert und modellierter Wertzuwachs pro Jahr und Szenario.

### Speicherung und Exportformat

Transaktionen werden als UTF-8-CSV mit allen Modellfeldern in `data/transactions.csv` gespeichert. Schreiben erfolgt über eine temporäre Datei und atomaren Austausch. Dezimalwerte werden ohne unnötige Rundung gespeichert.

Der Benutzerexport ist eine UTF-8-CSV **mit BOM und Semikolon als Trennzeichen** für Excel und ONLYOFFICE. Spalten: Datum, Transaktionstyp, ETF-Name, ISIN oder Symbol, Stückzahl, Kaufkurs, Verkaufskurs, Marktpreis, Betrag, Herkunft des Betrags, Gebühren, Steuern, Währung, Datenquelle, Kursquelle und `transaction_id`.

### Datenschutz

Broker-CSV-Dateien und `data/` enthalten sensible Finanzdaten. Sie gehören nicht in öffentliche Repositories oder unverschlüsselte Freigaben. `.gitignore` schließt Daten, Exporte, beliebige CSV/JSON, `.env`, Bytecode und Caches aus; nur die anonymisierte Beispieldatei und Konfigurationsvorlage sind freigegeben. GrowthLedger speichert weder Gegenpartei noch IBAN und niemals API-Schlüssel oder Passwörter.

### Tests und Mitwirkung

```bash
python3 -m unittest discover -v
python3 -m py_compile growthledger.py
```

Beiträge sollten Standardbibliothek und `Decimal` beibehalten, anonymisierte Tests ergänzen, keinen Netzwerkzugriff in Phase 1 einführen und `python3 growthledger.py --help` funktionsfähig halten. Fehlerberichte dürfen keine echten Finanzdaten enthalten.

### Roadmap: Phase 2 – Automatischer Kursabruf

Phase 1 definiert nur die abstrakte, dokumentierte `PriceProvider`-Schnittstelle und Felder für Ticker, ISIN, Börsenplatz, Kursquelle, Kursdatum, Abrufzeitpunkt und Erfassungsart. Phase 2 kann Netzwerk-Provider, Tages-/Monatsendkurse und einen lokalen Cache ergänzen. API-Schlüssel sollen dann ausschließlich aus Umgebungsvariablen kommen; Netzwerk- und Anbieterfehler müssen sicher behandelt werden. Broker-Kaufkurse bleiben unveränderlich und abgerufene Werte werden nur als `market_price` gespeichert. **Phase 1 ruft keine Kurse automatisch ab.**

### Lizenz

MIT License, Copyright © 2026 GrowthLedger Contributors. Siehe `LICENSE`.

---

## English

GrowthLedger is a local Python 3 terminal application for managing and analysing an ETF savings plan. Phase 1 imports Trade Republic CSV files, records manual transactions, creates reports and forecasts, draws ASCII charts, and exports tables. It uses only the Python standard library, `Decimal` for financial values, and **no internet access**.

> GrowthLedger is a calculation and record-keeping tool, not financial advice. Forecasts are not return guarantees. Markets fluctuate and losses are possible.

### Requirements and setup

- Python 3.10 or newer
- Linux terminal; no third-party packages

No installation is required after cloning:

```bash
python3 growthledger.py --help
python3 growthledger.py sample-data
python3 growthledger.py list
python3 growthledger.py report
```

On first access, `data/transactions.csv` and `data/config.json` are created automatically. The global `--data-dir PATH` option selects another data directory. The local configuration contains only Phase 2 metadata such as ETF name, ISIN, ticker, and exchange; `config.example.json` is its template.

### Project structure

```text
growthledger.py                  model, storage, import, calculations, and CLI
data/transactions.csv           private local data; created automatically
data/config.json                local configuration; created automatically
export/                         local exports
examples/trade_republic_sample.csv  anonymised import file
tests/test_growthledger.py      offline unittest suite
config.example.json             secret-free configuration template
```

The single-file implementation is logically separated into model, storage, import, calculations, forecast, charts, export, CLI, and price supply. It can later be split into modules without changing calculation logic.

### CLI commands

Add data manually; when no parameters are supplied, the application prompts interactively:

```bash
python3 growthledger.py add
python3 growthledger.py add --date 2026-01-01 --amount 25 --buy-price 100 --market-price 102
python3 growthledger.py add --date 2026-01-01 --transaction-type etf_buy \
  --amount 25 --buy-price 100 --shares 0.25 --name "Sample ETF" \
  --identifier IE00B4L5Y983 --currency EUR
```

An explicitly supplied actual share count takes priority. Only when it is missing for a purchase does GrowthLedger calculate `shares = amount / buy_price`; a sale uses `sell_price` correspondingly. Manual prices receive `price_source=manual`.

List and report:

```bash
python3 growthledger.py list
python3 growthledger.py report
```

`list` never shows counterparty names or IBANs. `report` shows cash flows, purchases, sales, holdings, weighted purchase price, fees, taxes, dividends, market value, and simplified return. If an active position has no `market_price`, no portfolio value is fabricated.

Forecasts and charts:

```bash
python3 growthledger.py forecast --monthly 25 --years 20 --return 5
python3 growthledger.py forecast --monthly 25 --years 20 --returns 3 5 7
python3 growthledger.py forecast --monthly 25 --years 20 --return 5 --start-value 1000
python3 growthledger.py chart
python3 growthledger.py chart --monthly 50 --years 15 --return 6
```

`forecast` uses the calculable current portfolio value as its default starting value; `--start-value` overrides it. `chart` shows cumulative purchases, available historical portfolio values, investment versus portfolio value, and a forecast scenario.

Export and sample data:

```bash
python3 growthledger.py export --output export/growthledger.csv
python3 growthledger.py sample-data
```

Sample records are clearly anonymised and are neither inserted twice nor written over existing data.

### Trade Republic import

```bash
python3 growthledger.py import-trade-republic --file traderepublic.csv
python3 growthledger.py import-trade-republic --file traderepublic.csv --preview
python3 growthledger.py import-trade-republic --file traderepublic.csv --dry-run
python3 growthledger.py import-trade-republic --file traderepublic.csv --skip-duplicates --verbose
```

`--preview` validates and displays recognised records; `--dry-run` validates the entire import. Neither modifies data. By default, a known or file-internal duplicate `transaction_id` aborts the entire import. `--skip-duplicates` skips it. Invalid rows never cause a partial import; only after full validation is the target file replaced atomically.

UTF-8 and UTF-8 with BOM, empty fields, and additional columns are supported. Required columns are `date`, `category`, `type`, and `transaction_id`. Expected fields are:

```text
datetime,date,account_type,category,type,asset_class,name,symbol,shares,price,
amount,fee,tax,currency,original_amount,original_currency,fx_rate,description,
transaction_id,counterparty_name,counterparty_iban,payment_reference,mcc_code
```

Counterparty, IBAN, payment reference, and MCC are neither stored nor displayed. A complete anonymised file is provided under `examples/`.

#### Business classification

- `CASH / CUSTOMER_INPAYMENT` is a settlement-account deposit (`cash_deposit`), not a security purchase. It does not increase the ETF purchase total.
- `TRADING / BUY / FUND` with an identifier, `shares`, and `price` is an ETF purchase. Broker share count and execution price are preserved exactly.
- `TRADING / SELL` is a sale and reduces holdings.
- Unambiguous dividends, fees, and taxes are recorded separately. Ambiguous cases are stored as `unknown`, never guessed.
- Trade Republic's `symbol` field may contain an ISIN such as `IE00B4L5Y983`; valid ISINs are also stored in the ISIN field.
- If `amount` is present, `amount_source=csv`. If it is absent for a purchase or sale, exact `shares * price` is calculated with `Decimal` and `amount_source=calculated` is stored.

`buy_price` or `sell_price` is the actual broker execution price. `market_price` is exclusively a manual valuation, cut-off-date, or month-end price. A market price never overwrites a purchase price. Phase 1 has no automatic market prices.

### Calculations

```text
Holdings = sum of purchased shares - sum of sold shares
Weighted purchase price = sum(shares × buy_price) / sum of purchased shares
Portfolio value per position = holdings × latest available market_price
Simplified profit/loss = portfolio value + sale proceeds + dividends
                         - purchase amounts - fees - taxes
Simplified return = profit/loss / (purchase amounts + fees + taxes) × 100
```

Cash deposits are reported separately and never counted again as invested ETF capital. Sales reduce shares and their proceeds enter the simplified total view. Fees and taxes reduce it; dividends increase it. Without tax-lot assignment, GrowthLedger cannot reliably separate realised and unrealised gains; the display avoids such false precision. No currency conversion is performed for multiple currencies.

Forecasts use the effective monthly rate:

```text
monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
```

The starting value compounds monthly; the savings contribution is added at the **end of each month**. Cumulative contributions, final value, and modelled growth are displayed for every year and scenario.

### Storage and export format

Transactions are stored as UTF-8 CSV with all model fields in `data/transactions.csv`. Writes use a temporary file followed by atomic replacement. Decimal values are stored without premature rounding.

The user export is a UTF-8 CSV **with BOM and semicolon delimiter** for Excel and ONLYOFFICE. Columns: date, transaction type, ETF name, ISIN or symbol, shares, purchase price, sale price, market price, amount, amount origin, fees, taxes, currency, data source, price source, and `transaction_id`.

### Privacy

Broker CSV files and `data/` contain sensitive financial information. Do not put them in public repositories or unencrypted shares. `.gitignore` excludes data, exports, arbitrary CSV/JSON, `.env`, bytecode, and caches; only the anonymised sample and configuration template are allowed. GrowthLedger stores neither counterparties nor IBANs, and never API keys or passwords.

### Tests and contributing

```bash
python3 -m unittest discover -v
python3 -m py_compile growthledger.py
```

Contributions should retain standard-library-only operation and `Decimal`, add anonymised tests, introduce no Phase 1 networking, and keep `python3 growthledger.py --help` working. Bug reports must not contain real financial data.

### Roadmap: Phase 2 – Automatic price retrieval

Phase 1 defines only the abstract, documented `PriceProvider` interface and fields for ticker, ISIN, exchange, price source, price date, retrieval timestamp, and capture type. Phase 2 can add network providers, daily/month-end prices, and a local cache. API keys must then come exclusively from environment variables; network and provider failures must be handled safely. Broker purchase prices remain immutable and fetched values are stored only as `market_price`. **Phase 1 performs no automatic price retrieval.**

### License

MIT License, Copyright © 2026 GrowthLedger Contributors. See `LICENSE`.
