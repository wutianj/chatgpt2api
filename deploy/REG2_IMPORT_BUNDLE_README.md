# reg2 Import Bundle

This bundle applies the reg2 account import workflow to a running
`chatgpt2api` server.

## Contents

- `api/accounts.py`: backend route and normalization logic.
- `web_dist/`: prebuilt Vue admin portal assets.
- `docs/runbooks/reg2-account-import.md`: operator instructions.
- `apply-reg2-import-bundle.sh`: server-side apply and rollback generator.
- `manifest.json`: machine-readable file list and hashes.
- `CHANGELOG.md`: release note entry for the reg2 import workflow.
- `deploy/build-reg2-import-bundle.ps1`: local build, package, and verify helper.
- `deploy/push-reg2-import-bundle.ps1`: Windows upload and apply helper.
- `deploy/verify-reg2-import-bundle.ps1`: local zip integrity checker.
- `scripts/smoke_reg2_import.py`: import API smoke checker with fake sample data.
- `docs/runbooks/examples/reg2-image-site-sample.jsonl`: fake reg2 JSONL sample.

## Server Apply

Build a fresh local bundle from the repository:

```powershell
cd D:\yewu\_repo_reviews\yukkcat-chatgpt2api
.\deploy\build-reg2-import-bundle.ps1
```

Upload and extract the zip on the server, then run:

```bash
cd /tmp/reg2-import-bundle
APP_DIR=/opt/chatgpt2api CONTAINER_NAME=chatgpt2api bash apply-reg2-import-bundle.sh
```

From Windows, if SSH access is available, the repository also includes a helper:

```powershell
cd D:\yewu\_repo_reviews\yukkcat-chatgpt2api
.\deploy\push-reg2-import-bundle.ps1 -HostName 199.30.91.19 -User root
```

The push helper verifies the selected bundle locally before any upload or
dry-run output.

With a key file:

```powershell
.\deploy\push-reg2-import-bundle.ps1 -HostName 199.30.91.19 -User root -IdentityFile C:\path\to\id_rsa
```

Before uploading, verify the newest local zip:

```powershell
.\deploy\verify-reg2-import-bundle.ps1
```

Dry-run the upload command without connecting:

```powershell
.\deploy\push-reg2-import-bundle.ps1 -HostName 199.30.91.19 -User root -DryRun
```

Expected output:

```text
manifest ok
reg2 import route ok
applied reg2 import bundle
backup: /opt/chatgpt2api/backups/reg2-import-<timestamp>
rollback: /opt/chatgpt2api/backups/reg2-import-<timestamp>/rollback-reg2-import.sh
```

## Verify

```bash
docker exec chatgpt2api python - <<'PY'
from api.app import create_app
routes = {getattr(route, "path", "") for route in create_app().routes}
assert "/api/accounts/import/reg2" in routes
print("reg2 import route ok")
PY

curl -fsS http://127.0.0.1:3000/version

grep -R "导入 reg2" /opt/chatgpt2api/web_dist >/dev/null
grep -R "/api/accounts/import/reg2" /opt/chatgpt2api/web_dist >/dev/null
```

Then open the admin account page and confirm that `导入/添加` contains
`导入 reg2 注册机账号`.

Optional API smoke with fake sample data:

```bash
python scripts/smoke_reg2_import.py --base-url http://127.0.0.1:3000 --admin-key "$CHATGPT2API_AUTH_KEY" --no-sync
```

## Rollback

Run the rollback script printed by the apply command:

```bash
APP_DIR=/opt/chatgpt2api CONTAINER_NAME=chatgpt2api bash /opt/chatgpt2api/backups/reg2-import-<timestamp>/rollback-reg2-import.sh
```
