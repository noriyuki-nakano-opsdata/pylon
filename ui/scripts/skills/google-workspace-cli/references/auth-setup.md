# Auth Setup

Use this reference when `./ui/scripts/gws auth status` reports no credentials or when the user needs a non-default auth flow.

## Fastest Local Flow

If `gcloud` is installed:

```bash
./ui/scripts/gws auth setup
./ui/scripts/gws auth login
```

## Manual OAuth Flow

1. Create a Google Cloud project
2. Configure an OAuth consent screen
3. Create a Desktop OAuth client
4. Save the downloaded client JSON to:

```text
~/.config/gws/client_secret.json
```

5. Run:

```bash
./ui/scripts/gws auth login
```

## Headless Or CI Flow

Provide a credentials file:

```bash
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/path/to/credentials.json
./ui/scripts/gws auth status
```

Or provide a token:

```bash
export GOOGLE_WORKSPACE_CLI_TOKEN="ya29..."
./ui/scripts/gws auth status
```

## Delegated Service Account Flow

Use this when a Google Workspace administrator wants agents to act on behalf of a domain user.

1. Create a service account in Google Cloud
2. Enable domain-wide delegation on that service account
3. Download the service account key JSON
4. Save it to:

```text
~/.config/gws/service-account.json
```

5. In Google Workspace Admin Console, authorize the service account client ID for the scopes you need
6. Export these variables before calling `./ui/scripts/gws`

```bash
export GWS_DELEGATED_SERVICE_ACCOUNT_FILE="$HOME/.config/gws/service-account.json"
export GWS_DELEGATED_SUBJECT="user@your-domain.example"
export GWS_DELEGATED_SCOPES="https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/calendar.readonly"
```

7. Run the command through the repo wrapper:

```bash
./ui/scripts/gws drive files list --params '{"pageSize": 5}'
```

The wrapper mints a short-lived delegated access token and injects it as `GOOGLE_WORKSPACE_CLI_TOKEN`.

## Keyless Delegated Flow

Use this when service account key creation is blocked by organization policy.

1. Keep domain-wide delegation enabled on the service account
2. Authorize the service account client ID in Google Workspace Admin Console
3. Grant the operator identity `roles/iam.serviceAccountTokenCreator` on the service account
4. Obtain a Google Cloud OAuth access token for the operator identity
5. Export:

```bash
export GWS_DELEGATED_SERVICE_ACCOUNT_EMAIL="service-account@project.iam.gserviceaccount.com"
export GWS_OPERATOR_ACCESS_TOKEN="ya29..."
export GWS_DELEGATED_SUBJECT="user@your-domain.example"
export GWS_DELEGATED_SCOPES="https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/calendar.readonly"
```

6. Run `./ui/scripts/gws ...`

The wrapper calls IAM Credentials `signJwt`, exchanges the signed JWT for a Workspace access token, and then runs `gws`.

## Decision Rule

- Use `auth login` for local interactive users
- Use `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` for agents, CI, or servers
- Use delegated service account auth when a Workspace admin has approved domain-wide delegation
- Use `GOOGLE_WORKSPACE_CLI_TOKEN` only when another trusted system already issues tokens
