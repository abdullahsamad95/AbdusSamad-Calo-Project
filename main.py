#!/usr/bin/env python3
# calo_generate_excel.py
# — Set IN_DIR and OUT_DIR below and run:  python v2.py
# Requires: pip install pandas numpy openpyxl

import re
import gzip
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import os

IN_DIR  = os.getenv("IN_DIR", "/data.zip")  # mounted in container
OUT_DIR = os.getenv("OUT_DIR", "/out")      # mounted in container



def extract_if_zip(in_path: Path) -> Path:
    """If IN_DIR points to a .zip, extract to temp folder and return that folder."""
    p = Path(in_path)
    if p.is_file() and p.suffix.lower() == ".zip":
        tmpdir = Path(tempfile.mkdtemp(prefix="calo_logs_"))
        import zipfile
        with zipfile.ZipFile(p, "r") as zf:
            zf.extractall(tmpdir)
        return tmpdir
    return p


def parse_logs(data_dir: Path) -> pd.DataFrame:
    """Parse .gz logs into structured records (START/END RequestId blocks)."""
    start_re = re.compile(r"^\d{4}-\d{2}-\d{2}T.*START RequestId:\s+(?P<rid>[0-9a-f\-]{36})")
    end_re   = re.compile(r"^\d{4}-\d{2}-\d{2}T.*END RequestId:\s+(?P<rid>[0-9a-f\-]{36})")

    fields_patterns = {
        'paymentBalance': re.compile(r'paymentBalance:\s*([0-9\.\-]+)'),
        'updatePaymentBalance': re.compile(r'updatePaymentBalance:\s*(true|false)', re.I),
        'oldBalance': re.compile(r'oldBalance:\s*([0-9\.\-]+)'),
        'newBalance': re.compile(r'newBalance:\s*([0-9\.\-]+)'),
        'amount': re.compile(r'amount:\s*([0-9\.\-]+)'),
        'action': re.compile(r"action:\s*'([^']+)'"),
        'transactionAction': re.compile(r"transactionAction:\s*'([^']+)'"),
        'walletId': re.compile(r'"walletId":"?([^",\'}]+)'),
        'userId': re.compile(r"userId:\s*'([^']+)'"),
        'email': re.compile(r'"email":"?([^",\'}]+)'),
        'id': re.compile(r'"id":"?([^",\'}]+)'),
    }

    records = []
    gz_files = sorted(Path(data_dir).rglob("*.gz"))
    for gz in gz_files:
        try:
            with gzip.open(gz, 'rt', encoding="utf-8", errors="ignore") as f:
                current_id = None
                buffer_lines = []
                start_ts = None

                for raw in f:
                    s = raw.strip()
                    mstart = start_re.match(s)
                    if mstart:
                        if current_id and buffer_lines:
                            records.append(_extract_record("\n".join(buffer_lines), current_id, gz, start_ts, fields_patterns))
                        current_id = mstart.group('rid')
                        buffer_lines = [s]
                        start_ts = s.split('Z')[0] + 'Z' if 'Z' in s else s[:25]
                        continue
                    mend = end_re.match(s)
                    if mend and current_id and (mend.group('rid') == current_id):
                        buffer_lines.append(s)
                        records.append(_extract_record("\n".join(buffer_lines), current_id, gz, start_ts, fields_patterns))
                        current_id, buffer_lines, start_ts = None, [], None
                        continue
                    if current_id:
                        buffer_lines.append(s)
                if current_id and buffer_lines:
                    records.append(_extract_record("\n".join(buffer_lines), current_id, gz, start_ts, fields_patterns))
        except Exception:
            continue

    return pd.DataFrame(records)


def _extract_record(text: str, rid: str, gz_path: Path, start_ts: str, patterns: dict) -> dict:
    rec = {"requestId": rid, "file": str(gz_path), "start_ts": start_ts}
    for k, pat in patterns.items():
        m = pat.search(text)
        if m:
            rec[k] = m.group(1)
    return rec


def analyze(df: pd.DataFrame) -> dict:
    """Compute per-event metrics + aggregates."""
    df = df.copy()
    df['ts'] = pd.to_datetime(df.get('start_ts'), errors='coerce')

    def to_float(x):
        try: return float(x)
        except: return np.nan

    for col in ['paymentBalance', 'oldBalance', 'newBalance', 'amount']:
        if col in df.columns:
            df[col] = df[col].apply(to_float)

    df['delta'] = df['newBalance'] - df['oldBalance']

    def best_sign(row):
        amt, dlt = row.get('amount'), row.get('delta')
        if pd.isna(amt) or pd.isna(dlt): return np.nan
        return 1.0 if abs(dlt - amt) <= abs(dlt + amt) else -1.0

    df['amount_sign'] = df.apply(best_sign, axis=1)
    df['expected_delta'] = df['amount'] * df['amount_sign']
    df['mismatch'] = (df['delta'] - df['expected_delta']).abs() > 1e-6

    df['overdraft_before'] = df['oldBalance'] < 0
    df['overdraft_after']  = df['newBalance'] < 0
    df['overdraft_cross']  = (~df['overdraft_before']) & (df['overdraft_after'])

    df = df.sort_values(['userId', 'walletId', 'ts', 'requestId'], na_position='last')
    if 'userId' in df.columns and 'walletId' in df.columns:
        df['next_old'] = df.groupby(['userId', 'walletId'])['oldBalance'].shift(-1)
    else:
        df['next_old'] = np.nan
    df['flow_break'] = (df['newBalance'].notna()) & (df['next_old'].notna()) & ((df['newBalance'] - df['next_old']).abs() > 1e-6)

    def z_anomalies(sub: pd.DataFrame) -> pd.Series:
        vals = sub['delta'].dropna()
        if len(vals) < 5: return pd.Series([False] * len(sub), index=sub.index)
        mu, sd = vals.mean(), vals.std(ddof=1)
        if sd == 0: return pd.Series([False] * len(sub), index=sub.index)
        return (abs(sub['delta'] - mu) > 3 * sd)

    if 'userId' in df.columns:
        df['delta_anomaly'] = df.groupby('userId', group_keys=False).apply(z_anomalies)
    else:
        df['delta_anomaly'] = False

    for col in ["overdraft_after", "mismatch", "flow_break", "delta_anomaly"]:
        df[col] = df[col].fillna(False).astype(bool)

    if 'userId' in df.columns:
        per_user = df.dropna(subset=['userId']).groupby('userId').agg(
            first_ts=('ts','min'),
            last_ts=('ts','max'),
            events=('requestId','count'),
            overdraft_events=('overdraft_after','sum'),
            overdraft_crossings=('overdraft_cross','sum'),
            mismatches=('mismatch','sum'),
            flow_breaks=('flow_break','sum'),
            last_balance=('newBalance', lambda x: x.dropna().iloc[-1] if len(x.dropna()) else np.nan),
            min_balance=('newBalance','min'),
            max_balance=('newBalance','max'),
        ).reset_index()
        per_user['final_overdraft'] = per_user['last_balance'] < 0
    else:
        per_user = pd.DataFrame()

    return {'df': df, 'per_user': per_user}


def export_excel(analysis: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    df = analysis['df'].copy()
    per_user = analysis['per_user'].copy()

    def make_naive(d, cols):
        for c in cols:
            if c in d.columns:
                d[c] = pd.to_datetime(d[c], utc=True, errors='coerce').dt.tz_convert(None)
        return d

    per_user = make_naive(per_user, ['first_ts','last_ts'])
    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'], utc=True, errors='coerce').dt.tz_convert(None)

    red_flags  = df[df['overdraft_after'] | df['mismatch'] | df['flow_break'] | df['delta_anomaly']].copy()
    overdrafts = df[df['overdraft_after']].copy()
    mismatches = df[df['mismatch']].copy()
    flow_breaks= df[df['flow_break']].copy()
    anomalies  = df[df['delta_anomaly']].copy()

    excel_path = out_dir / "calo_balance_reports.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as w:
        # README sheet
        readme = pd.DataFrame({
            "Item / Tab": [
                "PerUserSummary","RedFlags","OverdraftEvents","MismatchEvents","FlowBreaks","Anomalies","SampleRaw","ColumnDefinitions"
            ],
            "What it shows": [
                "Aggregated per-user stats (balances, overdrafts, mismatches etc.)",
                "All rows with any flagged issue (overdraft, mismatch, flow break, anomaly)",
                "Only rows where newBalance < 0",
                "Only rows where delta != expected amount",
                "Only rows where balances didn’t carry over correctly",
                "Only rows where delta is an unusual outlier (>3σ)",
                "First 200 parsed rows from raw logs",
                "Glossary of all column definitions"
            ]
        })
        readme.to_excel(w, sheet_name="README", index=False)

        # ColumnDefinitions sheet
        col_defs = pd.DataFrame({
            "Column": [
                "requestId","file","start_ts","ts","paymentBalance","oldBalance","newBalance","amount","action",
                "transactionAction","walletId","userId","email","id","delta","amount_sign","expected_delta",
                "mismatch","overdraft_before","overdraft_after","overdraft_cross","next_old","flow_break","delta_anomaly"
            ],
            "Definition": [
                "Unique identifier of the log invocation block",
                "Source .gz log file",
                "Raw timestamp string from the log",
                "Parsed datetime version of start_ts",
                "Balance at time of payment (from log)",
                "Balance before the transaction",
                "Balance after the transaction",
                "Transaction amount",
                "Action recorded in log",
                "Subtype of transaction action",
                "Wallet identifier for subscriber",
                "Subscriber/user identifier",
                "Email of the subscriber (if logged)",
                "Business transaction ID (if logged)",
                "newBalance - oldBalance",
                "+1 if amount acts like credit, -1 if debit",
                "Expected delta = amount * amount_sign",
                "True if delta != expected_delta (inconsistency)",
                "True if oldBalance < 0",
                "True if newBalance < 0",
                "True if crossed from >=0 to <0",
                "Next event’s oldBalance (for flow check)",
                "True if newBalance != next oldBalance",
                "True if delta is an outlier (>3σ for that user)"
            ]
        })
        col_defs.to_excel(w, sheet_name="ColumnDefinitions", index=False)

        if not per_user.empty:
            per_user.to_excel(w, sheet_name="PerUserSummary", index=False)

        red_flags.to_excel(w, sheet_name="RedFlags", index=False)
        overdrafts.to_excel(w, sheet_name="OverdraftEvents", index=False)
        mismatches.to_excel(w, sheet_name="MismatchEvents", index=False)
        flow_breaks.to_excel(w, sheet_name="FlowBreaks", index=False)
        anomalies.to_excel(w, sheet_name="Anomalies", index=False)
        df.head(200).to_excel(w, sheet_name="SampleRaw", index=False)

    return excel_path


def main():
    in_path = extract_if_zip(Path(IN_DIR))
    out_dir = Path(OUT_DIR)

    if not in_path.exists():
        raise SystemExit(f"[ERROR] IN_DIR does not exist: {IN_DIR}")
    if not any(Path(in_path).rglob("*.gz")):
        raise SystemExit(f"[ERROR] No .gz log files found under: {in_path}")

    print(f"[INFO] Parsing logs from {in_path} ...")
    df = parse_logs(in_path)
    print(f"[INFO] Parsed {len(df)} blocks")

    print("[INFO] Analyzing and building report ...")
    analysis = analyze(df)

    print(f"[INFO] Writing Excel to {out_dir} ...")
    excel_path = export_excel(analysis, out_dir)
    print(f"[OK] Report written → {excel_path}")


if __name__ == "__main__":
    main()
