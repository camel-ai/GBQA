from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from environment.export.generator import generate_task_packages


class ExportGeneratorTests(unittest.TestCase):
    def test_generate_draft_task_package_from_approved_seed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seed_path = root / "approved_task_seeds.jsonl"
            output_dir = root / "tasks"
            seed_path.write_text(
                json.dumps(
                    {
                        "task_id": "gbqa/acme-flow-ui",
                        "slug": "acme-flow-ui",
                        "benchmark_status": "draft",
                        "repository": "https://github.com/acme/flow-ui",
                        "baseline_release": "v1.0.0",
                        "fixed_release": "v1.1.0",
                        "baseline_archive_url": "https://github.com/acme/flow-ui/archive/refs/tags/v1.0.0.tar.gz",
                        "interaction_modes": ["api"],
                        "primary_interaction_mode": "api",
                        "service": {
                            "host": "127.0.0.1",
                            "port": 8000,
                            "health_path": "/health",
                            "api_base_path": "/api",
                        },
                        "tags": {
                            "domain": ["web-productivity"],
                            "runtime": ["docker"],
                            "interaction": ["api"],
                            "benchmark": ["release-pair"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            generated = generate_task_packages(input_path=seed_path, output_dir=output_dir)

            self.assertEqual(generated, [output_dir / "acme-flow-ui"])
            task_root = output_dir / "acme-flow-ui"
            self.assertTrue((task_root / "task.toml").exists())
            self.assertTrue((task_root / "gbqa.yaml").exists())
            self.assertTrue((task_root / "instruction.md").exists())
            self.assertTrue((task_root / "environment" / "Dockerfile").exists())
            metadata = (task_root / "gbqa.yaml").read_text(encoding="utf-8")
            self.assertIn('benchmark_status: "draft"', metadata)
            self.assertIn('archive_url: "https://github.com/acme/flow-ui/archive/refs/tags/v1.0.0.tar.gz"', metadata)
            self.assertIn('default_mode: "terminal"', metadata)
            self.assertIn('kind: "http_api"', metadata)

    def test_generate_normalizes_unsafe_slug(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            seed_path = root / "approved_task_seeds.jsonl"
            output_dir = root / "tasks"
            payload = {
                "task_id": "gbqa/unsafe",
                "slug": "../unsafe task",
                "benchmark_status": "draft",
                "repository": "https://github.com/acme/unsafe",
                "baseline_release": "v1.0.0",
                "fixed_release": "v1.1.0",
                "baseline_archive_url": "https://github.com/acme/unsafe/archive/refs/tags/v1.0.0.tar.gz",
                "interaction_modes": ["api"],
                "primary_interaction_mode": "api",
            }
            seed_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            generated = generate_task_packages(input_path=seed_path, output_dir=output_dir)

            self.assertEqual(generated, [output_dir / "unsafe-task"])
            self.assertTrue((output_dir / "unsafe-task" / "gbqa.yaml").exists())


if __name__ == "__main__":
    unittest.main()
