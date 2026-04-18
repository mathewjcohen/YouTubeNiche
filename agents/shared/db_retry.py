import httpx


def patch_postgrest_http1(sb):
    """Replace PostgREST session with HTTP/1.1-only to avoid StreamReset on GitHub Actions.

    Builds a fresh httpx.Client from sb.supabase_url/supabase_key rather than copying
    headers from the old session (copying causes Illegal header value errors in httpcore).
    """
    from postgrest import SyncPostgrestClient

    rest_url = f"{str(sb.supabase_url).rstrip('/')}/rest/v1"
    session = httpx.Client(
        base_url=rest_url,
        headers={
            "apikey": sb.supabase_key,
            "Authorization": f"Bearer {sb.supabase_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        http2=False,
        follow_redirects=True,
    )
    sb._postgrest = SyncPostgrestClient(rest_url, http_client=session)
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
