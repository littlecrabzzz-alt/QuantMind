"""Isolated PostgreSQL + HTTP checks. No credentials, model calls or research compute.
Apply research_workbench_v1.sql and v2.sql to disposable research_test first.
DATABASE_URL=.../research_test PYTHONPATH=.:scripts python3 scripts/test_research_drafts.py
"""
import asyncio
from copy import deepcopy
import json
import logging
logging.disable(logging.CRITICAL)
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
from uuid import uuid4

assert os.environ.get('DATABASE_URL', '').endswith('/research_test'), 'Disposable DB required'
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from backend.shared.database_manager_v2 import get_session
from backend.services.engine.research import runtime
from backend.services.engine.research.drafts import DraftStore
from backend.services.engine.research.planning import admission, inventory, Plan
from backend.services.engine.research.store import Store
from backend.services.engine.routers import research_runs as h
from backend.services.engine.routers import research_drafts as api


async def main():
    node = uuid4().hex
    cfg = dict(node_id=node, snapshot_id='test-fixed', manifest_sha256='abc', label='Disposable test', source='test-only', image={})
    base = dict(market='CN', universe={'size': 100}, features=['mom_ret_20d', 'amt_ratio_5_20'],
                split={'train': ['2023', '2024'], 'valid': ['2025-01', '2025-03'], 'test': ['2025-04', '2025-06']},
                portfolio={'initial_capital': 10000000}, exchange={})
    available = inventory(cfg, base)
    p = dict(title='检验动量和成交量', question='在固定模板内检验组合增量', subject='100只固定A股，固定训练/验证/开发比较区间',
             method='固定公式计算并与基线对照', baselines=['20日动量', '同池等权'], steps=['复现基线', '计算并比较因子'],
             outputs=['计算指标及证据文件'], criteria=['固定开发门槛'], limitations=['不代表独立验证'], questions=[],
             requirements={'dataset': 'current_frozen_template', 'executor': 'factor_expression', 'features': base['features'], 'missing': []},
             expression='rank(mom_ret_20d) * rank(amt_ratio_5_20)')
    assert admission(p, available)['ready']
    for changes in ({'dataset': 'other'}, {'executor': 'unavailable'}, {'features': ['missing_field']}, {'missing': ['新数据']}):
        blocked = deepcopy(p); blocked['requirements'].update(changes)
        assert not admission(blocked, available)['ready']
    for field, value in [('questions', ['待决定']), ('expression', '__import__("os")'), ('expression', 'lag(mom_ret_20d, -1)')]:
        assert not admission({**p, field: value}, available)['ready']
    d, store = DraftStore(), Store()
    owner = ('test-tenant', 'test-user')
    app = FastAPI(); app.include_router(h.router)
    with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, 'ROOT', Path(tmp)), patch.object(runtime, 'settings', return_value=cfg), \
            patch.object(runtime, 'models', return_value=['glm-5.3-flash']), \
            patch.object(runtime, 'credentials', return_value={'base_url': 'https://invalid.example/no-calls'}), \
            patch.object(h, 'owner', side_effect=lambda r: ('test-tenant', r.headers.get('test-user', 'test-user'))):
        target = Path(tmp) / 'inputs/test-fixed/snapshot/config.json'; target.parent.mkdir(parents=True); target.write_text(json.dumps(base))
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            root = '/api/v1/research-runs'
            async def count():
                return len(await store.get(owner, node))
            input_data = dict(question='一个全新的问题', subject='尚未确定', material='')
            responses = await asyncio.gather(*(client.post(root+'/drafts', json=input_data) for _ in range(6)))
            assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
            ids = {r.json()['draft_id'] for r in responses}; assert len(ids) == 1
            ident = ids.pop(); path = root+'/drafts/'+ident
            assert await count() == 0, 'Saving input started research'
            assert (await client.get(path, headers={'test-user': 'other'})).status_code == 404
            assert (await client.get(path, headers={'X-Research-Node': 'other'})).status_code == 409
            assert (await client.post(root+'/drafts', json={'question': ' '})).status_code == 422
            assert (await client.post(root, json={'idempotency_key': 'old-client-key', 'node_id': node, 'kind': 'strategy'})).status_code == 409
            assert (await client.post(path+'/execute', json={'key': 'approve-key', 'version': 1, 'reviewed': True})).status_code == 409
            async def msg(mode, content='讨论', key=None):
                current = (await client.get(path)).json()
                body = dict(key=key or uuid4().hex, revision=current['revision'], mode=mode, content=content, model='glm-5.3-flash')
                r = await client.post(path+'/messages', json=body)
                assert r.status_code == 200, r.text
                return body
            async def answer(plan):
                row = await d.claim(node, 'test-lease'); assert row
                await d.complete(row, 'test-lease', reply={'answer': '已根据现有材料整理。', 'plan': plan})
            body = await msg('ask')
            assert (await client.post(path+'/messages', json=body)).status_code == 200
            assert (await client.post(path+'/messages', json={**body, 'content': 'conflict'})).status_code == 409
            await answer(p)  # Even a model incorrectly returns a plan in ask mode: ignore it.
            detail = (await client.get(path)).json(); assert not detail['plans'] and await count() == 0
            assert (await client.post(path+'/messages', json={**body, 'key': uuid4().hex})).status_code == 409
            await msg('plan'); blocked = deepcopy(p); blocked['requirements']['dataset'] = 'other'; await answer(blocked)
            approval = dict(key=uuid4().hex, version=1, reviewed=True, hours=.1, candidate_limit=1)
            assert (await client.post(path+'/execute', json=approval)).status_code == 409
            await msg('revise'); await answer(p)
            approval['version'] = 2
            assert (await client.post(path+'/execute', json={**approval, 'reviewed': False})).status_code == 422
            assert (await client.post(path+'/execute', json={**approval, 'version': 1})).status_code == 409
            assert await count() == 0
            with patch.object(api, 'current_inventory', return_value={**available, 'manifest_sha256': 'changed'}):
                assert (await client.post(path+'/execute', json=approval)).status_code == 409
            # Failure saving approval must also roll back the new run/case.
            try:
                with patch.object(api.drafts, 'save', side_effect=RuntimeError('simulated write failure')):
                    await client.post(path+'/execute', json=approval)
                raise AssertionError('Expected transaction failure')
            except RuntimeError:
                pass
            assert await count() == 0, 'Orphan execution survived rollback'
            responses = await asyncio.gather(*(client.post(path+'/execute', json={**approval, 'key': uuid4().hex}) for _ in range(6)))
            assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
            run_ids = {r.json()['run_id'] for r in responses}; assert len(run_ids) == 1 and await count() == 1
            run = run_ids.pop()
            assert (await client.post(root+'/'+run+'/continue-window', json={'node_id': node, 'hours': .1, 'idempotency_key': uuid4().hex})).status_code == 409
            before = deepcopy((await client.get(path)).json()['plans'])
            await msg('ask', '进展如何'); await answer(None)
            assert (await store.get(owner, node, run))[0]['status'] == 'queued'
            assert (await client.get(path)).json()['plans'] == before
            # Both endpoints that generate a plan must request pause; cancellation wins over late model results.
            await msg('plan', '调整方法')
            assert (await store.get(owner, node, run))[0]['status'] == 'pause_requested'
            row = await d.claim(node, 'late-response'); assert row
            await client.post(path+'/messages/cancel')
            await d.complete(row, 'late-response', reply={'answer': 'late', 'plan': p})
            assert len((await client.get(path)).json()['plans']) == 2
            assert (await client.post(path+'/execute', json=approval)).status_code == 409
            await msg('revise'); await answer({**p, 'title': '第三版'})
            assert (await client.post(path+'/execute', json={**approval, 'version': 3})).status_code == 409, 'Old active run overlapped new version'
            async with get_session() as db:
                await db.execute(text("UPDATE research_windows SET status='paused' WHERE run_id=:id"), {'id': run})
            third = await client.post(path+'/execute', json={**approval, 'version': 3}); assert third.status_code == 200, third.text
            run3 = third.json()['run_id']; assert run3 != run and await count() == 2
            async with get_session() as db:
                await db.execute(text("UPDATE research_windows SET status='paused' WHERE run_id=:id"), {'id': run3})
            resume = dict(approval, version=3, action='resume', parent_run_id=run3)
            resumed = await asyncio.gather(*(client.post(path+'/execute', json=resume) for _ in range(4)))
            assert all(r.status_code == 200 for r in resumed), [r.text for r in resumed]
            assert len({r.json()['run_id'] for r in resumed}) == 1 and await count() == 3
            assert (await client.post(path+'/execute', json={**resume, 'key': uuid4().hex})).status_code == 409
            latest_run = resumed[0].json()['run_id']
            async with get_session() as db:
                await db.execute(text("UPDATE research_windows SET status='paused' WHERE run_id=:id"), {'id': latest_run})
            next_resume = await client.post(path+'/execute', json={**resume, 'key': uuid4().hex, 'parent_run_id': latest_run})
            assert next_resume.status_code == 200, next_resume.text
            replay = await client.post(path+'/execute', json=resume)
            assert replay.json()['run_id'] == next_resume.json()['run_id'], 'Replay rewound active pointer'
            current = (await client.get(path)).json()
            assert current['run_id'] == next_resume.json()['run_id']
            assert current['plans'][:2] == before
    print('PASS: input dedupe, ownership/node isolation, discussion-only, plan versions, missing resources, explicit approval, atomic rollback, concurrent start/resume, pause on revision, late cancellation, stale-client closure')

if __name__ == '__main__':
    asyncio.run(main())
