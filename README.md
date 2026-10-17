# Haw Valley Water — SQL Quiz

**Quiz site:** `https://<your-github-username>.github.io/<repo-name>/` ← replace after deploying

A five-question, 20-point SQL quiz about water main breaks and repairs at a fictional utility, Haw Valley Water. Takers sign in, open a question, write a query, run it against a hosted PostgreSQL database, and see the result table. The data is made up, but shaped like a real utility's records: old cast iron breaks most, breaks cluster in winter, and some breaks are still waiting on a crew.

IDS 706 · Assignment 7.

---

## How it fits together

```
 Browser (quiz site, GitHub Pages)
   │  sign in / sign up ─────────────▶ Supabase Auth
   │  read questions, save answers ──▶ Supabase REST (row-level security)
   │  Run SQL ───────────────────────▶ Edge Function "run-sql"
   │                                     │ 1. rejects signed-out users (401)
   │                                     │ 2. runs SQL as read-only role quiz_reader
   │                                     │ 3. checks result against the answer key
   │                                     │ 4. writes to the audit log
   ▼                                     ▼
                 Supabase PostgreSQL (hosted)
                 quiz.*         the quiz data (read-only for takers)
                 public.questions, answers, audit_log

 GitHub Actions ── QUIZ_READER_DATABASE_URL (GitHub Secret) ──▶ same database, read-only
```

| Requirement | Where it lives |
|---|---|
| Hosted PostgreSQL | Supabase project; data in schema `quiz` (`supabase/01_schema.sql`, `02_seed.sql`) |
| Authentication | Supabase Auth (email + password). Signed-out users get no table privileges on `answers` and a 401 from `run-sql`. Enforced in the database and the server, not only by hiding buttons. |
| GitHub Actions + Secrets | `.github/workflows/db-check.yml` connects using the `QUIZ_READER_DATABASE_URL` secret and runs `scripts/check_db.py` |
| 20-point SQL quiz with hints | `public.questions` (`supabase/04_questions.sql`); each hint has the expected SQL and the expected result table |

### Extra credit

- **Parameterized queries.** The app's own reads and writes (questions, saved answers, audit rows) go through the Supabase client libraries, which bind values as parameters. No values are pasted into SQL strings. The one exception is the taker's query itself, which *is* the SQL being tested; it runs under the read-only role described below, so it can't change anything.
- **Audit log.** `public.audit_log` records every run and every save: who (user id and email), when, which question, the SQL text, whether it worked, and how many rows came back.
- **Integrity check.** The log is append-only (triggers block `UPDATE`, `DELETE`, and `TRUNCATE` for everyone), takers can read only their own rows and can't insert, and every row carries a SHA-256 hash of its contents plus the previous row's hash. `select * from verify_audit_log();` recomputes the chain and reports any row that was altered. CI runs this check.

### Why takers can't damage the database

Takers' SQL never runs as the database owner. The `run-sql` function connects as `quiz_reader`, a role that can only `SELECT` from the `quiz` tables. Each query also runs inside a `READ ONLY` transaction with a 5-second timeout, is wrapped as a subquery so only one `SELECT` can run, and returns at most 500 rows. `scripts/check_db.py` checks each of these on every CI run.

---

## The data

Fictional system: 5 pressure zones, 200 mains (about 132 miles), 4 crews, 120 breaks from 2023 through 2025, 116 repairs. Times are local time with no time zone.

| Table | Columns | Notes |
|---|---|---|
| `pressure_zones` | zone_id, zone_name | |
| `mains` | main_id, zone_id, material, diameter_in, length_ft, install_year | material: Cast Iron, Ductile Iron, PVC, Asbestos Cement |
| `crews` | crew_id, crew_name, shift | |
| `breaks` | break_id, main_id, reported_at, break_type, cause, est_loss_gal | one row per reported break |
| `repairs` | repair_id, break_id, crew_id, started_at, completed_at, repair_method, cost_usd | **no row** = no crew assigned yet; **completed_at empty** = still in progress |

Takers can write `mains` or `quiz.mains`; both work.

## The quiz (5 × 4 points = 20)

| # | Question | Skills |
|---|---|---|
| 1 | Miles of pipe by material | `GROUP BY`, `SUM`, `ROUND` |
| 2 | January 2025 breaks | `JOIN`, date range filter, `ORDER BY` |
| 3 | Break rate per 100 miles | two aggregations combined; a single join double-counts pipe length |
| 4 | Breaks still open | `LEFT JOIN`, `IS NULL`, `CASE` |
| 5 | Fastest crews | timestamp math, `AVG`, `HAVING` |

Each question on the site has a hint with the expected SQL and the expected result. Results are graded by values, not by matching the SQL text or the column names. Row order counts, because every question states a sort order.

---

## Using the quiz

1. Open the quiz site and create an account (email + password), or sign in.
2. Pick a question. The table list on the page shows every column.
3. Type a query and press **Run** (or Ctrl+Enter). The result table appears below with a ✓ when it matches the answer key.
4. Press **Save** to keep your answer. Saved answers come back the next time you sign in.
5. Signed out, you can read the questions, but Run and Save are disabled, and the server rejects the request even if someone calls it directly.

---

## Setting it up yourself

You need a free Supabase account and a GitHub account. Steps 1–6 happen in the Supabase dashboard.

### 1. Create the Supabase project
New project → pick a region → save the database password somewhere safe (a password manager, not this repo).

### 2. Load the database
Open **SQL Editor** and run each file, in this order, by pasting its contents and pressing Run:

1. `supabase/01_schema.sql` — tables
2. `supabase/02_seed.sql` — data
3. `supabase/03_app.sql` — questions/answers/audit tables, security rules, read-only role
4. `supabase/04_questions.sql` — the five questions and answer key

If you ever re-run `01_schema.sql`, re-run `03_app.sql` afterward so the read-only role gets its permissions back.

### 3. Give the read-only role a password
In the SQL Editor, run this once (letters and numbers only, so it works in a URL). It is not saved anywhere in git:

```sql
alter role quiz_reader with login password 'PICK_A_LONG_PASSWORD';
```

### 4. Build the connection string
Click **Connect** at the top of the dashboard → **Session pooler** → copy the URI. It looks like:

```
postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres
```

Change the user from `postgres.<ref>` to `quiz_reader.<ref>`, put in the password from step 3, and add `?sslmode=require`:

```
postgresql://quiz_reader.abcdefghijklmnop:PICK_A_LONG_PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require
```

This one string is used in three places: your local `.env`, the Edge Function secret, and the GitHub secret.

### 5. Turn on sign-in
**Authentication → Sign In / Providers → Email**: enabled. For a class quiz, turning off **Confirm email** lets graders sign up and start right away.
**Authentication → URL Configuration**: set Site URL to your quiz site's URL.

### 6. Deploy the `run-sql` function
**Edge Functions → Deploy a new function → Via editor**. Name it `run-sql`, paste in `supabase/functions/run-sql/index.ts`, and deploy.
Then **Edge Functions → Secrets** → add `QUIZ_READER_DATABASE_URL` with the string from step 4.
(`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are provided automatically.)
If Run shows a CORS or 401 error while you're signed in, open the function's details and turn off **Verify JWT**. The function checks sign-in itself (step 1 in the diagram), so this doesn't open it to signed-out users.

With the Supabase CLI instead: `supabase functions deploy run-sql` and `supabase secrets set QUIZ_READER_DATABASE_URL=...`.

### 7. Check it from your machine
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then paste your string from step 4 into .env
python scripts/check_db.py  # every line should say PASS
```

### 8. GitHub Actions
Repo → **Settings → Secrets and variables → Actions → New repository secret**: name `QUIZ_READER_DATABASE_URL`, value from step 4. Push to `main`, or run **Database check** by hand from the Actions tab. A green run means CI reached the hosted database using the secret. The workflow also runs every Monday, which keeps a free Supabase project from pausing.

### 9. The quiz site
The page is one HTML file in `docs/index.html`. At the top it needs your project URL and your **anon / publishable** key (Supabase → Project Settings → API). That key is meant to be public; row-level security and the Edge Function protect the data. **Never put the service_role key or a database password in the page.**
Turn on GitHub Pages: **Settings → Pages → Deploy from a branch → main → /docs**.

### Changing the data or questions
Edit `scripts/generate_seed.py` or `scripts/questions.py`, then:
```bash
python scripts/generate_seed.py      # rewrites supabase/02_seed.sql
# reload 01 → 02 → 03 in the SQL Editor
python scripts/build_questions.py    # reruns every hint and rewrites 04_questions.sql
# run 04 in the SQL Editor
```
Expected results are always produced by running the hint SQL, never typed by hand.

---

## Repository layout

```
supabase/
  01_schema.sql          quiz tables
  02_seed.sql            generated data
  03_app.sql             app tables, row-level security, read-only role, audit log + integrity check
  04_questions.sql       generated questions + answer key
  functions/run-sql/     Edge Function that runs takers' SQL
scripts/
  generate_seed.py       makes 02_seed.sql (fixed random seed)
  questions.py           the five questions
  build_questions.py     makes 04_questions.sql by running each hint
  check_db.py            the CI health check
  quizdb.py              shared run/compare code (matches the Edge Function)
docs/index.html          the quiz site (GitHub Pages)
.github/workflows/db-check.yml
```

## Known limits

- The database owner (`postgres`) could still disable the audit triggers and rewrite the whole hash chain. The integrity check protects the log from quiz takers, not from the project owner.
- A semicolon inside a string literal is rejected by the one-statement rule. None of the questions need one.

## Screenshots

_Add: signed-out view (Run disabled), a correct run with ✓, the hint open, and a green Actions run._
