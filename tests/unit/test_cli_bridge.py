"""Unit tests for CLIBridge and CLIBridgeProvider."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pylon.bridges.cli_bridge import CLIBridge, CLIBridgeProvider
from pylon.providers.base import Message, Response


class TestCLIBridge:
    def test_cli_bridge_init(self) -> None:
        bridge = CLIBridge(["echo", "hello"], working_dir="/tmp", timeout=60.0)
        assert bridge._command == ["echo", "hello"]
        assert bridge._working_dir == "/tmp"
        assert bridge._timeout == 60.0
        assert bridge._process is None
        assert bridge._env is None

    @pytest.mark.asyncio
    async def test_cli_bridge_start_stop(self) -> None:
        bridge = CLIBridge(["cat"])
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            await bridge.start()
            assert bridge.is_running is True
            assert bridge._process is mock_proc

            mock_proc.returncode = 0
            mock_proc.wait = AsyncMock(return_value=0)
            await bridge.stop()
            mock_proc.terminate.assert_called_once()
            assert bridge._process is None

    @pytest.mark.asyncio
    async def test_cli_bridge_send(self) -> None:
        bridge = CLIBridge(["cat"])
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        mock_stdout = MagicMock()
        mock_stdout.readline = AsyncMock(return_value=b"response\n")

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdin = mock_stdin
        mock_proc.stdout = mock_stdout

        bridge._process = mock_proc

        result = await bridge.send("hello")
        assert result == "response"
        mock_stdin.write.assert_called_once_with(b"hello\n")

    def test_cli_bridge_is_running(self) -> None:
        bridge = CLIBridge(["cat"])
        assert bridge.is_running is False

        mock_proc = MagicMock()
        mock_proc.returncode = None
        bridge._process = mock_proc
        assert bridge.is_running is True

        mock_proc.returncode = 0
        assert bridge.is_running is False


class TestCLIBridgeProvider:
    @pytest.mark.asyncio
    async def test_cli_bridge_provider_chat(self) -> None:
        bridge = CLIBridge(["echo"])
        bridge.send = AsyncMock(return_value="test response")

        provider = CLIBridgeProvider(bridge, "test-provider", "test-model")
        messages = [Message(role="user", content="hello")]

        result = await provider.chat(messages)
        assert isinstance(result, Response)
        assert result.content == "test response"
        assert result.model == "test-model"
        assert result.finish_reason == "stop"

    def test_cli_bridge_provider_properties(self) -> None:
        bridge = CLIBridge(["echo"])
        provider = CLIBridgeProvider(bridge, "my-provider", "my-model")
        assert provider.provider_name == "my-provider"
        assert provider.model_id == "my-model"

    @pytest.mark.asyncio
    async def test_cli_bridge_provider_stream(self) -> None:
        bridge = CLIBridge(["echo"])
        mock_stdin = MagicMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()

        lines = [b"line1\n", b"line2\n", b""]
        call_idx = 0

        async def readline():
            nonlocal call_idx
            val = lines[call_idx] if call_idx < len(lines) else b""
            call_idx += 1
            return val

        mock_stdout = MagicMock()
        mock_stdout.readline = readline

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdin = mock_stdin
        mock_proc.stdout = mock_stdout
        bridge._process = mock_proc

        provider = CLIBridgeProvider(bridge, "test", "test-model")
        messages = [Message(role="user", content="hello")]
        chunks = [c async for c in provider.stream(messages)]
        # Two content chunks + one finish_reason chunk
        assert any(c.content == "line1" for c in chunks)
        assert any(c.content == "line2" for c in chunks)
        assert chunks[-1].finish_reason == "stop"


class TestCLIBridgeErrors:
    @pytest.mark.asyncio
    async def test_send_without_start_raises(self) -> None:
        bridge = CLIBridge(["cat"])
        with pytest.raises(RuntimeError, match="Process not started"):
            await bridge.send("hello")

    @pytest.mark.asyncio
    async def test_stream_without_start_raises(self) -> None:
        bridge = CLIBridge(["cat"])
        with pytest.raises(RuntimeError, match="Process not started"):
            async for _ in bridge.stream("hello"):
                pass

    @pytest.mark.asyncio
    async def test_stop_timeout_falls_back_to_kill(self) -> None:
        bridge = CLIBridge(["cat"])
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.stdin = None

        wait_call_count = 0

        async def variable_wait():
            nonlocal wait_call_count
            wait_call_count += 1
            if wait_call_count == 1:
                # First call from terminate path — times out
                await asyncio.Future()  # Blocks forever; cancelled by wait_for timeout
            # Second call from kill path — succeeds immediately
            return 0

        mock_proc.wait = variable_wait
        bridge._process = mock_proc

        await bridge.stop()
        mock_proc.kill.assert_called_once()
        assert bridge._process is None
