"""Temporary release, real router/tool/SSE, mocked identity verifier and LLM.

Runs no service startup hooks, production credentials, provider requests or
sockets. Engine middleware and router registration execute from their real AST.
"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from fastapi import FastAPI, HTTPException, Request, status  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from backend.services.engine.routers import tushare_data  # noqa: E402
from backend.services.engine.quantbot import tushare_tool  # noqa: E402
from backend.shared import tushare_pipeline, runtime_secrets  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def engine_app():
    app = FastAPI()
    manager = Mock()
    manager.verify_token.side_effect = lambda token: (
        {"sub": "real-reader", "tenant_id": "test"} if token == "fixture-jwt" else {}
    )
    namespace = {
        "app": app,
        "Request": Request,
        "status": status,
        "JSONResponse": JSONResponse,
        "get_internal_call_secret": lambda: "fixture-internal",
        "AuthManager": lambda: manager,
        "logger": Mock(),
    }
    tree = ast.parse((ROOT / "backend/services/engine/main.py").read_text())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "auth_middleware"
    ]
    nodes += [
        node
        for node in tree.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.ImportFrom)
            and child.module == "backend.services.engine.routers.tushare_data"
            for child in ast.walk(node)
        )
    ]
    assert len(nodes) == 2, (
        "Real middleware and Tushare router registration are required"
    )
    exec(
        compile(
            ast.Module(body=nodes, type_ignores=[]), "engine-main-registration", "exec"
        ),
        namespace,
    )
    return app


class AgentIntegration(unittest.TestCase):
    def test_query_code_field_is_resolved_by_store(self):
        self.assertIsNone(
            tushare_tool.ReadArguments.model_validate(
                {
                    "action": "query",
                    "release_id": "data-" + "a" * 64,
                    "api_name": "index_weight",
                    "fields": ["index_code"],
                    "codes": ["SH000300"],
                }
            ).code_field
        )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tushare-agent-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        files = {}

        def save(family, suffix, raw):
            sha = hashlib.sha256(raw).hexdigest()
            name = f"{family}/{sha}.{suffix}"
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(raw)
            files[name] = {"sha256": sha, "bytes": len(raw)}
            return name

        sink = pa.BufferOutputStream()
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "ts_code": "SH510300",
                        "trade_date": "20260908",
                        "close": 4.2,
                        "_fetched_at": "2026-09-08T10:00:00Z",
                        "_observation": "fixture",
                    }
                ]
            ),
            sink,
        )
        parquet = save("parquet", "parquet", sink.getvalue().to_pybytes())
        self.text_path = save(
            "extracted",
            "json",
            json.dumps(
                {
                    "parse_status": "parsed",
                    "pages": [
                        {"page_number": 1, "text": "<script>untrusted</script>原文证据"}
                    ],
                }
            ).encode(),
        )
        inventory = save(
            "documents",
            "json",
            json.dumps(
                {
                    "files": [{"path": self.text_path, **files[self.text_path]}],
                    "mappings": [],
                    "counts": [],
                }
            ).encode(),
        )
        manifest = {
            "files": files,
            "datasets": [{"api_name": "fund_daily", "path": parquet}],
            "documents": {"path": inventory},
        }
        raw = json.dumps(manifest, sort_keys=True).encode()
        self.release = "data-" + hashlib.sha256(raw).hexdigest()
        path = self.root / "releases" / self.release / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
        self.addCleanup(patch.stopall)
        patch.object(tushare_data, "ROOT", self.root).start()
        self.socket = patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ).start()
        self.dns = patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")
        ).start()
        self.secret = patch.object(
            tushare_pipeline,
            "get_secret",
            side_effect=AssertionError("provider credentials forbidden"),
        ).start()
        patch.object(
            runtime_secrets,
            "get_secret",
            side_effect=AssertionError("credentials forbidden"),
        ).start()
        stubs = {}
        for name, values in {
            "backend.services.engine.quantbot.intent_parser": {
                "parse_intent": AsyncMock(return_value={"intent": "chat"})
            },
            "backend.services.engine.alpha_agent.launcher": {"get_launcher": Mock()},
            "backend.services.engine.quantbot.task_store": {
                "QuantBotTaskStore": Mock()
            },
        }.items():
            module = types.ModuleType(name)
            module.__dict__.update(values)
            stubs[name] = module
        with patch.dict(sys.modules, stubs):
            self.quantbot = load(
                "backend/services/engine/routers/quantbot_router.py",
                "candidate_quantbot_tushare",
            )
        self.app = engine_app()
        self.app.include_router(self.quantbot.router)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer fixture-jwt"}
        patch.dict(
            "os.environ",
            {
                "AI_IDE_LLM_API_KEY": "synthetic-model-key",
                "AI_IDE_LLM_BASE_URL": "https://model.invalid",
                "AI_IDE_LLM_MODEL": "fixture",
            },
        ).start()
        self.real_async = httpx.AsyncClient

    def tearDown(self):
        self.socket.assert_not_called()
        self.dns.assert_not_called()
        self.secret.assert_not_called()

    def chat(self, **values):
        return self.client.post(
            "/api/v1/quantbot/chat",
            json={
                "message": "读取已存数据",
                "tushare_release_id": self.release,
                **values,
            },
            headers=self.headers,
        )

    def mock_model(self, actions):
        calls = []

        def handle(request):
            body = json.loads(request.content)
            calls.append(body)
            if len(calls) <= len(actions):
                args = {"release_id": self.release, **actions[len(calls) - 1]}
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "id": "call" + str(len(calls)),
                                            "type": "function",
                                            "function": {
                                                "name": tushare_tool.NAME,
                                                "arguments": json.dumps(args),
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"已读取固定版本证据"}}]}\n\ndata: [DONE]\n\n',
            )

        patch.object(
            httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: self.real_async(
                transport=httpx.MockTransport(handle), **kwargs
            ),
        ).start()
        return calls

    def test_engine_registration_identity_and_real_schema_query_sse(self):
        url = "/api/v1/tushare-data/datasets"
        self.assertEqual(
            self.client.get(url, params={"release_id": self.release}).status_code, 401
        )
        self.assertEqual(
            self.client.get(
                url,
                params={"release_id": self.release},
                headers={"X-User-Id": "forged"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                url,
                params={"release_id": self.release},
                headers={"X-Internal-Call": "fixture-internal"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                url, params={"release_id": self.release}, headers=self.headers
            ).status_code,
            200,
        )
        calls = self.mock_model(
            [
                {"action": "schema", "api_name": "fund_daily"},
                {
                    "action": "query",
                    "api_name": "fund_daily",
                    "fields": ["ts_code", "close"],
                },
            ]
        )
        with patch.object(
            tushare_tool, "execute", wraps=tushare_tool.execute
        ) as execute:
            response = self.chat()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(execute.call_count, 2)
        self.assertIn('"close": 4.2', response.text)
        self.assertIn(self.release, response.text)
        self.assertIn("已读取固定版本证据", response.text)
        self.assertEqual(len(calls), 3)
        self.assertNotIn("tools", calls[-1])
        self.assertEqual(calls[0]["tools"][0]["function"]["name"], tushare_tool.NAME)

    def test_original_document_reference_and_text_reach_agent(self):
        calls = self.mock_model(
            [
                {"action": "documents", "view": "files"},
                {"action": "text", "path": self.text_path},
            ]
        )
        response = self.chat()
        self.assertIn(self.text_path, response.text)
        self.assertIn("原文证据", response.text)
        self.assertIn('"untrusted_data": true', response.text)
        self.assertIn("原文证据", calls[-1]["messages"][-1]["content"])
        self.assertEqual(
            response.headers["content-type"], "text/event-stream; charset=utf-8"
        )

    def test_no_tools_compatibility_and_unsupported_model_no_fallback(self):
        requests = self.mock_model([])
        response = self.chat(tushare_release_id=None)
        self.assertIn("已读取固定版本证据", response.text)
        self.assertEqual(len(requests), 1)
        self.assertNotIn("tools", requests[0])
        with patch.object(
            httpx,
            "AsyncClient",
            side_effect=lambda **kw: self.real_async(
                transport=httpx.MockTransport(lambda request: httpx.Response(400)), **kw
            ),
        ):
            response = self.chat()
        self.assertIn("未回退", response.text)
        self.assertNotIn('"tool_result"', response.text)

    def test_message_pin_is_explicit_and_multiple_pins_are_rejected(self):
        calls = self.mock_model(
            [
                {"action": "schema", "api_name": "fund_daily"},
                {"action": "query", "api_name": "fund_daily", "fields": ["close"]},
            ]
        )
        response = self.chat(
            tushare_release_id=None, message="读取版本 " + self.release
        )
        self.assertIn('"close": 4.2', response.text)
        self.assertEqual(len(calls), 3)
        response = self.chat(
            tushare_release_id=None, message=self.release + " data-" + "0" * 64
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(calls), 3)

    def test_tool_identity_pin_and_bounds(self):
        unauth = Request({"type": "http", "headers": []})
        with self.assertRaises(HTTPException) as denied:
            tushare_tool.execute(
                unauth,
                self.release,
                {
                    "release_id": self.release,
                    "action": "schema",
                    "api_name": "fund_daily",
                },
            )
        self.assertEqual(denied.exception.status_code, 401)
        request = Request({"type": "http", "headers": []})
        request.state.user = {"user_id": "reader", "tenant_id": "test"}
        base = {
            "release_id": self.release,
            "action": "query",
            "api_name": "fund_daily",
            "fields": ["close"],
        }
        for changed in (
            {"release_id": "data-" + "0" * 64},
            {"limit": 101},
            {"fields": ["close"] * 21},
            {"max_chars": 12001},
            {"fields": None},
            {"root": "/etc"},
            {"fields": ["close);DROP TABLE stored;--"]},
        ):
            with self.assertRaises((HTTPException, ValueError)):
                tushare_tool.execute(request, self.release, {**base, **changed})
        for api_name in ("p_list", "p_get"):
            with self.assertRaises(HTTPException) as private:
                tushare_tool.execute(
                    request,
                    self.release,
                    {**base, "api_name": api_name},
                )
            self.assertEqual(private.exception.status_code, 404)
            self.assertEqual(private.exception.detail, "Dataset unavailable")
        self.assertEqual(
            self.client.post(
                "/api/v1/quantbot/chat",
                json={"message": "x", "tushare_release_id": self.release},
            ).status_code,
            401,
        )
        with patch.object(
            tushare_data, "schema", return_value={"fields": [{"name": "x" * 25000}]}
        ):
            result = tushare_tool.execute(
                request,
                self.release,
                {
                    "release_id": self.release,
                    "action": "schema",
                    "api_name": "fund_daily",
                },
            )
        self.assertEqual(result["error"], "response_limit")
        self.assertLess(len(json.dumps(result)), tushare_tool.MAX_RESULT_CHARS)

    def test_gateway_route_strips_forged_identity_and_forwards_verified_identity(self):
        auth = types.ModuleType("backend.services.api.user_app.middleware.auth")

        async def optional(request: Request):
            return (
                {"user_id": "gateway-reader", "tenant_id": "test"}
                if request.headers.get("authorization") == "Bearer fixture-jwt"
                else None
            )

        auth.get_optional_user = optional
        shared = types.ModuleType("backend.shared.auth")
        shared.get_internal_call_secret = lambda: "fixture-internal"
        with patch.dict(sys.modules, {auth.__name__: auth, shared.__name__: shared}):
            proxy = load(
                "backend/services/api/routers/engine_proxy.py",
                "candidate_tushare_proxy",
            )
        proxy.ENGINE_BASE_URL = "http://engine.test"
        forwarded = []

        @self.app.middleware("http")
        async def capture_headers(request, call_next):
            forwarded.append(dict(request.headers))
            return await call_next(request)

        with patch.object(
            httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: self.real_async(
                transport=httpx.ASGITransport(app=self.app), **kwargs
            ),
        ):
            gateway = FastAPI()
            gateway.include_router(proxy.router)
            with TestClient(gateway) as client:
                path = "/api/v1/tushare-data/datasets"
                self.assertEqual(
                    client.get(
                        path,
                        params={"release_id": self.release},
                        headers={"X-User-Id": "forged"},
                    ).status_code,
                    401,
                )
                response = client.get(
                    path,
                    params={"release_id": self.release},
                    headers={
                        **self.headers,
                        "X-User-Id": "forged",
                        "X-Internal-Call": "forged",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.json()["datasets"][0]["api_name"], "fund_daily"
                )
                self.assertEqual(forwarded[-1]["x-user-id"], "gateway-reader")
                self.assertEqual(forwarded[-1]["x-internal-call"], "fixture-internal")


if __name__ == "__main__":
    unittest.main()
