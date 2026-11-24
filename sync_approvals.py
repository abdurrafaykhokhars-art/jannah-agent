"""Every 30 minutes: read your Approve / Decline taps from Telegram and confirm them."""
from agent.common import run_main, sync_decisions


def main():
    print(f"{sync_decisions()} new decision(s)")


if __name__ == "__main__":
    run_main("Sync Approvals", main)
