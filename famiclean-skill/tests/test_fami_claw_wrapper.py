from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch


WRAPPER_PATH = (
    Path(__file__).resolve().parent.parent / "skills" / "fami-claw-skill" / "fami-claw"
)


def load_wrapper_module():
    loader = SourceFileLoader("fami_claw_wrapper", str(WRAPPER_PATH))
    spec = importlib.util.spec_from_loader("fami_claw_wrapper", loader)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load wrapper from {WRAPPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FamiClawWrapperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wrapper = load_wrapper_module()

    def test_normalize_args_supports_gas_status_alias(self) -> None:
        self.assertEqual(
            self.wrapper.normalize_args(["gas-status"]),
            ["--json", "get-total-gas"],
        )

    def test_apply_runtime_defaults_uses_famiclean_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("DEVICE_IP=192.0.2.10\n", encoding="utf-8")

            with patch.dict(os.environ, {"FAMICLEAN_ENV_FILE": str(env_file)}, clear=False):
                result = self.wrapper.apply_runtime_defaults(Path("/tmp/famiclean-home"), ["--json", "get-total-gas"])

        self.assertEqual(
            result,
            [
                "--env-file",
                str(env_file.resolve()),
                "--home",
                "/tmp/famiclean-home",
                "--json",
                "get-total-gas",
            ],
        )

    def test_apply_runtime_defaults_keeps_explicit_env_file(self) -> None:
        result = self.wrapper.apply_runtime_defaults(
            Path("/tmp/famiclean-home"),
            ["--env-file", "/tmp/custom.env", "--json", "get-total-gas"],
        )

        self.assertEqual(
            result,
            [
                "--home",
                "/tmp/famiclean-home",
                "--env-file",
                "/tmp/custom.env",
                "--json",
                "get-total-gas",
            ],
        )


if __name__ == "__main__":
    unittest.main()
