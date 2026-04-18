import httpx


def patch_postgrest_http1(sb):
    """Replace PostgREST httpx session with an HTTP/1.1-only client.

    GitHub Actions runners get HTTP/2 StreamReset errors from Supabase PostgREST.
    The auth client (GoTrue) still uses HTTP/2 — only PostgREST is patched here.
    """
    old = sb.postgrest.session
    sb.postgrest.session = httpx.Client(
        base_url=str(old.base_url),
        headers=dict(old.headers),
        http2=False,
        follow_redirects=True,
    )
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
