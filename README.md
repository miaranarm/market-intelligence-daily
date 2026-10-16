# Market Intelligence Daily

Public repository for a multi-asset market-intelligence system with three planned daily email reports in Madagascar time (UTC+3). The public report page is intended to be published at https://miaranarm.github.io/market-intelligence-daily/.

## Current status

- [x] Public repository verified.
- [x] Report HTML generation and single-link email delivery workflow added.
- [ ] GitHub Pages publication confirmed from branch `main`, folder `/docs`.
- [ ] First public report page validated.
- [x] Manual GitHub Actions workflow for testing Gmail SMTP delivery.
- [ ] Gmail credentials verified as GitHub Actions secrets.
- [ ] Test email received successfully.
- [x] First prototype of market-data/news collection and report generation committed.
- [ ] Prototype run validated against live sources and email delivery.
- [x] Scheduled workflow configured for 05:30, 13:30 and 21:00 Madagascar time (UTC+3); end-to-end delivery still unverified.

**Important:** The scheduled workflow is configured, but the first scheduled report, public Pages URL, and email delivery have not yet been verified end to end. The prototype collects market prices and headlines, keeps technical/quantitative indicators out of the reader-facing report, emails a single link after the report page is committed, and saves snapshots for later audit. Because this repository is public, the tracked snapshots under `data/` are also public. Technical indicators (such as RSI and moving averages) must not appear in the reader-facing report. The system does not yet provide a complete fundamental analysis or calibrated directional probabilities.

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

The initial watchlist spans major equity indices, volatility, US Treasury yields, FX, commodities, crypto, ETFs and selected large-cap US stocks. Technical and quantitative measures (including RSI, moving averages and realized volatility) are for internal analysis and scenario comparison only; they are not displayed in the reader-facing report. The report should emphasize what happened, why it may matter, cross-asset effects, relevant news, scenarios, and assets to monitor. Price changes may be shown as market observations, not as standalone trading signals. Data are subject to provider availability, delays and quality limits; missing data and collection errors are listed in each report. The report-generation workflow supports both scheduled and manual runs; scheduled emails depend on valid repository secrets and a working public report URL.

## Planned report schedule

Target delivery times in Madagascar time (Indian/Antananarivo, UTC+3):

- **05:30** — initial decision-oriented report: macro, fundamentals, cross-asset effects, scenarios, estimated probabilities when validated, and watchlist. Technical analysis is used internally and not displayed.
- **13:30** — changes since the morning report and any evidence-based revisions, without repeating unchanged material.
- **21:00** — audit of earlier forecasts, outcomes, probability calibration and lessons.

GitHub Actions schedules can start late. We will schedule the jobs early enough to leave time for analysis and email delivery, record actual timestamps, and report delays transparently. Exact delivery times cannot be guaranteed.

## Research and quality controls

Implemented in the current prototype:
- Responsive, sectioned HTML report with clickable source URLs and a market-data source link on each price row.
- Macro/news collection from official feeds (Federal Reserve, US Bureau of Labor Statistics, European Central Bank and US Energy Information Administration) plus several Google News RSS searches. Headlines are interleaved by feed so a single source is less likely to dominate the report.
- Forecast ledger: a transparent, simple five-session momentum baseline is recorded once per asset and market date, with one- and five-session evaluation horizons.
- Self-audit section reports matured sample sizes and directional accuracy, shows recent errors, and warns when the sample is too small to support conclusions.
- Automated GitHub Actions checks for Python syntax and unit tests on pushes to the main branch and pull requests.

Still required before this can be called a professional-grade macro briefing:
- Generate explanatory macroeconomic analysis that connects each verified event to the nine asset categories; the current news module primarily collects headlines and does not yet provide a complete, source-by-source macro narrative.
- Validate each official RSS feed's availability and the provenance of article links during live runs.
- Test the complete market-data collection, report publication, GitHub Pages URL and SMTP email delivery end to end.
- Expand coverage and validate data freshness, especially for intraday quotes, bonds, funds and non-US markets.
- Evaluate forecast performance over a sufficiently large out-of-sample sample, with relevant benchmarks and costs before changing analytical rules automatically.

The self-audit baseline is experimental, not a validated trading strategy. Directional accuracy alone does not demonstrate profitability. No probabilities will be presented as calibrated until calibration has been measured, and no trading execution is planned.

## Public visibility and security

This repository is public. Source code, commit history, the `docs/` report page, and tracked files in `data/` are visible to anyone. In particular, `data/forecasts.json` and `data/market_history.csv` contain quantitative indicators intended for internal analysis; they are nevertheless public because they are tracked in this public repository. Do not commit credentials, API keys, app passwords, or personal data. GitHub Actions secrets are stored separately in repository settings and are not automatically published. The report workflow needs `contents: write` to commit report snapshots and the generated page, and sends email through Gmail SMTP over STARTTLS without printing credentials.