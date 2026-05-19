import argparse
from pathlib import Path

from src.auth.oauth_user import OAuthUserAuth
from src.auth.token_store import TokenStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Google Calendar OAuth and save encrypted token.")
    parser.add_argument("--client-secrets", required=True)
    parser.add_argument("--token-path", required=True)
    parser.add_argument("--passphrase", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    store = TokenStore(Path(args.token_path), args.passphrase)
    auth = OAuthUserAuth(store, args.client_secrets, args.port)
    auth.get_credentials()
    print(f"Saved encrypted Calendar token to {args.token_path}")


if __name__ == "__main__":
    main()
