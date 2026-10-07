# Lingxi Advisor user and development guide

[Back to the project README](../../../README.md)

## Installation

Make GitHub credentials available as described under [GitHub access](#github-access),
then run the normal installer from the repository root:

```sh
npm install
npx . install
```

Requirements are Node.js 18+, Python 3.12 for the managed runtime, and `uv`.
The installer detects or asks for the target agent and shows its plan.

To select a host explicitly, replace the paths in this OpenCode example:

```sh
npx . install --agent opencode \
  --target /absolute/path/to/project \
  --config-root /absolute/path/to/agent-config \
  --yes
```

The target identifies the project or host location; the configuration root
identifies where that host's configuration is managed. Repository and issue
identity are supplied when using Advisor, rather than fixed during installation.

### Host details

Runtime Search/Apply is packaged for all six targets. The preparation operator
is installed for iCode and OpenCode.

| Agent | Target definition |
| --- | --- |
| iCode 0.28 | [Target](../targets/icode-chrys-0.28.json) |
| OpenCode 1.x | [Target](../targets/opencode-1.x.json) |
| Pi 0.85.1 | [Target](../targets/pi-0.85.1.json) |
| Codex 0.136.x | [Target](../targets/codex-native.json) |
| Claude Code 2.1.285 | [Target](../targets/claude-code-2.1.285.json) |
| DeepSeek Harness 0.2.0-rc.2 | [Target](../targets/deepseek-harness-0.2.0-rc.2.json) |

The target definitions record compatibility and verification scope.
The Codex target declares `>=0.136.0 <0.137.0` and fixture-level verification;
that does not establish live compatibility with other Codex versions.
Host MCP sampling support is a separate condition from tool registration.

## Configuration

### GitHub access

Provide `GITHUB_TOKEN` in the environment that starts the agent and MCP
services. Optional `GITHUB_TOKEN_1` through `GITHUB_TOKEN_15` support additional
tokens. Restart the relevant processes after updating credentials.

Credentials remain in the startup environment. Do not put secret values in
`--set` arguments or commit them to configuration files.

### Model configuration

Runtime can use either an independent model or negotiated host MCP sampling.
The preparation operator needs an independent model for generation.

For an independent model, provide the non-secret model name and endpoint
together using `gate_model_name` and `gate_model_base_url`.
Supply `LINGXI_ADVISOR_MODEL_API_KEY` in the startup environment, or separate
`LINGXI_ADVISOR_JUDGE_API_KEY` and `LINGXI_ADVISOR_GENERATOR_API_KEY`.

For example, with the actual credentials already available in the environment:

```sh
npx . install --agent opencode \
  --target /absolute/path/to/project \
  --config-root /absolute/path/to/agent-config \
  --set gate_model_name=YOUR_MODEL_NAME \
  --set gate_model_base_url=https://YOUR_MODEL_ENDPOINT/v1
```

Replace all placeholders with your own settings. The managed configuration
supplies the selected model and endpoint to the runtime; setting model-name or
endpoint environment variables alone is not a substitute for this configuration.

With no independent model selected, Runtime negotiates host sampling.
If the host cannot provide it, configure an independent model before requesting
model-backed screening or generation. Installing the tools alone does not
establish that a model is available.

### Optional settings page

After installation, run:

```sh
npx . config-ui
```

The page lets you inspect and adjust supported defaults. It is not a required
installation step. It listens on `127.0.0.1`, uses the runtime's existing
configuration, and does not display secret values.

If you used a custom installation home, provide the same location with
`--home /absolute/path/to/installation-home`. If multiple deployments are
available, use `--deployment-id <id>` to select one.

Restart or reload the agent after saving changes. Some installation-level
settings are read-only in the page and must be changed through installation.

### Data and preparation settings

The default data root is `<config-root>/lingxi/advisor/data`.
Use `--set data_root=/absolute/path` to select another location.

Repository operations are controlled by `allow_clone`, `allow_fetch`, and
`allow_refresh`; their defaults are disabled. Grounded preparation needs an
appropriate checkout and permission for any required preparation operations.

For batch preparation, `batch_input_path` identifies the authorized JSONL input.
The operator provides capability, status, result, and prepared-knowledge
reading tools.

## Task inputs

For an existing GitHub issue, provide its repository and issue number.
The agent can call Search with:

```json
{
  "context": {
    "repo": "owner/repository",
    "issue_number": 123
  }
}
```

Search can load the public issue description when it is omitted. For a new
task without an issue number, provide a description and repository:

```json
{
  "issue_description": "Add an option to skip startup checks.",
  "context": {
    "repo": "owner/repository"
  }
}
```

Use the `owner/repository` form, not a local path. Description-only Search can
attempt authenticated GitHub repository inference. If it is ambiguous or finds
no match, it falls back to approved pre-retrieved knowledge. Giving the
repository explicitly avoids relying on inference.

The agent uses `lingxi.advisor.search` followed by
`lingxi.advisor.apply`, preserving knowledge references. Some hosts expose
underscore aliases instead. See the [Skill](../source/assets/skills/lingxi-advisor/SKILL.md)
and [tool reference](../source/assets/skills/lingxi-advisor/references/mcp-tools.md)
for exact arguments and return statuses.

## Knowledge preparation

Light and Grounded Analysis describe **how historical knowledge is constructed**.
They do not select how deeply the coding agent reasons about your current task.
Start with the default settings; selecting a construction method is an advanced
option, separate from deciding when to prepare knowledge.

| Construction method | Parameter value | What it does |
| --- | --- | --- |
| **Issue–patch-based (Light)** | `light` | Extracts knowledge from a historical issue and patch without exploring a repository checkout. |
| **Repository-grounded (Grounded Analysis)** | `grounded_analysis` | Uses an agent/tool workflow to explore the historical checkout and supplement issue–patch context with code evidence. |

Grounded Analysis requires the historical checkout and permission for any
necessary repository preparation operations. It is agent-led code exploration,
not an interactive interview with the user.

The difference is the evidence used during construction. Light still needs
retrieval, screening, and model generation when suitable prepared results are
unavailable. These labels do not establish an end-to-end latency or quality
ranking.

Search reuses valid, compatible knowledge. Missing, stale, invalid, or
incompatible knowledge can trigger preparation.

### Knowledge structure

Both construction methods use the same default knowledge structure: **12 sections of issue-specific analysis** and **10 sections of transferable summary**. Together they cover understanding the issue and fixing it. The summary reorganizes the analysis into reusable guidance; its sections are not a one-to-one renaming of the analysis sections.

The tables group the template sections by purpose for readability. These groups do not add fields or imply a one-to-one mapping between the two steps.

**Step 1 — issue-specific analysis · 12 sections (`fine_grained_analysis`)**

| Knowledge category | Purpose | Template sections |
| --- | --- | --- |
| **Understanding** | **Code** — locate the issue in the code and trace dependencies | `repository_hierarchy`<br>`dependency_analysis`<br>`call_trace` |
| **Understanding** | **Problem** — explain what went wrong and why | `bug_category`<br>`root_cause`<br>`behavior_comparison` |
| **Understanding** | **Usage** — identify the triggering scenario | `usage_context` |
| **Fixing** | **Change** — explain the repair and its implementation | `fix_logic`<br>`fix_steps` |
| **Fixing** | **Verify** — capture checks and tests | `fix_checklist`<br>`test_case` |
| **Fixing** | **Summarize** — consolidate the issue, fix, and lesson | `conclusion` |

**Step 2 — transferable summary · 10 sections (`general_summary`)**

| Knowledge category | Purpose | Template sections |
| --- | --- | --- |
| **Understanding** | **Code** — retain architectural context and useful code references | `relevant_architecture`<br>`involved_components`<br>`specific_involved_classes_functions_methods` |
| **Understanding** | **Problem** — generalize how to diagnose this kind of issue | `general_root_cause_analysis_steps`<br>`bug_categorization` |
| **Understanding** | **Feature** — describe the affected functionality | `feature_or_functionality_of_issue` |
| **Fixing** | **Change** — capture the reusable repair approach | `general_fix_pattern` |
| **Fixing** | **Verify** — retain a reusable validation checklist | `summary_of_fix_checklist` |
| **Fixing** | **Fit** — preserve design patterns and coding practices | `design_patterns_and_coding_practices` |
| **Understanding & Fixing** | **Supporting concepts** — retain additional knowledge needed to understand or apply the repair | `additional_concepts` |

These sections are defined by the built-in generation templates. The [optional settings page](#optional-settings-page) lets you adjust model, generation, and retrieval settings; it does not provide an editor or selector for knowledge sections.

### Preparation time

A request can involve several kinds of work:

| Stage | Work that may take time | What reuse can save |
| --- | --- | --- |
| Historical retrieval | GitHub searches and fetching issue/repair context | Matching pre-retrieved candidate records can avoid the corresponding live candidate search. |
| Candidate screening | Relevance review and applicable checks | Approved records may reduce review work, depending on the retrieval path and settings. |
| Knowledge construction | Model generation; historical code exploration for Grounded Analysis | Valid, compatible knowledge avoids repeated generation. |
| Application | Reading and validating selected knowledge for the agent | Prepared content can be used once selected and validated. |

These are distinct stages. A knowledge-generation cache hit does not imply
that the request made no GitHub calls or model calls. Changing the task,
context, or required knowledge can introduce preparation work again.

Timing depends on API/network conditions, candidate processing, the model,
and repository preparation. No fixed response time is promised.

### Advance preparation and reuse

Preparation timing is separate from construction method:

- **On demand:** Search prepares missing knowledge during a task.
- **In advance:** The preparation operator handles individual task inputs or
  batches, so their results are ready for compatible later use.

The operator is available on iCode and OpenCode and requires an independently
configured model for generation. Its
[workflow instructions](../delivery/opencode-1.x/assets/skills/knowledge-preparation-operator/SKILL.md)
and [tool reference](../delivery/opencode-1.x/assets/skills/knowledge-preparation-operator/references/mcp-tools.md)
describe authorized batch input, preparation, status, results, and reading
knowledge.

Batch preparation can move retrieval and construction work before the coding
session. Which work a later request skips depends on what was prepared and
whether that request matches the saved records.

In particular, the portable local pre-retrieved lookup matches an exact target
identifier or normalized task description, subject to repository and approval
checks. It should not be described as general semantic search over all locally
prepared knowledge for arbitrary new tasks.

The practical expectations are:

- Preparing a known set of tasks can reduce repeated work for matching requests.
- Compatible historical knowledge can be reused instead of generated again.
- A different task may still need GitHub discovery and candidate screening.
- “Prepared in advance” does not mean either preparation or all future use is
  network-free.

### Using the guidance

Historical guidance needs to be checked against the current code and tests.
Source references identify where it came from; they do not prove that it is
correct for a new task or establish its causal contribution to a successful fix.
When no usable knowledge is returned, the agent continues without it.

## Relationship to the paper

Lingxi Advisor is an online version of the paper's procedural-knowledge approach: reconstruct methods from earlier repairs, abstract reusable knowledge, and use that knowledge to guide new work.

| Aspect | Paper and public plugin |
| --- | --- |
| Knowledge construction | The paper builds repository-grounded knowledge offline, requiring substantial preparation. Advisor constructs knowledge on demand from historical issues and patches, using either Light or Grounded Analysis. Optional advance preparation and reuse are also supported. |
| Retrieval and issue discovery | The paper retrieves and reranks knowledge from its prepared knowledge base. Advisor uses GitHub APIs to discover relevant historical issues and patches, screens candidates, and reuses or constructs knowledge for them. This is a different retrieval pipeline. |
| Quality and effectiveness | Advisor's online retrieval quality and downstream effectiveness may fall short of the paper's offline approach; equivalent performance has not been established. |
| Solving workflow | The paper guides multiple analyses and combines complementary findings. The plugin exposes Search/Apply for a host agent's workflow; installing it does not reproduce the paper's full exploration and aggregation procedure. |
| Reported results | The paper's 74.6% resolved rate on SWE-bench Verified belongs to the research system, not the current plugin release. |

The paper contains the research method and experiments; this guide describes the online tool. Preparing knowledge in advance can reduce repeated work, but does not by itself reproduce the paper's offline knowledge base, retrieval and reranking pipeline, or benchmark results.

## Evaluation integration

Integration with [eval-kit-swe-pro](https://github.com/spine-se-lab/eval-kit-swe-pro)
is in progress. Evaluation runners live in that separate repository; this
project supplies the Advisor interface. Advisor-enabled evaluation is an
optional integration rather than a requirement for everyday use.

The current runtime instructions distinguish normal bounded Search from
evaluation Search. Ordinary calls, including a regular GitHub issue number,
use the new-task workflow. Evaluation retains benchmark target identity and
applies target-specific leakage checks, including the temporal boundary.

Same-repository, patch, and general retrieval checks still apply to ordinary
use. Do not treat an ordinary historical-issue prompt as equivalent to an
evaluation setup with a benchmark cutoff. The
[tool reference](../source/assets/skills/lingxi-advisor/references/mcp-tools.md)
describes these boundaries. A gate is a control mechanism, not a guarantee
that an arbitrary evaluation setup is free of leakage.

## Development

From the repository root:

```sh
npm run build
npm run validate
python -m pytest -q plugins/lingxi-advisor/source/tests
```

The build consumes the locked upstream release and generates per-host
`delivery/` packages. Edit the maintained sources rather than generated
delivery files. See the [plugin package](../README.md) for interface names
and package structure.
