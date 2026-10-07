"""
SAJHA MCP Server — Data Connectors: SQL drivers, one per kind (optional Python packages).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Dict

from sajha.connectors.drivers.base import (ConnectorError, DriverMissing, QueryTimeout, SQLDriver,  # noqa: F401
                                           installed, json_schema_for)
from sajha.connectors.drivers.cloud import BigQueryDriver, DatabricksDriver, SnowflakeDriver
from sajha.connectors.drivers.enterprise import OracleDriver, SQLServerDriver
from sajha.connectors.drivers.files import DuckDBDriver, SQLiteDriver
from sajha.connectors.drivers.mysql import MariaDBDriver, MySQLDriver
from sajha.connectors.drivers.postgres import PgVectorDriver, PostgresDriver, RedshiftDriver

DRIVERS: Dict[str, SQLDriver] = {d.kind: d for d in (
    PostgresDriver(), PgVectorDriver(), RedshiftDriver(), MySQLDriver(), MariaDBDriver(), SQLServerDriver(),
    OracleDriver(), SnowflakeDriver(), BigQueryDriver(), DatabricksDriver(), SQLiteDriver(), DuckDBDriver())}


def get_driver(kind: str) -> SQLDriver:
    d = DRIVERS.get(kind)
    if d is None:
        raise ConnectorError(f'no SQL driver for kind {kind!r}')
    return d


def driver_installed(kind: str) -> bool:
    d = DRIVERS.get(kind)
    if d is None:
        return True                                # HTTP adapters need no package
    if kind in ('postgresql', 'pgvector', 'redshift'):
        return installed('psycopg2') or installed('psycopg')
    return installed(d.module)
