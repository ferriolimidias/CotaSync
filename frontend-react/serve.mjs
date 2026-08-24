import app from "./.output/server/index.mjs";

const port = Number(process.env.PORT || 3000);
const hostname = process.env.HOST || "0.0.0.0";
const apiProxyTarget = (
  process.env.API_PROXY_TARGET || "http://cotasync_test_backend:8000"
).replace(/\/$/, "");

Bun.serve({
  hostname,
  port,
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      const target = new URL(`${apiProxyTarget}${url.pathname}${url.search}`);
      return fetch(target, request);
    }
    if (url.pathname.startsWith("/assets/") || url.pathname === "/favicon.ico") {
      const filePath = new URL(`./.output/public${url.pathname}`, import.meta.url);
      const asset = Bun.file(filePath);
      if (await asset.exists()) return new Response(asset);
    }
    return app.fetch(request, {}, { waitUntil() {} });
  },
});

console.log(`CotaSync React staging server: http://${hostname}:${port}`);
