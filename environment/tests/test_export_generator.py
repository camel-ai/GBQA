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
                        "hints": {
                            "weak": "Weak behavior-area hint.",
                            "medium": "Medium reproduction hint.",
                            "strong": "Strong function-level hint.",
                        },
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
            self.assertTrue((task_root / "tests" / "target_bug_found" / "check.py").exists())
            self.assertFalse((task_root / "tests" / "quality").exists())
            metadata = (task_root / "gbqa.yaml").read_text(encoding="utf-8")
            self.assertIn('benchmark_status: "draft"', metadata)
            self.assertIn('archive_url: "https://github.com/acme/flow-ui/archive/refs/tags/v1.0.0.tar.gz"', metadata)
            self.assertIn('default_provider: "daytona"', metadata)
            self.assertIn('    - "modal"', metadata)
            self.assertIn('default_mode: "terminal"', metadata)
            self.assertIn('kind: "http_api"', metadata)
            self.assertIn('method: "targeted_bug"', metadata)
            self.assertIn('target_bug_id: "acme-flow-ui"', metadata)
            self.assertIn('hint_level: "medium"', metadata)
            self.assertIn('weak: "Weak behavior-area hint."', metadata)
            self.assertIn('medium: "Medium reproduction hint."', metadata)
            self.assertIn('strong: "Strong function-level hint."', metadata)
            task_toml = (task_root / "task.toml").read_text(encoding="utf-8")
            self.assertIn('GBQA_EVAL_METHOD = "${GBQA_EVAL_METHOD:-targeted_bug}"', task_toml)
            self.assertIn('runtime_provider = "daytona"', task_toml)
            self.assertIn('supported_runtime_providers = ["daytona", "modal"]', task_toml)
            self.assertIn('target_hint_level = "medium"', task_toml)
            self.assertIn('target_hint = "Medium reproduction hint."', task_toml)
            instruction = (task_root / "instruction.md").read_text(encoding="utf-8")
            self.assertIn("/logs/agent/gbqa/issue.json", instruction)
            self.assertIn("Medium reproduction hint.", instruction)
            ground_truth = json.loads(
                (task_root / "bugs" / "ground_truth.json").read_text(encoding="utf-8")
            )
            self.assertEqual(ground_truth["target_bug"]["id"], "acme-flow-ui")
            self.assertEqual(ground_truth["target_bug"]["hint_level"], "medium")
            self.assertEqual(
                ground_truth["target_bug"]["hints"]["strong"],
                "Strong function-level hint.",
            )

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
