# Lingxi Advisor plugin package

This directory contains the source, target definitions, and generated agent
packages for [Lingxi Advisor](../../README.md).

| Interface | Value |
| --- | --- |
| Plugin ID | `lingxi-advisor` |
| Runtime MCP server | `lingxi-advisor` |
| Runtime tools | `lingxi.advisor.search`, `lingxi.advisor.apply` |
| Preparation tools | `lingxi.advisor.knowledge_preparation_capabilities` and the other `lingxi.advisor.*` preparation tools |
| Environment prefix | `LINGXI_ADVISOR_*` |
| Default data path | `<config-root>/lingxi/advisor/data` |

All packaged agents receive Search/Apply. iCode and OpenCode also receive the
knowledge-preparation operator.

For setup, usage, and build commands, see the [user and development guide](docs/usage.md).
The build generates `delivery/` from the locked release in `source/upstream`;
do not edit generated delivery files directly.
