import argparse
import json
import os
import urllib.request


def _http_get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP helper for Google Drive OAuth flow")
    parser.add_argument("--api-base", default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument(
        "--namespace",
        default="google-drive",
        choices=["google-drive", "google-drive-bot"],
        help="Public namespace for connect/status routes",
    )
    parser.add_argument("--telegram-user-id", type=int, required=True, help="Telegram user id")
    args = parser.parse_args()

    connect_url = f"{args.api_base}/{args.namespace}/connect/{args.telegram_user_id}"
    status_url = f"{args.api_base}/{args.namespace}/status/{args.telegram_user_id}"

    print("1) Open this URL in a browser to connect Google Drive:")
    print(connect_url)
    print("\n2) After approving, check status:")
    print(status_url)

    if os.getenv("DOCUMIND_AUTO_CHECK_STATUS", "").strip():
        print("\nStatus response:")
        print(_http_get_json(status_url))


if __name__ == "__main__":
    main()

