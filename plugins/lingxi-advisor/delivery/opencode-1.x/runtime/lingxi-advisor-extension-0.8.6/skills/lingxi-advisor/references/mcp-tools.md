# Runtime MCP Tool Reference

## Portable Search

The portable call is:

```text
lingxi_advisor_search(issue_description)
```

SWE-bench-style tasks keep the primary context form:

```text
lingxi_advisor_search(
  issue_description,
  context={"repo": "owner/repo", "base_commit": "COMMIT", "instance_id": "INSTANCE_ID"},
  generation_mode="light"
)
```

For a regular GitHub issue without an instance id or base commit, use the
fallback form:

```text
lingxi_advisor_search(
  context={"repo": "owner/repo", "issue_number": 123},
  generation_mode="light"
)
```

Include `issue_description` in this form when it is already available; when it
is omitted, bounded Search loads the public issue title/body from GitHub.

For a new issue that has not been filed and therefore has no issue number, use:

```text
lingxi_advisor_search(
  issue_description,
  context={"repo": "owner/repo"},
  generation_mode="light"
)
```

An evaluation target may also use the explicit identity form while keeping
repository context separate:

```text
lingxi_advisor_search(
  issue_description,
  context={"repo": "owner/repo", "base_commit": "COMMIT"},
  target_issue={"instance_id": "INSTANCE_ID", "issue_number": 123}
)
```

Provide `issue_description`, or provide `repo` plus a positive `issue_number`.
Complete public `repo`, `instance_id`, and `base_commit` take the primary path.
The bounded GitHub fallback loads omitted public issue text, resolves a stable
identity, and uses the repository's latest default-branch commit before running
the same new-issue workflow; the issue creation time is not a temporal
boundary. When only `repo` is present, Search derives a stable path-free
identity and resolves the repository's latest default-branch commit. Do not send
`instance_id`, `base_commit`, or timestamp fields as null placeholders.
Calls without a repository first use authenticated GitHub issue search to infer
the most likely repository. A confident match enters bounded live retrieval as
a new issue. Ambiguous or missing matches check only exact approved
pre-retrieved knowledge.

Normal bounded Search treats regular runtime input as a new issue, including
calls with `repo` and a positive `issue_number`. Evaluation Search preserves
the existing identity-derived behavior: an explicit `target_issue`,
`instance_id`, legacy `issue_id`, or positive `issue_number` identifies an
existing target. Only those evaluation targets run target-specific leakage
checking, including the temporal boundary. Same-repository, patch, and general
retrieval validation remain mandatory for new issues.

`issue_mode` and leakage behavior are server-owned outputs, not caller inputs.
Do not pass either field from an Agent, harness, or evaluation wrapper.

Search always follows the existing Artifact lifecycle: reuse a valid compatible
Artifact, or run the existing Codify preparation/generation path when knowledge
is missing, stale, invalid, or incompatible. Repeated identical calls reuse the
validated Artifact instead of regenerating it.

Normal runtime Search uses a bounded query budget and stops when its candidate
budget is satisfied. It does not enumerate every closed issue or pull request.
Evaluation launchers explicitly select the exhaustive evaluation strategy and
print phase progress while repositories or search catalogs are being prepared.
Neither mode promises a fixed number of matches; `no_candidates` is a complete,
valid result and the coding task should continue without historical knowledge.

Advanced Retrieval/Gate controls remain available to Operator and evaluation
callers, but are not part of the portable runtime core.

The Search response contains:

```text
status
instance_id
generation_mode
issue_mode
target_leakage_check
retrieval_status
retrieval_source
selected_count
completed_count
cache_hit_count
generated_count
missing_count
failed_count
knowledge_matches[]
unresolved_knowledge[]
error
```

Each match contains a path-free `artifact_ref`, SHA256, historical issue
metadata, candidate fingerprint, `cache_hit`, and directly usable
`knowledge_xml`.

| Search status | Meaning |
| --- | --- |
| `completed` | Every selected Artifact was read and returned. |
| `partial` | Some selected knowledge is usable and some is unresolved. |
| `miss` | Compatibility status for a request that produced no usable Artifact. |
| `no_candidates` | No safe applicable historical candidate was found. |
| `failed` | Selection failed or requested preparation produced no usable Artifact. |

## Portable Apply

Pass the Search-returned matches without rewriting them:

```text
lingxi_advisor_apply(
  issue_description,
  knowledge_matches
)
```

The portable MCP interface accepts only the current issue and the unmodified
Search matches. Runtime callers do not supply additional selection or storage
inputs. When a host truncates a large Search result, retain each
`artifact_ref`; within the same MCP server process, Apply restores the exact
Search-approved match before validation. An unknown or unapproved ref is not
restored.

The Apply response contains at least:

```text
status
content
source_artifact_refs[]
error
```

`completed` means sourced content is usable; `partial` means some sourced
content remains usable; `failed` means no safely sourced content can be used.

Apply validates the Search-returned matches and turns them into bounded,
source-attributed content while preserving Artifact refs. How the server
combines, transforms, or stores that content is not part of the portable
Runtime contract. The agent decides whether each historical claim applies to
the current code.

## Consumption Rules

- Preserve Search match identity and pass the full approved match set to Apply.
- Let Apply produce consumable content from the approved match set.
- Preserve `source_artifact_refs` with any conclusion derived from Apply.
- Treat claims from different historical issues as independent evidence.
- A repeated identical issue/context Search should have `cache_hit_count > 0`,
  `generated_count = 0`, and non-empty matches when the first call produced an
  Artifact.
- Do not loop merely to increase the number of matches.
- Search XML remains directly available, but the default Runtime Skill uses
  Apply when forming reusable patch-agent context.
