"""Optional selection credentials must not prevent unrelated engine routes loading."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class SelectionConfigurationBoundary(unittest.TestCase):
    def run_without_credentials(self, code):
        environment = os.environ.copy()
        for key in ('LLM_API_KEY', 'DASHSCOPE_API_KEY', 'QWEN_API_KEY', 'OPENAI_API_KEY'):
            environment[key] = ''
        root = Path(__file__).resolve().parents[3]
        environment['PYTHONPATH'] = str(root) + os.pathsep + environment.get('PYTHONPATH', '')
        result = subprocess.run([sys.executable, '-c', code], cwd=root, env=environment,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_selection_import_does_not_construct_an_optional_llm_client(self):
        self.run_without_credentials('''
from backend.services.engine.ai_strategy.services.selection import dashscope_client
from backend.services.engine.ai_strategy.services.selection import schema_retriever
from backend.services.engine.ai_strategy.services.selection import vector_parser
''')

    def test_actual_client_still_rejects_missing_configuration(self):
        self.run_without_credentials('''
from backend.services.engine.ai_strategy.services.selection.dashscope_client import DashScopeClient
try:
    DashScopeClient()
except ValueError as error:
    assert 'LLM_API_KEY' in str(error), str(error)
else:
    raise AssertionError('An unconfigured real LLM client must not be usable')
''')


if __name__ == '__main__':
    unittest.main()
