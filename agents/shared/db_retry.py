import httpx


def patch_postgrest_http1(sb):
    """Replace PostgREST session with HTTP/1.1-only to avoid StreamReset on GitHub Actions.

    Auth headers are passed via the postgrest headers= parameter so they flow through
    SyncPostgrestClient.headers (per-request headers) rather than only living on the
    httpx.Client base headers. This prevents Illegal header value errors from httpcore
    when the two header stores are merged during request building.
    """
    from postgrest import SyncPostgrestClient

    rest_url = f"{str(sb.supabase_url).rstrip('/')}/rest/v1"
    key = str(sb.supabase_key)
    pg = SyncPostgrestClient(
        rest_url,
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    pg.session.close()
    pg.session = httpx.Client(
        base_url=rest_url,
        headers={k: str(v) for k, v in pg.headers.items()},
        http2=False,
        follow_redirects=True,
    )
    sb._postgrest = pg
    return sb


def execute_with_retry(query, retries: int = 3, delay: float = 3.0):
    import time
    for attempt in range(retries):
        try:
            return query.execute()
        except httpx.RemoteProtocolError as e:
            if attempt == retries - 1:
                raise
            print(f"[db_retry] HTTP/2 StreamReset (attempt {attempt + 1}/{retries}), retrying in {delay}s... ({e})")
            time.sleep(delay)
