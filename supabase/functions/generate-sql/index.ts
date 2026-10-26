// generate-sql: retrieves quiz knowledge from Neo4j, then asks Gemini to draft SQL.
//
// POST { question: string }
// Header: Authorization: Bearer <signed-in user's Supabase access token>
//
// Generated SQL is returned for the user to inspect; this function never executes it.
// Set GEMINI_API_KEY, NEO4J_URI, NEO4J_DATABASE, NEO4J_USERNAME, and
// NEO4J_PASSWORD as Supabase Edge Function secrets.

import { createClient } from "npm:@supabase/supabase-js@2";

const EMBEDDING_MODEL = "gemini-embedding-2";
const GENERATION_MODEL = Deno.env.get("GEMINI_MODEL") ?? "gemini-2.5-flash";
const VECTOR_INDEX = "rag_knowledge";
const TOP_K = 4;
const MAX_QUESTION_LENGTH = 1200;

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name);
  if (!value) throw new Error(`Missing server configuration: ${name}.`);
  return value;
}

function basicAuthorization(username: string, password: string): string {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `Basic ${btoa(binary)}`;
}

async function postJson(url: string, body: unknown, headers: HeadersInit) {
  const requestHeaders = new Headers(headers);
  requestHeaders.set("Content-Type", "application/json");
  const response = await fetch(url, {
    method: "POST",
    headers: requestHeaders,
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(`Upstream request failed with status ${response.status}.`);
  }
  return payload;
}

async function embedQuestion(question: string, apiKey: string): Promise<number[]> {
  const payload = await postJson(
    `https://generativelanguage.googleapis.com/v1beta/models/${EMBEDDING_MODEL}:embedContent`,
    {
      model: `models/${EMBEDDING_MODEL}`,
      content: {
        parts: [{ text: `task: search result | query: ${question}` }],
      },
    },
    { "x-goog-api-key": apiKey },
  );

  const values = payload?.embedding?.values;
  if (!Array.isArray(values) || values.length === 0 ||
    !values.every((value: unknown) => typeof value === "number" && Number.isFinite(value))) {
    throw new Error("Gemini returned an invalid question embedding.");
  }
  return values;
}

type RetrievedDocument = {
  title: string;
  kind: string;
  text: string;
  score: number;
};

function isRetrievedDocument(value: unknown): value is RetrievedDocument {
  if (typeof value !== "object" || value === null) return false;
  const document = value as Record<string, unknown>;
  return typeof document.title === "string" &&
    typeof document.kind === "string" &&
    typeof document.text === "string" &&
    typeof document.score === "number";
}

async function retrieveContext(
  embedding: number[],
  neo4jUri: string,
  database: string,
  username: string,
  password: string,
): Promise<RetrievedDocument[]> {
  const uri = new URL(neo4jUri);
  if (!["neo4j+s:", "neo4j+ssc:"].includes(uri.protocol) || !uri.hostname) {
    throw new Error("NEO4J_URI must be an Aura neo4j+s:// connection URI.");
  }
  const endpoint = `https://${uri.hostname}/db/${encodeURIComponent(database)}/query/v2`;
  const payload = await postJson(
    endpoint,
    {
      statement: "CALL db.index.vector.queryNodes($index, $top_k, $embedding) " +
        "YIELD node, score RETURN node.title AS title, node.kind AS kind, " +
        "node.text AS text, score ORDER BY score DESC",
      parameters: { index: VECTOR_INDEX, top_k: TOP_K, embedding },
    },
    { Authorization: basicAuthorization(username, password) },
  );

  if (Array.isArray(payload?.errors) && payload.errors.length > 0) {
    console.error("Neo4j retrieval failed:", payload.errors);
    throw new Error("Neo4j could not retrieve context. Check the database and vector index.");
  }

  const fields: string[] = payload?.data?.fields;
  const values: unknown[][] = payload?.data?.values;
  if (!Array.isArray(fields) || !Array.isArray(values)) {
    throw new Error("Neo4j returned an invalid retrieval response.");
  }

  const columnIndex = Object.fromEntries(fields.map((field, index) => [field, index]));
  if (!["title", "kind", "text", "score"].every((field) => field in columnIndex)) {
    throw new Error("Neo4j returned an unexpected retrieval result shape.");
  }
  const documents = values.map((row) => ({
    title: row[columnIndex.title],
    kind: row[columnIndex.kind],
    text: row[columnIndex.text],
    score: row[columnIndex.score],
  }));
  if (documents.length === 0 || !documents.every(isRetrievedDocument)) {
    throw new Error("Neo4j returned no usable knowledge documents.");
  }
  return documents;
}

function extractSql(text: string): string {
  const trimmed = text.trim();
  const fenced = trimmed.match(/^```(?:sql)?\s*([\s\S]*?)\s*```$/i);
  const sql = (fenced?.[1] ?? trimmed).trim();
  if (!sql) throw new Error("Gemini returned an empty SQL response.");
  return sql;
}

async function generateSql(
  question: string,
  documents: RetrievedDocument[],
  apiKey: string,
): Promise<string> {
  const context = documents.map((document, index) =>
    `[${index + 1}] ${document.title} (${document.kind}, similarity ${document.score.toFixed(3)})\n${document.text}`
  ).join("\n\n");

  const payload = await postJson(
    `https://generativelanguage.googleapis.com/v1beta/models/${GENERATION_MODEL}:generateContent`,
    {
      systemInstruction: {
        parts: [{
          text: "You write PostgreSQL SQL for the fictional Haw Valley Water quiz database. " +
            "Use only the supplied retrieved context. Return one SQL query and no markdown fences. " +
            "Do not claim you executed or validated the query. If the context is insufficient, " +
            "make a reasonable best-effort query using only documented tables and columns.",
        }],
      },
      contents: [{
        role: "user",
        parts: [{
          text: `Retrieved knowledge:\n${context}\n\nNatural-language question:\n${question}`,
        }],
      }],
      generationConfig: { temperature: 0.2, maxOutputTokens: 700 },
    },
    { "x-goog-api-key": apiKey },
  );

  const text = payload?.candidates?.[0]?.content?.parts
    ?.map((part: { text?: unknown }) => typeof part.text === "string" ? part.text : "")
    .join("")
    .trim();
  if (!text) {
    console.error("Gemini returned no text:", payload?.promptFeedback ?? payload?.candidates);
    throw new Error("Gemini did not return SQL. Try rephrasing the question.");
  }
  return extractSql(text);
}

const supabaseUrl = requiredEnv("SUPABASE_URL");
const serviceRoleKey = requiredEnv("SUPABASE_SERVICE_ROLE_KEY");
const admin = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false },
});

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return reply(405, { error: "Use POST." });

  const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  const { data: auth, error: authError } = await admin.auth.getUser(token);
  if (authError || !auth?.user) return reply(401, { error: "Sign in to generate SQL." });

  let body: { question?: unknown };
  try {
    body = await req.json();
  } catch {
    return reply(400, { error: "Body must be JSON." });
  }

  if (typeof body.question !== "string" || !body.question.trim()) {
    return reply(400, { error: "Enter a natural-language question." });
  }
  const question = body.question.trim();
  if (question.length > MAX_QUESTION_LENGTH) {
    return reply(400, { error: `Question must be ${MAX_QUESTION_LENGTH} characters or fewer.` });
  }

  try {
    const apiKey = requiredEnv("GEMINI_API_KEY");
    const embedding = await embedQuestion(question, apiKey);
    const documents = await retrieveContext(
      embedding,
      requiredEnv("NEO4J_URI"),
      requiredEnv("NEO4J_DATABASE"),
      requiredEnv("NEO4J_USERNAME"),
      requiredEnv("NEO4J_PASSWORD"),
    );
    const sql = await generateSql(question, documents, apiKey);
    return reply(200, { sql, retrieved: documents });
  } catch (error) {
    console.error("SQL generation failed:", error);
    const message = error instanceof Error ? error.message : "SQL generation failed.";
    return reply(502, { error: message });
  }
});
