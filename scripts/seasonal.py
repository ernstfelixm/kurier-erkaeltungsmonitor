"""Create reproducible SARI seasonal comparisons from validated hospital rows.

This module uses the Python standard library only. A season runs from ISO week 31
through ISO week 30 of the following ISO year. Every source week belongs to one
season. Weeks missing in a historical season (especially ISO week 53) are null,
never invented or interpolated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

METRICS = {
    'sari': 'aufnahmen',
    'covid': 'covid',
    'influenza': 'influenza',
    'rsv': 'rsv',
}
START_WEEK = 31
END_WEEK = 30


def iso_weeks_in_year(year: int) -> int:
    return date(year, 12, 28).isocalendar().week


def parse_week(week: str) -> tuple[int, int]:
    try:
        year_string, week_string = week.split('-W')
        year, number = int(year_string), int(week_string)
        if week != f'{year:04d}-W{number:02d}':
            raise ValueError('Noncanonical week')
        date.fromisocalendar(year, number, 1)
        return year, number
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Ungueltige ISO-Woche: {week!r}') from exc


def season_start(week: str) -> int:
    year, number = parse_week(week)
    return year if number >= START_WEEK else year - 1


def season_weeks(start_year: int) -> list[str]:
    """All real ISO-week IDs within a season, in reporting order."""
    return (
        [f'{start_year}-W{w:02d}' for w in range(START_WEEK, iso_weeks_in_year(start_year) + 1)]
        + [f'{start_year + 1}-W{w:02d}' for w in range(1, END_WEEK + 1)]
    )


def aligned_week_ids(start_year: int, include_week_53: bool) -> list[str | None]:
    """Place an explicit empty ISO week 53 slot in years with only 52 weeks."""
    ids = [f'{start_year}-W{w:02d}' for w in range(START_WEEK, 53)]
    if include_week_53:
        ids.append(f'{start_year}-W53' if iso_weeks_in_year(start_year) == 53 else None)
    ids.extend(f'{start_year + 1}-W{w:02d}' for w in range(1, END_WEEK + 1))
    return ids


def aggregate_weekly(hospital: list[dict]) -> dict[str, dict[str, int]]:
    """Add station N and I and all hospital locations; do not sum diagnoses together."""
    totals: dict[str, dict[str, int]] = defaultdict(lambda: {m: 0 for m in METRICS})
    seen = set()
    for row in hospital:
        week = row['week']
        parse_week(week)
        key = (week, row['region'], row['station'])
        if key in seen:
            raise ValueError(f'Doppelte Krankenhaus-Zeile: {key}')
        seen.add(key)
        if row['station'] not in ('I', 'N'):
            raise ValueError(f'Ungueltige Station: {row["station"]}')
        for metric, column in METRICS.items():
            value = row[column]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f'Ungueltiger Wert fuer {column} in {week}')
            totals[week][metric] += value
    return dict(totals)


def percent_change(now: int, before: int | None) -> float | None:
    return round((now / before - 1) * 100, 1) if before is not None and before > 0 else None


def make_seasonal(hospital: list[dict], meta: dict) -> dict:
    weekly = aggregate_weekly(hospital)
    latest = meta['latest_week']
    complete = meta['latest_complete_week']
    if latest not in weekly or complete not in weekly:
        raise ValueError('Letzte Meldewoche fehlt in Krankenhausdaten')
    current_year = season_start(latest)
    previous_year = current_year - 1
    historical_years = [current_year - 3, current_year - 2, current_year - 1]
    current_actual = season_weeks(current_year)
    current_present = [week for week in current_actual if week in weekly]
    if not current_present or current_present[-1] != latest:
        raise ValueError('Aktuelle Saison ist nicht bis zur letzten Meldewoche vorhanden')
    if current_present != current_actual[:len(current_present)]:
        raise ValueError('In aktueller Saison fehlen Kalenderwochen')
    for year in historical_years:
        missing = [w for w in season_weeks(year) if w not in weekly]
        if missing:
            raise ValueError(f'Vergleichssaison {year}/{str(year+1)[-2:]} unvollstaendig: {missing[:4]}')
    include_week_53 = any(iso_weeks_in_year(y) == 53 for y in [current_year, *historical_years])
    current_slots = aligned_week_ids(current_year, include_week_53)
    previous_slots = aligned_week_ids(previous_year, include_week_53)
    historical_slots = [aligned_week_ids(year, include_week_53) for year in historical_years]
    if not all(len(ids) == len(current_slots) for ids in [previous_slots, *historical_slots]):
        raise AssertionError('Uneinheitliche Saisonachsen')
    provisional = set(meta['provisional_weeks'])
    if latest not in provisional and complete != latest:
        # A last reporting week can be complete if a future provider changes its lag.
        pass
    chronological = sorted(weekly, key=lambda w: date.fromisocalendar(*parse_week(w), 1))
    previous_week = chronological[chronological.index(latest) - 1] if chronological.index(latest) > 0 else None
    if previous_week and (date.fromisocalendar(*parse_week(latest), 1) - date.fromisocalendar(*parse_week(previous_week), 1)).days != 7:
        raise ValueError('Vorwochenvergleich nicht unmittelbar aufeinanderfolgend')
    completed = [w for w in current_present if w <= complete]
    last_complete = completed[-1] if completed else None
    before_complete = completed[-2] if len(completed) > 1 else None
    metrics = {}
    for metric in METRICS:
        data = []
        for slot, (now_id, prev_id) in enumerate(zip(current_slots, previous_slots)):
            historical = [ids[slot] for ids in historical_slots]
            valid_historical = all(w is not None and w in weekly for w in historical)
            avg = round(sum(weekly[w][metric] for w in historical) / 3, 3) if valid_historical else None
            data.append({
                'slot': slot,
                'week': now_id,
                'current': weekly[now_id][metric] if now_id in weekly else None,
                'previous': weekly[prev_id][metric] if prev_id is not None and prev_id in weekly else None,
                'average': avg,
                'provisional': now_id in provisional,
            })
        metrics[metric] = {
            'points': data,
            'latest_value': weekly[latest][metric],
            'latest_change_pct': percent_change(weekly[latest][metric], weekly[previous_week][metric] if previous_week else None),
            'latest_change_is_provisional': latest in provisional or previous_week in provisional,
            'last_complete_week': last_complete,
            'last_complete_value': weekly[last_complete][metric] if last_complete else None,
            'last_complete_change_pct': percent_change(weekly[last_complete][metric], weekly[before_complete][metric] if before_complete else None) if last_complete else None,
        }
    return {
        'schema_version': 1,
        'source': meta['source'],
        'downloaded_at_utc': meta['downloaded_at_utc'],
        'season_start_week': START_WEEK,
        'season_end_week': END_WEEK,
        'current_season': f'{current_year}/{str(current_year+1)[-2:]}',
        'previous_season': f'{previous_year}/{str(previous_year+1)[-2:]}',
        'average_seasons': [f'{y}/{str(y+1)[-2:]}' for y in historical_years],
        'latest_week': latest,
        'latest_complete_week': complete,
        'provisional_weeks': sorted(provisional),
        'metrics': metrics,
    }
