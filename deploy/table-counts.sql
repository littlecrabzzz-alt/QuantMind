-- Exact table counts, including empty tables; no account/secret values in output.
SELECT format('SELECT %L || ''|'' || count(*) FROM %I.%I;', schemaname || '.' || tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname='public' ORDER BY schemaname, tablename
\gexec
