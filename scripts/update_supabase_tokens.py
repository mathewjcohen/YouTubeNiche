"""
One-shot: push the locally refreshed token to all rows in youtube_accounts.

Run after refresh_token.py has written config/youtube_token.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from supabase import create_client
from agents.shared.config_loader import get_env

TOKEN_PATH = Path("config/youtube_token.json")

if not TOKEN_PATH.exists():
    print(f"[error] {TOKEN_PATH} not found — run scripts/refresh_token.py first")
    sys.exit(1)

token_dict = json.loads(TOKEN_PATH.read_text())

sb = create_client(get_env("SUPABASE_URL"), get_env("SUPABASE_SERVICE_KEY"))

accounts = sb.table("youtube_accounts").select("id, channel_name").execute()
if not accounts.data:
    print("[error] No rows in youtube_accounts")
    sys.exit(1)

for row in accounts.data:
    sb.table("youtube_accounts").update({"token_json": token_dict}).eq("id", row["id"]).execute()
    print(f"[ok] Updated token for: {row['channel_name']} ({row['id']})")

print(f"\nDone — {len(accounts.data)} account(s) updated.")
