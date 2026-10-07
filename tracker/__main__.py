import argparse
import os

from dotenv import load_dotenv

from .runtime import ROOT, run_tracker
from .state_client import StateClient
from .tools import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Festival Connectivity Tracker")
    parser.add_argument("command", choices=["run", "reset"])
    args = parser.parse_args()
    if args.command == "run":
        run_tracker()
        return
    load_dotenv(ROOT / "tracker" / ".env")
    config = load_config(str(ROOT / "tracker" / "config.yaml"))
    client = StateClient(os.getenv("BACKEND_URL", "http://127.0.0.1:8000"), os.environ["TRACKER_USERNAME"], os.environ["TRACKER_PASSWORD"], config["limits"]["max_retries"])
    print(client.reset())


if __name__ == "__main__":
    main()

