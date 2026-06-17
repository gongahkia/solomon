import * as net from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import * as vscode from "vscode";

type ShisaEvent = {
  topic?: string;
  kind?: string;
  data?: {
    text?: string;
    value?: string;
    sequence?: number;
    error?: {
      code?: string;
    };
  };
};

let client: net.Socket | undefined;
let statusItem: vscode.StatusBarItem;
let lineBuffer = "";
const values = new Map<string, string>();

function getConfig<T>(key: string, fallback: T): T {
  return vscode.workspace.getConfiguration("shisa").get<T>(key, fallback);
}

function defaultSocketPath(): string {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Caches", "shisa", "shisa.sock");
  }
  const runtime = process.env.XDG_RUNTIME_DIR;
  if (runtime) {
    return path.join(runtime, "shisa.sock");
  }
  if (process.platform !== "linux") {
    return "";
  }
  const uid = typeof process.getuid === "function" ? process.getuid() : 0;
  return `/run/user/${uid}/shisa.sock`;
}

function socketPath(): string {
  return getConfig("socket", "") || defaultSocketPath();
}

function topics(): string[] {
  return getConfig("topics", ["cloud_ctx", "vcs.summary", "risk_tier"]);
}

function backpressureLimit(): number {
  return getConfig("backpressureLimit", 16);
}

function frame(value: unknown): Buffer {
  const payload = Buffer.from(JSON.stringify(value));
  const header = Buffer.alloc(4);
  header.writeUInt32BE(payload.length, 0);
  return Buffer.concat([header, payload]);
}

function updateStatus(): void {
  const text = topics()
    .map((topic) => values.get(topic))
    .filter((value): value is string => Boolean(value))
    .join(" ") || values.get("subscription") || "";
  statusItem.text = text ? `$(pulse) ${text}` : "$(pulse) Shisa";
  statusItem.tooltip = client ? "Shisa connected" : "Shisa disconnected";
  statusItem.show();
}

function applyEvent(event: ShisaEvent): void {
  const topic = event.topic ?? "subscription";
  if (event.kind === "error") {
    values.set(topic, event.data?.error?.code ?? "error");
  } else {
    const value = event.data?.text ?? event.data?.value ?? event.data?.sequence?.toString();
    if (value) {
      values.set(topic, value);
    }
  }
  updateStatus();
}

function onData(chunk: Buffer): void {
  lineBuffer += chunk.toString("utf8");
  for (;;) {
    const newline = lineBuffer.indexOf("\n");
    if (newline < 0) {
      break;
    }
    const line = lineBuffer.slice(0, newline).trim();
    lineBuffer = lineBuffer.slice(newline + 1);
    if (!line) {
      continue;
    }
    try {
      applyEvent(JSON.parse(line) as ShisaEvent);
    } catch {
      values.set("subscription", "bad_event");
      updateStatus();
    }
  }
}

function sendSubscribe(): void {
  client?.write(frame({
    v: 1,
    op: "subscribe",
    request_id: "vscode-shisa",
    topics: topics(),
    backpressure_limit: backpressureLimit(),
  }));
}

function connect(): void {
  if (client) {
    return;
  }
  lineBuffer = "";
  values.clear();
  const path = socketPath();
  if (!path) {
    values.set("subscription", "no_socket");
    updateStatus();
    return;
  }
  const socket = net.createConnection(path);
  client = socket;
  socket.once("connect", sendSubscribe);
  socket.on("data", onData);
  socket.on("error", (err) => {
    const code = (err as NodeJS.ErrnoException).code;
    values.set("subscription", code ?? "socket_error");
    updateStatus();
    socket.destroy();
  });
  socket.on("close", () => {
    if (client === socket) {
      client = undefined;
    }
    updateStatus();
  });
  updateStatus();
}

function disconnect(): void {
  client?.end();
  client = undefined;
  updateStatus();
}

function refresh(): void {
  if (!client) {
    connect();
    return;
  }
  client.write(JSON.stringify({ op: "ping", reason: "manual" }) + "\n");
}

export function activate(context: vscode.ExtensionContext): void {
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusItem.command = "shisa.refresh";
  context.subscriptions.push(
    statusItem,
    vscode.commands.registerCommand("shisa.connect", connect),
    vscode.commands.registerCommand("shisa.disconnect", disconnect),
    vscode.commands.registerCommand("shisa.refresh", refresh),
  );
  updateStatus();
  connect();
}

export function deactivate(): void {
  disconnect();
}
