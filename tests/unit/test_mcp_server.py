"""Comprehensive tests for MCP server with all 4 primitives and OAuth 2.1."""

import pytest

from pylon.protocols.mcp.auth import (
    OAuthClientConfig,
    OAuthProvider,
    PKCEChallenge,
    check_scope,
    expand_scopes,
)
from pylon.protocols.mcp.client import McpClient
from pylon.protocols.mcp.server import DEFAULT_PAGE_SIZE, FORBIDDEN, UNAUTHORIZED, McpServer
from pylon.protocols.mcp.session import SessionManager
from pylon.protocols.mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    JsonRpcRequest,
    PromptArgument,
    PromptDefinition,
    ResourceDefinition,
    ResourceTemplate,
    SamplingResponse,
    ToolDefinition,
)

# --- helpers ---


def _make_server_with_all() -> McpServer:
    """Create a server with tools, resources, prompts, and sampling."""
    server = McpServer()

    server.register_tool(
        ToolDefinition(name="echo", description="Echo input", input_schema={"type": "object"}),
        handler=lambda args: {"echo": args.get("text", "")},
    )
    server.register_tool(
        ToolDefinition(name="add", description="Add numbers", input_schema={"type": "object"}),
        handler=lambda args: {"result": args.get("a", 0) + args.get("b", 0)},
    )

    server.register_resource(
        ResourceDefinition(
            uri="file:///readme",
            name="readme",
            description="README",
            mime_type="text/plain",
        ),
        handler=lambda uri: {"contents": [{"uri": uri, "text": "Hello World"}]},
    )

    server.register_resource_template(
        ResourceTemplate(uri_template="file:///docs/{name}", name="docs", description="Doc files")
    )

    server.register_prompt(
        PromptDefinition(
            name="greeting",
            description="Generate greeting",
            arguments=[PromptArgument(name="name", description="User name", required=True)],
        ),
        handler=lambda name, args: {
            "messages": [{"role": "user", "content": f"Hello {args.get('name', 'World')}"}]
        },
    )

    server.register_sampling_handler(
        lambda req: SamplingResponse(
            role="assistant",
            content=f"Response to: {req.messages[0].content if req.messages else 'empty'}",
            model="test-model",
            stop_reason="end_turn",
        )
    )

    return server


def _get_token(oauth: OAuthProvider, scopes: list[str]) -> str:
    """Get an access token with the given scopes via full PKCE flow."""
    client = OAuthClientConfig(
        client_id="test-client",
        client_secret="test-secret",
        redirect_uri="http://localhost/callback",
        scopes=scopes,
    )
    oauth.register_client(client)
    pkce = PKCEChallenge.generate()
    code = oauth.create_authorization_code(
        client_id="test-client",
        redirect_uri="http://localhost/callback",
        scopes=scopes,
        code_challenge=pkce.code_challenge,
    )
    assert code is not None
    token_resp = oauth.exchange_code(
        code=code,
        client_id="test-client",
        redirect_uri="http://localhost/callback",
        code_verifier=pkce.code_verifier,
    )
    assert token_resp is not None
    return token_resp.access_token


# ===== 1. Initialize =====


class TestInitialize:
    def test_initialize_returns_capabilities(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(method="initialize", params={"capabilities": {}}, id=1)
        resp = server.handle_request(req)
        assert resp.error is None
        assert resp.result["capabilities"]["tools"] is True
        assert resp.result["capabilities"]["resources"] is True
        assert resp.result["capabilities"]["prompts"] is True
        assert resp.result["capabilities"]["sampling"] is True
        assert "sessionId" in resp.result
        assert resp.headers.get("Mcp-Session-Id") == resp.result["sessionId"]

    def test_initialize_server_info(self):
        server = McpServer(name="my-server", version="1.0.0")
        req = JsonRpcRequest(method="initialize", params={}, id=1)
        resp = server.handle_request(req)
        assert resp.result["serverInfo"]["name"] == "my-server"
        assert resp.result["serverInfo"]["version"] == "1.0.0"

    def test_initialize_empty_server(self):
        server = McpServer()
        req = JsonRpcRequest(method="initialize", params={}, id=1)
        resp = server.handle_request(req)
        caps = resp.result["capabilities"]
        assert caps["tools"] is False
        assert caps["resources"] is False
        assert caps["prompts"] is False
        assert caps["sampling"] is False


# ===== 2. Tools =====


class TestTools:
    def test_list_tools(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req)
        tools = resp.result["tools"]
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"echo", "add"}

    def test_call_tool_echo(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"text": "hello"}},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.result == {"echo": "hello"}

    def test_call_tool_add(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "add", "arguments": {"a": 3, "b": 7}},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.result == {"result": 10}

    def test_call_tool_not_found(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "nonexistent", "arguments": {}},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == INTERNAL_ERROR


# ===== 3. Resources =====


class TestResources:
    def test_list_resources(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(method="resources/list", id=1)
        resp = server.handle_request(req)
        resources = resp.result["resources"]
        assert len(resources) == 1
        assert resources[0]["uri"] == "file:///readme"

    def test_read_resource(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="resources/read",
            params={"uri": "file:///readme"},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.result["contents"][0]["text"] == "Hello World"

    def test_read_resource_not_found(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="resources/read",
            params={"uri": "file:///nonexistent"},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None

    def test_subscribe_resource(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="resources/subscribe",
            params={"uri": "file:///readme", "sessionId": "sess-1"},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.result["subscribed"] is True
        assert resp.result["uri"] == "file:///readme"

    def test_subscribe_nonexistent_resource(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="resources/subscribe",
            params={"uri": "file:///nope"},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None

    def test_list_resource_templates(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(method="resources/templates/list", id=1)
        resp = server.handle_request(req)
        templates = resp.result["resourceTemplates"]
        assert len(templates) == 1
        assert templates[0]["uriTemplate"] == "file:///docs/{name}"


# ===== 4. Prompts =====


class TestPrompts:
    def test_list_prompts(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(method="prompts/list", id=1)
        resp = server.handle_request(req)
        prompts = resp.result["prompts"]
        assert len(prompts) == 1
        assert prompts[0]["name"] == "greeting"

    def test_get_prompt(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="prompts/get",
            params={"name": "greeting", "arguments": {"name": "Alice"}},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.result["messages"][0]["content"] == "Hello Alice"

    def test_get_prompt_not_found(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="prompts/get",
            params={"name": "nonexistent"},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None


# ===== 5. Sampling =====


class TestSampling:
    def test_create_sampling_message(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="sampling/createMessage",
            params={
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "maxTokens": 100,
            },
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.result["role"] == "assistant"
        assert "What is 2+2?" in resp.result["content"]
        assert resp.result["model"] == "test-model"

    def test_sampling_not_supported(self):
        server = McpServer()
        req = JsonRpcRequest(
            method="sampling/createMessage",
            params={"messages": [{"role": "user", "content": "hi"}]},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None


# ===== 6. OAuth Scope Enforcement =====


class TestOAuthScopes:
    def _make_oauth_server(self, scopes: list[str]) -> tuple[McpServer, str]:
        oauth = OAuthProvider()
        server = _make_server_with_all()
        server._oauth = oauth
        token = _get_token(oauth, scopes)
        return server, token

    def test_tools_list_with_read_scope(self):
        server, token = self._make_oauth_server(["tools:read"])
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req, access_token=token)
        assert resp.error is None
        assert len(resp.result["tools"]) == 2

    def test_tools_call_denied_with_read_only(self):
        server, token = self._make_oauth_server(["tools:read"])
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"text": "hi"}},
            id=1,
        )
        resp = server.handle_request(req, access_token=token)
        assert resp.error is not None
        assert resp.error.code == FORBIDDEN

    def test_tools_call_allowed_with_call_scope(self):
        server, token = self._make_oauth_server(["tools:call"])
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {"text": "hi"}},
            id=1,
        )
        resp = server.handle_request(req, access_token=token)
        assert resp.error is None

    def test_resources_read_denied_without_scope(self):
        server, token = self._make_oauth_server(["tools:read"])
        req = JsonRpcRequest(
            method="resources/read",
            params={"uri": "file:///readme"},
            id=1,
        )
        resp = server.handle_request(req, access_token=token)
        assert resp.error is not None
        assert resp.error.code == FORBIDDEN

    def test_admin_scope_grants_all(self):
        server, token = self._make_oauth_server(["admin"])
        methods = [
            "tools/list",
            "tools/call",
            "resources/list",
            "prompts/list",
            "sampling/createMessage",
        ]
        for method in methods:
            params = None
            if method == "tools/call":
                params = {"name": "echo", "arguments": {"text": "hi"}}
            elif method == "sampling/createMessage":
                params = {"messages": [{"role": "user", "content": "hi"}]}
            req = JsonRpcRequest(method=method, params=params, id=1)
            resp = server.handle_request(req, access_token=token)
            assert resp.error is None, f"Failed for method {method}: {resp.error}"

    def test_no_token_returns_unauthorized(self):
        oauth = OAuthProvider()
        server = _make_server_with_all()
        server._oauth = oauth
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req, access_token=None)
        assert resp.error is not None
        assert resp.error.code == UNAUTHORIZED

    def test_invalid_token_returns_unauthorized(self):
        oauth = OAuthProvider()
        server = _make_server_with_all()
        server._oauth = oauth
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req, access_token="invalid-token")
        assert resp.error is not None
        assert resp.error.code == UNAUTHORIZED

    def test_write_scope_includes_read(self):
        server, token = self._make_oauth_server(["write"])
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req, access_token=token)
        assert resp.error is None

    def test_read_scope_hierarchy(self):
        server, token = self._make_oauth_server(["read"])
        # read scope should allow tools:read
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req, access_token=token)
        assert resp.error is None
        # but not tools:call
        req2 = JsonRpcRequest(
            method="tools/call",
            params={"name": "echo", "arguments": {}},
            id=2,
        )
        resp2 = server.handle_request(req2, access_token=token)
        assert resp2.error is not None
        assert resp2.error.code == FORBIDDEN


# ===== 7. Session Management =====


class TestSessionManagement:
    def test_create_session(self):
        manager = SessionManager()
        session = manager.create_session()
        assert session.session_id is not None
        assert manager.get_session(session.session_id) is session

    def test_delete_session(self):
        manager = SessionManager()
        session = manager.create_session()
        assert manager.delete_session(session.session_id) is True
        assert manager.get_session(session.session_id) is None

    def test_delete_nonexistent_session(self):
        manager = SessionManager()
        assert manager.delete_session("nonexistent") is False


# ===== 8. Pagination =====


class TestPagination:
    def test_tools_pagination(self):
        server = McpServer()
        for i in range(15):
            server.register_tool(
                ToolDefinition(name=f"tool-{i}", description=f"Tool {i}"),
                handler=lambda args: {},
            )
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req)
        assert len(resp.result["tools"]) == DEFAULT_PAGE_SIZE
        assert resp.result["nextCursor"] is not None

        # get next page
        req2 = JsonRpcRequest(
            method="tools/list",
            params={"cursor": resp.result["nextCursor"]},
            id=2,
        )
        resp2 = server.handle_request(req2)
        assert len(resp2.result["tools"]) == 5
        assert resp2.result.get("nextCursor") is None

    def test_no_pagination_when_few_items(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(method="tools/list", id=1)
        resp = server.handle_request(req)
        assert "nextCursor" not in resp.result

    def test_prompts_pagination(self):
        server = McpServer()
        for i in range(12):
            server.register_prompt(
                PromptDefinition(name=f"prompt-{i}", description=f"Prompt {i}"),
                handler=lambda name, args: {"messages": []},
            )
        req = JsonRpcRequest(method="prompts/list", id=1)
        resp = server.handle_request(req)
        assert len(resp.result["prompts"]) == DEFAULT_PAGE_SIZE
        assert resp.result["nextCursor"] is not None


# ===== 9. Error Handling =====


class TestErrorHandling:
    def test_method_not_found(self):
        server = McpServer()
        req = JsonRpcRequest(method="nonexistent/method", id=1)
        resp = server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == METHOD_NOT_FOUND

    def test_tool_handler_exception(self):
        server = McpServer()
        server.register_tool(
            ToolDefinition(name="failing", description="Fails"),
            handler=lambda args: 1 / 0,
        )
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "failing", "arguments": {}},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == INTERNAL_ERROR

    def test_response_preserves_request_id(self):
        server = McpServer()
        req = JsonRpcRequest(method="initialize", params={}, id=42)
        resp = server.handle_request(req)
        assert resp.id == 42


class TestDtoBoundaryValidation:
    def test_initialize_rejects_non_object_capabilities(self):
        server = McpServer()
        req = JsonRpcRequest(
            method="initialize",
            params={"capabilities": []},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == INVALID_PARAMS

    def test_tools_call_rejects_non_object_arguments(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="tools/call",
            params={"name": "echo", "arguments": "bad"},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == INVALID_PARAMS

    def test_sampling_rejects_invalid_messages_shape(self):
        server = _make_server_with_all()
        req = JsonRpcRequest(
            method="sampling/createMessage",
            params={"messages": [{"role": "user"}]},
            id=1,
        )
        resp = server.handle_request(req)
        assert resp.error is not None
        assert resp.error.code == INVALID_PARAMS


# ===== 10. Notifications =====


class TestNotifications:
    def test_tools_list_changed_notification(self):
        server = McpServer()
        server.drain_notifications()  # clear any initial
        server.register_tool(
            ToolDefinition(name="new-tool", description="New"),
            handler=lambda args: {},
        )
        notifications = server.drain_notifications()
        methods = [n["method"] for n in notifications]
        assert "notifications/tools/list_changed" in methods

    def test_resources_list_changed_notification(self):
        server = McpServer()
        server.drain_notifications()
        server.register_resource(
            ResourceDefinition(uri="file:///new", name="new", description="New"),
            handler=lambda uri: {},
        )
        notifications = server.drain_notifications()
        methods = [n["method"] for n in notifications]
        assert "notifications/resources/list_changed" in methods

    def test_drain_clears_notifications(self):
        server = McpServer()
        server.register_tool(ToolDefinition(name="t", description="T"))
        server.drain_notifications()
        assert len(server.drain_notifications()) == 0


# ===== 11. Client Integration =====


class TestClientIntegration:
    def test_client_initialize(self):
        server = _make_server_with_all()
        client = McpClient()
        client.connect(server)
        result = client.initialize()
        assert result.capabilities.tools is True
        assert result.server_info["name"] == "pylon-mcp"

    def test_client_list_and_call_tools(self):
        server = _make_server_with_all()
        client = McpClient()
        client.connect(server)
        client.initialize()
        tools_result = client.list_tools()
        assert len(tools_result["tools"]) == 2
        result = client.call_tool("add", {"a": 5, "b": 3})
        assert result == {"result": 8}

    def test_client_resources(self):
        server = _make_server_with_all()
        client = McpClient()
        client.connect(server)
        client.initialize()
        resources = client.list_resources()
        assert len(resources["resources"]) == 1
        data = client.read_resource("file:///readme")
        assert data["contents"][0]["text"] == "Hello World"

    def test_client_prompts(self):
        server = _make_server_with_all()
        client = McpClient()
        client.connect(server)
        client.initialize()
        prompts = client.list_prompts()
        assert len(prompts["prompts"]) == 1
        result = client.get_prompt("greeting", {"name": "Bob"})
        assert result["messages"][0]["content"] == "Hello Bob"

    def test_client_sampling(self):
        server = _make_server_with_all()
        client = McpClient()
        client.connect(server)
        client.initialize()
        result = client.create_sampling_message(
            messages=[{"role": "user", "content": "Tell me a joke"}],
            max_tokens=50,
        )
        assert result["role"] == "assistant"
        assert "Tell me a joke" in result["content"]

    def test_client_auto_reconnect(self):
        server = _make_server_with_all()
        client = McpClient()
        client.connect(server)
        client.initialize()
        client.disconnect()
        # auto-reconnect should re-initialize
        tools = client.list_tools()
        assert len(tools["tools"]) == 2

    def test_client_no_server_raises(self):
        client = McpClient()
        client._auto_reconnect = False
        with pytest.raises(RuntimeError, match="Not connected"):
            client.list_tools()

    def test_client_with_oauth_token(self):
        oauth = OAuthProvider()
        server = _make_server_with_all()
        server._oauth = oauth
        token = _get_token(oauth, ["admin"])
        client = McpClient(access_token=token)
        client.connect(server)
        client.initialize()
        tools = client.list_tools()
        assert len(tools["tools"]) == 2


# ===== 12. Auth Helpers =====


class TestAuthHelpers:
    def test_expand_admin_scope(self):
        expanded = expand_scopes(["admin"])
        assert "tools:read" in expanded
        assert "tools:call" in expanded
        assert "resources:read" in expanded
        assert "sampling:create" in expanded

    def test_expand_read_scope(self):
        expanded = expand_scopes(["read"])
        assert "tools:read" in expanded
        assert "tools:call" not in expanded

    def test_check_scope_direct(self):
        assert check_scope("tools:read", ["tools:read"]) is True
        assert check_scope("tools:call", ["tools:read"]) is False

    def test_check_scope_hierarchy(self):
        assert check_scope("tools:call", ["admin"]) is True
        assert check_scope("sampling:create", ["write"]) is True
        assert check_scope("sampling:create", ["read"]) is False

    def test_pkce_generate_and_verify(self):
        pkce = PKCEChallenge.generate()
        assert pkce.verify(pkce.code_verifier) is True
        assert pkce.verify("wrong-verifier") is False

    def test_token_refresh(self):
        oauth = OAuthProvider()
        token = _get_token(oauth, ["tools:read"])
        # find the refresh token
        refresh_token = None
        for rt, at in oauth._refresh_tokens.items():
            if at == token:
                refresh_token = rt
                break
        assert refresh_token is not None
        new_resp = oauth.refresh_access_token(refresh_token)
        assert new_resp is not None
        assert new_resp.access_token != token
        # old token should be invalid
        assert oauth.validate_token(token) is None
        # new token should be valid
        assert oauth.validate_token(new_resp.access_token) is not None
