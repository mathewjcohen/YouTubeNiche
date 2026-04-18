import anthropic
from agents.shared.config_loader import get_env

def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=get_env("ANTHROPIC_API_KEY"), max_retries=3)

def complete(prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> str:
    client = get_client()
    message = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text

def complete_sonnet(prompt: str, max_tokens: int = 4096) -> str:
    return complete(prompt, model="claude-sonnet-4-6", max_tokens=max_tokens)
