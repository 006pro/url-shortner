"""CLI to mint a new API key.

There's no public "create API key" endpoint by design -- this app has no user
registration, so a key is provisioned out-of-band by whoever runs the service.

Usage:
    python -m scripts.create_api_key "My label"
"""

import sys

from app.database import SessionLocal
from app.models import ApiKey
from app.security import generate_api_key, hash_api_key


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "default"

    raw_key = generate_api_key()
    db = SessionLocal()
    try:
        db.add(ApiKey(key_hash=hash_api_key(raw_key), label=label))
        db.commit()
    finally:
        db.close()

    print(f"Created API key for '{label}':")
    print(raw_key)
    print("\nStore this now -- only the hash is kept, it cannot be shown again.")


if __name__ == "__main__":
    main()
