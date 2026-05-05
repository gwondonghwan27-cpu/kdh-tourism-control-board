import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const root = path.resolve("..");
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
      response.writeHead(200, { "content-type": mime[path.extname(filePath)] || "text/plain;charset=utf-8" });
      response.end(body);
    });
  })
  .listen(port, "127.0.0.1");
