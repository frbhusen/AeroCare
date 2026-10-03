# Changelog

## 2026-10-03
- New platform core (Flask + SQLAlchemy + PostgreSQL): multi-tenant schema with RLS, composite tenant FKs, server sessions with single-session enforcement, CSRF, login rate limiting, permission catalog with role defaults and overrides, scope-aware principal, idempotent offline operations, 30 s server-side undo deletion, secure file storage with quota, immutable audit log, notifications, CLI (schema init, superadmin bootstrap, purge, storage GC).
- Knowledge files created under `docs/`.
