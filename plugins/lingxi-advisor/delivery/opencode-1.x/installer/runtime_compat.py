"""Narrow runtime compatibility fixes for declared coding-agent hosts."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from difflib import SequenceMatcher
import inspect
import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlencode, urlsplit


logger = logging.getLogger(__name__)
_GITHUB_SEARCH_ENDPOINT = "https://api.github.com/search/issues"
_GITHUB_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+#-]{2,}")
_STOP_WORDS = {
    "after", "also", "another", "because", "before", "being", "causing",
    "could", "does", "from", "have", "into", "issue", "plugin", "should",
    "that", "their", "there", "these", "this", "under", "using", "when",
    "where", "which", "while", "with", "would",
}
_SEARCH_TOOL_DESCRIPTION = (
    "Search safe same-repository historical issue knowledge. issue_description "
    "is the only required input. When context.repo is omitted and GitHub "
    "credentials are available, Lingxi Advisor infers a repository from GitHub "
    "issue matches before running bounded live retrieval. Explicit repo, "
    "instance_id, base_commit, and issue_number remain authoritative."
)


def _github_repository(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return candidate
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "github.com",
        "www.github.com",
    }:
        return candidate
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return candidate
    repository = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    return f"{parts[0]}/{repository}" if repository else candidate


def normalize_search_arguments(arguments: Any) -> Any:
    """Normalize the two malformed shapes observed from Chrys/OpenCode."""
    if not isinstance(arguments, Mapping):
        return arguments
    normalized = {name: value for name, value in arguments.items() if value is not None}
    for field in ("context", "target_issue"):
        nested = normalized.get(field)
        if isinstance(nested, str):
            # OpenCode with DeepSeek sends the nested object as JSON text.
            # FastMCP would parse it later, but repository inference runs
            # first and would otherwise replace it, dropping issue_number.
            try:
                parsed = json.loads(nested)
            except ValueError:
                parsed = None
            if isinstance(parsed, Mapping):
                nested = parsed
        if not isinstance(nested, Mapping):
            continue
        cleaned = {name: value for name, value in nested.items() if value is not None}
        if field == "context" and "repo" in cleaned:
            cleaned["repo"] = _github_repository(cleaned["repo"])
        if cleaned:
            normalized[field] = cleaned
        else:
            normalized.pop(field, None)
    return normalized


def _github_tokens() -> tuple[str, ...]:
    tokens: list[str] = []
    for index in range(16):
        name = "GITHUB_TOKEN" if index == 0 else f"GITHUB_TOKEN_{index}"
        for token in re.split(r"[,;\r\n]+", os.environ.get(name, "")):
            token = token.strip()
            if token and token not in tokens:
                tokens.append(token)
    return tuple(tokens)


def _bounded_query(terms: str) -> str:
    suffix = " in:title,body is:issue"
    return terms[: 256 - len(suffix)].rstrip() + suffix


def repository_search_queries(issue_description: str) -> tuple[str, ...]:
    """Build bounded GitHub issue-search queries from public issue text."""
    normalized = " ".join(str(issue_description or "").split())
    words = _WORD_RE.findall(normalized)
    if not words:
        return ()
    queries: list[str] = []
    phrase = " ".join(words[:12])
    if len(words) >= 4:
        queries.append(_bounded_query(f'"{phrase}"'))
    keywords: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered in _STOP_WORDS or lowered in keywords:
            continue
        keywords.append(lowered)
        if len(keywords) == 10:
            break
    if len(keywords) >= 3:
        query = _bounded_query(" ".join(keywords))
        if query not in queries:
            queries.append(query)
    return tuple(queries)


def _github_issue_search(
    query: str,
    tokens: tuple[str, ...],
) -> list[dict[str, Any]]:
    # Keep network imports lazy so startup validation remains usable in the
    # deliberately minimal subprocess environment exercised by installers.
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    if not tokens:
        return []
    url = f"{_GITHUB_SEARCH_ENDPOINT}?{urlencode({'q': query, 'per_page': 10})}"
    for token in tokens:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "lingxi-advisor/0.3.12",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:  # noqa: S310
                payload = response.read(4_000_001)
        except HTTPError as exc:
            if exc.code in {401, 403, 429}:
                continue
            return []
        except (OSError, TimeoutError, URLError):
            continue
        if len(payload) > 4_000_000:
            return []
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            return []
        items = value.get("items") if isinstance(value, Mapping) else None
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, Mapping)]
    return []


def _repository_slug(item: Mapping[str, Any]) -> str | None:
    repository = item.get("repository")
    if isinstance(repository, Mapping):
        full_name = str(repository.get("full_name") or "").strip()
        if _GITHUB_REPOSITORY_RE.fullmatch(full_name):
            return full_name
    value = str(item.get("repository_url") or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.hostname != "api.github.com"
        or len(parts) != 3
        or parts[0] != "repos"
    ):
        return None
    slug = f"{parts[1]}/{parts[2]}"
    return slug if _GITHUB_REPOSITORY_RE.fullmatch(slug) else None


def _normalized_text(value: Any) -> str:
    return " ".join(word.lower() for word in _WORD_RE.findall(str(value or "")))


def _candidate_score(
    issue_description: str,
    item: Mapping[str, Any],
) -> tuple[float, bool]:
    issue = _normalized_text(issue_description)
    title = _normalized_text(item.get("title"))
    candidate = _normalized_text(
        f"{item.get('title') or ''} {item.get('body') or ''}"
    )
    if not issue or not title:
        return 0.0, False
    exact = len(candidate) >= 40 and (candidate in issue or issue in candidate)
    issue_words = set(issue.split())
    candidate_words = set(candidate.split())
    title_words = set(title.split())
    coverage = len(issue_words & candidate_words) / max(1, len(issue_words))
    title_coverage = len(issue_words & title_words) / max(1, len(title_words))
    sequence = SequenceMatcher(None, issue[:4000], candidate[:4000]).ratio()
    score = max(
        0.82 if exact else 0.0,
        0.55 * coverage + 0.25 * title_coverage + 0.20 * sequence,
    )
    return min(score, 1.0), exact


def infer_github_repository(
    issue_description: str,
    *,
    search: Callable[
        [str, tuple[str, ...]], list[dict[str, Any]]
    ] | None = None,
) -> str | None:
    """Infer one repository from authenticated global GitHub issue search."""
    tokens = _github_tokens()
    if not tokens:
        logger.info(
            "Lingxi Advisor repository inference skipped: no GitHub credential"
        )
        return None
    search = search or _github_issue_search
    candidates: dict[tuple[str, str], tuple[float, bool]] = {}
    for query in repository_search_queries(issue_description):
        for item in search(query, tokens):
            repo = _repository_slug(item)
            if not repo:
                continue
            identity = str(item.get("html_url") or item.get("number") or "")
            score = _candidate_score(issue_description, item)
            previous = candidates.get((repo, identity))
            if previous is None or score[0] > previous[0]:
                candidates[(repo, identity)] = score
        if any(exact for _score, exact in candidates.values()):
            break
    repo_scores: dict[str, tuple[float, bool]] = {}
    for (repo, _identity), score in candidates.items():
        if repo not in repo_scores or score[0] > repo_scores[repo][0]:
            repo_scores[repo] = score
    ranked = sorted(
        (
            (score, exact, repo)
            for repo, (score, exact) in repo_scores.items()
        ),
        reverse=True,
    )
    if not ranked:
        logger.info(
            "Lingxi Advisor repository inference completed: no GitHub issue match"
        )
        return None
    best_score, best_exact, best_repo = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    if not best_exact and (
        best_score < 0.50 or best_score - runner_up < 0.08
    ):
        logger.info(
            "Lingxi Advisor repository inference completed: ambiguous match "
            "confidence=%.3f",
            best_score,
        )
        return None
    logger.info(
        "Lingxi Advisor repository inference completed: repository=%s "
        "confidence=%.3f",
        best_repo,
        best_score,
    )
    return best_repo


def compact_search_result(value: Any) -> Any:
    """Keep Search metadata and refs while omitting oversized XML."""
    if not isinstance(value, Mapping):
        return value
    compacted = dict(value)
    matches = compacted.get("knowledge_matches")
    if isinstance(matches, list):
        compacted["knowledge_matches"] = [
            {name: item for name, item in match.items() if name != "knowledge_xml"}
            if isinstance(match, Mapping)
            else match
            for match in matches
        ]
    return compacted


def install_runtime_compatibility(
    server: Any,
    *,
    compact_search: bool,
    repository_resolver: Callable[[str], Any] | None = None,
) -> Any:
    """Install argument normalization and an optional reference-only Search view."""
    manager = server._tool_manager
    call_tool = manager.call_tool

    async def normalized_call(
        name: str,
        arguments: dict[str, Any],
        context: Any = None,
        convert_result: bool = False,
    ) -> Any:
        if name == "lingxi.advisor.search":
            arguments = normalize_search_arguments(arguments)
            context_value = (
                arguments.get("context")
                if isinstance(arguments, Mapping)
                else None
            )
            context_mapping = (
                dict(context_value)
                if isinstance(context_value, Mapping)
                else {}
            )
            target_value = (
                arguments.get("target_issue")
                if isinstance(arguments, Mapping)
                else None
            )
            target_mapping = (
                target_value if isinstance(target_value, Mapping) else {}
            )
            has_repository = bool(
                context_mapping.get("repo") or target_mapping.get("repo")
            )
            issue_description = (
                str(arguments.get("issue_description") or "")
                if isinstance(arguments, Mapping)
                else ""
            )
            if issue_description.strip() and not has_repository:
                if repository_resolver is None:
                    import asyncio

                    repository = await asyncio.to_thread(
                        infer_github_repository,
                        issue_description,
                    )
                else:
                    repository = repository_resolver(issue_description)
                    if inspect.isawaitable(repository):
                        repository = await repository
                if (
                    isinstance(repository, str)
                    and _GITHUB_REPOSITORY_RE.fullmatch(repository)
                ):
                    arguments = dict(arguments)
                    arguments["context"] = {
                        **context_mapping,
                        "repo": repository,
                    }
                    arguments.setdefault("prepare_if_missing", True)
        return await call_tool(
            name, arguments, context=context, convert_result=convert_result
        )

    manager.call_tool = normalized_call
    get_tool = getattr(manager, "get_tool", None)
    search_tool = (
        get_tool("lingxi.advisor.search") if callable(get_tool) else None
    )
    if search_tool is not None:
        try:
            search_tool.description = _SEARCH_TOOL_DESCRIPTION
        except (AttributeError, TypeError, ValueError):
            logger.warning(
                "Lingxi Advisor could not update the Search tool description"
            )
    if compact_search:
        if search_tool is None:
            raise RuntimeError("Search tool is unavailable for result compaction")
        original = search_tool.fn

        async def compacted_search(*args: Any, **kwargs: Any) -> Any:
            return compact_search_result(await original(*args, **kwargs))

        search_tool.fn = compacted_search
    return server
