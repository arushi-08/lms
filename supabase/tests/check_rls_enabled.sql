-- Paste this into the Supabase SQL editor. For every table in the public
-- schema it reports whether row level security is on, and what the public
-- `anon` role can actually do to it.
--
-- The anon key ships in the browser, so it is public. Anything anon can do,
-- any visitor can do.
--
-- Verdicts:
--
--   EXPOSED             RLS is off and anon holds grants. Anyone with your
--                       anon key can do exactly those things to every row.
--                       Fix this before real accounts exist.
--   RLS OFF             RLS is off, but anon has no grants either. Not
--                       reachable from a browser today; one stray GRANT away.
--   GRANTED, NO POLICY  RLS is on and anon has grants, but no policy allows
--                       anything, so every read comes back empty. Safe, but
--                       usually not what was intended.
--   locked              RLS is on and anon has no grants at all. Reachable
--                       only with the service role. This is the correct state
--                       for answer keys, payments and audit tables.
--   ok                  RLS on, anon granted, policies present.
--
-- Column-level grants are counted: a table can look ungranted at table level
-- while still exposing specific columns. Missing that would under-report.
--
-- This query modifies nothing.

with tables as (
    select c.relname as table_name, c.relrowsecurity as rls_enabled
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
),
table_privs as (
    select table_name, string_agg(distinct privilege_type, ', ' order by privilege_type) as privs
    from information_schema.role_table_grants
    where table_schema = 'public' and grantee = 'anon'
    group by table_name
),
column_privs as (
    select table_name,
           string_agg(distinct privilege_type, ', ' order by privilege_type) as privs,
           count(distinct column_name) as n_columns
    from information_schema.role_column_grants
    where table_schema = 'public' and grantee = 'anon'
    group by table_name
),
resolved as (
    select
        t.table_name,
        t.rls_enabled,
        coalesce(p.n, 0) as policies,
        case
            when tp.privs is not null then tp.privs
            when cp.privs is not null then cp.privs || ' (' || cp.n_columns || ' columns)'
        end as anon_can
    from tables t
    left join table_privs  tp on tp.table_name = t.table_name
    left join column_privs cp on cp.table_name = t.table_name
    left join (
        select tablename as table_name, count(*) as n
        from pg_policies where schemaname = 'public' group by tablename
    ) p on p.table_name = t.table_name
)
select
    table_name,
    rls_enabled,
    policies,
    coalesce(anon_can, '-') as anon_can,
    case
        when not rls_enabled and anon_can is not null then 'EXPOSED'
        when not rls_enabled                          then 'RLS OFF'
        when anon_can is null                         then 'locked'
        when policies = 0                             then 'GRANTED, NO POLICY'
        else 'ok'
    end as verdict
from resolved
order by
    case
        when not rls_enabled and anon_can is not null then 0
        when not rls_enabled                          then 1
        when anon_can is null                         then 3
        when policies = 0                             then 2
        else 4
    end,
    table_name;
