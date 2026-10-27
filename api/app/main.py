from fastapi import FastAPI, HTTPException, Response
from psycopg.types.json import Jsonb

from .db import get_conn
from .models import EventIn

app = FastAPI(title="RelayOps API")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events", status_code=202)
def create_event(event: EventIn, response: Response):
    # TODO: idempotency
    conn = get_conn()
    try:
        row = conn.execute(
            """
            INSERT INTO events (event_id, type, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id, status
            """,
            (event.event_id, event.type, Jsonb(event.payload)),
        ).fetchone()

        # eveniment nou
        if row is not None:
            conn.commit()
            return row

        # daca deja exista , il citim:
        existing = conn.execute(
            """
            SELECT event_id, type, payload, status, attempts, created_at, updated_at
            FROM events WHERE event_id = %s
            """,
            (event.event_id,),
        ).fetchone()
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    # 3) același conținut 
    # 200 cu starea curentă; 
    # conținut diferit -> 409
    if existing["type"] != event.type or existing["payload"] != event.payload:
        raise HTTPException(status_code=409, detail="event_id already exists with different content")

    response.status_code = 200
    return existing

   


@app.get("/events/{event_id}")
def get_event(event_id: str):
    conn = get_conn()
    row = conn.execute(
        """
        SELECT id, event_id, type, payload, status, attempts, created_at, updated_at
        FROM events WHERE event_id = %s
        ORDER BY id LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")

    # am inregistrat de asemenea delivery attempts in bd , le adaugam la raspuns!
    row["delivery_attempts"] = conn.execute(
        """
        SELECT attempt, status_code, error, created_at
        FROM delivery_attempts
        WHERE event_pk = %s
        ORDER BY attempt, id
        """,
        (row["id"],),
    ).fetchall()
    row.pop("id") 
    return row