# Market Intelligence Daily

Public repository for a multi-asset market-intelligence system with three planned daily email reports in Madagascar time (UTC+3). The public report page is intended to be published at https://miaranarm.github.io/market-intelligence-daily/.

## Current status

- [x] Public repository verified.
- [x] Report HTML generation and single-link email delivery workflow added.
- [ ] GitHub Pages enabled from branch `main`, folder `/docs`.
- [ ] First public report page validated.
- [x] Manual GitHub Actions workflow for testing Gmail SMTP delivery.
- [ ] Gmail credentials added as GitHub Actions secrets.
- [ ] Test email received successfully.
- [x] First prototype of market-data/news collection and report generation committed.
- [ ] Prototype run validated against live sources and email delivery.
- [ ] Scheduled reports enabled only after the prototype is validated.

**Important:** The scheduled market reports are not enabled yet. The prototype collects market prices and headlines, retains technical/quantitative indicators internally for analysis, emails a decision-oriented report when manually launched, and saves snapshots for later audit. Technical indicators (such as RSI and moving averages) must not appear in the reader-facing report. The system does not yet provide a complete fundamental analysis or calibrated directional probabilities.

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

## Current prototype scope

The initial watchlist spans major equity indices, volatility, US Treasury yields, FX, commodities, crypto, ETFs and selected large-cap US stocks. Technical and quantitative measures (including RSI, moving averages and realized volatility) are for internal analysis and scenario comparison only; they are not displayed in the reader-facing report. The report should emphasize what happened, why it may matter, cross-asset effects, relevant news, scenarios, and assets to monitor. Price changes may be shown as market observations, not as standalone trading signals. Data are subject to provider availability, delays and quality limits; missing data and collection errors are listed in each report. The report-generation workflow is currently manual so it can be tested before scheduled emails are enabled.

## Planned report schedule

Target delivery times in Madagascar time (Indian/Antananarivo, UTC+3):

- **05:30** — initial decision-oriented report: macro, fundamentals, cross-asset effects, scenarios, estimated probabilities when validated, and watchlist. Technical analysis is used internally and not displayed.
- **13:30** — changes since the morning report and any evidence-based revisions, without repeating unchanged material.
- **21:00** — audit of earlier forecasts, outcomes, probability calibration and lessons.

GitHub Actions schedules can start late. We will schedule the jobs early enough to leave time for analysis and email delivery, record actual timestamps, and report delays transparently. Exact delivery times cannot be guaranteed.

## Research and quality controls planned

The report engine must distinguish observations from interpretation, cite data/news sources and timestamps, state when data is unavailable, retain the exact forecast snapshots for later audit, and avoid presenting estimated probabilities as certainties. Technical/quantitative methods will be evaluated out of sample with costs and slippage where relevant. No trading execution is planned.

## Public visibility and security

This repository is public. Source code, commit history, the `docs/` report page, and tracked files in `data/` are visible to anyone. In particular, `data/forecasts.json` and `data/market_history.csv` contain quantitative indicators intended for internal analysis; they are nevertheless public because they are tracked in this public repository. Do not commit credentials, API keys, app passwords, or personal data. GitHub Actions secrets are stored separately in repository settings and are not automatically published. The report workflow needs `contents: write` to commit report snapshots and the generated page, and sends email through Gmail SMTP over STARTTLS without printing credentials.