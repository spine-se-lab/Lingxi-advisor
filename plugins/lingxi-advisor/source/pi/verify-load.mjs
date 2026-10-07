// Load only the owned activation through Pi's actual extension loader. This
// probe does not start an MCP process, model, session, or user extension.
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [root, entry, cwd] = process.argv.slice(2);
const { loadExtensions } = await import(
  pathToFileURL(join(root, "dist/core/extensions/loader.js"))
);
const result = await loadExtensions([entry], cwd);
const extension = result.extensions[0];
const tools = [...(extension?.tools.keys() ?? [])];
const required = ["lingxi_advisor_search", "lingxi_advisor_apply"];
const loaded = !result.errors.length && required.every(name => tools.includes(name));
process.stdout.write(JSON.stringify({ loaded, tools }));
if (!loaded) process.exitCode = 2;
