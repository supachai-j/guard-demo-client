# Multi-Workspace Design — guard-demo-client

**Status**: Proposal — awaiting ตั้ม review
**Date**: 2026-05-17
**Author**: Oracle (Tumz Presale)
**Context**: [[guard-demo-platform-direction]] Phase 2 (Standardize as internal tool). Team size confirmed 18 ppl (Presale Security 12 + SA Team 6).

## Goal

Move guard-demo-client from single-tenant single-user to **multi-workspace, multi-user** so the 18-person team can use it across multiple deals concurrently without config/data collision.

**Non-goals** (Phase 3, not now):
- Customer-facing SaaS
- Org-level billing / SSO / SCIM
- Public marketplace of workspaces

## Personas

| Persona | What they do |
|---|---|
| **Workspace owner** | Creates workspace per deal, invites teammates, manages provider keys |
| **Workspace editor** | Runs playbooks, creates custom playbooks, edits config |
| **Workspace viewer** | Reads run history, comparison, audit log (no writes) |

For 18-person internal team: owner+editor only initially; viewer for later (Phase 3 customer-share).

## Data Model

### New tables

```python
class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True)  # url-safe id, e.g. "aigw-mmt"
    name = Column(String)  # display name e.g. "AI Gateway — MMT"
    description = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime, nullable=True)  # soft-delete

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)  # bcrypt
    display_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    is_superadmin = Column(Boolean, default=False)  # can create workspaces
    created_at = Column(DateTime, default=datetime.utcnow)

class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role = Column(String)  # "owner" | "editor" | "viewer"
    joined_at = Column(DateTime, default=datetime.utcnow)
```

### Scope existing tables — add `workspace_id` column

Tables that become workspace-scoped:
- `app_config` — was single row, becomes 1 row per workspace (config table → `workspace_config`)
- `playbooks` — custom playbooks scoped per workspace; built-ins still global
- `playbook_runs` — every run belongs to one workspace
- `audit_log` — per-workspace audit trail
- `conversations` + `messages` — per-workspace chat history
- `session_recordings` — per-workspace
- `demo_prompts` — per-workspace
- `rag_sources` — per-workspace
- `tools` — per-workspace
- `mcp_tool_capabilities` — per-workspace

Tables that stay global:
- `users`, `workspaces`, `workspace_members`
- Built-in playbooks (live in code, not DB)

### Migration strategy

1. Add `workspace_id` column to each scoped table (NULL-able initially)
2. On migration: create one default workspace `"default"`, all existing rows get `workspace_id=1`
3. Backfill complete → make column NOT NULL
4. Use existing `backend/migrations.py` Migration dataclass pattern

## API Changes

### New endpoints

```
POST   /api/workspaces                  Create workspace (superadmin)
GET    /api/workspaces                  List workspaces user is member of
GET    /api/workspaces/{slug}           Workspace detail
PUT    /api/workspaces/{slug}           Update workspace
DELETE /api/workspaces/{slug}           Archive workspace (soft delete)
GET    /api/workspaces/{slug}/members   List members
POST   /api/workspaces/{slug}/members   Add member
DELETE /api/workspaces/{slug}/members/{user_id}  Remove member

POST   /api/users                       Create user (superadmin)
GET    /api/users/me                    Current user info
PATCH  /api/users/me                    Update profile
GET    /api/users                       List users (superadmin only)
```

### Existing endpoints — workspace header pattern

Every workspace-scoped endpoint accepts:
- Header `X-Workspace: <slug>` — selects active workspace for the request
- Backend validates user is a member of that workspace
- Filters all queries by `workspace_id`

Affected: `/api/config`, `/api/playbooks/*`, `/api/playbook-runs/*`, `/api/audit/*`, `/api/conversations/*`, `/api/chat/*`, `/api/recordings/*`, `/api/demo-prompts/*`, `/api/rag/*`, `/api/tools/*`

### Auth changes

`require_admin` dep → `require_member(workspace_slug)` dep:
- Decodes JWT → user
- Looks up WorkspaceMember(workspace=slug, user=user.id)
- Raises 403 if not a member
- Returns (user, workspace, role)

JWT payload extends with `user_id` (currently only `sub`/username).

## UI Changes

### New components

1. **Workspace switcher** (top nav)
   - Dropdown showing user's workspaces
   - "Create workspace" if superadmin
   - Selected workspace persisted to localStorage + sent as `X-Workspace` header
2. **Workspace admin page** `/admin/workspace`
   - Members table + add/remove
   - Workspace settings (name, description)
   - Archive workspace
3. **User management page** `/admin/users` (superadmin only)
   - Create/disable users, reset passwords
   - View per-user activity summary

### Modified pages

- **Login** — same flow, JWT now carries user_id → workspace switcher loads on first render
- **Admin Console** — every panel (Threat Lab tabs etc.) reads from active workspace
- **Run History** — already filtered by workspace via API; no UI change needed
- **Audit log** — per-workspace by default; superadmin can toggle "all workspaces"

## Deployment model

For 18-person team, **don't host on ตั้ม's MacBook**. Options:

| Option | Cost | Pros | Cons |
|---|---|---|---|
| **Cloudflare Tunnel + Mac** | $0 | Quick, no server | Mac-dependent (laptop offline = team blocked) |
| **Small VPS** (Hetzner ~$5/mo) | $60/yr | Always-on, full control | Need ops (TLS, backups, updates) |
| **AIS internal VM** | $0 internal | On-trust-network, IT-managed | Approval cycle, less flexibility |
| **Cloudflare Workers + R2** | $0-5/mo | Edge deploy, scales | Backend refactor needed (FastAPI → Workers) |

**Recommendation**: AIS internal VM if approval is fast (~2 weeks), else Hetzner VPS for trial (~2 months) then migrate. Cloudflare Tunnel + Mac = OK for very first internal demo only (week 1).

## Open Architecture Questions (ตั้มต้อง decide)

1. **Q1 — Built-in playbooks scope**: OWASP + POC built-ins (in code) — visible in every workspace, OR copied to each workspace on creation so they can be customized?
   - Recommend: **visible in every workspace, read-only**. Users duplicate-to-customize via existing flow.

2. **Q2 — Provider keys scope**: Each workspace has its own provider keys (e.g., MMT deal uses Account A's Lakera key; another deal uses Account B). OR: shared globally + per-workspace can override.
   - Recommend: **per-workspace** (clean separation, no key leak between deals).

3. **Q3 — Workspace creation permission**: Anyone can create workspaces, OR superadmin only?
   - Recommend: **anyone with active session** for now (18 ppl team, trust model). Add admin approval later if abuse.

4. **Q4 — User belongs to multiple workspaces**: Yes (assumed) — but UI shows one at a time via switcher. OR cross-workspace queries (e.g., "all my runs across all workspaces")?
   - Recommend: **one at a time via switcher** for MVP. Cross-workspace views = Phase 2.5.

5. **Q5 — Default workspace migration**: Existing single-tenant data — move to one default workspace `"default"` with all current users as members? OR archive old data + start fresh?
   - Recommend: **move to "default" workspace**, ตั้ม = sole member initially.

6. **Q6 — Initial users**: ตั้ม creates 18 user accounts manually OR self-registration with email allowlist?
   - Recommend: **superadmin creates users** for first deployment. Self-registration = Phase 2.5.

7. **Q7 — Role granularity**: owner/editor/viewer 3 roles, OR just owner/member 2 roles?
   - Recommend: **3 roles** — viewer is needed for "let me show this to manager who won't touch anything".

## Build Phases (cheapest-test first)

### Phase 2.1 — Minimum viable workspace (1-2 days)
- Add Workspace + WorkspaceMember + User tables (NO scope migration yet)
- Add `/api/workspaces` CRUD endpoints
- Add UI workspace switcher (visual only; doesn't filter anything yet)
- Tests for workspace CRUD

**Cheap test**: ตั้ม creates 2 workspaces, sees them in switcher, switches between them. Nothing else changes. Confirms data model works before scope migration.

### Phase 2.2 — Scope Playbook + PlaybookRun (1 day)
- Add `workspace_id` to both tables
- Migration: existing rows → default workspace
- All `/api/playbooks/*` and `/api/playbook-runs/*` filter by `X-Workspace` header
- UI uses active workspace

**Test**: create custom playbook in workspace A → not visible in workspace B.

### Phase 2.3 — Scope AppConfig (1 day)
- AppConfig → `workspace_config` table (1 row per workspace)
- Migration: existing config → default workspace
- All `/api/config` reads/writes by workspace
- UI provider config per workspace

**Test**: change Lakera key in workspace A → workspace B still has old key.

### Phase 2.4 — Scope audit/conversations/recordings (1-2 days)
- Add `workspace_id` to remaining tables
- Filter all related endpoints

**Test**: chat in workspace A → audit log of workspace B is empty.

### Phase 2.5 — User auth + workspace membership (1-2 days)
- Replace default admin/admin with real user accounts
- Login form supports user/pass
- Add WorkspaceMember enforcement on every workspace-scoped endpoint
- `/admin/workspace` page for member management

**Test**: user X not in workspace A → 403 on workspace A endpoints.

### Phase 2.6 — Deploy (varies by chosen option)
- Containerize (Dockerfile already exists)
- Set up TLS, secrets, backups
- DNS + access control
- Onboard first 2-3 teammates as canaries

**Total estimate**: 5-8 days of focused work spread across phases.

## Risks

| Risk | Mitigation |
|---|---|
| Schema migration breaks existing data | Run on Mac dev DB first; create_all() is additive, scope migration is reversible (nullable workspace_id) |
| Active provider config "leaks" between workspaces if forgotten | Phase 2.3 must be done before Phase 2.6 deployment; tests with stub-providers must verify |
| 18-person team rejects tool ("we already have email/Slack") | Phase 1 validation incomplete — DON'T deploy widely until aigw-mmt T1 produces evidence of value |
| Cloud deploy cost surprises | Start with Cloudflare Tunnel + Mac for week-1 trial; only invest in VPS after usage proven |
| Free-tier provider rate limits hit faster with 18 concurrent users | Phase 2.5 should consider per-workspace API key requirement (no shared free-tier keys) |

## Out of scope (Phase 3 / later)

- SSO integration (Entra ID)
- Customer-facing workspace share (read-only public links)
- Billing / quota per workspace
- Audit log export for compliance
- Cross-workspace analytics dashboard
- Workspace templates (clone a deal's setup to new deal)

## What I recommend ตั้ม decide first

1. **Phase 2.1 only**, then review — confirms architecture before scope migration
2. Q1-Q7 answers above (or override with own preferences)
3. Deployment target (AIS internal VM vs Hetzner VPS)

If Phase 2.1 ships and works → continue 2.2-2.5. If it doesn't fit workflow → revise design before scope migration (cheaper rollback).
