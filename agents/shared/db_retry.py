import httpx


def patch_postgrest_http1(sb):
    """Force PostgREST to use HTTP/1.1 to avoid StreamReset on GitHub Actions.

    Uses sb.postgrest (supabase's lazy-init path) so auth headers are set up via
    supabase's own options.headers mechanism — the same path that works with the
    default session. Only the underlying httpx transport is replaced.
    PostgREST builds absolute request URLs, so the replacement session needs no base_url.
    """
    pg = sb.postgrest  # trigger lazy init; auth headers populated via supabase options
    pg.session.close()
    pg.session = httpx.Client(http2=False, follow_redirects=True)
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
