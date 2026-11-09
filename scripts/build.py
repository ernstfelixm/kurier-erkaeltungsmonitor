
"""Download, validate and publish SARI weekly JSON. Python standard library only."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

# Import der neuen Saisonberechnung
if __package__:
    from .seasonal import make_seasonal
else:
    from seasonal import make_seasonal


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public"

URLS = {
    "patient": (
        "https://opendata-files.sozialversicherung.at/sari/"
        "SARI_Wohnregion_Patient_v202602.csv?q=now"
    ),
    "hospital": (
        "https://opendata-files.sozialversicherung.at/sari/"
        "SARI_Region_Krankenanstalt_v202602.csv?q=now"
    ),
}

DIAGNOSES = (
    "AUFNAHMEN",
    "COVID",
    "INFLUENZA",
    "RSV",
    "PNEUMOKOKKEN",
    "SONSTIGE",
)

REQUIRED = {
    "patient": {
        "JAHR",
        "KW",
        "WOHNORT",
        "GESCHLECHT",
        "ALTERSGRUPPE",
        "STATION",
        "BEV_ZAHL",
        *DIAGNOSES,
    },
    "hospital": {
        "JAHR",
        "KW",
        "BUNDESLAND",
        "STATION",
        *DIAGNOSES,
    },
}

SOURCE = (
    "Statistische Daten des Dachverbandes "
    "der Sozialversicherungsträger"
)


def download(url: str) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "KURIER-SARI-monitor/1.0 "
                "(journalism; open data)"
            ),
            "Accept": "text/csv,*/*",
        },
    )

    with urlopen(req, timeout=90) as res:
        data = res.read(80_000_001)

    if not data or len(data) > 80_000_000:
        raise ValueError(
            "Leere oder unerwartet grosse CSV-Datei"
        )

    return data


def integer(value: str, column: str, row: int) -> int:
    v = (
        (value or "")
        .strip()
        .replace("\u00a0", "")
        .replace(" ", "")
    )

    if not v.isdigit():
        raise ValueError(
            f"Zeile {row}, {column}: "
            f"keine nichtnegative ganze Zahl: {value!r}"
        )

    return int(v)


def parse(raw: bytes, kind: str) -> list[dict]:
    text = None

    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass

    if text is None:
        raise ValueError("CSV-Encoding unbekannt")

    sample = text[:10000]
    delim = max(
        (";", ",", "\t"),
        key=lambda c: sample.splitlines()[0].count(c),
    )

    reader = csv.DictReader(
        io.StringIO(text),
        delimiter=delim,
    )

    headers = set(reader.fieldnames or [])
    missing = REQUIRED[kind] - headers

    if missing:
        raise ValueError(
            f"{kind}: Fehlende Spalten: {sorted(missing)}. "
            f"Erhalten: {sorted(headers)}"
        )

    rows = []

    for i, r in enumerate(reader, 2):
        if not any(
            (x or "").strip()
            for x in r.values()
            if isinstance(x, str)
        ):
            continue

        year = integer(r["JAHR"], "JAHR", i)
        week = integer(r["KW"], "KW", i)

        try:
            monday = date.fromisocalendar(
                year, week, 1
            )
        except ValueError as ex:
            raise ValueError(
                f"Zeile {i}: ungueltige ISO-Woche "
                f"{year}-W{week}: {ex}"
            ) from ex

        record = {
            "week": f"{year:04d}-W{week:02d}",
            "week_start": monday.isoformat(),
            "year": year,
            "kw": week,
            "station": (r["STATION"] or "").strip(),
        }

        if record["station"] not in ("I", "N"):
            raise ValueError(
                f"Zeile {i}: Unbekannte Station "
                f"{record['station']!r}"
            )

        region_column = (
            "WOHNORT"
            if kind == "patient"
            else "BUNDESLAND"
        )

        record["region"] = (
            r[region_column] or ""
        ).strip()

        if not record["region"]:
            raise ValueError(
                f"Zeile {i}: Region fehlt"
            )

        if kind == "patient":
            record["sex"] = (
                r["GESCHLECHT"] or ""
            ).strip()

            record["age"] = (
                r["ALTERSGRUPPE"] or ""
            ).strip()

            if not record["sex"] or not record["age"]:
                raise ValueError(
                    f"Zeile {i}: "
                    "Geschlecht oder Altersgruppe fehlt"
                )

            record["population"] = integer(
                r["BEV_ZAHL"],
                "BEV_ZAHL",
                i,
            )

            if record["population"] == 0:
                raise ValueError(
                    f"Zeile {i}: BEV_ZAHL=0; "
                    "Bezugsbasis bitte pruefen"
                )

        for col in DIAGNOSES:
            record[col.lower()] = integer(
                r[col],
                col,
                i,
            )

        for col in DIAGNOSES:
            if (
                col != "AUFNAHMEN"
                and record[col.lower()]
                > record["aufnahmen"]
            ):
                raise ValueError(
                    f"Zeile {i}: Diagnose {col} "
                    "groesser als AUFNAHMEN"
                )

        rows.append(record)

    if not rows:
        raise ValueError(
            f"{kind}: Keine Zeilen"
        )

    identities = [
        (
            r["week"],
            r["region"],
            r["station"],
            r.get("sex"),
            r.get("age"),
        )
        for r in rows
    ]

    if len(identities) != len(set(identities)):
        raise ValueError(
            f"{kind}: Mehrfache Zeilen "
            "mit derselben Dimensionskombination"
        )

    return rows


def aggregate(
    rows: list[dict],
    fields: tuple[str, ...],
    population: bool = False,
) -> list[dict]:

    bucket = {}

    for r in rows:
        key = tuple(r[f] for f in fields)

        if key not in bucket:
            bucket[key] = {
                f: r[f]
                for f in fields
            }

            for d in DIAGNOSES:
                bucket[key][d.lower()] = 0

        for d in DIAGNOSES:
            bucket[key][d.lower()] += (
                r[d.lower()]
            )

    if population:
        # Population is repeated across stations.
        # Count residence/sex/age once per week.
        denominators = {}

        for r in rows:
            key = (
                r["week"],
                r["region"],
                r["sex"],
                r["age"],
            )

            value = r["population"]

            if (
                key in denominators
                and denominators[key] != value
            ):
                raise ValueError(
                    "Widerspruechliche BEV_ZAHL "
                    f"fuer {key}: "
                    f"{denominators[key]} vs {value}"
                )

            denominators[key] = value

        for key, value in denominators.items():
            week, region, sex, age = key

            dimensions = {
                "week": week,
                "region": region,
                "sex": sex,
                "age": age,
            }

            group_key = tuple(
                dimensions[f]
                for f in fields
            )

            if group_key not in bucket:
                raise ValueError(
                    "Ungueltige Aggregationsdimension "
                    "fuer Population"
                )

            bucket[group_key]["population"] = (
                bucket[group_key].get(
                    "population", 0
                ) + value
            )

    result = list(bucket.values())

    for o in result:
        if population:
            for d in DIAGNOSES:
                o[d.lower() + "_per_100k"] = round(
                    o[d.lower()]
                    / o["population"]
                    * 100000,
                    3,
                )

    return sorted(
        result,
        key=lambda r: tuple(
            str(r[f])
            for f in fields
        ),
    )


def write_json(
    path: Path,
    obj: object,
) -> None:

    path.write_text(
        json.dumps(
            obj,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


def create(
    patient: list[dict],
    hospital: list[dict],
    hashes: dict[str, str],
    now: str | None = None,
) -> dict:

    patient_latest = max(
        x["week"] for x in patient
    )

    hospital_latest = max(
        x["week"] for x in hospital
    )

    if patient_latest != hospital_latest:
        raise ValueError(
            "Patienten- und Krankenhausdatei "
            "enthalten unterschiedliche "
            "letzte Kalenderwochen"
        )

    latest = patient_latest

    weeks = sorted({
        r["week"]
        for r in patient
    })

    if len(weeks) < 3:
        raise ValueError(
            "Weniger als drei Berichtswochen vorhanden"
        )

    # Die letzten beiden verfügbaren Wochen
    # gelten als vorläufig.
    complete = weeks[-3]

    updated = now or datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    meta = {
        "source": SOURCE,
        "downloaded_at_utc": updated,
        "latest_week": latest,
        "latest_complete_week": complete,
        "provisional_weeks": weeks[-2:],
        "sha256": hashes,
        "population_method": (
            "Deduplicated by week, residence, "
            "sex and age across stations"
        ),
    }

    # Bestehende Datenaufbereitung
    overview = aggregate(
        patient,
        ("week",),
        True,
    )

    states = aggregate(
        patient,
        ("week", "region"),
        True,
    )

    ages = aggregate(
        patient,
        ("week", "age"),
        True,
    )

    clinic = aggregate(
        hospital,
        ("week", "region", "station"),
    )

    # NEU: Saisonvergleiche für alle Erkrankungen
    # Berechnung erfolgt aus Krankenhausstandortdaten.
    seasonal = make_seasonal(
        hospital,
        meta,
    )

    # Bestehende JSON-Dateien bleiben erhalten.
    # seasonal.json wird zusätzlich veröffentlicht.
    public = {
        "overview.json": overview,
        "states.json": states,
        "age-groups.json": ages,
        "hospital.json": clinic,
        "latest.json": meta,
        "seasonal.json": seasonal,
    }

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    for name, item in public.items():
        write_json(
            OUT / name,
            item,
        )

    write_json(
        OUT / "manifest.json",
        {
            "schema_version": 1,
            **meta,
            "files": list(public),
        },
    )

    (OUT / ".nojekyll").write_text(
        "",
        encoding="utf-8",
    )

    return meta


def main() -> None:
    raw = {
        kind: download(url)
        for kind, url in URLS.items()
    }

    parsed = {
        kind: parse(data, kind)
        for kind, data in raw.items()
    }

    hashes = {
        kind: hashlib.sha256(
            data
        ).hexdigest()
        for kind, data in raw.items()
    }

    meta = create(
        parsed["patient"],
        parsed["hospital"],
        hashes,
    )

    print(
        json.dumps(
            meta,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
