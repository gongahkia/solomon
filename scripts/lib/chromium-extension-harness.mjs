import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, extname, join, resolve } from "node:path";

const DEFAULT_CHROMIUM = process.env.CHROMIUM_BIN ?? "chromium-browser";

export class AssertionError extends Error {
  constructor(message) {
    super(message);
    this.name = "AssertionError";
  }
}

export function assert(condition, message) {
  if (!condition) {
    throw new AssertionError(message);
  }
}

class CDPClient {
  constructor(webSocketUrl) {
    this.webSocketUrl = webSocketUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.events = new Map();
  }

  async connect() {
    this.socket = new WebSocket(this.webSocketUrl);

    await new Promise((resolveConnection, rejectConnection) => {
      this.socket.addEventListener("open", resolveConnection, { once: true });
      this.socket.addEventListener("error", rejectConnection, { once: true });
    });

    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);

      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);

        if (message.error) {
          reject(new Error(message.error.message));
        } else {
          resolve(message.result);
        }

        return;
      }

      if (message.method && this.events.has(message.method)) {
        for (const listener of this.events.get(message.method)) {
          listener(message.params);
        }
      }
    });

    return this;
  }

  send(method, params = {}) {
    const id = this.nextId;
    this.nextId += 1;

    const promise = new Promise((resolveCommand, rejectCommand) => {
      this.pending.set(id, {
        resolve: resolveCommand,
        reject: rejectCommand
      });
    });

    this.socket.send(JSON.stringify({ id, method, params }));
    return promise;
  }

  on(method, listener) {
    const listeners = this.events.get(method) ?? [];
    listeners.push(listener);
    this.events.set(method, listeners);
  }

  close() {
    this.socket?.close();
  }
}

async function waitFor(predicate, description, timeoutMs = 10000) {
  const startedAt = Date.now();
  let lastError = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const value = await predicate();

      if (value) {
        return value;
      }
    } catch (error) {
      lastError = error;
    }

    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }

  throw new Error(`${description} timed out${lastError ? `: ${lastError.message}` : ""}`);
}

async function requestJson(url) {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }

  return response.json();
}

export async function startStaticServer(directory) {
  const root = resolve(directory);
  const server = createServer(async (request, response) => {
    try {
      const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
      const pathname = requestUrl.pathname === "/" ? "/linkedin-feed.html" : requestUrl.pathname;
      const filePath = resolve(root, `.${pathname}`);

      if (!filePath.startsWith(root)) {
        response.writeHead(403);
        response.end("Forbidden");
        return;
      }

      const body = await readFile(filePath);
      const contentType =
        extname(filePath) === ".html" ? "text/html; charset=utf-8" : "application/octet-stream";

      response.writeHead(200, { "content-type": contentType });
      response.end(body);
    } catch (error) {
      response.writeHead(404);
      response.end(String(error.message));
    }
  });

  await new Promise((resolveListen) => server.listen(0, "127.0.0.1", resolveListen));

  const address = server.address();
  return {
    origin: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolveClose) => server.close(resolveClose))
  };
}

export async function buildTestExtension(root, matches) {
  const outputDir = resolve(root, ".tmp", `extension-${Date.now()}`);
  await mkdir(resolve(root, ".tmp"), { recursive: true });
  await rm(outputDir, { recursive: true, force: true });
  await cp(resolve(root, "extension"), outputDir, { recursive: true });

  const manifestPath = resolve(outputDir, "manifest.json");
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  manifest.content_scripts = manifest.content_scripts.map((contentScript) => ({
    ...contentScript,
    matches
  }));
  manifest.host_permissions = [...new Set([...(manifest.host_permissions ?? []), ...matches])];

  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  return outputDir;
}

export async function startChromium({ extensionDir, startUrl, viewport = "1100,900" }) {
  const userDataDir = await mkdtemp(join(tmpdir(), "decorum-chrome-"));
  const debugPort = 40000 + Math.floor(Math.random() * 10000);
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    `--user-data-dir=${userDataDir}`,
    `--disable-extensions-except=${extensionDir}`,
    `--load-extension=${extensionDir}`,
    `--remote-debugging-port=${debugPort}`,
    `--window-size=${viewport}`,
    startUrl
  ];

  const browser = spawn(DEFAULT_CHROMIUM, args, {
    stdio: ["ignore", "pipe", "pipe"]
  });

  let stderr = "";
  browser.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });

  browser.stdout.on("data", () => {});

  await waitFor(
    () => requestJson(`http://127.0.0.1:${debugPort}/json/version`),
    "Chromium DevTools endpoint",
    15000
  );

  async function targets() {
    return requestJson(`http://127.0.0.1:${debugPort}/json/list`);
  }

  async function targetClient(predicate, description) {
    const target = await waitFor(async () => {
      const candidates = await targets();
      return candidates.find(predicate);
    }, description);

    return new CDPClient(target.webSocketDebuggerUrl).connect();
  }

  async function close() {
    browser.kill("SIGTERM");
    await new Promise((resolveExit) => browser.once("exit", resolveExit));
    await rm(userDataDir, { recursive: true, force: true });
  }

  return {
    debugPort,
    browser,
    stderr: () => stderr,
    page: () => targetClient((target) => target.type === "page" && target.url === startUrl, "Page target"),
    serviceWorker: () =>
      targetClient(
        (target) =>
          target.type === "service_worker" &&
          target.url.startsWith("chrome-extension://") &&
          target.url.endsWith("/src/background/service-worker.js"),
        "Extension service worker target"
      ),
    close
  };
}

export async function evaluate(client, expression, options = {}) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: Boolean(options.awaitPromise),
    returnByValue: options.returnByValue ?? true
  });

  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text);
  }

  return result.result.value;
}

export async function waitForExpression(
  client,
  expression,
  description,
  timeoutMs = 10000,
  options = {}
) {
  return waitFor(
    async () => evaluate(client, expression, { awaitPromise: true, ...options }),
    description,
    timeoutMs
  );
}

export function artifactName(path) {
  return basename(path).replace(/[^a-z0-9.-]+/gi, "-");
}
