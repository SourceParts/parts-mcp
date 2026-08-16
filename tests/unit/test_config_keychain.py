"""
Unit tests for the CLI-keychain credential fallback (field report 4.7).

`parts auth login` stores credentials in the OS keychain under service
'parts-cli'; a local MCP server must honor that session when
SOURCE_PARTS_API_KEY is unset instead of requiring a launcher wrapper.
"""
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from parts_mcp.config import _cli_keychain_key


def _fake_keyring(value):
    mod = ModuleType("keyring")
    mod.get_password = lambda service, account: (
        value if (service, account) == ("parts-cli", "api-key") else None
    )
    return mod


class TestCliKeychainFallback:
    def test_reads_the_cli_api_key_entry(self):
        with patch.dict(sys.modules, {"keyring": _fake_keyring("sp_live_abc")}):
            assert _cli_keychain_key() == "sp_live_abc"

    def test_empty_when_entry_missing(self):
        with patch.dict(sys.modules, {"keyring": _fake_keyring(None)}):
            assert _cli_keychain_key() == ""

    def test_empty_when_keyring_absent(self):
        """Hosted containers have no keyring package — must not raise."""
        with patch.dict(sys.modules, {"keyring": None}):
            assert _cli_keychain_key() == ""

    def test_empty_when_keychain_errors(self):
        mod = ModuleType("keyring")

        def _boom(service, account):
            raise RuntimeError("no secret service on this host")

        mod.get_password = _boom
        with patch.dict(sys.modules, {"keyring": mod}):
            assert _cli_keychain_key() == ""
