"""Bridge Layer - CLI tool and service adapters for LLMProvider protocol.

Bridges wrap external CLI tools (Claude Code, Codex, Kimi Code, Gemini CLI),
HTTP services (OpenClaw), and protocol clients (MCP) behind the unified
LLMProvider interface.
"""

from pylon.bridges.cli_bridge import CLIBridge, CLIBridgeProvider
from pylon.bridges.claude_code import ClaudeCodeBridge, ClaudeCodeProvider
from pylon.bridges.codex import CodexBridge, CodexProvider
from pylon.bridges.gemini_cli import GeminiCLIBridge, GeminiCLIProvider
from pylon.bridges.kimi_code import KimiCodeBridge, KimiCodeProvider
from pylon.bridges.mcp_client import MCPClientBridge
from pylon.bridges.openclaw import OpenClawBridge

__all__ = [
    "CLIBridge",
    "CLIBridgeProvider",
    "ClaudeCodeBridge",
    "ClaudeCodeProvider",
    "CodexBridge",
    "CodexProvider",
    "GeminiCLIBridge",
    "GeminiCLIProvider",
    "KimiCodeBridge",
    "KimiCodeProvider",
    "MCPClientBridge",
    "OpenClawBridge",
]
