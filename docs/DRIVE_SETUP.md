# Google Drive mailbox setup

## 1. Create a service account

1. In Google Cloud Console, create or select a project.
2. Enable the Google Drive API.
3. Create a service account and download its JSON key to the Ubuntu machine.
4. Keep the key outside the repository, for example /etc/render-worker/google-drive.json.
5. Copy the service account email address.

The worker uses the Google Drive API with the Drive scope because it needs to list, download, move, and upload files.

## 2. Create and share the mailbox

1. In Google Drive, create a folder named Render Worker Mailbox.
2. Share that folder with the service account email as Editor.
3. Copy the folder ID from the folder URL.
4. Put the key path and folder ID in the local .env file:

~~~env
GOOGLE_SERVICE_ACCOUNT_FILE=/etc/render-worker/google-drive.json
DRIVE_MAILBOX_ROOT_ID=your_folder_id
~~~

The worker creates inbox, processing, completed, failed, and outputs folders under this root on first setup.

## 3. Submit a job

Create one folder under inbox. Add job.json and every file referenced by its input paths. A typical job package is shown in examples/jobs/example.

The Cloud editor can place these files using the connected Google Drive workflow. The local worker does not need access to ChatGPT credentials; it only needs access to the shared mailbox.

## 4. Check results

For each successful job, outputs/<job_id>/ contains output.mp4, qa.json, and status.json.

The original input folder moves from processing to completed. Failed jobs move to failed, and a status-failed.json is written to the output folder when Drive remains reachable.

## Security notes

- Treat the service-account JSON as a password. Never upload it to Drive or GitHub.
- Share only the mailbox root folder, not your whole Drive.
- Do not expose a local HTTP port for this workflow.
- Remove the service account's access when the worker is no longer needed.
