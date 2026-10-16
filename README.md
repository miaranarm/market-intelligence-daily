# Market Intelligence Daily

Public repository for a multi-asset market-intelligence system with three planned daily email reports in Madagascar time (UTC+3). The public report page is intended to be published at https://miaranarm.github.io/market-intelligence-daily/.

## Current status

- [x] Public repository verified.
- [x] Report HTML generation and single-link email delivery workflow added.
- [x] GitHub Pages publication verified from branch `main`, folder `/docs`.
- [x] Public report page opened and validated by the repository owner.
- [x] Manual GitHub Actions workflow for testing Gmail SMTP delivery.
- [x] Gmail SMTP credentials are configured as GitHub Actions secrets (the test send succeeded).
- [x] Test email received successfully by the recipient.
- [x] Market-data/news collection and report generation committed.
- [x] Official SEC EDGAR XBRL Company Facts integration added for a selected set of US companies, reporting latest usable quarterly revenue and diluted EPS plus year-over-year comparisons when available.
- [x] Funnel architecture added: world regime → regions → cross-asset interactions → asset classes → sectors/company events → instruments → action and audit.
- [x] Expanded company-results coverage across US, Europe, Asia and major sectors, plus a broader equity watchlist and representative mutual funds.
- [x] Explicit directional scenario probabilities added using a transparent cross-asset heuristic; probabilities are explicitly marked experimental and not statistically calibrated.
- [x] Morning/update/evening reports use the same funnel hierarchy; the evening report includes the self-audit ledger.
- [x] Manual live report run completed successfully; report generation, history commit, Pages deployment and email-link delivery have succeeded in repeated runs.
- [x] Scheduled workflow configured for 05:30, 13:30 and 21:00 Madagascar time (UTC+3); continue monitoring scheduled runs for reliability.

**Current validation:** The public Pages URL has been opened successfully. Multiple manual report workflows have completed end to end, including tests, report generation, history commit and email-link delivery. The scheduled delivery cycle should continue to be monitored. The prototype collects market prices and headlines, adds a limited SEC XBRL fundamentals sample for selected US issuers, keeps technical/quantitative indicators out of the reader-facing report, emails a single link after the report page is committed, and saves snapshots for later audit. Because this repository is public, the tracked snapshots under `data/` are also public. Technical indicators (such as RSI and moving averages) must not appear in the reader-facing report. The system does not yet provide a complete company-by-company fundamental model or statistically calibrated directional probabilities. Its current probability estimates are an explicitly labeled heuristic that must be audited against future outcomes.

## Workflow monitoring and recovery

The `Workflow watchdog` reacts to completion events from report generation, code validation, and GitHub Pages deployment. If one fails, times out, or is cancelled, it posts a diagnostic link to [the control issue](https://github.com/miaranarm/market-intelligence-daily/issues/1). This is event-driven monitoring rather than a 10-second polling loop. It intentionally does not retry report generation automatically, which could otherwise create repeated commits or duplicate emails. Inspect the linked run, correct the cause, and rerun the appropriate workflow from Actions.

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
- Macro/news collection from official feeds (Federal Reserve, US Bureau of Labor Statistics, European Central Bank, US Energy Information Administration, Bank of England and Bank of Japan) plus targeted Google News RSS searches for IMF and World Bank domains and other market topics. IMF direct RSS returned HTTP 403 and the tested World Bank endpoint returned malformed XML in a live run, so they are not misrepresented as working primary feeds. Feed reachability is checked by live runs; failures are reported. Headlines are interleaved by feed so a single source is less likely to dominate the report. Headline text is normalized to suppress exact repeats across different search feeds; this reduces duplicated stories but does not independently verify the underlying reporting.
- Forecast ledger: a transparent, simple five-session momentum baseline is recorded once per asset and market date, with one- and five-session evaluation horizons.
- Self-audit section reports matured sample sizes and directional accuracy, shows recent errors, and warns when the sample is too small to support conclusions.
- Saved morning scenario probabilities are evaluated against the next distinct S&P 500 observation using directional accuracy and a multiclass Brier score; the system waits for a later market date so an incomplete same-day bar is not treated as a final result.
- The HTML report estimates reading time from its generated word count; the target is approximately 30 minutes when market news and instrument coverage justify that length.
- Automated GitHub Actions checks for Python syntax and unit tests on pushes to the main branch and pull requests.

Still required before this can be called a professional-grade macro briefing:
- Expand the initial SEC revenue/EPS sample to structured company fundamentals: margins, cash flow, balance sheets, valuation, verified analyst consensus, official earnings-calendar coverage, original filings, and company-by-company source validation. The SEC figures are reported actuals, not consensus surprises. Headline search is not a substitute for reading filings or transcripts.
- Validate each official RSS feed's availability and the provenance of article links during live runs.
- Test the complete market-data collection, report publication, GitHub Pages URL and SMTP email delivery end to end.
- Expand coverage and validate data freshness, especially for intraday quotes, bonds, funds and non-US markets.
- Validate the directional-probability heuristic over a sufficiently large out-of-sample sample, including calibration, Brier/log scores, relevant benchmarks and costs before changing analytical rules automatically.
- Expand the report with deeper verified primary-source analysis so the reading time approaches the requested 30 minutes when the news flow warrants it; do not pad quiet days with repetitive prose.

The self-audit baseline is experimental, not a validated trading strategy. Directional accuracy alone does not demonstrate profitability. No probabilities will be presented as calibrated until calibration has been measured, and no trading execution is planned.

## Public visibility and security

This repository is public. Source code, commit history, the `docs/` report page, and tracked files in `data/` are visible to anyone. In particular, `data/forecasts.json` and `data/market_history.csv` contain quantitative indicators intended for internal analysis; they are nevertheless public because they are tracked in this public repository. Do not commit credentials, API keys, app passwords, or personal data. GitHub Actions secrets are stored separately in repository settings and are not automatically published. The report workflow needs `contents: write` to commit report snapshots and the generated page, and sends email through Gmail SMTP over STARTTLS without printing credentials.