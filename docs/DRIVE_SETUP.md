# Google Drive mailbox setup

## Recommended: OAuth for a personal Google Drive

A personal My Drive is owned by a human Google account. Use OAuth so uploaded output files remain owned by that account and count against its Drive storage quota.

1. In Google Cloud Console, create or select a project and enable the Google Drive API.
2. If this worker will access only your own Google account, use Google's Personal mode onboarding flow for the OAuth app. Personal mode is bound to the account that created it and avoids the 7-day test-user token expiry.
3. Create an OAuth Client ID with application type Desktop app and download the client JSON to the Ubuntu machine, outside the repository.
4. If Personal mode is not available and you configure an External app in Testing mode, add your account as a test user. Be aware that Google expires authorizations and offline refresh tokens after seven days in Testing mode. For a long-running worker, use Personal mode or publish the app to Production and complete any verification Google requires for the Drive scope.
5. In .env, set:

~~~env
GOOGLE_OAUTH_CLIENT_FILE=/etc/render-worker/oauth-desktop-client.json
GOOGLE_TOKEN_FILE=var/google-token.json
DRIVE_MAILBOX_ROOT_ID=your_mailbox_folder_id
~~~

6. Create a folder named Render Worker Mailbox in the same Google account and copy its folder ID from the URL.
7. Run the one-time authorization:

~~~bash
source .venv/bin/activate
render-worker auth-drive
~~~

The command prints an authorization URL and waits for the OAuth callback on 127.0.0.1:8765. On a remote/headless Ubuntu host, open an SSH tunnel from your desktop:

~~~bash
ssh -L 8765:127.0.0.1:8765 USER@HOST
~~~

Keep that SSH session open, open the authorization URL in your desktop browser, and complete consent. The worker stores a refreshable token at var/google-token.json and restricts its permissions to the local owner.

Then create the mailbox folders:

~~~bash
render-worker setup-drive
~~~

## Optional: Service Account for a Shared Drive

Google documents that service accounts have no Drive storage quota and cannot own files. Use them only when the mailbox is inside a Google Shared Drive that the service account can access. Personal Gmail accounts cannot create Shared Drives.

1. Enable the Google Drive API in a Google Cloud project.
2. Create a service account and download its JSON key outside the repository.
3. Add the service account as a member of the target Shared Drive with a role that can add and organize files.
4. Set GOOGLE_SERVICE_ACCOUNT_FILE and DRIVE_MAILBOX_ROOT_ID in .env. Leave GOOGLE_OAUTH_CLIENT_FILE unset.
5. Run render-worker setup-drive.

The worker checks that a service-account mailbox root belongs to a Shared Drive and rejects a personal My Drive folder.

## Mailbox structure and job submission

The worker creates inbox, processing, completed, failed, and outputs folders under the configured root.

Create one folder under inbox. Add job.json and every file referenced by its input paths. A typical job package is shown in examples/jobs/example. The Cloud editor can create or upload these files using the connected Google Drive workflow.

For each successful job, outputs/<job_id>/ contains output.mp4, qa.json, and status.json. The original input folder moves from processing to completed. Failed jobs move to failed, and a status-failed.json is written to the output folder when Drive remains reachable.

## Security

- Never commit OAuth client JSON, token JSON, or service-account JSON.
- Share only the mailbox folder or Shared Drive required by the worker.
- Do not expose a local HTTP API. The OAuth callback is a one-time loopback authorization flow.
- Remove the app's Drive access or revoke the OAuth grant when the worker is no longer needed.
