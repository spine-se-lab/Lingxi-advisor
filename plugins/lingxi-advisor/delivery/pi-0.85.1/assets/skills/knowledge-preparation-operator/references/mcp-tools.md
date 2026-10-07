# MCP Tool Reference

## Contents

- Capabilities
- Complete preparation
- Result lookup
- Knowledge reading
- Status semantics

## Capabilities

Call:

```text
knowledge_preparation_capabilities()
```

Check supported generation modes, live-search authority, write/refresh
authority, Grounded clone/fetch authority, and candidate limits before choosing
optional behavior.

Exact capability fields:

```text
generation_modes
allow_live_search
allow_update_preretrieved
allow_refresh
grounded_allow_clone
grounded_allow_fetch
max_search_candidate_count
max_final_top_k
batch.configured
input_policy
```

If the requested mode or candidate counts exceed these capabilities, report
the mismatch. Do not silently alter the user's request. Clone/fetch are
server-owned authorities and are intentionally absent from the preparation
tool arguments.

## Complete preparation

Call:

```text
prepare_historical_knowledge(
  instance,
  generation_mode="light",
  search_candidate_count=5,
  final_top_k=3,
  update_preretrieved=false,
  run_gate_for_preretrieved=false,
  search_type="semantic",
  fallback_search_type="hybrid",
  minimum_similarity_score=2,
  maximum_misleading_risk=3,
  resume=true,
  refresh_instance_metadata=false,
  refresh_search_cache=false
)
```

Required `instance` fields:

```text
instance_id
repo
base_commit
problem_statement
```

`requirements` is strongly recommended. The server discards unknown private
target fields before executing the pipeline.

If a required field is missing, obtain it from an already-authorized public
task source or ask the user. Never derive repository, base commit, or problem
text from the shape of an `instance_id`.

Important returned fields:

```text
request_id
status
retrieval_status
generation_status
retrieval_source
selected_count
completed_count
cache_hit_count
generated_count
failed_count
retryable
knowledge_artifacts[]
error
```

Each artifact contains:

```text
artifact_name
knowledge_uri
sha256
generation_mode
knowledge_cache_key
historical_candidate_fingerprint
repo
historical_issue_number
cache_hit
```

Server paths and credentials are intentionally absent.

## Batch preparation

The Operator Host must provision the authorized JSONL with `--batch-input` or
`LINGXI_ADVISOR_BATCH_INPUT_PATH`. The path is server-owned and is never a tool
argument. Start only when `lingxi.advisor.knowledge_preparation_capabilities` reports
`batch.configured=true`:

    start_preparation_batch(
      generation_mode="light",
      resume=true,
      continue_on_error=true,
      retry_failed=false
    )

Poll with:

    get_preparation_batch(batch_id, offset=0, limit=50)

Wait for a terminal status, then use each item request_id with
get_preparation_result and read_prepared_knowledge. The Batch tool delegates
every item to the same Codify prepare operation and persists status through the
Job Store/Worker adapters.

## Result lookup

Call:

```text
get_preparation_result(request_id)
```

Use the exact 24-character request ID returned by preparation. This returns the
same compact, path-redacted result shape.

The equivalent MCP resource is:

```text
lingxi.advisor://runs/<request_id>/result
```

## Knowledge reading

Call:

```text
read_prepared_knowledge(request_id, artifact_name)
```

Use only an `artifact_name` returned by the same request. The server rejects
absolute paths, parent traversal, unpublished files, invalid XML, and artifacts
over its response limit.

The equivalent MCP resource is:

```text
lingxi.advisor://runs/<request_id>/artifacts/<artifact_name>
```

The XML root is:

```xml
<historical_knowledge>
  <fine_grained_analysis>...</fine_grained_analysis>
  <general_summary>...</general_summary>
</historical_knowledge>
```

## Status semantics

| Status | Agent action |
| --- | --- |
| `completed` | Read and use all returned XML artifacts. |
| `partial` | Use completed artifacts; state that fewer than requested or some failed. |
| `no_candidates` | Continue without historical knowledge. |
| `failed` | Read `error`; retry only when `retryable=true`. |

`retrieval_source=preretrieved` means live GitHub search was skipped.
`cache_hit=true` means generation, repository restoration, and model work were
successfully bypassed for that reusable artifact.

Pre-retrieved candidates have already passed the persisted validation
contract. Keeping `run_gate_for_preretrieved=false` avoids repeating the model
gate; it does not weaken live-search leakage checks.

If reading a published artifact fails, call
`get_preparation_result(request_id)` once to check whether the publication is
still current. Do not use an artifact whose XML could not be read and
validated. For retryable pipeline failures, retry the unchanged request at
most once per user action unless an explicit caller retry policy says
otherwise.
