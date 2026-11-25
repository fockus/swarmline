#!/usr/bin/env node
import { once } from "node:events";
import { existsSync } from "node:fs";
import process from "node:process";

let session = null;
let fullText = "";
let finalSent = false;
let toolCallCount = 0;
let currentModelId = "";
const pendingTools = new Map();

function send(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function fail(message, details = {}) {
  send({ type: "error", kind: "runtime_crash", message, details, recoverable: false });
}

function readJsonLines(stream, onRecord) {
  let buffer = "";
  stream.setEncoding("utf8");
  stream.on("data", chunk => {
    buffer += chunk;
    while (true) {
      const index = buffer.indexOf("\n");
      if (index < 0) break;
      const line = buffer.slice(0, index).replace(/\r$/, "");
      buffer = buffer.slice(index + 1);
      if (!line.trim()) continue;
      try {
        onRecord(JSON.parse(line));
      } catch (error) {
        fail(`Invalid JSONL bridge request: ${error.message}`);
      }
    }
  });
}

function textFromMessage(message) {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter(part => part && part.type === "text")
      .map(part => part.text || "")
      .join("");
  }
  return "";
}

function normalizeMessage(message) {
  return {
    role: String(message?.role || "assistant"),
    content: textFromMessage(message),
    metadata: message?.metadata || {},
  };
}

function summarizeResult(result) {
  if (typeof result === "string") return result.slice(0, 500);
  const content = result?.content;
  if (Array.isArray(content)) {
    const text = content
      .filter(part => part && part.type === "text")
      .map(part => part.text || "")
      .join("\n");
    if (text) return text.slice(0, 500);
  }
  try {
    return JSON.stringify(result).slice(0, 500);
  } catch {
    return String(result).slice(0, 500);
  }
}

function splitModel(rawModel, provider, modelId) {
  if (provider && modelId) return { provider, modelId };
  if (!rawModel) return { provider: null, modelId: null };
  if (rawModel.includes(":")) {
    const [modelProvider, ...rest] = rawModel.split(":");
    return { provider: modelProvider, modelId: rest.join(":") };
  }
  if (rawModel.includes("/")) {
    const [modelProvider, ...rest] = rawModel.split("/");
    return { provider: modelProvider, modelId: rest.join("/") };
  }
  return { provider: null, modelId: rawModel };
}

function firstNumber(...values) {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function costFromSource(source) {
  const cost = source?.cost;
  if (typeof cost === "number" && Number.isFinite(cost)) return cost;
  const total = firstNumber(cost?.total, cost?.totalUsd, source?.total_cost_usd, source?.totalCostUsd);
  return total;
}

// Aggregate token usage / cost across every usage-bearing source we can find:
// per-message usage on assistant messages first, session-level aggregates as
// a fallback. PI (pi-ai) usage objects use {input, output, cost:{total}}; be
// liberal in accepted key spellings since the SDK API is not pinned here.
function collectUsage(rawMessages, sessionInstance) {
  const sources = [];
  for (const message of Array.isArray(rawMessages) ? rawMessages : []) {
    if (message && message.role === "assistant" && message.usage && typeof message.usage === "object") {
      sources.push(message.usage);
    }
  }
  if (sources.length === 0) {
    const aggregate = sessionInstance?.usage ?? sessionInstance?.stats?.usage ?? null;
    if (aggregate && typeof aggregate === "object") sources.push(aggregate);
  }

  let inputTokens = 0;
  let outputTokens = 0;
  let totalCostUsd = 0;
  let sawUsage = false;
  let sawCost = false;
  for (const source of sources) {
    const input = firstNumber(source.input_tokens, source.inputTokens, source.input, source.prompt_tokens);
    const output = firstNumber(source.output_tokens, source.outputTokens, source.output, source.completion_tokens);
    if (input !== null) {
      inputTokens += input;
      sawUsage = true;
    }
    if (output !== null) {
      outputTokens += output;
      sawUsage = true;
    }
    const cost = costFromSource(source);
    if (cost !== null) {
      totalCostUsd += cost;
      sawCost = true;
    }
  }
  return {
    usage: sawUsage ? { input_tokens: inputTokens, output_tokens: outputTokens } : null,
    totalCostUsd: sawCost ? totalCostUsd : null,
  };
}

function buildFinalPayload(sessionInstance, rawMessages) {
  const messages = Array.isArray(rawMessages) ? rawMessages : [];
  const { usage, totalCostUsd } = collectUsage(messages, sessionInstance);
  const payload = {
    type: "final",
    text: fullText,
    session_id: sessionInstance.sessionId,
    new_messages: messages.map(normalizeMessage),
    native_metadata: { session_file: sessionInstance.sessionFile },
  };
  if (usage) {
    payload.usage = usage;
    payload.metrics = {
      input_tokens: usage.input_tokens,
      output_tokens: usage.output_tokens,
      tool_calls_count: toolCallCount,
      model: currentModelId,
    };
  }
  if (totalCostUsd !== null) payload.total_cost_usd = totalCostUsd;
  return payload;
}

async function buildModel(modelRegistry, request) {
  const options = request.options || {};
  const runtime = request.runtime || {};
  const modelInfo = splitModel(runtime.model, options.provider, options.model_id);
  if (!modelInfo.provider || !modelInfo.modelId) return undefined;
  return modelRegistry.find(modelInfo.provider, modelInfo.modelId) || undefined;
}

async function buildToolset(pi, options) {
  const cwd = options.cwd || process.cwd();
  if (options.toolset === "readonly") {
    if (typeof pi.createReadOnlyTools === "function") return pi.createReadOnlyTools(cwd);
    return pi.readOnlyTools || [];
  }
  if (options.toolset === "coding" || options.coding_profile) {
    if (typeof pi.createCodingTools === "function") return pi.createCodingTools(cwd);
    return pi.codingTools || [];
  }
  return [];
}

function buildCustomTools(pi, tools) {
  if (!Array.isArray(tools) || typeof pi.defineTool !== "function") return [];
  return tools.map(tool =>
    pi.defineTool({
      name: tool.name,
      label: tool.name,
      description: tool.description || tool.name,
      parameters: tool.parameters || { type: "object", properties: {} },
      execute: async (_toolCallId, params) => {
        const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const responsePromise = new Promise(resolve => pendingTools.set(id, resolve));
        send({ type: "tool_request", id, name: tool.name, args: params || {} });
        const response = await responsePromise;
        if (response.ok) {
          return { content: [{ type: "text", text: String(response.result ?? "") }], details: {} };
        }
        return {
          content: [{ type: "text", text: String(response.result || response.error || "Tool failed") }],
          details: {},
          isError: true,
        };
      },
    }),
  );
}

function wireEvents(sessionInstance) {
  return sessionInstance.subscribe(event => {
    switch (event.type) {
      case "agent_start":
        send({ type: "status", text: "PI agent started" });
        break;
      case "message_update": {
        const update = event.assistantMessageEvent || {};
        if (update.type === "text_delta" && update.delta) {
          fullText += update.delta;
          send({ type: "assistant_delta", text: update.delta });
        } else if (update.type === "thinking_delta" && update.delta) {
          send({ type: "thinking_delta", text: update.delta });
        }
        break;
      }
      case "tool_execution_start":
        send({
          type: "tool_call_started",
          name: event.toolName || "",
          correlation_id: event.toolCallId || "",
          args: event.args || {},
        });
        break;
      case "tool_execution_end":
        toolCallCount += 1;
        send({
          type: "tool_call_finished",
          name: event.toolName || "",
          correlation_id: event.toolCallId || "",
          ok: !event.isError,
          result_summary: summarizeResult(event.result),
        });
        break;
      case "agent_end":
        finalSent = true;
        send(buildFinalPayload(sessionInstance, event.messages));
        break;
      case "queue_update":
        send({ type: "status", text: "PI queue updated" });
        break;
      case "compaction_start":
        send({ type: "status", text: "PI compaction started" });
        break;
      case "compaction_end":
        send({ type: "status", text: "PI compaction completed" });
        break;
      case "auto_retry_start":
        send({ type: "status", text: "PI auto retry started" });
        break;
      case "auto_retry_end":
        send({ type: "status", text: "PI auto retry completed" });
        break;
      default:
        break;
    }
  });
}

// Resume a persisted session file via whichever opener this pi-coding-agent
// version exposes. Throws with a descriptive message when the file is missing
// or the installed SDK has no resume-capable API.
function resumeSessionManager(pi, sessionFile) {
  if (!existsSync(sessionFile)) {
    throw new Error(`Session file not found: ${sessionFile}`);
  }
  for (const name of ["open", "load", "resume"]) {
    if (typeof pi.SessionManager[name] === "function") {
      return pi.SessionManager[name](sessionFile);
    }
  }
  throw new Error("Installed SessionManager exposes no open/load/resume API");
}

// Returns {manager} on success, or {error} when resume failed and the request
// did not opt into resume_fallback (caller must terminate the run).
function buildSessionManager(pi, request) {
  const options = request.options || {};
  const cwd = options.cwd || process.cwd();
  if (options.session_mode !== "persisted") {
    return { manager: pi.SessionManager.inMemory() };
  }
  const sessionFile = options.session_file || request.session_file || null;
  if (!sessionFile) {
    return { manager: pi.SessionManager.create(cwd) };
  }
  try {
    return { manager: resumeSessionManager(pi, sessionFile) };
  } catch (error) {
    const resumeFallback = options.resume_fallback === true || request.resume_fallback === true;
    send({
      type: "error",
      kind: "session_not_found",
      message: `Cannot resume PI session: ${error.message}`,
      details: { session_file: sessionFile },
      recoverable: true,
    });
    if (!resumeFallback) return { error };
    return { manager: pi.SessionManager.create(cwd) };
  }
}

async function run(request) {
  const options = request.options || {};
  const packageName = options.package_name || "@mariozechner/pi-coding-agent";
  let pi;
  try {
    pi = await import(packageName);
  } catch (error) {
    fail(
      `Cannot import ${packageName}. Install it with: npm install -g ${packageName}`,
      { error: error.message },
    );
    return;
  }

  const authStorage = options.auth_file ? pi.AuthStorage.create(options.auth_file) : pi.AuthStorage.create();
  const modelRegistry = pi.ModelRegistry.create(authStorage);
  const { manager: sessionManager, error: resumeError } = buildSessionManager(pi, request);
  if (resumeError) return;

  // project_instructions=false: skip project resource discovery (AGENTS.md
  // etc.) so the toggle has the same meaning as on the other runtimes.
  const loadProjectResources = options.project_instructions !== false;
  const loader = new pi.DefaultResourceLoader({
    cwd: options.cwd || process.cwd(),
    agentDir: loadProjectResources ? options.agent_dir || undefined : undefined,
    systemPromptOverride: () => request.system_prompt || "",
  });
  if (loadProjectResources && typeof loader.reload === "function") {
    await loader.reload();
  }

  const model = await buildModel(modelRegistry, request);
  currentModelId = model?.id || options.model_id || (request.runtime || {}).model || "";
  const tools = await buildToolset(pi, options);
  const customTools = buildCustomTools(pi, request.tools || []);

  const created = await pi.createAgentSession({
    cwd: options.cwd || process.cwd(),
    sessionManager,
    authStorage,
    modelRegistry,
    resourceLoader: loader,
    model,
    tools,
    customTools,
    thinkingLevel: options.thinking_level || undefined,
  });

  session = created.session;
  const unsubscribe = wireEvents(session);
  const lastUser = [...(request.messages || [])].reverse().find(message => message.role === "user");
  const prompt = lastUser?.content || "";
  try {
    await session.prompt(prompt);
    if (finalSent) return;
    if (!fullText) {
      const messages = Array.isArray(session.messages) ? session.messages : [];
      fullText = textFromMessage([...messages].reverse().find(message => message.role === "assistant"));
    }
    finalSent = true;
    send(buildFinalPayload(session, session.messages));
  } catch (error) {
    fail(`PI SDK prompt failed: ${error.message}`);
  } finally {
    unsubscribe();
    if (typeof session.dispose === "function") session.dispose();
  }
}

readJsonLines(process.stdin, record => {
  if (record.type === "run") {
    run(record).catch(error => fail(`PI SDK bridge failed: ${error.message}`));
  } else if (record.type === "tool_response") {
    const resolve = pendingTools.get(record.id);
    if (resolve) {
      pendingTools.delete(record.id);
      resolve(record);
    }
  } else if (record.type === "cancel" && session) {
    session.abort().catch(error => fail(`PI SDK abort failed: ${error.message}`));
  }
});

await once(process.stdin, "end");
