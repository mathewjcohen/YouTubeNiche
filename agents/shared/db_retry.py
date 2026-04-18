import time
import httpx


def execute_with_retry(query, retries: int = 3, delay: float = 3.0):
    for attempt in range(retries):
        try:
            return query.execute()
        except httpx.RemoteProtocolError as e:
            if attempt == retries - 1:
                raise
            print(f"[db_retry] HTTP/2 StreamReset (attempt {attempt + 1}/{retries}), retrying in {delay}s... ({e})")
            time.sleep(delay)
