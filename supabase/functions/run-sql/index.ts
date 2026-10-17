// run-sql: Supabase Edge Function that runs a signed-in taker's SQL.
//
// POST { sql: string, question_id?: number }
// Header: Authorization: Bearer <the user's Supabase access token>
//
// 1. Rejects anyone who is not signed in (401).
// 2. Runs the query as the read-only quiz_reader role, in a READ ONLY
//    transaction with a 5 s timeout, wrapped as a subquery so only a
//    single SELECT can run. At most 500 rows come back.
// 3. If question_id is given, compares the result to that question's
//    expected result (values only; column names don't matter).
// 4. Writes one row to public.audit_log (who, what SQL, ok/error).
//
// Secrets: QUIZ_READER_DATABASE_URL (set by you). SUPABASE_URL and
// SUPABASE_SERVICE_ROLE_KEY are provided by Supabase automatically.

import { createClient } from "npm:@supabase/supabase-js@2";
import postgres from "npm:postgres@3.4.5";

const MAX_ROWS = 500;
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const admin = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { persistSession: false } },
);
const sql = postgres(Deno.env.get("QUIZ_READER_DATABASE_URL")!, {
  ssl: Deno.env.get("PGSSLMODE") === "disable" ? false : "require", // Supabase needs require
  prepare: false, // required by the Supabase pooler
  max: 2,
  idle_timeout: 20,
});

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

function cleanSql(text: unknown): string {
  if (typeof text !== "string") throw new Error("Enter a query.");
  const s = text.trim().replace(/[;\s]+$/, "");
  if (!s) throw new Error("Enter a query.");
  if (s.length > 4000) throw new Error("Query is too long (4,000 characters max).");
  if (s.includes(";")) throw new Error("Run one statement at a time (remove the extra semicolon).");
  const firstWord = s.replace(/^(\s*--[^\n]*\n)+/, "").trim().split(/[\s(]/)[0].toLowerCase();
  if (!["select", "with", "values", "table", ""].includes(firstWord)) {
    throw new Error("Only SELECT queries can run here. The quiz database is read-only.");
  }
  return s;
}

// Same rule as scripts/quizdb.py: numbers to 2 decimals, everything else as text.
function norm(v: unknown) {
  if (v === null || typeof v === "boolean") return v;
  if (typeof v === "number") return Math.round(v * 100) / 100;
  return String(v);
}

function matches(
  got: { columns: string[]; rows: unknown[][] },
  exp: { columns: string[]; rows: unknown[][] },
  orderMatters: boolean,
) {
  if (got.columns.length !== exp.columns.length) return false;
  let a = got.rows.map((r) => JSON.stringify(r.map(norm)));
  let b = exp.rows.map((r) => JSON.stringify(r.map(norm)));
  if (!orderMatters) { a = [...a].sort(); b = [...b].sort(); }
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return reply(405, { error: "Use POST." });

  // 1. Signed-in users only.
  const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  const { data: auth, error: authError } = await admin.auth.getUser(token);
  if (authError || !auth?.user) return reply(401, { error: "Sign in to run queries." });
  const user = auth.user;

  let body: { sql?: unknown; question_id?: unknown };
  try { body = await req.json(); } catch { return reply(400, { error: "Body must be JSON." }); }
  const questionId = Number.isInteger(body.question_id) ? (body.question_id as number) : null;

  let query = "";
  let result: { columns: string[]; rows: unknown[][]; truncated: boolean } | null = null;
  let errorText: string | null = null;
  try {
    query = cleanSql(body.sql);
    // 2. Read-only role, read-only transaction, single SELECT, row cap.
    result = await sql.begin("read only", async (tx) => {
      await tx`set local statement_timeout = '5s'`;
      await tx`set local search_path = quiz`;
      const shape = await tx.unsafe(`select * from (${query}\n) as q limit 0`);
      const columns = shape.columns.map((c: { name: string }) => c.name);
      const [{ j }] = await tx.unsafe(
        `select json_agg(t)::text as j from (select * from (${query}\n) as q limit ${MAX_ROWS + 1}) as t`,
      );
      const objs: Record<string, unknown>[] = JSON.parse(j ?? "[]");
      return {
        columns,
        rows: objs.slice(0, MAX_ROWS).map((o) => columns.map((c: string) => o[c])),
        truncated: objs.length > MAX_ROWS,
      };
    });
  } catch (e) {
    errorText = e instanceof Error ? e.message : String(e);
  }

  // 3. Optional answer check against the stored expected result.
  let correct: boolean | null = null;
  if (result && questionId !== null) {
    const { data: q } = await admin.from("questions")
      .select("hint_result, order_matters").eq("id", questionId).maybeSingle();
    if (q) correct = matches(result, q.hint_result, q.order_matters);
  }

  // 4. Audit log (parameterized insert through the client library).
  await admin.from("audit_log").insert({
    user_id: user.id,
    user_email: user.email,
    action: "run",
    question_id: questionId,
    sql_text: typeof body.sql === "string" ? body.sql.slice(0, 4000) : "",
    ok: errorText === null,
    row_count: result ? result.rows.length : null,
    error: errorText,
  });

  if (errorText) return reply(400, { error: errorText });
  return reply(200, { ...result, correct });
});
