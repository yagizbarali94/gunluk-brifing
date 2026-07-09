// Günlük brifing — sayfa içi sohbet için sunucusuz proxy.
// Anahtar tarayıcıya inmez: Netlify ortam değişkeni ANTHROPIC_API_KEY kullanılır.
// Basit koruma: CHAT_PASS ortam değişkeni doluysa istemci x-chat-pass başlığıyla eşleşmeli.

export default async (req) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }
  const pass = process.env.CHAT_PASS;
  if (pass && req.headers.get("x-chat-pass") !== pass) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  let body;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "bad json" }, { status: 400 });
  }
  const question = (body.question || "").toString();
  const history = Array.isArray(body.history) ? body.history : [];
  const briefing = body.briefing || null;
  if (!question || question.length > 2000) {
    return Response.json({ error: "bad request" }, { status: 400 });
  }

  const system =
    "Sen Yağız'ın finansal öğrenme asistanısın. Türkçe, kısa ve net yanıt ver; " +
    "kavramları gerektiğinde bu şirketten örnekle açıkla. Kişisel yatırım tavsiyesi " +
    "verme (al/sat deme); eğitici ve dengeli ol, bilmediğinde bilmediğini söyle. " +
    "Aşağıda kullanıcının şu an incelediği günlük şirket brifinginin verisi var; " +
    "soruları öncelikle bu bağlam ve genel finans bilgisiyle yanıtla.\n\nBrifing verisi:\n" +
    (briefing ? JSON.stringify(briefing).slice(0, 12000) : "(yok)");

  const messages = history
    .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
    .slice(-8)
    .concat([{ role: "user", content: question }]);

  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: process.env.CLAUDE_MODEL || "claude-sonnet-4-6",
      max_tokens: 900,
      system,
      messages,
    }),
  });
  const data = await r.json();
  if (!r.ok) {
    return Response.json(
      { error: (data && data.error && data.error.message) || "api error" },
      { status: 502 }
    );
  }
  const answer = (data.content || [])
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("");
  return Response.json({ answer });
};

export const config = { path: "/api/chat" };
