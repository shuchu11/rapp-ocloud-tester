# test_orchestrator_rapp.py
import json
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import requests
from datetime import datetime
import time
import numpy as np
import itertools

RAPP_URL = "http://192.168.8.35:5000"
INSTANCE_ID = "be0cc18b-1b8e-4b58-a2bc-9f4681ac6142"

TEST_TYPE = "TIMING_WINDOWS"

PARAM_RANGES = {
    "TIMING_WINDOWS": {
        "T1a_cp_dl": [
            {"min": 285, "max": 429},
            {"min": 285, "max": 470},
            {"min": 285, "max": 550}
        ],
        "Ta4": [
            {"min": 110, "max": 180},
            {"min": 110, "max": 280}
        ],
        "runs_per_case": 2
    }
}


def generate_test_cases_yaml():
    """Generate test case YAML files from parameter ranges"""
    params = PARAM_RANGES[TEST_TYPE]
    runs = params.get('runs_per_case', 2)

    # Get ODUs from TEIV
    resp = requests.get(f"{RAPP_URL}/teiv/odus")
    odus = resp.json()['odus']

    test_cases = []
    counter = 0

    for odu in odus:
        odu_urn = odu['urn']
        vendor_name = odu['name'].lower()

        # Map to cell URN (assumes pattern)
        cell_urn = odu_urn.replace(':gnb:', ':cell:').replace('-lavoisier', '-cell-1').replace('-joule', '-cell-1')

        # Generate all parameter combinations
        t1a_values = params['T1a_cp_dl']
        ta4_values = params.get('Ta4', [])

        for t1a in t1a_values:
            for ta4 in ta4_values:
                test_id = f"tw-{vendor_name}-{counter:02d}"

                test_case = {
                    'testId': test_id,
                    'testType': 'TIMING_WINDOWS',
                    'description': f"Timing test {vendor_name} - T1a({t1a['min']},{t1a['max']}) Ta4({ta4['min']},{ta4['max']})",
                    'target': {
                        'oduUrn': odu_urn,
                        'cellUrn': cell_urn
                    },
                    'parameters': {
                        'T1a_cp_dl': t1a,
                        'Ta4': ta4
                    },
                    'execution': {
                        'runsPerCase': runs,
                        'stabilizationTime': 30
                    }
                }

                test_cases.append(test_case)
                counter += 1

    return test_cases


def create_test_yaml_files(test_cases):
    """Write test cases to YAML files"""
    import yaml
    import os

    os.makedirs('test_cases/timing_windows', exist_ok=True)

    for tc in test_cases:
        filename = f"test_cases/timing_windows/{tc['testId']}.yaml"
        with open(filename, 'w') as f:
            yaml.dump(tc, f, default_flow_style=False)
        print(f"[CREATE] {filename}")


def load_tests_to_rapp():
    """Load test cases into rApp"""
    resp = requests.post(f"{RAPP_URL}/tests/load")
    result = resp.json()
    print(f"[LOAD] {result['count']} tests loaded")
    return result['loaded']


def run_test_via_rapp(test_id):
    """Execute test via rApp API"""
    print(f"\n{'='*60}\nTest {test_id}\n{'='*60}")

    try:
        resp = requests.post(f"{RAPP_URL}/tests/run/{test_id}", timeout=300)

        if resp.status_code == 200:
            result = resp.json()
            print(f"[SUCCESS] Execution ID: {result['execution_id']}")
            print(f"  Runs: {result['results'].get('successful_runs', 0)}")
            print(f"  Throughput: {result['results'].get('avg_throughput_mbps', 0):.1f} Mbps")
            print(f"  RSRP: {result['results'].get('avg_rsrp_dbm', 0):.1f} dBm")
            return result
        else:
            print(f"[FAIL] {resp.status_code}: {resp.text}")
            return None

    except Exception as e:
        print(f"[ERROR] {e}")
        return None


def query_results_from_db():
    """Query test results from rApp database"""
    # This would ideally be an rApp endpoint, but for now use sqlite directly
    import sqlite3

    conn = sqlite3.connect('/root/rapp-gnb-test-farmework/rapp.db')
    cursor = conn.cursor()

    query = """
    SELECT
        te.test_id,
        te.oru_vendor,
        tr.successful_runs,
        tr.avg_throughput_mbps,
        tr.avg_jitter_ms,
        tr.avg_loss_percent,
        tr.avg_rsrp_dbm,
        tr.avg_rsrq_db,
        tr.avg_sinr_db,
        tc.parameters_json
    FROM test_executions te
    JOIN test_results tr ON tr.test_execution_id = te.id
    JOIN test_cases tc ON tc.test_id = te.test_id
    WHERE te.status = 'completed'
    ORDER BY te.timestamp DESC
    """

    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        results.append({
            'test_id': row[0],
            'oru': row[1],
            'successful_runs': row[2],
            'avg_throughput_mbps': row[3],
            'avg_jitter_ms': row[4],
            'avg_loss_percent': row[5],
            'avg_rsrp_dbm': row[6],
            'avg_rsrq_db': row[7],
            'avg_sinr_db': row[8],
            'params': json.loads(row[9]) if row[9] else {}
        })

    return results


def plot_test_results(results, timestamp):
    """Plot aggregated results"""
    if not results:
        print("[WARN] No results to plot")
        return

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle(f'O-RAN Test Results - {timestamp}', fontsize=16, fontweight='bold')

    test_ids = [r['test_id'] for r in results]
    colors = ['#ff7f0e' if 'pegatron' in r['oru'].lower() else '#1f77b4' for r in results]

    def plot_metric(ax, key, title, ylabel):
        data = [r.get(key, 0) for r in results]
        ax.bar(test_ids, data, color=colors, alpha=0.7)
        ax.set_title(title, fontweight='bold')
        ax.set_ylabel(ylabel)
        ax.tick_params(axis='x', rotation=45, labelsize=8)
        ax.grid(axis='y', alpha=0.3)

    plot_metric(axes[0,0], 'avg_throughput_mbps', 'Throughput', 'Mbps')
    plot_metric(axes[0,1], 'avg_jitter_ms', 'Jitter', 'ms')
    plot_metric(axes[0,2], 'avg_loss_percent', 'Loss', '%')
    plot_metric(axes[1,0], 'avg_rsrp_dbm', 'RSRP', 'dBm')
    plot_metric(axes[1,1], 'avg_rsrq_db', 'RSRQ', 'dB')
    plot_metric(axes[1,2], 'avg_sinr_db', 'SINR', 'dB')

    plt.tight_layout()
    filename = f'results_{timestamp}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"[PLOT] Saved to {filename}")
    plt.close()


def main():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*70}")
    print(f"rApp-Integrated Test Suite - {timestamp}")
    print(f"{'='*70}\n")

    # Step 1: Generate test cases
    print("[STEP 1] Generating test cases from parameter ranges...")
    test_cases = generate_test_cases_yaml()
    print(f"  Generated {len(test_cases)} test cases")

    # Step 2: Write YAML files
    print("\n[STEP 2] Writing YAML files...")
    create_test_yaml_files(test_cases)

    # Step 3: Load into rApp
    print("\n[STEP 3] Loading tests into rApp...")
    loaded_tests = load_tests_to_rapp()

    # Step 4: Execute tests
    print("\n[STEP 4] Executing tests via rApp API...")
    for test_id in loaded_tests:
        run_test_via_rapp(test_id)
        time.sleep(10)

    # Step 5: Query results
    print("\n[STEP 5] Querying results from database...")
    results = query_results_from_db()
    print(f"  Retrieved {len(results)} completed tests")

    # Step 6: Plot
    print("\n[STEP 6] Plotting results...")
    plot_test_results(results, timestamp)

    print(f"\n{'='*70}")
    print(f"Test suite complete")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
