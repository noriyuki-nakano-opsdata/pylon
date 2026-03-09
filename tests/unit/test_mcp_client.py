"""Unit tests for MCPClientBridge."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pylon.bridges.mcp_client import MCPClientBridge


class TestMCPClientBridge:
    def test_mcp_client_init(self) -> None:
        client = MCPClientBridge(name="test-server")
        assert client._name == "test-server"
        assert client._process is None
        assert client.is_connected is False
        assert client._next_id == 0

    @pytest.mark.asyncio
    async def test_mcp_client_connect(self) -> None:
        client = MCPClientBridge(name="test")
        mock_proc = MagicMock()
        mock_proc.returncode = None

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            await client.connect(["node", "server.js"])
            assert client.is_connected is True
            mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_mcp_client_list_tools(self) -> None:
        client = MCPClientBridge()
        tools_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "read_file", "description": "Read a file"},
                    {"name": "write_file", "description": "Write a file"},
                ],
            },
        }

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(
            return_value=json.dumps(tools_response).encode() + b"\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdin = mock_stdin
        mock_proc.stdout = mock_stdout
        client._process = mock_proc

        tools = await client.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_mcp_client_call_tool(self) -> None:
        client = MCPClientBridge()
        tool_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": "file contents here"},
        }

        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(
            return_value=json.dumps(tool_response).encode() + b"\n"
        )

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdin = mock_stdin
        mock_proc.stdout = mock_stdout
        client._process = mock_proc

        result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
        assert result["content"] == "file contents here"

    @pytest.mark.asyncio
    async def test_mcp_client_disconnect(self) -> None:
        client = MCPClientBridge()
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        client._process = mock_proc

        await client.disconnect()
        mock_proc.terminate.assert_called_once()
        assert client._process is None
        assert client.is_connected is False
