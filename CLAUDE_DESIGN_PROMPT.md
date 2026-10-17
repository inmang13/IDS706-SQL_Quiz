Design and build the quiz site for a SQL practice quiz. It must be a working single page, not just a mockup: one self-contained index.html that I will host on GitHub Pages.

WHAT IT IS
A 5-question, 20-point SQL quiz about water main breaks at a fictional utility, "Haw Valley Water." A classmate signs in, opens a question, types SQL, runs it against a live Postgres database, and sees the result table. A TA grades by running SQL and comparing the result to the hint.

WHAT TO AVOID (I disliked an earlier version of this)
- Long made-up business stories in the questions. Show question text exactly as the database gives it; don't add to it.
- Repeating the same title and text in two places.
- Clutter. One question on screen at a time.

LAYOUT
- Top bar: "Haw Valley Water · SQL Quiz", total score (e.g. "8 / 20"), and Sign in / the signed-in email + Sign out.
- Left: list of the 5 questions with points and a status dot (not started / saved / correct). On phones this becomes a row of numbered tabs.
- Main panel for the selected question, top to bottom:
  1. Title and points.
  2. Prompt (1–2 sentences, from the database).
  3. "Return: <output_columns>" on its own line, in monospace.
  4. SQL editor: large monospace textarea. Ctrl/Cmd+Enter runs.
  5. Buttons: Run, Save. A small "Saved 2:14 pm" note after saving.
  6. Result: row count, then a table with sticky header that scrolls inside its own box. A clear badge: "✓ Matches the answer key" or "Not a match yet". Errors from the database show in a calm red box with the message as-is.
  7. "Show hint" disclosure: the expected SQL in a code block with a Copy button, and the expected result as a table.
- Right side (collapsible, below the editor on phones): "Tables" panel listing each table and its columns, so takers never have to guess names.

SIGNED-OUT STATE (this is graded, it must be obvious)
Questions, tables panel, and hints are visible. The editor is read-only and greyed, Run and Save are disabled, and a short line says "Sign in to run and save queries." Sign in / Create account is a small modal with email + password and a toggle between the two.

VISUAL DIRECTION
Calm, engineering-tool feel: light background, one restrained blue accent, high-contrast text, generous spacing, system font for text and a monospace font for SQL and results. Also works in dark mode. Fully usable at 375 px wide.

TABLES PANEL CONTENT (all in schema quiz; "mains" and "quiz.mains" both work)
pressure_zones(zone_id, zone_name)
mains(main_id, zone_id, material, diameter_in, length_ft, install_year)
crews(crew_id, crew_name, shift)
breaks(break_id, main_id, reported_at, break_type, cause, est_loss_gal)
repairs(repair_id, break_id, crew_id, started_at, completed_at, repair_method, cost_usd)
Note under repairs: "No row = no crew assigned yet. Empty completed_at = still in progress."

HOW THE PAGE TALKS TO THE BACKEND (Supabase; use these exactly)
Load supabase-js v2 from https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2 and put these two constants at the very top of the script so I can paste my values in:
  const SUPABASE_URL = "https://YOUR-PROJECT.supabase.co";
  const SUPABASE_ANON_KEY = "YOUR-ANON-OR-PUBLISHABLE-KEY";
Never include any other key or password.

- Auth: supabase.auth.signInWithPassword({ email, password }), supabase.auth.signUp({ email, password }), supabase.auth.signOut(), and supabase.auth.onAuthStateChange to update the page.
- Questions (works signed out):
  supabase.from("questions").select("id,title,prompt,output_columns,points,hint_sql,hint_result").order("id")
  hint_result is { "columns": [...], "rows": [[...], ...] }.
- Saved answers (signed in only):
  load:  supabase.from("answers").select("question_id,sql_text")
  save:  supabase.from("answers").upsert({ user_id: session.user.id, question_id, sql_text }, { onConflict: "user_id,question_id" })
- Run (signed in only):
  const { data, error } = await supabase.functions.invoke("run-sql", { body: { sql, question_id } });
  Success: data = { columns: [...], rows: [[...], ...], truncated: boolean, correct: true | false | null }
  Failure: error is set; get the message with  (await error.context.json()).error
  If truncated is true, say "Showing first 500 rows."
- Show result values exactly as returned (including timestamps like 2025-01-05T03:15:00), so takers can compare to the hint. Show null as a muted "NULL".
- Score: sum the points of questions whose latest Run in this session returned correct: true.

Keep all JavaScript in the one file, no build step, no frameworks beyond supabase-js.
