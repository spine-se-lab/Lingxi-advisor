from __future__ import annotations

import asyncio
import json
import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def compat(load_source):
    return importlib.import_module(load_source.__name__ + ".runtime_compat")


def test_search_arguments_normalize_github_url_and_omit_nulls(compat) -> None:
    value = compat.normalize_search_arguments({
        "issue_description": "public issue",
        "context": {
            "repo": "https://github.com/django/djangoproject.com.git",
            "issue_number": 2795,
            "base_commit": None,
            "instance_id": None,
        },
        "target_issue": None,
        "final_top_k": None,
    })

    assert value == {
        "issue_description": "public issue",
        "context": {"repo": "django/djangoproject.com", "issue_number": 2795},
    }


def test_search_arguments_do_not_rewrite_non_github_repository(compat) -> None:
    value = compat.normalize_search_arguments({
        "issue_description": "public issue",
        "context": {"repo": "gitlab.example/owner/repo"},
    })

    assert value["context"]["repo"] == "gitlab.example/owner/repo"


def test_repository_queries_are_bounded_and_keep_issue_filter(compat) -> None:
    queries = compat.repository_search_queries(
        "Dispatcher crashes when a missing cache key reaches the async worker. "
        * 20
    )

    assert queries
    assert all(len(query) <= 256 for query in queries)
    assert all(query.endswith(" in:title,body is:issue") for query in queries)


def test_repository_inference_accepts_an_exact_github_issue_match(
    compat, monkeypatch
) -> None:
    for index in range(1, 16):
        monkeypatch.delenv(f"GITHUB_TOKEN_{index}", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    description = (
        "Async dispatcher crashes on missing cache key\n\n"
        "The worker raises KeyError before the fallback can run."
    )

    def search(_query, tokens):
        assert tokens == ("fixture-token",)
        return [{
            "repository_url": "https://api.github.com/repos/owner/runtime",
            "html_url": "https://github.com/owner/runtime/issues/42",
            "number": 42,
            "title": "Async dispatcher crashes on missing cache key",
            "body": "The worker raises KeyError before the fallback can run.",
        }]

    assert compat.infer_github_repository(
        description, search=search
    ) == "owner/runtime"


def test_repository_inference_without_credentials_stays_offline(
    compat, monkeypatch
) -> None:
    for index in range(16):
        name = "GITHUB_TOKEN" if index == 0 else f"GITHUB_TOKEN_{index}"
        monkeypatch.delenv(name, raising=False)

    def unexpected_search(*_args):
        raise AssertionError("GitHub search must not run without a credential")

    assert compat.infer_github_repository(
        "A sufficiently detailed issue description for repository inference.",
        search=unexpected_search,
    ) is None


def test_compact_search_result_keeps_metadata_and_artifact_ref(compat) -> None:
    value = compat.compact_search_result({
        "status": "completed",
        "knowledge_matches": [{
            "artifact_ref": {"knowledge_cache_key": "owner__repo__issue_1"},
            "historical_issue_number": 1,
            "knowledge_xml": "x" * 100_000,
        }],
    })

    assert value == {
        "status": "completed",
        "knowledge_matches": [{
            "artifact_ref": {"knowledge_cache_key": "owner__repo__issue_1"},
            "historical_issue_number": 1,
        }],
    }


def test_runtime_hook_normalizes_before_tool_validation(compat) -> None:
    captured = {}

    class Manager:
        async def call_tool(self, name, arguments, context=None, convert_result=False):
            captured.update(name=name, arguments=arguments)
            return {"status": "completed"}

    server = SimpleNamespace(_tool_manager=Manager())
    compat.install_runtime_compatibility(server, compact_search=False)
    result = asyncio.run(server._tool_manager.call_tool(
        "lingxi.advisor.search",
        {"issue_description": "issue", "context": {
            "repo": "https://github.com/owner/repo", "base_commit": None,
        }},
    ))

    assert result == {"status": "completed"}
    assert captured["arguments"]["context"] == {"repo": "owner/repo"}


def test_runtime_hook_infers_repo_and_enables_bounded_live_search(compat) -> None:
    captured = {}
    tool = SimpleNamespace(description="old description", fn=None)

    class Manager:
        def get_tool(self, _name):
            return tool

        async def call_tool(self, name, arguments, context=None, convert_result=False):
            captured.update(name=name, arguments=arguments)
            return {"status": "no_candidates"}

    server = SimpleNamespace(_tool_manager=Manager())
    compat.install_runtime_compatibility(
        server,
        compact_search=False,
        repository_resolver=lambda _description: "owner/inferred-repo",
    )
    result = asyncio.run(server._tool_manager.call_tool(
        "lingxi.advisor.search",
        {"issue_description": "A public issue description."},
    ))

    assert result == {"status": "no_candidates"}
    assert captured["arguments"]["context"] == {
        "repo": "owner/inferred-repo"
    }
    assert captured["arguments"]["prepare_if_missing"] is True
    assert "infers a repository" in tool.description


def test_runtime_hook_compacts_after_search_keeps_server_result(compat) -> None:
    async def search(**_arguments):
        return {
            "status": "completed",
            "knowledge_matches": [{
                "artifact_ref": {"knowledge_cache_key": "owner__repo__issue_1"},
                "knowledge_xml": "full approved knowledge",
            }],
        }

    tool = SimpleNamespace(fn=search)

    class Manager:
        def get_tool(self, _name):
            return tool

        async def call_tool(self, _name, arguments, context=None, convert_result=False):
            return await tool.fn(**arguments)

    server = SimpleNamespace(_tool_manager=Manager())
    compat.install_runtime_compatibility(
        server,
        compact_search=True,
        repository_resolver=lambda _description: None,
    )
    result = asyncio.run(server._tool_manager.call_tool(
        "lingxi.advisor.search", {"issue_description": "issue"}
    ))

    assert result == {
        "status": "completed",
        "knowledge_matches": [{
            "artifact_ref": {"knowledge_cache_key": "owner__repo__issue_1"},
        }],
    }


@pytest.mark.parametrize(("field", "identity", "expected"), [
    ("context",
     {"repo": "https://github.com/psf/requests", "issue_number": 6102},
     {"repo": "psf/requests", "issue_number": 6102}),
    ("target_issue",
     {"issue_number": 6102, "created_at": None},
     {"issue_number": 6102}),
])
def test_runtime_hook_keeps_identity_sent_as_json_text(compat, field, identity, expected) -> None:
    # OpenCode with DeepSeek V4.1 Flash sent `context` as JSON text. Repository
    # inference must see it, or it replaces the context and drops issue_number.
    captured = {}
    tool = SimpleNamespace(description="old description", fn=None)
    inferred = []

    class Manager:
        def get_tool(self, _name):
            return tool

        async def call_tool(self, name, arguments, context=None, convert_result=False):
            captured.update(arguments=arguments)
            return {"status": "no_candidates"}

    server = SimpleNamespace(_tool_manager=Manager())
    compat.install_runtime_compatibility(
        server,
        compact_search=False,
        repository_resolver=lambda description: inferred.append(description) or "owner/inferred-repo",
    )
    asyncio.run(server._tool_manager.call_tool(
        "lingxi.advisor.search",
        {"issue_description": "A public issue description.", field: json.dumps(identity)},
    ))

    assert captured["arguments"][field] == expected
    assert inferred == [] if field == "context" else inferred
