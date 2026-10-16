# Market Intelligence Daily

Private repository for a multi-asset market-intelligence system with three planned daily email reports in Madagascar time (UTC+3).

## Current status

- [x] Private repository verified.
- [x] Manual GitHub Actions workflow for testing Gmail SMTP delivery.
- [ ] Gmail credentials added as GitHub Actions secrets.
- [ ] Test email received successfully.
- [ ] Market-data/news collection and report-generation engine implemented and validated.
- [ ] Scheduled reports enabled only after the report engine is ready.

**Important:** The scheduled market reports are not enabled yet. The email test workflow sends only a clearly labelled test message; it does not invent market analysis.

## Configure Gmail securely

Use the Gmail account that will send the emails. Do not use your normal Gmail password.

1. Sign in to the sender Gmail account and enable 2-Step Verification if it is not already enabled.
2. Create a Google App Password for this project in your Google Account security settings. Google may not offer App Passwords for every account or security configuration.
3. In this GitHub repository, open **Settings → Secrets and variables → Actions → New repository secret**.
4. Add these three secrets:

| Secret name | Value |
| --- | --- |
| `SMTP_USERNAME` | Gmail address used to send the messages |
| `SMTP_APP_PASSWORD` | Google App Password (spaces may be omitted) |
| `REPORT_RECIPIENT` | `miaranarandriamanalina@gmail.com` |

Never commit credentials to a file, paste them into an issue, or put them in workflow YAML. Do not share the App Password in ChatGPT.

## Test delivery

After adding the three secrets:

1. Open the **Actions** tab in this repository.
2. Select **Test email delivery**.
3. Click **Run workflow**, then confirm **Run workflow**.
4. Open the run and check whether it succeeded.
5. Check the recipient inbox and Spam folder for **[Market Intelligence] Test de réception**.

If it fails, the workflow log should identify missing secrets or an SMTP authentication/connectivity error. Do not paste credentials into logs or chat.

## Planned report schedule

Target delivery times in Madagascar time (Indian/Antananarivo, UTC+3):

- **05:30** — full initial report: macro, fundamentals, technicals, scenarios, estimated probabilities and watchlist.
- **13:30** — changes since the morning report and any evidence-based revisions.
- **21:00** — audit of earlier forecasts, outcomes, probability calibration and lessons.

GitHub Actions schedules can start late. We will schedule the jobs early enough to leave time for analysis and email delivery, record actual timestamps, and report delays transparently. Exact delivery times cannot be guaranteed.

## Research and quality controls planned

The report engine must distinguish observations from interpretation, cite data/news sources and timestamps, state when data is unavailable, retain the exact forecast snapshots for later audit, and avoid presenting estimated probabilities as certainties. Technical/quantitative methods will be evaluated out of sample with costs and slippage where relevant. No trading execution is planned.

## Security

The workflow uses read-only repository permissions, does not print secrets, and sends mail only through Gmail SMTP over STARTTLS. Keep the repository private and review GitHub Actions logs before sharing them.