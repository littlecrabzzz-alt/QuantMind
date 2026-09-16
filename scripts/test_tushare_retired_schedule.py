"""Execute the actual schedule block without loading credentials or Celery."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


class RetiredSchedule(unittest.TestCase):
    def test_only_tushare_is_removed_after_relocation(self):
        source = Path(__file__).resolve().parents[1] / 'backend/services/engine/qlib_app/celery_config.py'
        tree = ast.parse(source.read_text())
        start = next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign)
                     and any(isinstance(t,ast.Name) and t.id=='beat_schedule' for t in n.targets))
        end = next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Expr)
                   and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='celery_app.conf.update')
        code = compile(ast.Module(body=tree.body[start:end], type_ignores=[]), str(source), 'exec')
        for role, retired, expected in [('authority',False,True),('authority',True,False),('sandbox',False,False)]:
            values = {'os':SimpleNamespace(getenv=lambda key,default=None:role if key=='QM_NODE_ROLE' else default),
                      'Path':lambda _:SimpleNamespace(exists=lambda:retired),
                      'crontab':lambda **kwargs:kwargs,'AUTO_INFERENCE_ENABLED':False,'NEWS_ENRICH_ENABLED':False}
            exec(code, values)
            schedule=values['beat_schedule']
            self.assertEqual('tushare-acquire-continuation' in schedule,expected)
            self.assertIn('market-sync-dispatch',schedule)
            self.assertIn('market-snapshot',schedule)


if __name__ == '__main__':
    unittest.main()
