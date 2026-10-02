# GrowthLedger

## Deutsch

GrowthLedger ist eine lokale Python-3-Terminalanwendung zur Verwaltung und Analyse eines ETF-Sparplans. Sie importiert Trade-Republic-CSV-Dateien, erfasst manuelle Transaktionen, erstellt Berichte und Prognosen, zeichnet ASCII-Diagramme und exportiert Tabellen. Phase 2 kann auf ausdrücklichen Befehl Marktpreise von Alpha Vantage oder Twelve Data abrufen. Die Anwendung verwendet ausschließlich die Python-Standardbibliothek und `Decimal` für Finanzwerte.

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

`buy_price` beziehungsweise `sell_price` ist der tatsächliche Broker-Ausführungskurs. `market_price` ist ausschließlich ein manueller oder automatisch abgerufener Bewertungs-, Stichtags- oder Monatsendkurs. Ein Marktpreis überschreibt nie den Kaufkurs.

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

### Roadmap: Phase 2 – Automatischer Kursabruf (umgesetzt)

Unterstützte Anbieter sind Alpha Vantage und Twelve Data. Lege den jeweiligen Schlüssel ausschließlich als Umgebungsvariable fest:

```bash
export ALPHA_VANTAGE_API_KEY="..."
python3 growthledger.py update-prices --provider alpha_vantage --symbol EUNL.DEX --history

export TWELVE_DATA_API_KEY="..."
python3 growthledger.py update-prices --provider twelve_data --symbol EUNL:XETR --history
```

`--symbol` ist der anbieterspezifische Ticker. Bei genau einer vorhandenen Position wird deren ISIN/Symbol automatisch zugeordnet; sonst ist zusätzlich `--asset-id IE00B4L5Y983` erforderlich. `--history` lädt standardmäßig fünf Jahre Historie und speichert Monatsendkurse; Alpha Vantage nutzt dafür seinen langfristigen Monatsendpunkt. Ohne diese Option wird nur der jüngste Kurs gespeichert. `--start`, `--end`, `--currency` und `--refresh` steuern Zeitraum, Fallback-Währung und Cache-Aktualisierung. Anbieter und Ticker können auch in `data/config.json` gesetzt werden.

Antworten werden ohne API-Schlüssel unter `data/cache/prices/` zwischengespeichert (aktuelle Kurse 15 Minuten, Historie 24 Stunden). API-, Netzwerk-, Symbol- und Ratenlimitfehler führen zu verständlichen Fehlermeldungen und verändern bestehende Transaktionen nicht. Automatische Datensätze erhalten `source=market_api`, `price_capture=automatic` und den Anbieter als `price_source`. Broker-Kaufkurse bleiben unverändert.

Nach mindestens zwei Marktpreisen über mindestens 30 Tage zeigt `chart` standardmäßig einen Vergleich aus annualisierter historischer Kurssteigerung (CAGR), 3 %, 5 % und 7 %. `forecast` verwendet ohne Renditeparameter denselben Szenarienvergleich. `--return` beziehungsweise `--returns` überschreibt diese Auswahl. Die Historie ist keine Vorhersage oder Garantie.

### Changelog

#### Phase 1 – Lokale Grundlage

- Lokale, deutschsprachige Terminalanwendung ausschließlich mit der Python-Standardbibliothek und `Decimal`.
- Sicherer Trade-Republic-CSV-Import mit Preview, Dry-run, Duplikaterkennung und atomarer Speicherung.
- Manuelle Erfassung von Einzahlungen, Auszahlungen, Käufen, Verkäufen, Dividenden, Gebühren und Steuern.
- Bestands-, Depotwert- und vereinfachte Renditeberechnung mit strikter Trennung von Kontoeinzahlung und ETF-Kauf.
- Berichte, ASCII-Diagramme, Sparplanprognosen und Excel-/ONLYOFFICE-kompatibler CSV-Export.
- Datenschutz durch Verwerfen sensibler Gegenparteidaten und Ignorieren lokaler Finanzdateien in Git.
- Vorbereitete abstrakte `PriceProvider`-Schnittstelle, jedoch noch ohne Netzwerk- oder API-Zugriff.

#### Phase 2 – Automatische Kurse und erweiterte Prognosen

- Konkrete Kursanbieter für Alpha Vantage und Twelve Data über die gemeinsame `PriceProvider`-Schnittstelle.
- API-Schlüssel werden ausschließlich aus `ALPHA_VANTAGE_API_KEY` beziehungsweise `TWELVE_DATA_API_KEY` gelesen und niemals gespeichert.
- Neuer Befehl `update-prices` für aktuelle Kurse und historische Monatsendkurse.
- Standardmäßig fünf Jahre Kurshistorie; Alpha Vantage verwendet dafür den langfristigen Monatsendpunkt.
- Lokaler JSON-Cache ohne Zugangsdaten mit 15 Minuten Gültigkeit für aktuelle und 24 Stunden für historische Abfragen.
- Automatische Kurse werden ausschließlich als `market_price` mit Anbieter, Kursdatum, Abrufzeitpunkt und `price_capture=automatic` gespeichert. Broker-Kauf- und Verkaufskurse bleiben unverändert.
- Gegenüberstellung von ETF-Kaufbeträgen und Depotwert inklusive Kursgewinn oder -verlust.
- Annualisierte historische Kurssteigerung (CAGR) sowie Prognosevergleich mit historischem Wert, 3 %, 5 % und 7 %.
- Prognosetabelle mit kumulierten künftigen Einzahlungen und prognostiziertem Depotwert je Jahr; vorhandenes Depotvermögen bleibt getrenntes Startkapital.
- Sicherer Umgang mit Netzwerk-, API-, Symbol- und Ratenlimitfehlern sowie erweiterte netzwerkfreie Tests für beide Anbieter.

### Tests und Mitwirkung

```bash
python3 -m unittest discover -v
python3 -m py_compile growthledger.py
```

Beiträge sollten Standardbibliothek und `Decimal` beibehalten, anonymisierte und netzwerkfreie Tests ergänzen und `python3 growthledger.py --help` funktionsfähig halten. Fehlerberichte dürfen keine echten Finanzdaten oder API-Schlüssel enthalten.

### Lizenz

MIT License, Copyright © 2026 GrowthLedger Contributors. Siehe `LICENSE`.

---

## English

GrowthLedger is a local Python 3 terminal application for managing and analysing an ETF savings plan. It imports Trade Republic CSV files, records manual transactions, creates reports and forecasts, draws ASCII charts, and exports tables. Phase 2 can retrieve market prices from Alpha Vantage or Twelve Data when explicitly requested. It uses only the Python standard library and `Decimal` for financial values.

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

`buy_price` or `sell_price` is the actual broker execution price. `market_price` is exclusively a manual or automatically retrieved valuation, cut-off-date, or month-end price. A market price never overwrites a purchase price.

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

### Roadmap: Phase 2 – Automatic price retrieval (implemented)

Supported providers are Alpha Vantage and Twelve Data. Set the applicable key exclusively as an environment variable:

```bash
export ALPHA_VANTAGE_API_KEY="..."
python3 growthledger.py update-prices --provider alpha_vantage --symbol EUNL.DEX --history

export TWELVE_DATA_API_KEY="..."
python3 growthledger.py update-prices --provider twelve_data --symbol EUNL:XETR --history
```

`--symbol` is the provider-specific ticker. With exactly one existing position, its ISIN/symbol is assigned automatically; otherwise also pass `--asset-id IE00B4L5Y983`. `--history` retrieves five years of history by default and stores month-end prices; Alpha Vantage uses its long-term monthly endpoint. Without it, only the latest price is stored. `--start`, `--end`, `--currency`, and `--refresh` control the period, fallback currency, and cache refresh. Provider and ticker can also be set in `data/config.json`.

Responses are cached without API keys under `data/cache/prices/` (current prices for 15 minutes, history for 24 hours). API, network, symbol, and rate-limit errors produce understandable messages and do not alter existing transactions. Automatic records receive `source=market_api`, `price_capture=automatic`, and the provider as `price_source`. Broker purchase prices remain unchanged.

After at least two market prices spanning at least 30 days, `chart` shows a default comparison of annualised historical price growth (CAGR), 3%, 5%, and 7%. Without return parameters, `forecast` uses the same scenario comparison. `--return` or `--returns` overrides this selection. Historical growth is not a prediction or guarantee.

### Changelog

#### Phase 1 – Local foundation

- Local German-language terminal application using only the Python standard library and `Decimal`.
- Safe Trade Republic CSV import with preview, dry-run, duplicate detection, and atomic storage.
- Manual entry of deposits, withdrawals, purchases, sales, dividends, fees, and taxes.
- Holdings, portfolio value, and simplified return calculations with strict separation of cash deposits and ETF purchases.
- Reports, ASCII charts, savings-plan forecasts, and Excel-/ONLYOFFICE-compatible CSV export.
- Privacy protection by discarding sensitive counterparty data and excluding local financial files from Git.
- Prepared abstract `PriceProvider` interface, but no network or API access yet.

#### Phase 2 – Automatic prices and extended forecasts

- Concrete Alpha Vantage and Twelve Data providers using the shared `PriceProvider` interface.
- API keys are read exclusively from `ALPHA_VANTAGE_API_KEY` or `TWELVE_DATA_API_KEY` and are never stored.
- New `update-prices` command for current prices and historical month-end prices.
- Five years of price history by default; Alpha Vantage uses its long-term monthly endpoint.
- Local credential-free JSON cache with a 15-minute lifetime for current and 24-hour lifetime for historical requests.
- Automatic prices are stored only as `market_price`, including provider, price date, retrieval timestamp, and `price_capture=automatic`. Broker purchase and sale prices remain unchanged.
- Comparison of ETF purchase amounts and portfolio value, including price gain or loss.
- Annualised historical price growth (CAGR) plus a forecast comparison using the historical value, 3%, 5%, and 7%.
- Forecast table with cumulative future contributions and projected portfolio value for every year; existing portfolio value remains separate starting capital.
- Safe handling of network, API, symbol, and rate-limit errors, plus extended network-free tests for both providers.

### Tests and contributing

```bash
python3 -m unittest discover -v
python3 -m py_compile growthledger.py
```

Contributions should retain standard-library-only operation and `Decimal`, add anonymised network-free tests, and keep `python3 growthledger.py --help` working. Bug reports must not contain real financial data or API keys.

### License

MIT License, Copyright © 2026 GrowthLedger Contributors. See `LICENSE`.
