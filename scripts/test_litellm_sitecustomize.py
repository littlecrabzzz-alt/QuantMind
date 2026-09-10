import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class LiteLLMSiteCustomizeTests(unittest.TestCase):
    def _startup_value(self, configured=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(
                REPO / "docker/litellm_sitecustomize.py", root / "sitecustomize.py"
            )
            capture = root / "captured.txt"
            package = root / "litellm/types/llms"
            package.mkdir(parents=True)
            for path in (
                root / "litellm/__init__.py",
                root / "litellm/types/__init__.py",
                package / "__init__.py",
            ):
                path.write_text("")
            (root / "litellm/types/utils.py").write_text(
                "import os\n"
                "from pathlib import Path\n"
                "Path(os.environ['CAPTURE']).write_text("
                "os.environ.get('LITELLM_LOCAL_MODEL_COST_MAP', ''))\n"
                "class Message:\n"
                "    @classmethod\n"
                "    def model_rebuild(cls):\n"
                "        pass\n"
            )
            (package / "openai.py").write_text(
                "class ChatCompletionReasoningSummaryTextBlock:\n"
                "    pass\n"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root)
            env["CAPTURE"] = str(capture)
            if configured is None:
                env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
            else:
                env["LITELLM_LOCAL_MODEL_COST_MAP"] = configured
            subprocess.run(
                [sys.executable, "-c", "pass"],
                check=True,
                env=env,
                capture_output=True,
                text=True,
            )
            return capture.read_text()

    def test_startup_defaults_to_bundled_model_cost_map(self):
        self.assertEqual(self._startup_value(), "True")

    def test_explicit_litellm_setting_is_preserved(self):
        self.assertEqual(self._startup_value("False"), "False")


if __name__ == "__main__":
    unittest.main()
