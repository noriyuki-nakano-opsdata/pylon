---
name: google-workspace-cli
description: Google Workspace CLI skill for Gmail, Drive, Calendar, Docs, Sheets, and Chat operations through the gws command-line tool. Use when a shell-enabled agent needs to inspect or modify Google Workspace resources with structured JSON output.
---

# Google Workspace CLI

Use this skill when the task requires interacting with Google Workspace from a shell-enabled Pylon agent. It is optimized for `gws`, the Google Workspace CLI from `googleworkspace/cli`.

## When to Use

- Listing or searching Drive files
- Reading or sending Gmail messages
- Creating or updating Calendar events
- Creating Sheets, Docs, or Chat messages
- Inspecting Workspace API schemas before making requests
- Automating Workspace workflows from shell-enabled agents

## Reference Routing

- Read [references/auth-setup.md](references/auth-setup.md) when authentication is missing or when choosing between interactive login and credentials-file auth.
- For Google Workspace admin-managed impersonation, use the delegated service account flow in the auth reference and prefer `GWS_DELEGATED_*` environment variables over ad hoc tokens.

## Workflow

1. Use the repo wrapper.
   Run `./ui/scripts/gws`, not raw `gws`, so the command works consistently with local installation paths.
2. Check auth first.
   Run `./ui/scripts/gws auth status` before any real request.
3. Stop early if auth is missing.
   If `credential_source` is `none`, do not guess. Ask the user to complete auth or provide a credentials file or token.
4. Use delegated auth when impersonation is required.
   If the task requires acting on behalf of a Workspace user, use either:
   `GWS_DELEGATED_SERVICE_ACCOUNT_FILE` + `GWS_DELEGATED_SUBJECT` + `GWS_DELEGATED_SCOPES`,
   or `GWS_DELEGATED_SERVICE_ACCOUNT_EMAIL` + `GWS_OPERATOR_ACCESS_TOKEN` + `GWS_DELEGATED_SUBJECT` + `GWS_DELEGATED_SCOPES`.
5. Prefer structured inputs.
   Use `--params` for query parameters, `--json` for request bodies, and keep payloads valid JSON.
6. Prefer safe previews for writes.
   For mutating actions, use `--dry-run` first when supported, then run the real command only after the intended request is clear.
7. Return operator-ready output.
   Summarize the command used, the Workspace object affected, and the result or next blocker.

## Common Commands

```bash
./ui/scripts/gws --version
./ui/scripts/gws auth status
GWS_DELEGATED_SERVICE_ACCOUNT_FILE="$HOME/.config/gws/service-account.json" \
GWS_DELEGATED_SUBJECT="user@your-domain.example" \
GWS_DELEGATED_SCOPES="https://www.googleapis.com/auth/drive.readonly" \
./ui/scripts/gws drive files list --params '{"pageSize": 10}'
GWS_DELEGATED_SERVICE_ACCOUNT_EMAIL="service-account@project.iam.gserviceaccount.com" \
GWS_OPERATOR_ACCESS_TOKEN="ya29..." \
GWS_DELEGATED_SUBJECT="user@your-domain.example" \
GWS_DELEGATED_SCOPES="https://www.googleapis.com/auth/drive.readonly" \
./ui/scripts/gws drive files list --params '{"pageSize": 10}'
./ui/scripts/gws drive files list --params '{"pageSize": 10}'
./ui/scripts/gws gmail users messages list --params '{"userId":"me","maxResults":10}'
./ui/scripts/gws calendar events list --params '{"calendarId":"primary","maxResults":10}'
./ui/scripts/gws sheets spreadsheets create --json '{"properties":{"title":"Q1 Budget"}}'
./ui/scripts/gws schema drive.files.list
```

## Output Shape

- Auth state: available credential source or blocker
- Command: exact `gws` invocation
- Result: key IDs, titles, links, or counts
- Risk note: whether the command is read-only or mutating
- Next step: follow-up command or user action needed

## Heuristics

- `auth status` is mandatory before assuming the environment is ready.
- For delegated runs, keep scopes as narrow as possible and set the subject explicitly to the intended Workspace user.
- Prefer narrow scopes and narrow queries over broad listing calls.
- Use `schema` when the resource or method shape is unclear.
- For write operations, show the body and target clearly before execution.

## Anti-Patterns

- Running write commands before checking auth
- Building malformed JSON inline without validation
- Using raw `gws` when the repo wrapper is available
- Treating Gmail or Drive mutations as low-risk side effects
