import argparse
import os

from dotenv import load_dotenv

from .run import ROOT, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestrated Festival Connectivity Tracker")
    parser.add_argument("command", choices=["run"])
    parser.parse_args()
    load_dotenv(ROOT / "orchestrator" / ".env")
    required = ["RESEARCHER_URL", "RESEARCHER_TOKEN", "VERIFIER_URL", "VERIFIER_TOKEN", "TRACKER_USERNAME", "TRACKER_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing from orchestrator/.env: {', '.join(missing)}")
    run()


if __name__ == "__main__":
    main()
