// Günlük brifing — "⭐ Hisse sabitle" paneli için sunucusuz uç.
// pinned.json'ı GitHub Contents API ile okur/günceller; her değişiklik
// main'e commit olur, ertesi sabahki workflow pinned.json'ı okur.
// Gerekli Netlify ortam değişkenleri:
//   GITHUB_TOKEN — fine-grained PAT, sadece bu repo, Contents: Read and write
//   CHAT_PASS    — sohbetle aynı erişim kelimesi (istemci x-chat-pass başlığı)

const REPO = "yagizbarali94/gunluk-brifing";
const FILE_API = `https://api.github.com/repos/${REPO}/contents/pinned.json`;

export default async (req) => {
  const pass = process.env.CHAT_PASS;
  if (!pass) {
    return Response.json({ error: "CHAT_PASS ayarlı değil — sabitleme kapalı" }, { status: 503 });
  }
  if (req.headers.get("x-chat-pass") !== pass) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    return Response.json({ error: "GITHUB_TOKEN eksik — Netlify ortam değişkenlerine ekle" }, { status: 503 });
  }

  const gh = {
    authorization: `Bearer ${token}`,
    accept: "application/vnd.github+json",
    "user-agent": "gunluk-brifing-pin",
  };

  const cur = await fetch(`${FILE_API}?ref=main`, { headers: gh });
  let sha = null;
  let pins = {};
  if (cur.status === 200) {
    const j = await cur.json();
    sha = j.sha;
    try {
      pins = JSON.parse(Buffer.from(j.content, "base64").toString("utf8")) || {};
    } catch { pins = {}; }
  } else if (cur.status !== 404) {
    return Response.json({ error: "GitHub okunamadı (" + cur.status + ")" }, { status: 502 });
  }

  if (req.method === "GET") {
    return Response.json({ pins });
  }
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  let body;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "bad json" }, { status: 400 });
  }
  const action = body.action === "remove" ? "remove" : "add";
  const date = String(body.date || "");
  const ticker = String(body.ticker || "").toUpperCase().trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return Response.json({ error: "tarih YYYY-MM-DD olmalı" }, { status: 400 });
  }
  const todayUtc = new Date().toISOString().slice(0, 10);
  if (action === "add" && date < todayUtc) {
    return Response.json({ error: "geçmiş tarihe sabitlenemez" }, { status: 400 });
  }
  if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(ticker)) {
    return Response.json({ error: "geçersiz hisse kodu" }, { status: 400 });
  }

  const list = new Set(pins[date] || []);
  if (action === "add") list.add(ticker);
  else list.delete(ticker);
  if (list.size) pins[date] = [...list].sort();
  else delete pins[date];

  const content = Buffer.from(JSON.stringify(pins, null, 1) + "\n").toString("base64");
  const put = await fetch(FILE_API, {
    method: "PUT",
    headers: { ...gh, "content-type": "application/json" },
    body: JSON.stringify({
      message: `pin: ${action === "add" ? "+" : "-"}${ticker} @ ${date}`,
      content,
      branch: "main",
      ...(sha ? { sha } : {}),
    }),
  });
  if (!put.ok) {
    const e = await put.json().catch(() => ({}));
    return Response.json({ error: e.message || "GitHub'a yazılamadı" }, { status: 502 });
  }
  return Response.json({ pins });
};

export const config = { path: "/api/pin" };
