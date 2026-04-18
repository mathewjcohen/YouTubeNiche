import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def get_env(key: str, required: bool = True) -> str:
    val = os.getenv(key, "").strip()
    if required and not val:
        raise EnvironmentError(f"Missing required env var: {key}")
    return val

def load_json_config(filename: str) -> dict:
    path = Path("config") / filename
    with path.open() as f:
        return json.load(f)

def get_rpm_table() -> dict:
    return load_json_config("niche_rpm_table.json")

def get_subreddits() -> dict:
    return load_json_config("subreddits.json")
