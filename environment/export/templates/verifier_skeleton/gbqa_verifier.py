from pathlib import Path
import json


def main() -> None:
    output_dir = Path("/logs/verifier")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reward.txt").write_text("0.0\n", encoding="utf-8")
    (output_dir / "reward.json").write_text(
        json.dumps({"reward": 0.0, "status": "draft_verifier"}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
