# KURIER Erkältungsmonitor – SARI-Datenpipeline

Quelle: https://www.sari-dashboard.at/opendata  
**Quellenangabe:** Statistische Daten des Dachverbandes der Sozialversicherungsträger

## Was wird veröffentlicht?

- `overview.json` – wöchentliche Österreichwerte nach Diagnose samt Aufnahmeraten
- `states.json` – Aufnahmen und Raten nach Wohnbundesland
- `age-groups.json` – Aufnahmen und Raten nach Altersgruppe
- `hospital.json` – Aufnahmen nach Bundesland des Krankenhausstandorts und Station, **ohne Bevölkerungsraten**
- `latest.json`, `manifest.json` – Berichtswochen, Datenstand, SHA-256 und Vorläufigkeit

Die letzte und vorletzte vorhandene KW sind vorläufig; `latest_complete_week` ist die drittletzte vorhandene Woche. Das ist eine konservative *Heuristik*, keine Garantie vollständiger Meldungen. **Wichtig:** Ein Wochenvergleich sollte zusätzlich die jeweils vorausgehende Woche prüfen. Die Daten zählen Aufnahmen, nicht Erkrankte oder Krankenhausbelegung. Diagnosekategorien können sich überlappen, `AUFNAHMEN` ist die eigene Gesamtzahl und wird nie als Summe der Diagnosen gebildet.

## Lokal

Python 3.12 oder neuer erforderlich, keine externen Pakete.

```bash
python -m unittest discover -s tests -v
python -m scripts.build
```

Die Pipeline holt beide CSVs immer neu und bricht bei unerwarteten Spalten, nichtnumerischen Werten, inkonsistenten Bevölkerungszahlen und unterschiedlichen letzten Wochen ab. Die aktuellen JSON-Dateien entstehen in `public/`. **Erster Produktivlauf muss redaktionell gegen das Originaldashboard geprüft werden:** Insbesondere Alterseinteilung und genaue `BEV_ZAHL`-Semantik sind anhand einer echten Stichprobe zu validieren; der direkte Abruf war bei der Erstellung nicht erreichbar.

## GitHub

1. Neues **öffentliches** Repository erstellen, Dateien auf `main` pushen.
2. Repository → **Settings → Pages** → **Build and deployment → Source: GitHub Actions** wählen.
3. Repository → **Actions → Update SARI data → Run workflow** und Deploy-Erfolg prüfen.
4. Ergebnis unter `https://OWNER.github.io/REPO/overview.json` und `.../manifest.json` testen.
5. Repository → **Settings → Actions → General** prüfen, dass Actions ausführbar sind.

## cron-job.org

Neuen Cronjob mit Zeitzone `Europe/Vienna` anlegen (beispielsweise Dienstag 17:00):

- Methode: `POST`
- URL: `https://api.github.com/repos/OWNER/REPO/actions/workflows/update-sari.yml/dispatches`
- Header: `Accept: application/vnd.github+json`
- Header: `Authorization: Bearer <FINE_GRAINED_TOKEN>`
- Header: `Content-Type: application/json`
- Body: `{"ref":"main"}`
- GitHub-Token: Fine-grained PAT für **nur dieses Repository**, mit `Actions: Read and write`. Token **nicht** im Repo einchecken. Tokenrotation einplanen.

Der API-Aufruf bestätigt lediglich das Auslösen des Workflows, nicht dessen Erfolg. GitHub-Actions-Fehlerbenachrichtigungen aktivieren. Cronjob bei Problemen wiederholen lassen. Unveränderte CSVs können erneut deployed werden, ohne falsche Daten zu erzeugen.

## Offene fachliche QA vor Veröffentlichung

- Semantik der Bevölkerungszahlen und Alterseinheiten anhand echter CSV-Zeilen prüfen.
- Prüfen, ob Wohnregionen ausschließlich neun Länder und keine Gesamtsummen enthalten.
- Diagnoseverläufe, wöchentliche Summen und Stichprobenwerte gegen das SARI-Dashboard abgleichen.
- Für regionale Vergleiche festlegen: Wohnort oder Krankenhausstandort; niemals beide vermischen.
- Die jüngsten Wochen deutlich als unvollständig kennzeichnen.

## Einbindung

In Shorthand die JSON-Dateien per `fetch('https://OWNER.github.io/REPO/overview.json')` abrufen. Für Produktionsbetrieb ggf. Caching und eine KURIER-Subdomain ergänzen.
