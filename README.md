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
- [x] Scheduled workflow: see « Report schedule » below (weekdays only, plus one weekly report on Sunday).
- [x] Report v2: one editorial reading report (about 30 minutes with the optional writing layer), nine asset categories, weekly agenda, weekend mode, audit against naive benchmarks. See « Report v2 ».

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
| `REPORT_RECIPIENT` | adresse du destinataire (à garder uniquement dans ce secret, jamais dans le dépôt public) |

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

## Report schedule

Heures de Madagascar (Indian/Antananarivo, UTC+3). Les marchés sont fermés le week-end : plus de rapports de cours périmés le samedi et le dimanche.

| Rapport | Quand | Contenu |
|---|---|---|
| `morning` | 05:30, lundi à vendredi | Lecture complète : essentiel, régime, agenda, faits marquants, 9 univers, scénarios, audit |
| `update` | 13:30, lundi à vendredi | Même structure, avec une partie « Depuis le rapport précédent » |
| `audit` | 21:00, lundi à vendredi | Bilan des prévisions du matin sur les observations disponibles; la séance américaine peut être encore ouverte |
| `weekly` | dimanche 18:00 | Semaine écoulée, 21 jours d'agenda, scénarios conditionnels de réouverture |

GitHub Actions peut démarrer en retard ; aucun horaire n'est garanti.

## Report v2

**Structure.** Chaque rapport ouvre sur un titre-diagnostic et « L'essentiel », puis : régime de marché (avec tableau macro), agenda, faits marquants, **les neuf univers** (indices, futures sur indices, actions, matières premières, devises, crypto-monnaies, obligations, ETF, fonds), scénarios et liste de surveillance, fiabilité de nos analyses, données et sources. Le détail brut des anciennes versions est conservé dans une annexe repliable, hors temps de lecture. Le plan de lecture affiche les minutes par partie.

**Temps de lecture.** Il est calculé (220 mots par minute, annexe exclue) et affiché. Sans rédaction assistée, un rapport tient environ 15 à 20 minutes ; avec elle, environ 25 à 30. Le rapport n'est jamais rallongé artificiellement : un jour calme donne un rapport plus court.

**Rédaction assistée (facultative).** Ajouter le secret `ANTHROPIC_API_KEY` (et, si souhaité, la variable `LLM_MODEL`). Un modèle de langage commente alors les données déjà collectées. Garde-fous appliqués par le code : seules les données du rapport lui sont transmises, les probabilités sont en lecture seule, tout paragraphe contenant un nombre absent des données ou ressemblant à un conseil d'achat/vente est écarté, et en cas d'échec le rapport est produit sans cette couche.

**Calendrier.** `data/calendar_manual.json` est tenu à la main (voir `CONSIGNE_CHATGPT.md`). Chaque événement a un statut « confirmé » (date issue du site officiel de l'institution) ou « à confirmer ». Avec le secret `FRED_API_KEY` (gratuit), les dates officielles des publications américaines (emploi, inflation, PIB…) sont ajoutées automatiquement.

**Courriel.** Un message court (titre, essentiel, bouton vers le rapport complet) avec la version texte intégrale en alternative.

**Audit.** Une seule prévision par date de base compte (les relances du jour sont ignorées) ; la zone « central » dépend de la volatilité ; chaque résultat est comparé à « toujours hausse », à la persistance et à la climatologie ; la version de la règle (`method_version`) est enregistrée. Aucune conclusion avant 30 séances distinctes.

**Aperçu hors ligne.** `python tools/preview_from_snapshot.py morning apercu.html` produit un rapport à partir du dernier instantané enregistré, sans accès réseau (les mini-graphiques de 30 jours n'apparaissent que lors des exécutions réelles).

## Research and quality controls

Implemented in the current prototype:
- Responsive, sectioned HTML report with clickable source URLs and a market-data source link on each price row.
- Macro/news collection combines official feeds from the Federal Reserve, BEA (RSS), U.S. Census Bureau economic indicators (RSS), ECB, EIA, Bank of England and Bank of Japan. The three BLS RSS endpoints previously failed in the hosted runner, so the workflow no longer depends on them: targeted Google News searches restricted to BLS archive pages are used for employment, CPI and PPI discovery, and a targeted Department of Labor search supplements weekly unemployment-claims coverage. Search results are leads, not verified primary data; readers should open the original institutional release before relying on a figure. The BEA publishes PCE, GDP and income/spending releases; Census adds trade, retail, housing and manufacturing indicators. These are complementary indicators, not replacements for BLS CPI or the full employment report. FRED and official BLS/BEA APIs remain candidates for a later structured time-series integration; FRED/BEA API credentials and source provenance must be handled explicitly before adding numerical macro series. Feed reachability is checked by live runs; failures are reported without blocking report generation. Headlines are interleaved by feed so a single source is less likely to dominate the report. Headline text is normalized to suppress exact repeats across different search feeds; this reduces duplicated stories but does not independently verify the underlying reporting.
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