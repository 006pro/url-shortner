import secrets
import string

ALPHABET = string.ascii_letters + string.digits  # base62, no separators to guess


def generate_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


# Reserved so custom aliases can never collide with real routes.
RESERVED_CODES = {"links", "docs", "openapi.json", "redoc", "health"}
