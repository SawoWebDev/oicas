# MASTER DEVELOPMENT PROMPT
# OICAS — Odoo Inventory Control & Analytics System
## Complete Excel-to-System Automation, Odoo Integration, Inventory Management, and Reporting Platform

---

## 1. YOUR ROLE AND MISSION

Act as a senior software architect, full-stack developer, business process analyst, inventory management specialist, Excel formula auditor, Odoo integration engineer, database architect, automation engineer, QA engineer, and deployment engineer.

Your mission is to BUILD THE ENTIRE OICAS SYSTEM.

This is a complete application development assignment. It is not merely a dashboard design, a spreadsheet converter, a prototype, a technical proposal, or a collection of independent modules.

The objective is to transform the existing manual Excel-based inventory management process into a complete, connected, automated, secure, and auditable web application.

The finished system must reproduce the verified business rules, formulas, relationships, operational workflows, classifications, and reporting requirements represented in the attached Excel workbooks.

The system must connect to the existing Odoo environment to retrieve inventory information and authenticate authorized users through the approved Odoo identity and access mechanism.

The application must eliminate unnecessary manual transfers of data between Excel files.

**Primary instruction: Analyze the complete existing process, understand how it works, build the replacement system, test the calculations against the original Excel files, and deliver a functioning application.**

Do not stop after presenting an implementation plan or generating sample code. Continue through development, testing, integration, and deployment preparation.

## 2. OFFICIAL SYSTEM NAME

System name: OICAS

Full name: Odoo Inventory Control & Analytics System

Purpose:

OICAS is a centralized inventory management, cycle-counting, reconciliation, classification, analytics, and reporting platform integrated with Odoo.

It replaces the manual workflow involving multiple Excel workbooks with a connected system that retrieves inventory information, calculates inventory metrics, schedules physical counts, records actual quantities, identifies discrepancies, tracks performance, and generates official reports.

The system must support both operational inventory personnel and management users.

## 3. ATTACHED REFERENCE WORKBOOKS

The following files will be attached to this development instruction:

1. `03_AMC Sep-Jul ABC Analysis.xlsx`
2. `10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx`
3. `automation flow 2.xlsx`
4. `COUNTED LIST.xlsx`

These files are the primary references for the existing business process.

Treat the workbooks as interconnected business artifacts rather than unrelated spreadsheets.

Do not assume that their worksheet names, column labels, formulas, or displayed values fully explain the underlying process. Inspect the actual workbook contents before making implementation decisions.

Do not begin by inventing a new workflow that ignores the existing process.

First determine how the existing workbooks work, how information flows between them, which data comes from Odoo, which data is manually recorded, and which calculations produce the final reports.

Preserve the existing business logic unless an authorized change is explicitly approved.

## 4. PHASE ZERO — COMPLETE EXCEL REVERSE-ENGINEERING

This phase is mandatory and must be completed before finalizing the application logic.

Inspect all four workbooks in full.

For each workbook, examine:

- All worksheets and their order.
- Visible and hidden worksheets.
- Populated rows and columns.
- Hidden rows and columns containing relevant information.
- Formulas and formula dependencies.
- Cross-sheet references.
- External workbook references.
- Named ranges and tables.
- Lookup tables and reference data.
- Data validation rules and dropdown lists.
- Conditional formatting and discrepancy indicators.
- Merged cells, report headers, and layout conventions.
- Embedded diagrams, shapes, notes, and other workflow information when available.
- Reporting periods and date conventions.
- Blank, missing, duplicated, and invalid values.
- The distinction between imported, manually entered, and calculated fields.

Inspect the underlying formulas, not only the values displayed in Excel.

If cached formula results are missing or stale, calculate or reconstruct the results using the verified formulas and available source data. Document any limitation that prevents exact reconstruction.

For every relevant formula, document:

1. Source workbook and worksheet.
2. Source cell or column.
3. Original formula.
4. Referenced cells, tables, or worksheets.
5. Business meaning.
6. Input data requirements.
7. Calculation sequence.
8. Output field.
9. Handling of missing values and invalid data.
10. Rounding and precision.
11. Expected result.
12. Validation procedure.
13. Whether the formula must be preserved, corrected, or confirmed.

Build a formula dependency map showing which source fields feed each calculation and which calculated fields feed the final reports.

Identify every relevant manual operation, including copying data between files, refreshing formulas, filtering records, updating count dates, classifying items, preparing reports, and consolidating counting results.

Translate these operations into an explicit business workflow.

### Required analysis deliverables

Before implementing the corresponding functionality, create:

- Excel Workbook Inventory.
- Worksheet and Column Data Dictionary.
- Formula and Calculation Register.
- Cross-Workbook Dependency Map.
- Current-State Business Process Map.
- Source-to-Target Data Mapping.
- Report Catalog.
- Business Rules Register.
- Data Quality and Exception Register.
- List of Unresolved Decisions.

These are working development artifacts, not the final product. Continue implementation after creating them.

If a rule is unclear, identify the specific rule and supporting evidence. Do not stop the entire project because of one ambiguity. Implement independent, verified functionality while keeping unresolved rules configurable or isolated pending approval.

## 5. UNDERSTAND EACH WORKBOOK

### 5.1 AMC and ABC Analysis

Reference: `03_AMC Sep-Jul ABC Analysis.xlsx`

Inspect all worksheets, including any demand source worksheet and item-family-specific analysis sheets.

Determine the actual calculation method for:

- Monthly demand.
- Total demand for the selected reporting period.
- Average Monthly Consumption.
- Demand contribution percentage.
- Demand frequency.
- Frequency percentage.
- Ranking and sorting.
- Cumulative demand percentage.
- Cumulative frequency percentage.
- ABC classification.
- Treatment of zero demand, missing demand, negative demand, and ties.

The reporting period may cover September through August. Confirm the actual period and month sequence from the workbook.

The workbook appears to use monthly lookup formulas from a demand worksheet and calculates total demand, percentages, frequencies, cumulative percentages, and classifications.

An existing classification pattern appears equivalent to:

- A for cumulative demand percentage below 80%.
- C for cumulative demand percentage of at least 95%.
- B otherwise.

Treat this as a rule to verify against the actual workbook, not as an instruction to override the original formula without examination.

Pay particular attention to the order of operations when calculating cumulative percentages and assigning ABC categories.

Do not assume that ABC classification and inventory movement classification are the same process.

Preserve the verified legacy rules as the baseline. Make thresholds configurable only through authorized settings, with version history and an effective date.

### 5.2 Inventory Masterlist and Cycle Count Tracker

Reference: `10.13.26 INVENTORY MASTERLIST & CYCLE COUNT TRACKER.xlsx`

Inspect the worksheets:

- `PROGRESS-overall`
- `PROGRESS-weekly`
- `Master`
- `DATA`

The masterlist includes fields such as:

- RM Code.
- Description.
- Action.
- Classification.
- AMC.
- Material Section.
- Plant Location.
- Counting interval.
- Counting interval in days.
- Unit of Measure.
- Counted Date.
- Next Count.
- Actual Count — Warehouse.
- Actual Count — Production.
- Stock in Months.
- Odoo Warehouse balance.
- Odoo Pre-Production balance.
- Warehouse discrepancy.
- Production discrepancy.
- Remarks.
- Discrepancy indicator.

Inspect the actual workbook for all additional columns, formulas, and lookup dependencies.

Determine how the masterlist retrieves product information, identifies the applicable classification, calculates counting dates, and compares physical quantities with Odoo quantities.

The overall progress report tracks categories such as:

- Fast Moving.
- Medium Moving.
- Slow Moving.
- Non Moving.

The weekly progress report includes weekly counting activity, discrepancies, accurate items, accuracy percentages, and completion percentages.

Reproduce the verified formulas and reporting structure. Establish the correct population and denominator for every percentage.

### 5.3 Automation Flow

Reference: `automation flow 2.xlsx`

Inspect the worksheets:

- `MAIN PAGE`
- `COUNTED LIST`
- `AMC`

Determine the actual manual operating sequence, information dependencies, counting process, reference information, and any existing automation logic.

Translate the relevant workflow into guided application steps and background automation.

If a worksheet represents a process diagram, use its actual relationships to define the application workflow rather than merely copying its visual appearance.

### 5.4 Counted List and Odoo Inventory

Reference: `COUNTED LIST.xlsx`

Inspect the worksheets:

- `LIST`
- `ODOO inv`
- `DATA`

The counted list includes fields such as:

- Date Counted.
- RM Code.
- Description.
- Total Count — Warehouse.
- Total Count — Production.
- Remarks.
- Counted By.
- Multiple warehouse count entries.
- Multiple production count entries.
- Odoo Warehouse balance.
- Odoo Pre-Production balance.
- Warehouse discrepancy.
- Production discrepancy.

The Odoo inventory worksheet contains product identifiers, product descriptions, stock quantities by location, and snapshot or download information.

The DATA worksheet contains product codes, descriptions, units of measure, and related reference information.

Determine the exact relationships between these datasets.

Support multiple count entries per item, date, location, and count round when required. Preserve every count entry and its audit history.

Never overwrite a prior count silently.

## 6. BUILD A SINGLE CONNECTED SYSTEM

The system must not consist of unrelated pages with duplicated or inconsistent calculation logic.

Create a centralized application architecture with shared services for:

- Inventory data.
- Odoo synchronization.
- Product and location mapping.
- Count scheduling.
- Physical count records.
- Inventory reconciliation.
- AMC calculation.
- Movement classification.
- ABC analysis.
- Progress and accuracy metrics.
- Report generation.
- Export generation.
- Audit logging.
- Permissions and configuration.

Use one authoritative calculation service for each business rule.

The dashboard, reports, exports, and drill-down screens must all use the same approved calculations.

If a calculation changes, update its central implementation and version the rule where necessary. Do not maintain separate formulas for the dashboard and exported reports.

## 7. REQUIRED END-TO-END AUTOMATED WORKFLOW

Implement and test this connected process.

### Step 1 — Authenticate the User

The user accesses OICAS through the approved Odoo identity and authentication mechanism.

Validate the user's identity and applicable permissions.

### Step 2 — Retrieve Odoo Inventory Data

Retrieve the required products, item identifiers, quantities, units of measure, warehouses, locations, and related information using supported Odoo APIs.

Record the source, synchronization time, company scope, location scope, and synchronization result.

### Step 3 — Validate and Prepare Data

Validate product mappings, location mappings, units of measure, duplicate codes, missing fields, and stale inventory snapshots.

Flag problems instead of silently correcting ambiguous data.

### Step 4 — Update the Inventory Masterlist

Combine verified Odoo product information with application-managed inventory attributes, historical demand information, and approved counting configurations.

Maintain the distinction between Odoo-owned fields and application-owned fields.

### Step 5 — Calculate AMC, ABC, and Movement Classifications

Apply the verified rules and available historical data.

Record the calculation period, source data, configuration version, and classification result.

### Step 6 — Generate Counting Priorities and Schedules

Determine which items must be counted, their approved counting intervals, due dates, priority, location, and assigned personnel.

Handle new items and items without previous count dates according to approved rules.

### Step 7 — Record Physical Inventory Counts

Authorized users record warehouse and production/pre-production counts, including count date, individual entries, responsible personnel, and remarks.

Allow controlled recounts and corrections.

### Step 8 — Aggregate Counts

Aggregate count entries according to the verified business rules.

Keep quantities separated by relevant warehouse, production area, stock location, count round, and unit of measure.

Do not combine incompatible quantities.

### Step 9 — Reconcile Physical Counts with Odoo

Compare physical quantities against the correct Odoo snapshot and mapped location.

Calculate the verified discrepancies, accuracy metrics, and reconciliation status.

### Step 10 — Review Discrepancies

Identify mismatches, incomplete counts, unmapped products, and questionable quantities.

Support recount requests, investigation remarks, assignments, and resolution history.

Do not modify Odoo inventory quantities automatically.

### Step 11 — Generate Official Reports

Generate the required dashboard metrics, inventory reports, weekly progress reports, ABC analysis, AMC reports, discrepancy reports, and Excel/PDF exports.

All reports must use consistent, validated data and calculation versions.

### Step 12 — Update the Next Cycle

Use the approved counting rules and completed count history to determine the next scheduled count.

Update progress and operational priorities without erasing historical records.

The entire process must be connected through shared data and services. Users must not need to copy and paste information manually between Excel files to complete the normal workflow.

## 8. ODOO INTEGRATION AND AUTHENTICATION

Odoo is the authoritative source for Odoo-owned product and inventory information.

Inspect the actual Odoo version, available APIs, authentication options, installed modules, company configuration, product fields, and stock-location structure.

Implement a secure integration appropriate to the existing deployment.

Authentication requirements:

- Provide a Login with Odoo workflow.
- Reuse Odoo identity and permissions where technically supported.
- Use an approved SSO/OAuth or secure server-side authentication method where available.
- Do not assume that an Odoo username and password automatically authenticate a separate application.
- Never expose Odoo credentials or tokens to the browser or AI model.
- Do not store plaintext passwords.
- Enforce authorization on the backend.
- Apply appropriate session security, expiration, revocation, and logging.

Inventory integration requirements:

- Retrieve products and stable product identifiers.
- Retrieve stock quantities for the required locations.
- Map warehouse and production/pre-production locations using verified identifiers.
- Handle pagination, API limits, timeouts, retries, and errors.
- Track synchronization status and last successful retrieval.
- Detect missing products, ambiguous mappings, stale data, and partial synchronization.
- Preserve historical snapshots for reproducible reports.

**OICAS must be read-only toward Odoo in the initial release.**

Do not create stock adjustments, stock moves, product changes, or other Odoo write operations.

Physical count data, application classifications, report history, and count schedules must be stored in the OICAS database.

If Odoo becomes unavailable, display the last successful synchronization time and a clear stale-data warning. Do not label cached information as current.

Use supported Odoo APIs or a controlled integration gateway. Do not connect directly to Odoo's PostgreSQL database or permit arbitrary queries against it.

## 9. DATA MODEL AND DATABASE DESIGN

Design a relational database with appropriate keys, constraints, relationships, indexes, and migration scripts.

Evaluate and implement the required entities, including:

- Users and Odoo identity mappings.
- Companies and authorized organizational scopes.
- Warehouses and stock locations.
- Inventory items.
- Product and location mappings.
- Inventory snapshots.
- Demand history.
- AMC calculation runs.
- ABC analysis runs.
- Movement classifications.
- Counting plans.
- Counting schedules.
- Count sessions.
- Individual count entries.
- Count rounds and location-level counts.
- Count assignments.
- Discrepancy and reconciliation records.
- Classification and interval configuration.
- Report definitions.
- Report execution history.
- Export history.
- Synchronization logs.
- Data quality exceptions.
- Audit logs.

Use stable identifiers. Do not rely on descriptions alone as keys.

Preserve the original Odoo product identifier when available.

Maintain historical source snapshots and calculation versions so that past reports can be reproduced.

Do not overwrite historical records when a new synchronization or count is received.

Use transactions, validation, and appropriate uniqueness constraints to prevent duplicate or partial submissions.

Distinguish missing values from actual zero quantities.

## 10. INVENTORY MASTERLIST MODULE

Build a complete inventory masterlist with search, filters, pagination, sorting, and detailed item views.

Required fields include the verified equivalents of:

- Item code.
- Odoo product identifier.
- Description.
- Material section.
- Plant location.
- Warehouse or stock location.
- Unit of measure.
- AMC.
- Stock in months.
- ABC classification.
- Movement classification.
- Action.
- Counting interval.
- Last count date.
- Next count date.
- Physical warehouse quantity.
- Physical production/pre-production quantity.
- Odoo warehouse quantity.
- Odoo production/pre-production quantity.
- Warehouse discrepancy.
- Production discrepancy.
- Remarks.
- Reconciliation status.

Include all additional fields discovered in the source workbooks.

Users must be able to inspect count history, data quality issues, and the source of calculated values.

Allow editing only for application-managed fields and only for authorized users.

## 11. PHYSICAL INVENTORY AND CYCLE COUNT MODULE

Implement a full count workflow with:

- Count plan creation.
- Item selection.
- Location selection.
- Personnel assignment.
- Count sheet generation.
- Physical quantity entry.
- Warehouse and production/pre-production separation.
- Multiple count entries.
- Multiple count rounds.
- Count validation.
- Submission and finalization.
- Recount requests.
- Correction reasons.
- Remarks and attachments where appropriate.
- Count history.
- Audit logging.

Record the user, date, time, count session, location, and relevant item identifier.

Do not treat an uncounted item as a confirmed zero quantity.

Do not automatically overwrite a submitted count. Use controlled corrections or recounts with a reason and audit trail.

Prevent duplicate submissions from generating duplicate count records.

Clearly indicate incomplete count sessions.

## 12. CENTRAL INVENTORY CALCULATION ENGINE

Implement deterministic and testable calculations for all official inventory metrics.

### Discrepancy

The baseline signed discrepancy is:

Physical Quantity − Odoo Quantity

Confirm the sign convention against the original Excel formulas.

Calculate separate warehouse and production/pre-production discrepancies using the correct mapped locations and matching snapshots.

### Inventory accuracy

Determine the original formula and reproduce it where valid.

An item-based accuracy measure may be calculated as:

Accurate counted items ÷ Total eligible counted items × 100

Use this only if it matches the approved business definition.

### Count completion

A count completion measure may be calculated as:

Completed eligible items ÷ Total eligible items in the approved counting plan × 100

Verify the actual denominator and inclusion rules.

### Other metrics

Calculate and document:

- Counted items.
- Remaining items.
- Items with discrepancies.
- Discrepancy rate.
- Accurate items.
- Net quantity variance.
- Absolute quantity variance.
- Overdue counts.
- Upcoming counts.
- Count completion.
- Historical progress.

Do not treat item-based accuracy, quantity variance, and financial inventory accuracy as interchangeable metrics.

Handle zero denominators, incomplete counts, missing balances, unit-of-measure conversions, and rounding explicitly.

Never claim financial loss without verified cost data and an approved valuation methodology.

## 13. AMC AND MOVEMENT CLASSIFICATION ENGINE

Implement the exact AMC and movement-classification methodology discovered in the reference workbooks.

Determine the observation period, source of demand or consumption, treatment of missing months, treatment of zero consumption, and classification thresholds.

Support:

- Fast Moving.
- Medium Moving.
- Slow Moving.
- Non Moving.

Display the classification basis, applicable period, source data, and effective rule version.

Calculate stock in months only when the required stock quantity and AMC inputs are valid.

Do not automatically interpret missing demand as zero consumption.

Keep AMC calculations and movement classification separate from ABC analysis.

Allow authorized configuration of thresholds with validation, effective dates, and audit history.

## 14. ABC ANALYSIS ENGINE

Implement the verified ABC methodology.

Required functions:

- Reporting-period selection.
- Monthly demand retrieval.
- Item-level demand aggregation.
- Total demand calculation.
- Demand contribution percentage.
- Demand frequency.
- Frequency percentage.
- Ranking.
- Cumulative demand percentage.
- ABC classification.
- Threshold configuration.
- Classification history.
- Comparison between analysis runs.
- Detailed item-level export.
- Summary report generation.

Preserve the original reporting period and item-family relationships.

Handle ties, missing demand, zero demand, negative values, and incomplete months through explicit business rules.

Store the analysis period, source snapshot, threshold configuration, and calculation version.

The ABC engine must produce reproducible results that can be compared with the original Excel formulas.

## 15. CYCLE COUNT SCHEDULING AND AUTOMATION

Build a scheduling engine based on the verified action rules, classification, interval, and last valid count date.

Support:

- Daily and weekly count planning.
- Scheduled and overdue counts.
- Upcoming counts.
- Assignment to responsible personnel.
- Location-based scheduling.
- Priority-based scheduling.
- Completion tracking.
- Recount scheduling.
- Historical schedule retention.

Verify the existing interval rules. Examples of 30-day or 90-day intervals must not become universal defaults unless confirmed.

Handle items that have never been counted through an approved initial scheduling rule.

Do not mark an item as counted merely because it appears in a plan.

## 16. DASHBOARD

Build a responsive management dashboard with actual calculated data.

Display:

- Total active items.
- Items counted.
- Items remaining.
- Count completion percentage.
- Inventory accuracy percentage.
- Items with discrepancies.
- Discrepancy rate.
- Overdue counts.
- Upcoming counts.
- Fast, medium, slow, and non-moving item totals.
- ABC classification distribution.
- Weekly progress.
- Accuracy and discrepancy trends.
- Progress by location and responsible personnel.
- Latest Odoo synchronization.
- Latest inventory snapshot.
- Data quality warnings.

Provide filters for date, reporting period, material section, location, movement classification, and relevant business dimensions.

Each KPI must support drill-down to its underlying records.

All displayed metrics must be based on actual data and approved formulas. Do not hardcode demonstration values into production screens.

## 17. COMPLETE REPORTING CENTER

Implement the following reports as integrated, filterable, exportable report definitions.

### Report 1 — Inventory Masterlist

Shows item details, location, UOM, AMC, stock in months, classifications, counting intervals, physical quantities, Odoo quantities, discrepancies, and next count date.

### Report 2 — Inventory Count Sheet

Provides a printable count sheet with item code, description, location, unit of measure, count fields, counter, date, and remarks.

### Report 3 — Physical Inventory Count Report

Shows individual count entries, count sessions, aggregated quantities, count dates, locations, responsible personnel, and count status.

### Report 4 — Odoo vs. Physical Inventory Reconciliation

Compares Odoo and physical quantities for each mapped location and reports signed variances, absolute variances, and reconciliation status.

### Report 5 — Inventory Discrepancy Report

Shows items with discrepancies, Odoo quantities, physical quantities, variances, location, last count date, remarks, and resolution status.

### Report 6 — Overall Cycle Count Progress

Reproduces the verified `PROGRESS-overall` methodology with totals, classification groups, counted items, discrepancies, completion, accuracy, and discrepancy rates.

### Report 7 — Weekly Cycle Count Progress

Reproduces the verified `PROGRESS-weekly` methodology, including week number, dates, counted items, discrepancies, accurate items, accuracy percentages, and cumulative progress.

### Report 8 — AMC Report

Shows demand or consumption history, AMC, observation period, stock quantity, stock in months, and applicable classification.

### Report 9 — ABC Analysis Report

Shows monthly demand, total demand, demand share, frequency, cumulative percentages, and ABC classification.

### Report 10 — Inventory Movement Classification

Groups items into fast, medium, slow, and non-moving categories with the verified classification basis and counting priority.

### Report 11 — Cycle Count Schedule and Overdue Report

Shows planned dates, last count, interval, next count, overdue days, priority, location, assignment, and completion status.

### Report 12 — Inventory Accuracy and Variance Trends

Shows historical count accuracy, discrepancies, completion, and variance trends using reproducible snapshots.

### Report 13 — Data Quality and Unmatched Inventory

Identifies duplicate item codes, missing products, missing units of measure, unmapped locations, missing counts, invalid quantities, and other data quality problems.

### Report 14 — Odoo Synchronization History

Shows synchronization time, source scope, retrieved records, failures, snapshot identifiers, and stale-data conditions.

### Report 15 — Inventory Audit Trail

Shows count creation, amendments, user, timestamp, reason, configuration changes, synchronization events, and report execution history.

### Report 16 — Custom Filtered Inventory Report

Allows authorized users to select approved fields, apply filters, sort and group records, and export results without changing source data.

All report definitions must use the central calculation engine.

## 18. EXCEL AND PDF EXPORTS

Provide Excel and PDF exports for all appropriate reports.

Excel exports must include:

- Report title.
- Reporting period.
- Generation timestamp.
- Applied filters.
- Clear column headers.
- Correct numeric and percentage formats.
- Suitable column widths.
- Frozen headers where appropriate.
- Summary and detailed worksheets where useful.
- Correct totals and subtotals.

PDF exports must include:

- Professional report formatting.
- Reporting period and source information.
- Page numbers.
- Repeated table headers where needed.
- Appropriate page breaks.
- Readable totals and percentages.

Exports must reflect the selected filters and a defined data snapshot.

Ensure that exported results match the corresponding application report.

## 19. APPLICATION NAVIGATION AND USER EXPERIENCE

Implement the following primary navigation:

- Dashboard.
- Inventory Masterlist.
- Cycle Count Planning.
- Physical Inventory Counting.
- Count History.
- Odoo Reconciliation.
- AMC Analysis.
- ABC Analysis.
- Movement Classification.
- Reports Center.
- Data Quality.
- Synchronization History.
- Audit Trail.
- System Configuration.

Use a professional, responsive interface suitable for desktop inventory operations and smaller screens.

Provide searchable tables, filters, pagination, clear status indicators, and detailed record views.

Display clear loading, empty, error, stale-data, and permission-denied states.

Clearly distinguish actual production data from development fixtures.

## 20. ADMINISTRATION AND CONFIGURATION

Provide a secured administration area for:

- Odoo connection configuration.
- Company and stock-location mappings.
- Synchronization settings.
- Counting intervals and scheduling rules.
- Movement classification thresholds.
- ABC thresholds.
- Unit-of-measure mappings.
- Discrepancy tolerance rules.
- Report configuration.
- User access and permissions.
- Audit and data-retention settings.

Validate all changes, preserve configuration history, and log important administrative operations.

Do not allow ordinary users to alter protected calculations or settings.

## 21. AI-ASSISTED INVENTORY ANALYSIS

AI may assist with report explanations, anomaly summaries, comparisons between reporting periods, and descriptions of verified discrepancies.

All AI operations must use controlled application services and authorized data.

AI must not invent inventory figures, modify Odoo records, change approved formulas, fabricate trends, or represent missing data as confirmed zero quantities.

Official reports must rely on deterministic application calculations.

AI-generated explanations must identify the relevant records, dates, and calculated values supporting the explanation.

AI must never claim that a synchronization, count, or report has succeeded unless the application has confirmed the result.

## 22. TECHNICAL ARCHITECTURE

Inspect the existing repository and development environment before choosing the final implementation stack.

Reuse a suitable existing architecture when available.

If no established stack exists, select and document a maintainable architecture consisting of:

- Responsive web frontend.
- Secure backend API.
- Relational database.
- Controlled Odoo integration layer.
- Background jobs for synchronization and report generation where appropriate.
- Automated tests.
- Database migrations.
- Secure environment configuration.
- Logging and monitoring.
- Deployment and backup procedures.

Use shared business services and a clear separation between presentation, business logic, persistence, and Odoo integration.

Use transactions, appropriate indexes, input validation, and controlled error handling.

Never commit production credentials, API tokens, or sensitive inventory exports to source control.

## 23. REQUIRED IMPLEMENTATION PHASES

Execute the project in this sequence.

**Phase 1 — Excel Reverse-Engineering**

Audit all four workbooks. Produce the formula register, data dictionary, dependency map, process map, report catalog, and unresolved-decision list.

**Phase 2 — Architecture and Database**

Design the application, database, central calculation engine, security model, report definitions, and Odoo integration contracts.

**Phase 3 — Odoo Authentication and Read-Only Integration**

Connect to the actual Odoo environment, verify the supported authentication method, retrieve inventory data, map stock locations, and validate snapshot handling.

**Phase 4 — Inventory Masterlist and Data Quality**

Build the inventory masterlist, reference data, mappings, filters, and validation tools.

**Phase 5 — Counting and Scheduling**

Implement count plans, count entry, assignments, multiple count rounds, count history, and cycle-count automation.

**Phase 6 — Reconciliation Engine**

Implement warehouse and production reconciliation, discrepancy calculations, accuracy metrics, and exception handling.

**Phase 7 — AMC, ABC, and Movement Classification**

Implement the verified formulas, classifications, thresholds, and historical analysis runs.

**Phase 8 — Dashboard and Reports**

Build all required reports, dashboard metrics, drill-downs, and Excel/PDF exports.

**Phase 9 — Security and Hardening**

Complete permissions, audit logs, error recovery, performance checks, backups, and security testing.

**Phase 10 — Validation and Deployment**

Run formula-parity tests, end-to-end tests, integration tests, user acceptance tests, and deployment verification. Produce documentation and handover materials.

Maintain a live task checklist showing completed, in-progress, blocked, and untested work.

Do not mark a phase complete merely because its screens or database tables exist.

## 24. AUTOMATED TESTING AND EXCEL PARITY

Use the reference workbooks as test fixtures wherever reliable source values and expected results are available.

Validate:

- Product codes and descriptions.
- Monthly demand.
- Total demand.
- Demand contribution percentages.
- Frequency and cumulative percentages.
- ABC classification.
- AMC.
- Movement classification.
- Stock in months.
- Last count and next count dates.
- Aggregated physical counts.
- Odoo stock quantities.
- Warehouse and production discrepancies.
- Count completion.
- Weekly progress.
- Inventory accuracy.
- Report totals and exported values.

For each difference, identify the exact cause, such as a formula dependency, missing source value, location mapping, reporting period, rounding rule, or data-quality issue.

Do not alter expected results merely to make a test pass.

If an original formula is incorrect, document the evidence and obtain approval for the corrected business rule before replacing the official calculation.

Include tests for:

- Empty datasets.
- Zero quantities.
- Missing demand months.
- Duplicate count submissions.
- Multiple count entries.
- Invalid units of measure.
- Unmapped stock locations.
- Stale Odoo snapshots.
- API timeouts and failed synchronization.
- Incomplete counts.
- Zero denominators.
- Unauthorized access.
- Historical report reproduction.
- Export consistency.

## 25. SECURITY, AUDITABILITY, AND OPERATIONAL SAFETY

Enforce server-side authorization.

Protect credentials and session tokens.

Record significant user actions and configuration changes.

Preserve historical counts and inventory snapshots.

Prevent unauthorized modification of submitted records.

Provide safe error recovery and backup procedures.

Ensure that the initial Odoo integration cannot modify ERP data.

Do not silently discard records, hide calculation failures, or substitute invented values when data is unavailable.

## 26. FINAL ACCEPTANCE CRITERIA

OICAS is complete only when all applicable conditions below are demonstrated:

1. All four Excel workbooks have been inspected.
2. The relevant worksheets, formulas, data relationships, and business rules are documented.
3. The manual process has been translated into a connected application workflow.
4. The approved Odoo authentication and read-only integration work against the actual environment.
5. Product and location mappings have been validated.
6. Inventory snapshots and synchronization failures are traceable.
7. Physical counts support separate locations and multiple count entries.
8. Historical count records remain intact.
9. Reconciliation uses the correct location balances and snapshots.
10. Discrepancy calculations match the approved rules.
11. AMC and movement classifications match the verified methodology.
12. ABC analysis matches the approved formulas and thresholds.
13. Counting schedules and progress metrics are correct.
14. All required reports work with their filters and source data.
15. Excel and PDF exports match the application reports.
16. Historical results can be reproduced using stored snapshots and calculation versions.
17. Permissions and audit logging have been tested.
18. Failed integrations and invalid data are handled safely.
19. Automated tests and Excel-parity results are documented.
20. Deployment, configuration, backup, and user documentation are complete.

## 27. FINAL DELIVERABLES

Provide:

- Complete OICAS application source code.
- Database schema and migrations.
- Odoo authentication and read-only integration.
- Inventory masterlist module.
- Cycle-count planning and physical-counting modules.
- Reconciliation and discrepancy engine.
- AMC analysis module.
- ABC analysis module.
- Movement-classification module.
- Dashboard and management analytics.
- All required reports.
- Excel and PDF export functionality.
- Configuration and administration screens.
- Audit trail and synchronization history.
- Automated test suite.
- Excel formula-parity test results.
- Data dictionary and formula register.
- Deployment and environment configuration instructions.
- Odoo integration documentation.
- User guide.
- Administrator guide.
- Known limitations and unresolved decisions.

Do not include real production secrets in the deliverables.

## 28. FINAL EXECUTION DIRECTIVE

Start by examining the four attached Excel workbooks in full.

Do not assume that the written descriptions in this prompt replace the need to inspect the actual formulas, source columns, and workbook relationships.

Build OICAS as one complete, interconnected application that automates the verified manual inventory workflow.

Connect Odoo data retrieval, inventory preparation, classifications, counting schedules, physical counts, reconciliation, discrepancy review, and report generation through shared data and calculation services.

Preserve the existing business rules unless a change is explicitly approved.

Test every important calculation against the original Excel results.

Continue through implementation, integration, testing, defect correction, and deployment preparation.

Do not claim completion for unimplemented or untested features.

If an essential business rule cannot be established from the workbooks, document the precise issue and request clarification while continuing with all independent, verified functionality.

**The final objective is a working Odoo-connected inventory control and analytics platform that replaces the manual Excel process, automates the complete operational workflow, preserves calculation accuracy, and generates reliable management and operational reports.**