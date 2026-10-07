"""Process integration checks; run with the shipped lingxi_advisor wheel[mcp]."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


SOURCE = Path(__file__).resolve().parents[1]
EXPECTED = {
    "runtime": ["lingxi.advisor.search", "lingxi.advisor.apply"],
    "operator": ["lingxi.advisor.knowledge_preparation_capabilities", "lingxi.advisor.prepare_historical_knowledge", "lingxi.advisor.start_preparation_batch",
                 "lingxi.advisor.get_preparation_batch", "lingxi.advisor.get_preparation_result", "lingxi.advisor.read_prepared_knowledge"],
}


def binding(tmp_path, config):
    file = tmp_path / "binding.json"
    file.write_text(json.dumps({"schema": "codehelix.plugin_binding/v1", "plugin_id": "lingxi-advisor",
                               "package_ref": {"root": str(SOURCE)}, "configuration": config}))
    return file


def command(binding_path, data, profile):
    return [sys.executable, "-B", str(SOURCE / "launcher.py"), "--binding", str(binding_path),
            "--data-root", str(data), "--profile", profile]


def runtime_environment(tmp_path: Path, **extra: str) -> dict[str, str]:
    """Load the locked wheel without relying on a developer machine install."""
    release = SOURCE / "upstream" / "lingxi-advisor-extension-0.8.6.zip"
    wheel_path = tmp_path / "lingxi_advisor.whl"
    with zipfile.ZipFile(release) as bundle:
        wheel_name = next(
            name for name in bundle.namelist()
            if name.endswith("lingxi_advisor-0.8.6-py3-none-any.whl")
        )
        wheel_path.write_bytes(bundle.read(wheel_name))
    extracted = tmp_path / "locked-core"
    with zipfile.ZipFile(wheel_path) as wheel:
        wheel.extractall(extracted)
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "PYTHONPATH": str(extracted),
        **extra,
    }


def test_managed_launcher_exposes_existing_log_levels():
    completed = subprocess.run(
        [sys.executable, "-B", str(SOURCE / "launcher.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert "--log-level {DEBUG,INFO,WARNING,ERROR}" in completed.stdout


async def connect(argv, environment, profile):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    parameters = StdioServerParameters(command=argv[0], args=argv[1:], env=environment)
    async with asyncio.timeout(30):
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == EXPECTED[profile]
            if profile == "runtime":
                search = await session.call_tool(
                    "lingxi.advisor.search",
                    {"issue_description": "Acceptance probe with no repository context."},
                )
                if search.isError:
                    # This client deliberately advertises no sampling callback.
                    # The runtime must fail explicitly rather than pretending
                    # that model-backed generation succeeded.
                    assert "did not advertise MCP sampling" in search.content[0].text
                    return
                search_value = json.loads(
                    next(item.text for item in search.content if item.type == "text")
                )
                assert search_value["status"] in {"miss", "no_candidates"}
                assert search_value["knowledge_matches"] == []

                apply = await session.call_tool(
                    "lingxi.advisor.apply",
                    {
                        "issue_description": "Acceptance probe with no repository context.",
                        "knowledge_matches": search_value["knowledge_matches"],
                    },
                )
                assert not apply.isError
                apply_value = json.loads(
                    next(item.text for item in apply.content if item.type == "text")
                )
                assert apply_value["status"] == "failed"
                assert apply_value["source_artifact_refs"] == []
            else:
                result = await session.call_tool("lingxi.advisor.knowledge_preparation_capabilities", {})
                assert not result.isError
                value = json.loads(next(item.text for item in result.content if item.type == "text"))
                assert value["allow_update_preretrieved"] is False


@pytest.mark.parametrize("profile", ["runtime", "operator"])
def test_real_shipped_core_initializes_with_managed_policy(tmp_path, profile):
    data = tmp_path / "data"
    config = binding(tmp_path, {"allow_preretrieved_updates": False})
    asyncio.run(connect(command(config, data, profile), runtime_environment(tmp_path), profile))
    assert data.is_dir()
    assert not list(tmp_path.rglob("runtime.env"))


def test_stale_dotenv_cannot_supply_missing_key_and_startup_environment_recovers(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    stale = "stale-dotenv-private-value"
    (data / ".env").write_text(f"LINGXI_ADVISOR_MODEL_API_KEY={stale}\nLINGXI_ADVISOR_JUDGE_API_KEY={stale}\nLINGXI_ADVISOR_GENERATOR_API_KEY={stale}\n")
    config = binding(tmp_path, {"gate_model_name": "test-model", "gate_model_base_url": "https://example.invalid/v1",
                              "allow_preretrieved_updates": False})
    argv = command(config, data, "operator")
    environment = runtime_environment(tmp_path)
    failed = subprocess.run(argv, env=environment, capture_output=True, text=True, timeout=30)
    assert failed.returncode == 2
    assert "LingxiAdvisor managed launcher started: profile=operator log_level=INFO" in failed.stderr
    assert "LingxiAdvisor managed launcher failed: stage=startup" in failed.stderr
    assert "Missing startup environment" in failed.stderr
    assert stale not in failed.stdout + failed.stderr
    # A new Agent/MCP process can pick up credentials without reinstalling.
    for key in ("first-startup-test-key", "rotated-startup-test-key"):
        asyncio.run(connect(argv, {**environment, "LINGXI_ADVISOR_MODEL_API_KEY": key}, "operator"))
        assert key not in config.read_text()
        assert key not in " ".join(argv)
    assert not list(tmp_path.rglob("runtime.env"))
