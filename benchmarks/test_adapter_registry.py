"""Regression tests for benchmark adapter reproducibility metadata."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shibahama_bench import adapters
from shibahama_bench.adapters import AdapterMetadata, validate_adapter_registry


class AdapterRegistryTests(unittest.TestCase):
    def test_current_registry_has_metadata_for_every_adapter(self) -> None:
        validate_adapter_registry()
        self.assertEqual(set(adapters.ADAPTERS), set(adapters.ADAPTER_METADATA))
        self.assertFalse(
            [
                metadata.name
                for metadata in adapters.ADAPTER_METADATA.values()
                if metadata.is_external
            ]
        )

    def test_external_adapter_requires_declared_result_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = {
                **adapters.ADAPTER_METADATA,
                "hosted-memory": AdapterMetadata(
                    name="hosted-memory",
                    is_external=True,
                    result_artifacts=("hosted/hosted-memory-local.json",),
                ),
            }
            adapter_classes = {**adapters.ADAPTERS, "hosted-memory": adapters.WarehouseAdapter}

            with mock.patch.object(adapters, "ADAPTER_METADATA", metadata), mock.patch.object(
                adapters, "ADAPTERS", adapter_classes
            ):
                with self.assertRaisesRegex(RuntimeError, "external benchmark adapters require"):
                    validate_adapter_registry(results_root=Path(tmpdir))


if __name__ == "__main__":
    unittest.main()
