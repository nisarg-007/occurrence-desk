"""Loads one month of BTS Reporting Carrier On-Time Performance CSV into `carriers`,
`airports` and `flights`, via `psycopg` binary `COPY` — half a million rows in seconds,
not an hour with row-by-row `INSERT` (work pack §2.3).

Load order matters and is not optional: `carriers` and `airports` first, built from the
distinct values in the *same* file, or every flight row's foreign keys reject and it looks
like the schema is broken when it isn't (work pack §2.3, §2.8).

Column choice: BTS ships three airport-id flavours (`OriginAirportID`, `OriginAirportSeqID`,
`OriginCityMarketID`). This loader uses `OriginAirportID` / `DestAirportID` — the plain
airport identifier, stable across a runway/terminal change at the same airport — because
that's what `airports.airport_id` in the canonical schema (§0.6) is. Picking one of the
other two here would join silently wrong a month later, which is exactly the trap the work
pack names.

The `2400` decision: BTS's `hhmm` time fields use `2400` for a scheduled/actual time that
represents midnight at the end of the operating day. `_parse_hhmm` normalises it to
`00:00:00`. This loader does NOT shift `flight_date` forward for a `2400` value — BTS's own
`FlightDate` already denotes the scheduled departure's calendar day, and shifting it would
silently disagree with every other date-keyed field (delay minutes, the day-of-week a report
gets linked against). The normalisation is written down here, once, rather than left for
whoever writes the next query against `crs_dep_time` to guess at.

`COPY` cannot express `ON CONFLICT`, so every load lands rows in a `TEMP` staging table
first and merges from there with `INSERT ... ON CONFLICT DO NOTHING` — which is what makes
re-running this loader against a month you've already loaded a safe no-op rather than a
unique-constraint crash.

Usage:
    python -m db.seed.load_bts /path/to/T_ONTIME_REPORTING.csv
"""

from __future__ import annotations

import csv
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from db.database import session_scope

logger = logging.getLogger(__name__)

#: BTS column names this loader depends on (work pack §0.2) — a header missing any of these
#: means the file isn't what we think it is, and we refuse rather than load garbage.
REQUIRED_COLUMNS = (
    "FlightDate",
    "Reporting_Airline",
    "DOT_ID_Reporting_Airline",
    "Tail_Number",
    "Flight_Number_Reporting_Airline",
    "OriginAirportID",
    "Origin",
    "OriginCityName",
    "OriginState",
    "DestAirportID",
    "Dest",
    "DestCityName",
    "CRSDepTime",
    "DepTime",
    "DepDelayMinutes",
    "CRSArrTime",
    "ArrTime",
    "ArrDelayMinutes",
    "Cancelled",
    "CancellationCode",
    "Diverted",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
    "Distance",
)


def _parse_hhmm(raw: str) -> str | None:
    """BTS `hhmm` string -> `HH:MM:SS`, or None. See module docstring for the `2400` decision."""
    raw = raw.strip()
    if not raw:
        return None
    raw = raw.zfill(4)
    if raw == "2400":
        return "00:00:00"
    hh, mm = raw[:2], raw[2:]
    if not (hh.isdigit() and mm.isdigit()) or int(hh) > 23 or int(mm) > 59:
        return None
    return f"{hh}:{mm}:00"


def _int_or_none(raw: str) -> int | None:
    raw = raw.strip()
    return int(float(raw)) if raw else None


def _cancellation_code(raw: str) -> str | None:
    raw = raw.strip()
    return raw if raw in ("A", "B", "C", "D") else None


def _check_header(fieldnames: Sequence[str] | None) -> None:
    if fieldnames is None:
        raise ValueError("empty CSV: no header row")
    missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        raise ValueError(f"CSV is missing required BTS columns: {missing}")


def load_reference_data(session: Session, csv_path: Path) -> tuple[int, int]:
    """Pass 1: distinct carriers and airports from the file, committed before any flight
    row can reference them. Returns (carriers_seen, airports_seen)."""
    carriers: dict[int, str | None] = {}
    airports: dict[int, tuple[str | None, str | None, str | None]] = {}

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _check_header(reader.fieldnames)
        for row in reader:
            dot_id = _int_or_none(row["DOT_ID_Reporting_Airline"])
            if dot_id is not None:
                carriers.setdefault(dot_id, row["Reporting_Airline"].strip() or None)

            origin_id = _int_or_none(row["OriginAirportID"])
            if origin_id is not None:
                airports.setdefault(
                    origin_id,
                    (
                        row["Origin"].strip() or None,
                        row["OriginCityName"].strip() or None,
                        row["OriginState"].strip() or None,
                    ),
                )
            dest_id = _int_or_none(row["DestAirportID"])
            if dest_id is not None:
                airports.setdefault(
                    dest_id,
                    (row["Dest"].strip() or None, row["DestCityName"].strip() or None, None),
                )

    raw_conn = session.connection().connection
    with raw_conn.cursor() as cur:  # type: ignore[attr-defined]  # psycopg3 Cursor at runtime
        cur.execute(
            "CREATE TEMP TABLE _stage_carriers (dot_id integer, iata_code text, name text) "
            "ON COMMIT DROP"
        )
        cur.execute(
            "CREATE TEMP TABLE _stage_airports (airport_id integer, iata_code text, "
            "city_name text, state text) ON COMMIT DROP"
        )

        with cur.copy("COPY _stage_carriers (dot_id, iata_code, name) FROM STDIN") as cp:
            for dot_id, name in carriers.items():
                cp.write_row((dot_id, None, name))

        with cur.copy(
            "COPY _stage_airports (airport_id, iata_code, city_name, state) FROM STDIN"
        ) as cp:
            for airport_id, (iata, city, state) in airports.items():
                cp.write_row((airport_id, iata, city, state))

        cur.execute(
            "INSERT INTO carriers (dot_id, iata_code, name) "
            "SELECT dot_id, iata_code, name FROM _stage_carriers "
            "ON CONFLICT (dot_id) DO NOTHING"
        )
        cur.execute(
            "INSERT INTO airports (airport_id, iata_code, city_name, state) "
            "SELECT airport_id, iata_code, city_name, state FROM _stage_airports "
            "ON CONFLICT (airport_id) DO NOTHING"
        )
    session.commit()
    return len(carriers), len(airports)


_FLIGHT_COLUMNS = (
    "flight_date",
    "reporting_airline",
    "dot_id",
    "flight_number",
    "tail_number",
    "origin_airport_id",
    "dest_airport_id",
    "crs_dep_time",
    "dep_time",
    "dep_delay_minutes",
    "crs_arr_time",
    "arr_time",
    "arr_delay_minutes",
    "cancelled",
    "cancellation_code",
    "diverted",
    "carrier_delay",
    "weather_delay",
    "nas_delay",
    "security_delay",
    "late_aircraft_delay",
    "distance",
)


def load_flights(session: Session, csv_path: Path) -> int:
    """Pass 2: the flights themselves, streamed straight into a staging table via `COPY`,
    then merged with `ON CONFLICT DO NOTHING` against `flights.flight_date,
    reporting_airline, flight_number, origin_airport_id` — the idempotency key that makes
    re-running this loader for a month you've already loaded a safe no-op."""
    raw_conn = session.connection().connection
    with raw_conn.cursor() as cur:  # type: ignore[attr-defined]  # psycopg3 Cursor at runtime
        cur.execute(f"""
            CREATE TEMP TABLE _stage_flights (
                {", ".join(f"{c} text" for c in _FLIGHT_COLUMNS)}
            ) ON COMMIT DROP
        """)

        n = 0
        with (
            csv_path.open(newline="", encoding="utf-8") as f,
            cur.copy(f"COPY _stage_flights ({', '.join(_FLIGHT_COLUMNS)}) FROM STDIN") as cp,
        ):
            reader = csv.DictReader(f)
            _check_header(reader.fieldnames)
            for row in reader:
                tail = row["Tail_Number"].strip() or None
                cp.write_row(
                    (
                        row["FlightDate"].strip(),
                        row["Reporting_Airline"].strip(),
                        row["DOT_ID_Reporting_Airline"].strip(),
                        row["Flight_Number_Reporting_Airline"].strip(),
                        tail,
                        row["OriginAirportID"].strip(),
                        row["DestAirportID"].strip(),
                        _parse_hhmm(row["CRSDepTime"]),
                        _parse_hhmm(row["DepTime"]),
                        str(_int_or_none(row["DepDelayMinutes"]) or ""),
                        _parse_hhmm(row["CRSArrTime"]),
                        _parse_hhmm(row["ArrTime"]),
                        str(_int_or_none(row["ArrDelayMinutes"]) or ""),
                        "t" if row["Cancelled"].strip() in ("1", "1.0") else "f",
                        _cancellation_code(row["CancellationCode"]),
                        "t" if row["Diverted"].strip() in ("1", "1.0") else "f",
                        str(_int_or_none(row["CarrierDelay"]) or ""),
                        str(_int_or_none(row["WeatherDelay"]) or ""),
                        str(_int_or_none(row["NASDelay"]) or ""),
                        str(_int_or_none(row["SecurityDelay"]) or ""),
                        str(_int_or_none(row["LateAircraftDelay"]) or ""),
                        str(_int_or_none(row["Distance"]) or ""),
                    )
                )
                n += 1

        # A tail number this file introduces must exist before the FK from `flights` can
        # be satisfied — insert distinct tail numbers first.
        cur.execute("""
            INSERT INTO aircraft (tail_number)
            SELECT DISTINCT tail_number FROM _stage_flights
            WHERE tail_number IS NOT NULL AND tail_number <> ''
            ON CONFLICT (tail_number) DO NOTHING
        """)

        cols = ", ".join(_FLIGHT_COLUMNS)
        cur.execute(f"""
            INSERT INTO flights ({cols})
            SELECT
                flight_date::date,
                reporting_airline,
                dot_id::int,
                flight_number::int,
                NULLIF(tail_number, ''),
                origin_airport_id::int,
                dest_airport_id::int,
                NULLIF(crs_dep_time, '')::time,
                NULLIF(dep_time, '')::time,
                NULLIF(dep_delay_minutes, '')::int,
                NULLIF(crs_arr_time, '')::time,
                NULLIF(arr_time, '')::time,
                NULLIF(arr_delay_minutes, '')::int,
                cancelled::boolean,
                NULLIF(cancellation_code, ''),
                diverted::boolean,
                NULLIF(carrier_delay, '')::int,
                NULLIF(weather_delay, '')::int,
                NULLIF(nas_delay, '')::int,
                NULLIF(security_delay, '')::int,
                NULLIF(late_aircraft_delay, '')::int,
                NULLIF(distance, '')::int
            FROM _stage_flights
            ON CONFLICT (flight_date, reporting_airline, flight_number, origin_airport_id)
            DO NOTHING
        """)
    session.commit()
    return n


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) != 2:
        print("usage: python -m db.seed.load_bts /path/to/T_ONTIME_REPORTING.csv", file=sys.stderr)
        raise SystemExit(2)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"no such file: {csv_path}", file=sys.stderr)
        raise SystemExit(2)

    with session_scope() as session:
        n_carriers, n_airports = load_reference_data(session, csv_path)
        logger.info("reference data: %d carrier(s), %d airport(s) seen", n_carriers, n_airports)
        n_flights = load_flights(session, csv_path)
        logger.info("flights: %d row(s) processed from %s", n_flights, csv_path)


if __name__ == "__main__":
    main()
