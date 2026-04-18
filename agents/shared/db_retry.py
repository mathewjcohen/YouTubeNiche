import httpx


def patch_postgrest_http1(sb):
    # h2 is a transitive dep of supabase, enabling HTTP/2 by default.
    # Supabase PostgREST rejects HTTP/2 with RST_STREAM PROTOCOL_ERROR.
    # Replace only the transport — session auth headers are never touched.
    pg = sb.postgrest  # trigger lazy init
    pg.session._transport = httpx.HTTPTransport(http2=False)
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
