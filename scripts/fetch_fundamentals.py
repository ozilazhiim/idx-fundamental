#!/usr/bin/env python3
"""Fetch current IDX fundamentals through ihsg-cli (command: idx).

This exporter deliberately does NOT fabricate 3Y/5Y mean P/E or P/B values.
The provider's current fundamentals payload does not include those historical
averages. Those four columns are emitted as null with an explanatory note.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TICKERS_FILE = DATA_DIR / "tickers.txt"
JSON_OUT = DATA_DIR / "fundamentals_latest.json"
CSV_OUT = DATA_DIR / "fundamentals_latest.csv"

CHUNK_SIZE = int(os.getenv("IDX_CHUNK_SIZE", "8"))
SLEEP_BETWEEN_CHUNKS = float(os.getenv("IDX_SLEEP_SECONDS", "1.5"))
MAX_RETRIES = int(os.getenv("IDX_MAX_RETRIES", "3"))
RETRY_BASE_SECONDS = float(os.getenv("IDX_RETRY_BASE_SECONDS", "5"))

# Output column order matches the user's spreadsheet headers.
OUTPUT_FIELDS = [
    "ticker",
    "pe_ratio",
    "mean_per_3y",
    "mean_per_5y",
    "book_value",
    "pbv_ratio",
    "mean_pbv_3y",
    "mean_pbv_5y",
    "roe",
    "npm",
    "eps_ttm",
    "der",
    "div_yield",
    "status",
    "source",
    "financial_currency",
    "currency",
    "note",
]

# These eight values are available from the current fundamentals endpoint.
CURRENT_FIELDS = [
    "pe_ratio",
    "book_value",
    "pbv_ratio",
    "roe",
    "npm",
    "eps_ttm",
    "der",
    "div_yield",
]

HISTORICAL_FIELDS = [
    "mean_per_3y",
    "mean_per_5y",
    "mean_pbv_3y",
    "mean_pbv_5y",
]


def normalize_ticker(value: str) -> str:
    ticker = str(value).strip().upper()
    ticker = re.sub(r"\.JK$", "", ticker)
    return ticker


def load_tickers() -> list[str]:
    if not TICKERS_FILE.exists():
        raise FileNotFoundError(
            f"Ticker file not found: {TICKERS_FILE}. Create it with one IDX ticker per line."
        )

    tickers: list[str] = []
    seen: set[str] = set()
    for raw in TICKERS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Permit comma/tab-separated values copied from a spreadsheet.
        for item in re.split(r"[\s,;]+", line):
            ticker = normalize_ticker(item)
            if ticker and re.fullmatch(r"[A-Z0-9]+", ticker) and ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)

    if not tickers:
        raise ValueError("No valid tickers found in data/tickers.txt")
    return tickers


def run_idx_compare(tickers: list[str]) -> dict[str, Any]:
    command = ["idx", "-o", "json", "stocks", "compare", ",".join(tickers)]
    last_error = "Unknown error"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired:
            last_error = "CLI timeout after 180 seconds"
        else:
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout)
                    if not isinstance(payload, dict):
                        raise ValueError("CLI JSON response is not an object")
                    return payload
                except (json.JSONDecodeError, ValueError) as exc:
                    last_error = f"Invalid JSON output: {exc}; stderr={result.stderr[-1000:]}"
            else:
                last_error = (
                    f"idx exit={result.returncode}; stderr={result.stderr[-1500:]}; "
                    f"stdout={result.stdout[-500:]}"
                )

        if attempt < MAX_RETRIES:
            wait_seconds = RETRY_BASE_SECONDS * attempt
            print(
                f"Retry {attempt}/{MAX_RETRIES - 1} for {','.join(tickers)} "
                f"after error: {last_error}. Waiting {wait_seconds}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)

    raise RuntimeError(last_error)


def nested(obj: Any, *keys: str) -> Any:
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def normalize_fundamental(item: dict[str, Any]) -> dict[str, Any]:
    symbol = normalize_ticker(item.get("symbol") or item.get("ticker") or "")
    currency = item.get("currency")
    financial_currency = item.get("financial_currency")

    pe_ratio = nested(item, "valuation", "pe_trailing")
    pbv_ratio = nested(item, "valuation", "price_to_book")
    book_value = nested(item, "per_share", "book_value")

    note_parts: list[str] = []
    if currency and financial_currency and currency.upper() != financial_currency.upper():
        # These fields mix the share price currency and statement currency.
        pbv_ratio = None
        book_value = None
        note_parts.append(
            "PBV/book_value kosong karena mata uang harga dan laporan keuangan berbeda"
        )

    sources = item.get("sources") or []
    source_text = ", ".join(str(source) for source in sources) if sources else "idx:auto"

    values = {
        "ticker": symbol,
        "pe_ratio": pe_ratio,
        "mean_per_3y": None,
        "mean_per_5y": None,
        "book_value": book_value,
        "pbv_ratio": pbv_ratio,
        "mean_pbv_3y": None,
        "mean_pbv_5y": None,
        "roe": nested(item, "profitability", "roe_pct"),
        "npm": nested(item, "profitability", "net_margin_pct"),
        "eps_ttm": nested(item, "per_share", "eps_ttm"),
        "der": nested(item, "health", "debt_to_equity"),
        "div_yield": nested(item, "dividend", "yield_pct"),
        "status": "OK",
        "source": source_text,
        "financial_currency": financial_currency,
        "currency": currency,
        "note": "; ".join(note_parts),
    }
    if not any(values.get(field) is not None for field in CURRENT_FIELDS):
        values["status"] = "NO_DATA"
        values["note"] = (values["note"] + "; " if values["note"] else "") + "Tidak ada metrik fundamental yang tersedia"

    return values


def write_outputs(rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "fields": OUTPUT_FIELDS, "rows": rows}
    JSON_OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tickers = load_tickers()
    chunks = [tickers[i : i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]

    print(f"Found {len(tickers)} tickers; {len(chunks)} compare batches.", flush=True)

    records_by_symbol: dict[str, dict[str, Any]] = {}
    failed_chunks: list[dict[str, str]] = []
    stale_chunks = 0
    warning_count = 0

    for index, chunk in enumerate(chunks, start=1):
        print(
            f"[{index}/{len(chunks)}] Fetching {', '.join(chunk)}",
            flush=True,
        )
        try:
            payload = run_idx_compare(chunk)
            raw_data = payload.get("data", [])
            if isinstance(raw_data, dict):
                raw_data = raw_data.get("items", [])
            if not isinstance(raw_data, list):
                raise ValueError("Expected payload.data to be an array")

            if payload.get("stale") is True:
                stale_chunks += 1
            warnings = payload.get("warnings") or []
            if warnings:
                warning_count += len(warnings)

            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                row = normalize_fundamental(item)
                if row["ticker"]:
                    if payload.get("stale") is True:
                        row["status"] = "STALE"
                        row["note"] = (row["note"] + "; " if row["note"] else "") + "Data berasal dari cache stale"
                    records_by_symbol[row["ticker"]] = row

            # Compare can omit symbols that failed while returning successful ones.
            returned = {normalize_ticker(item.get("symbol") or "") for item in raw_data if isinstance(item, dict)}
            for ticker in chunk:
                if ticker not in returned:
                    records_by_symbol.setdefault(
                        ticker,
                        {
                            "ticker": ticker,
                            **{field: None for field in OUTPUT_FIELDS if field not in ("ticker", "status", "source", "financial_currency", "currency", "note")},
                            "status": "NO_DATA",
                            "source": "",
                            "financial_currency": None,
                            "currency": None,
                            "note": "Ticker tidak muncul pada respons compare",
                        },
                    )
        except Exception as exc:  # continue other batches; record the failed symbols
            message = str(exc)[:1500]
            failed_chunks.append({"tickers": ",".join(chunk), "error": message})
            for ticker in chunk:
                records_by_symbol[ticker] = {
                    "ticker": ticker,
                    **{field: None for field in OUTPUT_FIELDS if field not in ("ticker", "status", "source", "financial_currency", "currency", "note")},
                    "status": "FETCH_ERROR",
                    "source": "",
                    "financial_currency": None,
                    "currency": None,
                    "note": message,
                }

        if index < len(chunks):
            time.sleep(SLEEP_BETWEEN_CHUNKS)

    rows = [records_by_symbol.get(ticker) for ticker in tickers]
    rows = [row for row in rows if row is not None]

    successful = sum(1 for row in rows if row["status"] in ("OK", "STALE"))
    no_data = sum(1 for row in rows if row["status"] == "NO_DATA")
    failed = sum(1 for row in rows if row["status"] == "FETCH_ERROR")

    # Do not replace last known output if the whole provider is blocking CI.
    if successful == 0:
        raise RuntimeError(
            "No successful fundamentals returned. Existing output files were not replaced. "
            "The provider may be blocking this GitHub Actions runner."
        )

    meta = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "ihsg-cli / idx, automatic provider chain (Yahoo Finance + MSN Money)",
        "requested_tickers": len(tickers),
        "successful_tickers": successful,
        "no_data_tickers": no_data,
        "failed_tickers": failed,
        "failed_chunks": failed_chunks,
        "stale_chunks": stale_chunks,
        "provider_warning_count": warning_count,
        "historical_means": "Not supplied by current fundamentals endpoint; left blank intentionally.",
        "historical_note": (
            "mean_per_3y, mean_per_5y, mean_pbv_3y and mean_pbv_5y are null. "
            "Do not interpret null as zero. A separate historical valuation dataset is required."
        ),
    }
    write_outputs(rows, meta)

    print(
        f"Done. OK/STALE={successful}, NO_DATA={no_data}, FETCH_ERROR={failed}. "
        f"Wrote {JSON_OUT} and {CSV_OUT}.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"FATAL: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1)
