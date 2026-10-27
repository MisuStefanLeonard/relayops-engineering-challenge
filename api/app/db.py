import os

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://relayops:relayops@db:5432/relayops"
)

_conn = None

# am adaugat connection_timeout=20 pana se initilizeaza conexiunea la baza de date, ca sa nu dea timeout la start
def get_conn() -> psycopg.Connection:
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=3)
    return _conn
