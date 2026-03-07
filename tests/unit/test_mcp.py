"""Tests for MCP protocol module."""

import unittest

from pylon.protocols.mcp import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    AuthorizationCode,
    InitializeResult,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    McpClient,
    McpServer,
    McpSession,
    MethodRouter,
    OAuthClientConfig,
    OAuthProvider,
    OAuthServerConfig,
    PKCEChallenge,
    PromptDefinition,
    ResourceDefinition,
    SessionManager,
    ServerCapabilities,
    TokenResponse,
    ToolDefinition,
    route,
)


class TestJsonRpcTypes(unittest.TestCase):
    def test_request_construction(self):
        req = JsonRpcRequest(method="tools/list", id=1)
        self.assertEqual(req.jsonrpc, "2.0")
        self.assertEqual(req.method, "tools/list")
        self.assertEqual(req.id, 1)
        self.assertIsNone(req.params)

    def test_request_with_params(self):
        req = JsonRpcRequest(method="tools/call", params={"name": "echo"}, id="abc")
        d = req.to_dict()
        self.assertEqual(d["method"], "tools/call")
        self.assertEqual(d["params"]["name"], "echo")
        self.assertEqual(d["id"], "abc")

    def test_response_success(self):
        resp = JsonRpcResponse(result={"ok": True}, id=1)
        d = resp.to_dict()
        self.assertEqual(d["result"], {"ok": True})
        self.assertNotIn("error", d)

    def test_response_error(self):
        resp = JsonRpcResponse(
            error=JsonRpcError(code=-32601, message="Not found"), id=1
        )
        d = resp.to_dict()
        self.assertEqual(d["error"]["code"], -32601)
        self.assertNotIn("result", d)

    def test_error_with_data(self):
        err = JsonRpcError(code=-32603, message="fail", data={"detail": "x"})
        d = err.to_dict()
        self.assertEqual(d["data"], {"detail": "x"})


class TestMethodRouter(unittest.TestCase):
    def setUp(self):
        self.router = MethodRouter()

    def test_register_and_dispatch(self):
        self.router.register("echo", lambda req: req.params)
        req = JsonRpcRequest(method="echo", params={"msg": "hi"}, id=1)
        resp = self.router.dispatch(req)
        self.assertEqual(resp.result, {"msg": "hi"})
        self.assertIsNone(resp.error)

    def test_method_not_found(self):
        req = JsonRpcRequest(method="nonexistent", id=2)
        resp = self.router.dispatch(req)
        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error.code, METHOD_NOT_FOUND)

    def test_list_methods(self):
        self.router.register("b_method", lambda r: None)
        self.router.register("a_method", lambda r: None)
        self.assertEqual(self.router.list_methods(), ["a_method", "b_method"])

    def test_handler_exception(self):
        def failing(req):
            raise ValueError("boom")

        self.router.register("fail", failing)
        req = JsonRpcRequest(method="fail", id=3)
        resp = self.router.dispatch(req)
        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error.code, INTERNAL_ERROR)

    def test_route_decorator(self):
        @route("tools/list")
        def handler(req):
            return []

        self.assertEqual(handler._rpc_method, "tools/list")


class TestMcpServer(unittest.TestCase):
    def setUp(self):
        self.server = McpServer(name="test-server", version="1.0.0")

    def test_initialize_handshake(self):
        req = JsonRpcRequest(method="initialize", params={"capabilities": {}}, id=1)
        resp = self.server.handle_request(req)
        self.assertIsNone(resp.error)
        self.assertEqual(resp.result["protocolVersion"], "2025-11-25")
        self.assertEqual(resp.result["serverInfo"]["name"], "test-server")
        self.assertIn("sessionId", resp.result)

    def test_tools_list_empty(self):
        req = JsonRpcRequest(method="tools/list", id=2)
        resp = self.server.handle_request(req)
        self.assertEqual(resp.result["tools"], [])

    def test_tools_register_and_list(self):
        tool = ToolDefinition(
            name="echo",
            description="Echo tool",
            inputSchema={"type": "object", "properties": {"msg": {"type": "string"}}},
        )
        self.server.register_tool(tool, handler=lambda args: args["msg"])

        req = JsonRpcRequest(method="tools/list", id=3)
        resp = self.server.handle_request(req)
        tools = resp.result["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "echo")

    def test_tools_call(self):
        tool = ToolDefinition(name="add", description="Add two numbers")
        self.server.register_tool(
            tool, handler=lambda args: args["a"] + args["b"]
        )
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "add", "arguments": {"a": 2, "b": 3}},
            id=4,
        )
        resp = self.server.handle_request(req)
        self.assertEqual(resp.result, 5)

    def test_tools_call_not_found(self):
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "missing", "arguments": {}},
            id=5,
        )
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error.code, INTERNAL_ERROR)

    def test_resources_list_and_read(self):
        resource = ResourceDefinition(
            uri="file:///readme.md",
            name="README",
            description="Project readme",
            mimeType="text/markdown",
        )
        self.server.register_resource(
            resource, handler=lambda uri: {"content": "# Hello"}
        )

        req_list = JsonRpcRequest(method="resources/list", id=6)
        resp = self.server.handle_request(req_list)
        self.assertEqual(len(resp.result["resources"]), 1)
        self.assertEqual(resp.result["resources"][0]["uri"], "file:///readme.md")

        req_read = JsonRpcRequest(
            method="resources/read",
            params={"uri": "file:///readme.md"},
            id=7,
        )
        resp = self.server.handle_request(req_read)
        self.assertEqual(resp.result, {"content": "# Hello"})

    def test_resources_read_not_found(self):
        req = JsonRpcRequest(
            method="resources/read", params={"uri": "missing"}, id=8
        )
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp.error)

    def test_prompts_list_and_get(self):
        prompt = PromptDefinition(
            name="greet", description="Greeting prompt"
        )
        self.server.register_prompt(
            prompt,
            handler=lambda name, args: {
                "messages": [{"role": "user", "content": f"Hello {args.get('name', 'world')}"}]
            },
        )

        req_list = JsonRpcRequest(method="prompts/list", id=9)
        resp = self.server.handle_request(req_list)
        self.assertEqual(len(resp.result["prompts"]), 1)
        self.assertEqual(resp.result["prompts"][0]["name"], "greet")

        req_get = JsonRpcRequest(
            method="prompts/get",
            params={"name": "greet", "arguments": {"name": "Alice"}},
            id=10,
        )
        resp = self.server.handle_request(req_get)
        self.assertEqual(
            resp.result["messages"][0]["content"], "Hello Alice"
        )

    def test_prompts_get_not_found(self):
        req = JsonRpcRequest(
            method="prompts/get", params={"name": "missing"}, id=11
        )
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp.error)

    def test_unknown_method(self):
        req = JsonRpcRequest(method="unknown/method", id=12)
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error.code, METHOD_NOT_FOUND)


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager()

    def test_create_session(self):
        session = self.manager.create_session()
        self.assertIsInstance(session, McpSession)
        self.assertIsNotNone(session.session_id)
        self.assertIsNotNone(session.created_at)

    def test_get_session(self):
        session = self.manager.create_session()
        retrieved = self.manager.get_session(session.session_id)
        self.assertEqual(retrieved.session_id, session.session_id)

    def test_get_nonexistent_session(self):
        self.assertIsNone(self.manager.get_session("nonexistent"))

    def test_delete_session(self):
        session = self.manager.create_session()
        self.assertTrue(self.manager.delete_session(session.session_id))
        self.assertIsNone(self.manager.get_session(session.session_id))

    def test_delete_nonexistent_session(self):
        self.assertFalse(self.manager.delete_session("nonexistent"))


class TestMcpClientServerIntegration(unittest.TestCase):
    def setUp(self):
        self.server = McpServer(name="integration-test", version="0.1.0")
        self.server.register_tool(
            ToolDefinition(name="multiply", description="Multiply two numbers"),
            handler=lambda args: args["x"] * args["y"],
        )
        self.server.register_resource(
            ResourceDefinition(
                uri="config://app",
                name="App Config",
                description="Application configuration",
                mimeType="application/json",
            ),
            handler=lambda uri: {"debug": True, "version": "1.0"},
        )
        self.server.register_prompt(
            PromptDefinition(name="summarize", description="Summarize text"),
            handler=lambda name, args: {
                "messages": [
                    {"role": "user", "content": f"Summarize: {args.get('text', '')}"}
                ]
            },
        )
        self.client = McpClient()
        self.client.connect(self.server)

    def test_initialize(self):
        result = self.client.initialize()
        self.assertIsInstance(result, InitializeResult)
        self.assertEqual(result.protocolVersion, "2025-11-25")
        self.assertTrue(result.capabilities.tools)

    def test_list_and_call_tool(self):
        self.client.initialize()
        result = self.client.list_tools()
        tools = result["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "multiply")

        call_result = self.client.call_tool("multiply", {"x": 6, "y": 7})
        self.assertEqual(call_result, 42)

    def test_list_and_read_resource(self):
        self.client.initialize()
        result = self.client.list_resources()
        resources = result["resources"]
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["uri"], "config://app")

        read_result = self.client.read_resource("config://app")
        self.assertEqual(read_result["debug"], True)

    def test_list_and_get_prompt(self):
        self.client.initialize()
        result = self.client.list_prompts()
        prompts = result["prompts"]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["name"], "summarize")

        get_result = self.client.get_prompt("summarize", {"text": "hello world"})
        self.assertIn("Summarize: hello world", get_result["messages"][0]["content"])

    def test_call_nonexistent_tool(self):
        self.client.initialize()
        with self.assertRaises(RuntimeError):
            self.client.call_tool("nonexistent", {})

    def test_client_close(self):
        self.client.initialize()
        self.client.close()
        self.client._auto_reconnect = False
        with self.assertRaises(RuntimeError):
            self.client.list_tools()


class TestPKCEChallenge(unittest.TestCase):
    def test_generate(self):
        pkce = PKCEChallenge.generate()
        self.assertTrue(len(pkce.code_verifier) > 0)
        self.assertTrue(len(pkce.code_challenge) > 0)
        self.assertEqual(pkce.code_challenge_method, "S256")

    def test_verify_valid(self):
        pkce = PKCEChallenge.generate()
        self.assertTrue(pkce.verify(pkce.code_verifier))

    def test_verify_invalid(self):
        pkce = PKCEChallenge.generate()
        self.assertFalse(pkce.verify("wrong-verifier"))


class TestOAuthProvider(unittest.TestCase):
    def setUp(self):
        self.provider = OAuthProvider()
        self.client = OAuthClientConfig(
            client_id="test-client",
            client_secret="test-secret",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read", "mcp:write"],
        )
        self.provider.register_client(self.client)

    def test_register_and_get_client(self):
        c = self.provider.get_client("test-client")
        self.assertIsNotNone(c)
        self.assertEqual(c.client_id, "test-client")

    def test_get_unknown_client(self):
        self.assertIsNone(self.provider.get_client("unknown"))

    def test_full_auth_flow(self):
        pkce = PKCEChallenge.generate()

        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        self.assertIsNotNone(code)

        token = self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        self.assertIsNotNone(token)
        self.assertIsInstance(token, TokenResponse)
        self.assertEqual(token.token_type, "Bearer")
        self.assertTrue(len(token.access_token) > 0)
        self.assertTrue(len(token.refresh_token) > 0)

    def test_validate_token(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        token = self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        meta = self.provider.validate_token(token.access_token)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["client_id"], "test-client")

    def test_validate_invalid_token(self):
        self.assertIsNone(self.provider.validate_token("bad-token"))

    def test_revoke_token(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        token = self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        self.assertTrue(self.provider.revoke_token(token.access_token))
        self.assertIsNone(self.provider.validate_token(token.access_token))

    def test_revoke_nonexistent_token(self):
        self.assertFalse(self.provider.revoke_token("nonexistent"))

    def test_refresh_token(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        token = self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        new_token = self.provider.refresh_access_token(token.refresh_token)
        self.assertIsNotNone(new_token)
        self.assertNotEqual(new_token.access_token, token.access_token)
        # Old token should be invalid
        self.assertIsNone(self.provider.validate_token(token.access_token))
        # New token should be valid
        self.assertIsNotNone(self.provider.validate_token(new_token.access_token))

    def test_refresh_invalid_token(self):
        self.assertIsNone(self.provider.refresh_access_token("bad-refresh"))

    def test_exchange_wrong_verifier(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        token = self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier="wrong-verifier",
        )
        self.assertIsNone(token)

    def test_exchange_wrong_client(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        token = self.provider.exchange_code(
            code=code,
            client_id="wrong-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        self.assertIsNone(token)

    def test_exchange_code_single_use(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        # Second use should fail
        token2 = self.provider.exchange_code(
            code=code,
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            code_verifier=pkce.code_verifier,
        )
        self.assertIsNone(token2)

    def test_auth_code_unknown_client(self):
        pkce = PKCEChallenge.generate()
        code = self.provider.create_authorization_code(
            client_id="unknown",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge=pkce.code_challenge,
        )
        self.assertIsNone(code)

    def test_dcr_disabled_by_default(self):
        result = self.provider.dynamic_client_registration(
            redirect_uris=["http://localhost:9090/callback"],
            scope="mcp:read",
        )
        self.assertIsNone(result)

    def test_dcr_enabled(self):
        config = OAuthServerConfig(dcr_enabled=True)
        provider = OAuthProvider(config=config)
        client = provider.dynamic_client_registration(
            redirect_uris=["http://localhost:9090/callback"],
            scope="tools:read resources:read",
        )
        self.assertIsNotNone(client)
        self.assertTrue(len(client.client_id) > 0)
        self.assertTrue(len(client.client_secret) > 0)
        self.assertEqual(client.scopes, ["tools:read", "resources:read"])
        # Should be retrievable
        self.assertIsNotNone(provider.get_client(client.client_id))

    def test_only_s256_supported(self):
        code = self.provider.create_authorization_code(
            client_id="test-client",
            redirect_uri="http://localhost:8080/callback",
            scopes=["mcp:read"],
            code_challenge="plain-challenge",
            code_challenge_method="plain",
        )
        self.assertIsNone(code)


class TestMcpPagination(unittest.TestCase):
    """Tests for MCP server pagination edge cases."""

    def setUp(self):
        self.server = McpServer()
        for i in range(5):
            self.server.register_tool(ToolDefinition(
                name=f"tool-{i}",
                description=f"Tool {i}",
                inputSchema={"type": "object"},
            ))

    def test_negative_cursor_clamped_to_zero(self):
        """Negative cursor values must be treated as 0, not cause unexpected slicing."""
        result = self.server._paginate(list(range(10)), cursor="-5", page_size=3)
        page, next_cursor = result
        # Should return items from index 0, not negative index
        assert page == [0, 1, 2]
        assert next_cursor == "3"


if __name__ == "__main__":
    unittest.main()
