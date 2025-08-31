# Calo Balance Reports (Dockerized)

A self-contained tool that parses Calo “balance-sync” logs, detects accounting issues, and exports an accountant-friendly Excel workbook.

---

## Features

- **Parses** AWS Lambda-style START/END blocks from `.gz` logs (or a `.zip` containing them).
- **Flags issues automatically**:
  - **Overdrafts** – when balance goes below zero after a transaction.
  - **Mismatches** – `(newBalance - oldBalance) != expected amount`.
  - **Flow Breaks** – when balances don’t line up between consecutive events for the same user/wallet.
  - **Delta Anomalies** – unusual transaction jumps/drops (>3σ).
- **Excel Output** with:
  - `README` sheet
  - `ColumnDefinitions` (plain-English glossary)
  - `PerUserSummary`
  - `RedFlags` (union of all issues)
  - `OverdraftEvents`, `MismatchEvents`, `FlowBreaks`, `Anomalies`
  - `SampleRaw` (first 200 parsed rows)

---

## Project Structure

```
.
├─ main.py               # Entry point script
├─ requirements.txt      # Dependencies (pandas, numpy, openpyxl)
├─ Dockerfile            # Docker setup
├─ .dockerignore         # Ignore caches/logs in docker build
├─ .gitignore            # Ignore logs/reports in git
├─ README.md             # This file
└─ balance-sync-logs/    # Provided test logs (unzipped .gz files)

```

---

## Quick Start with Docker

> No Python needed — just Docker.

### 1) Build image

```bash
docker build -t calo-project .
```

### 2) Run container

The project includes a file named balance-sync-logs.zip (containing the .gz log files).  
This file will be mounted directly into the container at runtime.

#### Windows CMD
```powershell
mkdir reports
docker run --rm ^
  -v "%cd%\balance-sync-logs.zip:/data.zip:ro" ^
  -v "%cd%\reports:/out" ^
  calo-project
```

#### Windows PowerShell
```powershell
mkdir reports
docker run --rm `
  -v "${PWD}\balance-sync-logs.zip:/data.zip:ro" `
  -v "${PWD}\reports:/out" `
  calo-project
```

#### macOS/Linux
```bash
mkdir -p reports
docker run --rm \
  -v "$PWD/balance-sync-logs.zip:/data.zip:ro" \
  -v "$PWD/reports:/out" \
  calo-project
```

Output: `./reports/calo_balance_reports.xlsx`

---

## Running Locally (optional)

If you prefer without Docker:

```bash
pip install -r requirements.txt

# Windows PowerShell
$$env:IN_DIR="D:\path\to\balance-sync-logs"
$env:OUT_DIR="D:\path\to\reports"
python main.py

# macOS/Linux
export IN_DIR=/path/to/balance-sync-logs
export OUT_DIR=/path/to/reports
python main.py
```

---

## Workbook Tabs

- **README** – Explains the sheets.
- **ColumnDefinitions** – Glossary of all fields.
- **PerUserSummary** – Aggregated stats by user.
- **RedFlags** – Any row flagged as overdraft, mismatch, flow break, or anomaly.
- **OverdraftEvents** – Transactions where `newBalance < 0`.
- **MismatchEvents** – Rows where `(newBalance - oldBalance) != expected amount`.
- **FlowBreaks** – Rows where `newBalance` doesn’t match the next event’s `oldBalance`.
- **Anomalies** – Rows with statistical outlier deltas (>3σ).
- **SampleRaw** – First 200 parsed rows from logs.

---

## Column Definitions (Glossary)

- **requestId** – Unique ID of the log block.  
- **file** – Source `.gz` log file.  
- **start_ts** – Raw timestamp from log.  
- **ts** – Parsed datetime.  
- **paymentBalance** – Balance recorded at time of payment.  
- **oldBalance** – Balance before transaction.  
- **newBalance** – Balance after transaction.  
- **amount** – Transaction amount.  
- **action** – Logged action (e.g., debit/credit).  
- **transactionAction** – Action subtype (payment/refund).  
- **walletId / walletSk** – Wallet identifiers.  
- **userId** – Subscriber identifier.  
- **phone / email** – Subscriber contact (if present).  
- **type / id** – Transaction type / business id.  
- **delta** – `newBalance - oldBalance`.  
- **amount_sign** – +1 if amount behaves like credit, -1 if debit.  
- **expected_delta** – `amount * amount_sign`.  
- **mismatch** – True if `delta != expected_delta`.  
- **overdraft_before** – True if `oldBalance < 0`.  
- **overdraft_after** – True if `newBalance < 0`.  
- **overdraft_cross** – True if crossed from `>=0` to `<0`.  
- **next_old** – Next event’s `oldBalance`.  
- **flow_break** – True if `newBalance != next_old`.  
- **delta_anomaly** – True if delta is >3σ outlier for that user.  


## Engineering Notes
- Logs are parsed per RequestId block (START → END). 
- Extracted fields include balances, deltas, overdrafts, mismatches, and anomalies. 
- Overdraft detection = when newBalance < 0. 
- Mismatch = when reported delta != computed amount. 
- RedFlags = any overdraft crossing or mismatched delta. 
- FlowBreaks = detected if event sequence is missing or requestId incomplete.
- Future extensions: pivot charts, dashboards (Tableau/PowerBI), or a Jupyter notebook with time-series plots.

---

## Design Choices

- **Python + Pandas** – well-suited for log parsing, data wrangling, and Excel output.  
- **openpyxl** – reliable Excel writer for accounting workflows.  
- **Docker** – ensures the same run everywhere, no dependency setup.  
- **Excel Output** – accessible to accountants, includes built-in explanations.

---

## Future Improvements

- Add interactive web dashboard (Streamlit/Dash).  
- Insert charts & pivot tables into Excel.  
- Automated alerting (email/Slack) on overdrafts/mismatches.  



### Author
**Abdus Samad Abdullah** – Data Engineer / Data Scientist
