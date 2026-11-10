# Supabase database CA

`supabase-ca-2021.crt` is a public CA certificate downloaded on 10 November 2026 from the certificate link in this project's authenticated Supabase Database Settings:

https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt

File SHA-256: `700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`.

The session endpoint was verified with this CA and hostname verification, negotiating TLS 1.3. This is not a private key. No system-wide trust settings were changed. Future certificate rotation must follow the project's official certificate instructions.

The local private connection uses `sslmode=verify-full` and this file's absolute path. Containers include it at `/app/certs/supabase-ca-2021.crt`; configure the container connection's `sslrootcert` accordingly. Do not copy a Mac-specific path into a hosted container.
