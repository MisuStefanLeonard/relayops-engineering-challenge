"""RelayOps delivery worker.

Polls the events table and delivers pending events to the configured
webhook receiver. Every request is signed with HMAC-SHA256.
"""
import hashlib
import hmac
import json
import os
import time
import signal , threading
import httpx
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://relayops:relayops@db:5432/relayops"
)
RECEIVER_URL = os.environ.get("RECEIVER_URL", "http://receiver:9000/webhook")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10"))
MAX_ATTEMPTS = 3
WORKER_DURATION = 120

# pentru SIGTERM
stop_event = threading.Event()

def handle_signal(signum, frame):
    print(f"Received signal {signum}, stopping worker...")
    stop_event.set()


def serialize(body: dict) -> bytes:
    # json.dumps pune spatii si dupa , si : dar httpx 0.28 serializează compact, fără spații. 
    # Semnătura e calculată peste un șir de bytes, iar receptorul primește alt șir
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def sign(raw: bytes) -> str:
    # semnează body-ul BRUT, nu un dict
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()

# modificare aici
def fetch_pending(conn):
    return conn.execute(
        """
        UPDATE events
        SET status = 'processing',
            locked = now() + make_interval(secs => %s),
            updated_at = now()
        WHERE id IN (
            SELECT id FROM EVENTS
            WHERE status = 'pending' OR (status = 'processing' AND locked < now())
            ORDER BY id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, event_id, type, payload
        """,
        (WORKER_DURATION, BATCH_SIZE),
    ).fetchall()


# Succes: orice răspuns 2xx. Un eveniment este delivered doar după un răspuns 2xx.
# Erori temporare: erori de rețea, timeout (5 secunde per încercare), 429, 5xx → retry cu backoff exponențial. 
# Dacă răspunsul conține Retry-After (secunde), următoarea încercare nu are loc mai devreme.
# Erori permanente: orice alt răspuns (ex. 400, 401) → failed, fără retry.
# Maximum 3 încercări per eveniment, apoi failed.

def succes(code:int) -> bool:
    return 200 <= code < 300

def temporary_error(code:int) -> bool:
    return code == 429 or 500 <= code < 600

def retry_after(resp : httpx.Response) -> int:
    retry_after = resp.headers.get("Retry-After") # verificam header-ul Retry-After, daca exista il returnam ca int, altfel returnam 0
    if retry_after is None:
        return 0
    try:
        return int(retry_after)
    except ValueError:
        return 0

# inregistram evenimentul in baza de date
def record_attempt(conn, event_pk, attempt, status_code, error):
    conn.execute(
        """
        INSERT INTO delivery_attempts (event_pk, attempt, status_code, error)
        VALUES (%s, %s, %s, %s)
        """,
        (event_pk, attempt, status_code, error),
    )

def permanent_error(code:int) -> bool:
    return not succes(code) and not temporary_error(code)

# adaugam connectiunea la bd sa inregistram evenimentul + returnam status_code si error
def deliver(client, event,conn) ->  tuple[str, int]:
    """Returns the number of attempts used, or 0 if delivery failed."""
    body = {
        "event_id": event["event_id"],
        "type": event["type"],
        "payload": event["payload"],
    }
    raw = serialize(body)
    # in loc de body , bytes raw al requestului 
    headers = {
        #"X-RelayOps-Signature": sign(body),
        "X-RelayOps-Signature": sign(raw),
        "Content-Type": "application/json"
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            # in loc de json=body , punem content
            resp = None
            status_code = None
            error = None


            resp = client.post(RECEIVER_URL, content=raw, headers=headers)
            status_code = resp.status_code
            print(f"delivered {event['event_id']} attempt={attempt} -> {resp.status_code}")
        except httpx.HTTPError as exc:
            # aici e timeout
            print(f"error delivering {event['event_id']} attempt={attempt}: {exc}")
            # time.sleep(2 ** attempt)

        record_attempt(conn, event["id"], attempt, status_code, error)
        print(f"event={event['event_id']} attempt={attempt} status={status_code} error={error}")

        # 1) succes
        if status_code is not None and succes(status_code):
            return "delivered", attempt

        # 2) eroare permanentă  -> fără retry
        if status_code is not None and permanent_error(status_code):
            return "failed", attempt

        # 3) temporară (rețea, 429, 5xx): retry dacă mai avem încercări
        if attempt == MAX_ATTEMPTS:
            break

        wait = 2 ** attempt  # backoff exponențial: 2s, 4s
        if resp is not None:
            wait = max(wait, retry_after(resp))  # nu mai devreme decât Retry-After

        if stop_event.wait(wait):                            
            # SIGTERM în timpul pauzei: nu mai așteptăm, evenimentul revine în pending
            return "pending", attempt

    return "failed", MAX_ATTEMPTS



def main():
    print(f"worker started, receiver={RECEIVER_URL}")
    signal.signal(signal.SIGTERM, handle_signal)   # docker compose stop / down
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
    with httpx.Client(timeout=5) as client:
        while True:
            events = fetch_pending(conn)
            for event in events:
                # am adaugat conn ca sa inregistram evenimentul in baza de date
                # si status 
                # le folosim la upadate la status
                status,attempts = deliver(client, event, conn)
                conn.execute(
                    "UPDATE events " \
                    "SET status = %s, attempts = %s, updated_at = now() " \
                    "WHERE id = %s",
                    (status, attempts, event["id"]),
                )
            if not events:
                time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
