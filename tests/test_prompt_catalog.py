"""Offline prompt provenance and completeness checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.prompts.catalog import catalog, get_prompt, identify_messages, validate_manifest
from coach.prompts import tasks
from _runner import run_tests


def test_shipped_prompts_are_frozen_and_registered():
    assert not validate_manifest()
    assert len(catalog()) == 20
    assert all(p.text.strip() and p.acceptance and p.contract for p in catalog())


def test_modified_prompt_requires_manifest_update():
    old = tasks.CONFIRM_SYSTEM_PROMPT
    try:
        tasks.CONFIRM_SYSTEM_PROMPT += "\nchanged"
        assert validate_manifest()
    finally:
        tasks.CONFIRM_SYSTEM_PROMPT = old


def test_unknown_id_rejected():
    try:
        get_prompt("not-registered")
    except KeyError:
        return
    raise AssertionError("unknown prompt accepted")


def test_composed_system_prompt_identified_without_user_content():
    p = get_prompt("context.state")
    items = identify_messages([{"role": "system", "content": p.text + "\nprivate state"},
                               {"role": "user", "content": "private answer"}])
    assert any(x["id"] == p.id for x in items)
    assert "private" not in repr(items)
    assert identify_messages([{"role": "user", "content": p.text}]) == []


def test_model_gateway_records_static_prompt_identity_on_success_and_failure():
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from coach.llm import client
    from coach.config import Settings
    prompt = get_prompt("planning.confirm")
    for failure in (False, True):
        sdk = Mock()
        if failure:
            sdk.chat.completions.create.side_effect = RuntimeError("fixture failure")
        else:
            sdk.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"confirmed":true}'))], usage=None)
        calls = []
        with patch.object(client, "get_client", return_value=sdk), patch.object(client.trace_mod, "note_llm_call", side_effect=lambda **kw: calls.append(kw)):
            try:
                client.json_call(prompt.text, "private-user-content", Settings(api_key="fixture"))
            except RuntimeError:
                assert failure
        assert len(calls) == 1
        assert calls[0]["prompts"] == [{"id": prompt.id, "version": prompt.version, "sha256": prompt.digest}]
        assert calls[0]["ok"] is not failure
        assert "private-user-content" not in repr(calls)


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
