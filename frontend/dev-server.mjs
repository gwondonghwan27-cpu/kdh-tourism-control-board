import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const serverDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(serverDir, "..");
const port = 5173;
const mime = {
  ".html": "text/html;charset=utf-8",
  ".js": "text/javascript;charset=utf-8",
  ".css": "text/css;charset=utf-8",
  ".csv": "text/csv;charset=utf-8",
};

http
  .createServer((request, response) => {
    let route = decodeURIComponent(request.url.split("?")[0]);
    if (request.method === "OPTIONS") {
      response.writeHead(204, corsHeaders());
      response.end();
      return;
    }
    if (request.method === "GET" && route === "/api/health") {
      sendJson(response, 200, { ok: true, service: "drawing-recognition-api", supports_cors: true });
      return;
    }
    if (request.method === "POST" && route === "/api/simulate-network") {
      handlePythonJsonRequest(request, response, "simulate_network_api.py", "simulation");
      return;
    }
    if (route === "/") route = "/frontend/index.html";
    const relativePath = path.normalize(route).replace(/^([\\/])+/, "");
    const filePath = path.join(root, relativePath);

    if (!filePath.startsWith(root)) {
      response.writeHead(403);
      response.end("forbidden");
      return;
    }

    fs.readFile(filePath, (error, body) => {
      if (error) {
        response.writeHead(404);
        response.end("missing");
        return;
      }
      response.writeHead(200, { ...corsHeaders(), "content-type": mime[path.extname(filePath)] || "text/plain;charset=utf-8" });
      response.end(body);
    });
  })
  .listen(port, "127.0.0.1");

function handlePythonJsonRequest(request, response, scriptName, label) {
  let body = "";
  request.setEncoding("utf8");
  request.on("data", (chunk) => {
    body += chunk;
    if (body.length > 30 * 1024 * 1024) request.destroy();
  });
  request.on("end", () => {
    const python = process.env.PYTHON || path.join(root, ".venv-win", "Scripts", "python.exe");
    const fallbackPython = "python";
    runPythonProcess(python, scriptName, body, label, (error, result) => {
      if (!error) {
        sendJson(response, 200, result);
        return;
      }
      runPythonProcess(fallbackPython, scriptName, body, label, (fallbackError, fallbackResult) => {
        if (fallbackError) {
          sendJson(response, 500, { error: fallbackError.message || String(fallbackError) });
          return;
        }
        sendJson(response, 200, fallbackResult);
      });
    });
  });
}

function runPythonProcess(command, scriptName, body, label, callback) {
  const script = path.join(root, "scripts", scriptName);
  const child = spawn(command, [script], { cwd: root, stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  child.on("error", callback);
  child.on("close", (code) => {
    if (code !== 0) {
      callback(new Error(stderr || `${label} process exited with code ${code}`));
      return;
    }
    try {
      callback(null, JSON.parse(stdout));
    } catch (error) {
      callback(new Error(`${label} response parse failed: ${error.message}`));
    }
  });
  child.stdin.end(body);
}

function sendJson(response, status, payload) {
  response.writeHead(status, { ...corsHeaders(), "content-type": "application/json;charset=utf-8" });
  response.end(JSON.stringify(payload));
}

function corsHeaders() {
  return {
    "access-control-allow-origin": "*",
    "access-control-allow-private-network": "true",
    "access-control-allow-methods": "GET,HEAD,POST,OPTIONS",
    "access-control-allow-headers": "content-type",
  };
}
