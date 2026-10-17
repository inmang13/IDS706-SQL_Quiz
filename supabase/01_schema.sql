-- 01_schema.sql
-- Quiz data: a fictional water utility ("Haw Valley Water") and its main breaks.
-- Everything a quiz taker can query lives in the `quiz` schema.
-- Run this first in the Supabase SQL Editor.

drop schema if exists quiz cascade;
create schema quiz;

-- Pressure zones: areas of the system served at the same pressure.
create table quiz.pressure_zones (
    zone_id     int primary key,
    zone_name   text not null unique
);

-- Mains: one row per pipe segment.
create table quiz.mains (
    main_id       int primary key,
    zone_id       int  not null references quiz.pressure_zones(zone_id),
    material      text not null check (material in ('Cast Iron','Ductile Iron','PVC','Asbestos Cement')),
    diameter_in   int  not null check (diameter_in > 0),
    length_ft     int  not null check (length_ft > 0),
    install_year  int  not null check (install_year between 1900 and 2025)
);

-- Crews that repair breaks.
create table quiz.crews (
    crew_id    int primary key,
    crew_name  text not null unique,
    shift      text not null check (shift in ('Day','Night'))
);

-- Breaks: one row per reported break. Times are local time (no time zone).
create table quiz.breaks (
    break_id      int primary key,
    main_id       int  not null references quiz.mains(main_id),
    reported_at   timestamp not null,
    break_type    text not null check (break_type in ('Circumferential','Longitudinal','Joint Leak','Corrosion Hole')),
    cause         text not null check (cause in ('Frost','Corrosion','Ground Movement','Pressure Surge','Third-Party Damage')),
    est_loss_gal  int  not null check (est_loss_gal >= 0)
);

-- Repairs: zero or one per break.
-- No row            = no crew assigned yet.
-- completed_at NULL = crew started but has not finished.
create table quiz.repairs (
    repair_id      int primary key,
    break_id       int  not null unique references quiz.breaks(break_id),
    crew_id        int  not null references quiz.crews(crew_id),
    started_at     timestamp not null,
    completed_at   timestamp,
    repair_method  text not null check (repair_method in ('Clamp','Pipe Section Replacement','Joint Repair')),
    cost_usd       numeric(10,2),
    check (completed_at is null or completed_at > started_at)
);

create index on quiz.mains(zone_id);
create index on quiz.breaks(main_id);
create index on quiz.repairs(crew_id);
