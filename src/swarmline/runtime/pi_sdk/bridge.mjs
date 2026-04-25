#!/usr/bin/env node
import { once } from "node:events";
import process from "node:process";

let session = null;
let fullText = "";
let finalSent = false;
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
        send({
          type: "final",
          text: fullText,
          session_id: sessionInstance.sessionId,
          new_messages: Array.isArray(event.messages) ? event.messages.map(normalizeMessage) : [],
          native_metadata: { session_file: sessionInstance.sessionFile },
        });
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
  const sessionManager =
    options.session_mode === "persisted"
      ? pi.SessionManager.create(options.cwd || process.cwd())
      : pi.SessionManager.inMemory();

  const loader = new pi.DefaultResourceLoader({
    cwd: options.cwd || process.cwd(),
    agentDir: options.agent_dir || undefined,
    systemPromptOverride: () => request.system_prompt || "",
  });
  if (typeof loader.reload === "function") await loader.reload();

  const model = await buildModel(modelRegistry, request);
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
    send({
      type: "final",
      text: fullText,
      session_id: session.sessionId,
      new_messages: Array.isArray(session.messages) ? session.messages.map(normalizeMessage) : [],
      native_metadata: { session_file: session.sessionFile },
    });
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
