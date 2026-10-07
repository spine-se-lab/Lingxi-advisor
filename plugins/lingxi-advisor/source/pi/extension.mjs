import { spawn } from "node:child_process";

function createBridge(binding) {
  let child = null;
  let nextId = 1;
  let stdout = "";
  const pending = new Map();

  function failAll(error) {
    for (const request of pending.values()) {
      request.signal?.removeEventListener("abort", request.abort);
      request.reject(error);
    }
    pending.clear();
  }

  function start() {
    if (child) return child;
    const bridgeProcess = spawn(binding.python, [
      "-B", "-m", "installer.pi_mcp_call", JSON.stringify(binding.runtimeCommand),
    ], {
      cwd: binding.packageRoot,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    child = bridgeProcess;
    stdout = "";
    bridgeProcess.stdout.on("data", chunk => {
      stdout += chunk;
      for (let newline; (newline = stdout.indexOf("\n")) >= 0;) {
        const line = stdout.slice(0, newline).trim();
        stdout = stdout.slice(newline + 1);
        if (!line) continue;
        let payload;
        try { payload = JSON.parse(line); }
        catch { bridgeProcess.kill(); failAll(new Error("LingxiAdvisor MCP bridge returned invalid output")); return; }
        const request = pending.get(payload.id);
        if (!request) continue;
        pending.delete(payload.id);
        request.signal?.removeEventListener("abort", request.abort);
        if (!payload.ok) {
          const detail = typeof payload.error === "string" ? payload.error : JSON.stringify(payload.error);
          request.reject(new Error(detail || "LingxiAdvisor MCP call failed"));
        } else {
          request.resolve(payload.result);
        }
      }
    });
    bridgeProcess.stderr.resume();
    bridgeProcess.on("error", () => failAll(new Error("LingxiAdvisor MCP bridge could not start")));
    bridgeProcess.on("close", code => {
      if (child === bridgeProcess) child = null;
      if (pending.size) {
        failAll(new Error(`LingxiAdvisor MCP bridge stopped unexpectedly (exit ${code ?? "unknown"})`));
      }
    });
    return bridgeProcess;
  }

  return {
    invoke(tool, parameters, signal) {
      if (signal?.aborted) return Promise.reject(new Error("LingxiAdvisor MCP call was cancelled"));
      return new Promise((resolve, reject) => {
        const bridgeProcess = start();
        const id = nextId++;
        const abort = () => {
          bridgeProcess.kill();
          failAll(new Error("LingxiAdvisor MCP call was cancelled"));
        };
        pending.set(id, { resolve, reject, signal, abort });
        signal?.addEventListener("abort", abort, { once: true });
        bridgeProcess.stdin.write(`${JSON.stringify({ id, tool, arguments: parameters })}\n`);
      });
    },
    close() {
      child?.stdin.end();
      child = null;
    },
  };
}

function textResult(value, canonicalName) {
  return {
    content: [{ type: "text", text: JSON.stringify(value, null, 2) }],
    details: { canonicalMcpTool: canonicalName },
  };
}

export function compactSearchResult(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const matches = Array.isArray(value.knowledge_matches)
    ? value.knowledge_matches.map(match => {
        if (!match || typeof match !== "object" || Array.isArray(match)) return match;
        const { knowledge_xml: _omitted, ...metadata } = match;
        return metadata;
      })
    : value.knowledge_matches;
  return { ...value, knowledge_matches: matches };
}

function searchSchema(Type) {
  const context = Type.Object({
    repo: Type.Optional(Type.String()),
    base_commit: Type.Optional(Type.String()),
    instance_id: Type.Optional(Type.String()),
    issue_number: Type.Optional(Type.Integer({ minimum: 1 })),
  });
  const targetIssue = Type.Object({
    instance_id: Type.Optional(Type.String()),
    issue_number: Type.Optional(Type.Integer({ minimum: 1 })),
    created_at: Type.Optional(Type.String()),
  });
  return Type.Object({
    issue_description: Type.String(),
    context: Type.Optional(context),
    target_issue: Type.Optional(targetIssue),
    generation_mode: Type.Optional(Type.String()),
    search_candidate_count: Type.Optional(Type.Integer({ minimum: 1 })),
    final_top_k: Type.Optional(Type.Integer({ minimum: 1 })),
    update_preretrieved: Type.Optional(Type.Boolean()),
    run_gate_for_preretrieved: Type.Optional(Type.Boolean()),
    search_type: Type.Optional(Type.String()),
    fallback_search_type: Type.Optional(Type.String()),
    minimum_similarity_score: Type.Optional(Type.Integer()),
    maximum_misleading_risk: Type.Optional(Type.Integer()),
    resume: Type.Optional(Type.Boolean()),
    refresh_instance_metadata: Type.Optional(Type.Boolean()),
    refresh_search_cache: Type.Optional(Type.Boolean()),
  });
}

function applySchema(Type) {
  return Type.Object({
    issue_description: Type.String(),
    knowledge_matches: Type.Array(Type.Object({}, { additionalProperties: true })),
  });
}

export default function lingxi_advisor(pi, binding, Type) {
  const bridge = createBridge(binding);
  pi.on("session_shutdown", () => bridge.close());
  for (const tool of [
    {
      alias: "lingxi_advisor_search",
      canonical: "lingxi.advisor.search",
      label: "LingxiAdvisor Search",
      description: "Search safe same-repository historical issue knowledge for the current coding task.",
      parameters: searchSchema(Type),
    },
    {
      alias: "lingxi_advisor_apply",
      canonical: "lingxi.advisor.apply",
      label: "LingxiAdvisor Apply",
      description: "Validate Search matches and turn them into bounded, source-attributed guidance.",
      parameters: applySchema(Type),
    },
  ]) {
    pi.registerTool({
      name: tool.alias,
      label: tool.label,
      description: tool.description,
      parameters: tool.parameters,
      async execute(_id, parameters, signal) {
        const result = await bridge.invoke(tool.canonical, parameters, signal);
        return textResult(
          tool.canonical === "lingxi.advisor.search" ? compactSearchResult(result) : result,
          tool.canonical,
        );
      },
    });
  }
}
