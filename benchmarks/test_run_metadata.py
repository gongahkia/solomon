"""Regression tests for benchmark run metadata."""

from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


def load_run_module():
    module_path = Path(__file__).with_name("run.py")
    spec = importlib.util.spec_from_file_location("benchmarks_run", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load benchmarks/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunMetadataTests(unittest.TestCase):
    def test_dataset_metadata_hashes_external_file(self) -> None:
        run = load_run_module()

        with tempfile.TemporaryDirectory() as tmpdir:
            dataset = Path(tmpdir) / "dataset.json"
            payload = b'{"cases":[]}\n'
            dataset.write_bytes(payload)

            metadata = run.dataset_metadata(dataset)

        self.assertEqual(metadata["dataset"], str(dataset))
        self.assertEqual(metadata["dataset_source"], "external-file")
        self.assertEqual(metadata["dataset_bytes"], len(payload))
        self.assertEqual(metadata["dataset_sha256"], hashlib.sha256(payload).hexdigest())

    def test_dataset_metadata_marks_builtin_suites(self) -> None:
        run = load_run_module()

        metadata = run.dataset_metadata(None)

        self.assertEqual(metadata["dataset_source"], "built-in")
        self.assertIsNone(metadata["dataset_sha256"])


if __name__ == "__main__":
    unittest.main()
