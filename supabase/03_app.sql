-- 03_app.sql
-- App tables (questions, saved answers, audit log), row-level security,
-- the read-only role that runs takers' SQL, and the audit-log integrity check.
-- Run after 02_seed.sql. Safe to re-run.

------------------------------------------------------------------------
-- 1. Read-only role for running quiz takers' SQL
------------------------------------------------------------------------
-- Created WITHOUT a password here so no password is ever saved in git.
-- After running this file, set the password once by hand (see README):
--   alter role quiz_reader with login password '<your password>';
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'quiz_reader') then
        create role quiz_reader nologin;
    end if;
end $$;

grant usage on schema quiz to quiz_reader;
grant select on all tables in schema quiz to quiz_reader;
alter role quiz_reader set search_path = quiz;
alter role quiz_reader set statement_timeout = '5s';
alter role quiz_reader set default_transaction_read_only = on;
-- quiz_reader gets no privileges on the app tables below, so a taker's SQL
-- can read quiz.* and nothing else, and can never write.

------------------------------------------------------------------------
-- 2. Questions (readable by everyone, including signed-out visitors)
------------------------------------------------------------------------
create table if not exists public.questions (
    id              int primary key,
    title           text not null,
    prompt          text not null,
    output_columns  text not null,
    order_matters   boolean not null,
    points          int  not null check (points > 0),
    hint_sql        text not null,
    hint_result     jsonb not null      -- {"columns": [...], "rows": [[...], ...]}
);
alter table public.questions enable row level security;
drop policy if exists questions_read on public.questions;
create policy questions_read on public.questions for select using (true);
grant select on public.questions to anon, authenticated, quiz_reader;

------------------------------------------------------------------------
-- 3. Saved answers (signed-in users only, own rows only)
------------------------------------------------------------------------
create table if not exists public.answers (
    user_id      uuid not null default auth.uid() references auth.users(id) on delete cascade,
    question_id  int  not null references public.questions(id),
    sql_text     text not null check (length(sql_text) <= 4000),
    updated_at   timestamptz not null default now(),
    primary key (user_id, question_id)
);
alter table public.answers enable row level security;
drop policy if exists answers_select_own on public.answers;
drop policy if exists answers_insert_own on public.answers;
drop policy if exists answers_update_own on public.answers;
create policy answers_select_own on public.answers for select to authenticated using (user_id = auth.uid());
create policy answers_insert_own on public.answers for insert to authenticated with check (user_id = auth.uid());
create policy answers_update_own on public.answers for update to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
revoke all on public.answers from anon;
grant select, insert, update on public.answers to authenticated;

------------------------------------------------------------------------
-- 4. Audit log: append-only, hash-chained
------------------------------------------------------------------------
create sequence if not exists public.audit_log_id_seq;
create table if not exists public.audit_log (
    id           bigint primary key,
    created_at   timestamptz not null default now(),
    user_id      uuid not null,
    user_email   text,
    action       text not null check (action in ('run', 'save')),
    question_id  int,
    sql_text     text not null,
    ok           boolean not null,
    row_count    int,
    error        text,
    prev_hash    text,
    row_hash     text not null
);

-- The hash covers every content column plus the previous row's hash,
-- so editing, deleting, or re-ordering any row breaks the chain.
create or replace function public.audit_row_hash(r public.audit_log)
returns text language sql immutable as $$
    select encode(sha256(convert_to(concat_ws('|',
        coalesce(r.prev_hash, 'GENESIS'),
        r.id,
        to_char(r.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
        r.user_id, coalesce(r.user_email, ''), r.action,
        coalesce(r.question_id::text, ''), r.sql_text, r.ok,
        coalesce(r.row_count::text, ''), coalesce(r.error, '')
    ), 'UTF8')), 'hex')
$$;

create or replace function public.audit_before_insert()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    -- One writer at a time, so ids and the chain stay in the same order.
    perform pg_advisory_xact_lock(706706);
    new.id := nextval('public.audit_log_id_seq');
    new.created_at := now();
    select row_hash into new.prev_hash from public.audit_log order by id desc limit 1;
    new.row_hash := public.audit_row_hash(new);
    return new;
end $$;

create or replace function public.audit_block_change()
returns trigger language plpgsql as $$
begin
    raise exception 'audit_log is append-only: % is not allowed', tg_op;
end $$;

drop trigger if exists audit_hash on public.audit_log;
drop trigger if exists audit_no_update on public.audit_log;
drop trigger if exists audit_no_truncate on public.audit_log;
create trigger audit_hash before insert on public.audit_log
    for each row execute function public.audit_before_insert();
create trigger audit_no_update before update or delete on public.audit_log
    for each row execute function public.audit_block_change();
create trigger audit_no_truncate before truncate on public.audit_log
    for each statement execute function public.audit_block_change();

alter table public.audit_log enable row level security;
drop policy if exists audit_select_own on public.audit_log;
create policy audit_select_own on public.audit_log for select to authenticated using (user_id = auth.uid());
-- Takers can read their own history and nothing else. Only the server
-- (service_role, used by the run-sql function) and the save trigger insert.
revoke all on public.audit_log from anon, authenticated;
grant select on public.audit_log to authenticated;
grant select, insert on public.audit_log to service_role;

-- Every save of an answer is logged automatically.
create or replace function public.log_answer_save()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    insert into public.audit_log (user_id, user_email, action, question_id, sql_text, ok)
    values (new.user_id, (select email from auth.users where id = new.user_id),
            'save', new.question_id, new.sql_text, true);
    return new;
end $$;
drop trigger if exists answers_audit on public.answers;
create trigger answers_audit after insert or update on public.answers
    for each row execute function public.log_answer_save();

-- Integrity check: recompute the chain and report any row that doesn't match.
create or replace function public.verify_audit_log()
returns table (total_rows bigint, broken_rows bigint, first_broken_id bigint)
language plpgsql security definer set search_path = public as $$
declare
    r public.audit_log;
    expected_prev text := null;
    n bigint := 0; bad bigint := 0; first_bad bigint := null;
begin
    for r in select * from public.audit_log order by id loop
        n := n + 1;
        if r.prev_hash is distinct from expected_prev
           or r.row_hash <> public.audit_row_hash(r) then
            bad := bad + 1;
            first_bad := coalesce(first_bad, r.id);
        end if;
        expected_prev := r.row_hash;
    end loop;
    return query select n, bad, first_bad;
end $$;
revoke all on function public.verify_audit_log() from public;
grant execute on function public.verify_audit_log() to authenticated, service_role, quiz_reader;
