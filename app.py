# app.py
import json
import os
import threading
import time
import uuid
from datetime import datetime
from itertools import product
from pathlib import Path

import numpy as np
import requests
import yaml
from flask import Flask, jsonify, request

import db
from ue_client import UEClient

db.init_db()
app = Flask(__name__)
ue = UEClient()

NFO_BASE = os.getenv("NFO_BASE_URL", "")
RAPP_URL = os.getenv("RAPP_URL", "")
TEST_CASES_DIR = "test_cases"
RESULTS_DIR = Path("test_results")
RESULTS_DIR.mkdir(exist_ok=True)


def save_execution_results(test_id, exec_id, param_set, data):
    """Save raw execution results to JSON file with parameter naming"""
    param_suffix = "_".join([f"{k}_{v}" for k, v in sorted(param_set.items())])
    filepath = RESULTS_DIR / f"exec_{exec_id}_{test_id}_{param_suffix}_{int(time.time())}.json"

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    return str(filepath)


def check_ue_status():
    """Check UE attachment status"""
    try:
        resp = requests.get(f"{RAPP_URL}/ue/status", timeout=10)
        if resp.status_code == 200:
            s = resp.json()
            return s.get("attached", False) and s.get("data_ip") is not None, s
    except:
        pass
    return False, None


def run_iperf_test(bandwidth_mbps=50, duration=10):
    """Execute iperf throughput test and capture detailed timeseries"""
    try:
        result = ue.run_iperf(bitrate=bandwidth_mbps, duration=duration)

        if not result or "end" not in result:
            return None

        summary = result["end"]["sum"]

        timeseries = {
            "timestamps": [],
            "throughput_mbps": [],
            "jitter_ms": [],
            "lost_percent": []
        }

        if "intervals" in result:
            for interval in result["intervals"]:
                data = interval.get("sum", {})
                timeseries["timestamps"].append(data.get("end", 0))
                bps = data.get("bits_per_second", 0)
                timeseries["throughput_mbps"].append(bps / 1_000_000)
                timeseries["jitter_ms"].append(data.get("jitter_ms", 0))
                timeseries["lost_percent"].append(data.get("lost_percent", 0))

        return {
            "throughput_mbps": summary.get("bits_per_second", 0) / 1_000_000,
            "jitter_ms": summary.get("jitter_ms", 0),
            "lost_percent": summary.get("lost_percent", 0),
            "timeseries": timeseries
        }

    except Exception as e:
        print(f"[ERROR] iperf failed: {e}")
        return None


def toggle_airplane_mode():
    """Cycle airplane mode to force reattachment"""
    try:
        requests.post(f"{RAPP_URL}/ue/airplane/on", timeout=10)
        time.sleep(2)
        requests.post(f"{RAPP_URL}/ue/airplane/off", timeout=10)
        time.sleep(5)
    except:
        pass


def terminate_gnb(instance_id):
    """Terminate gNB deployment"""
    try:
        resp = requests.post(f"{NFO_BASE}/deployments/{instance_id}/terminate/", timeout=60)
        print(f"[INFO] Termination: {resp.json()}")
    except Exception as e:
        print(f"[ERROR] Termination failed: {e}")


def deploy_via_nfo(config):
    """Internal function to deploy via NFO"""
    descriptor_payload = {
        "name": config["name"],
        "description": config.get("description", ""),
        "profile_type": config["profile_type"],
        "artifact_repo_url": config["artifact_repo_url"],
        "artifact_name": config["artifact_name"],
        "artifact_repo_branch": config.get("artifact_repo_branch", "main"),
        "target_cluster": config["target_cluster"],
        "values": config.get("values", {}),
    }

    resp = requests.post(f"{NFO_BASE}/vnf_instances/", json=descriptor_payload)
    resp.raise_for_status()
    descriptor_id = resp.json()["descriptor_id"]

    deployment_payload = {"descriptor": descriptor_id, "name": config["name"]}

    resp = requests.post(f"{NFO_BASE}/deployments/", json=deployment_payload)
    resp.raise_for_status()
    instance_id = resp.json()["instance_id"]

    instantiate_payload = {
        "instantiation_params": config.get("instantiation_params", {"namespace": "oai-test"})
    }

    resp = requests.post(
        f"{NFO_BASE}/deployments/{instance_id}/instantiate/", json=instantiate_payload
    )
    resp.raise_for_status()

    return {
        "descriptor_id": descriptor_id,
        "instance_id": instance_id,
        "operation_id": resp.json()["vnfLcmOpOccId"],
        "state": resp.json()["operationState"],
    }


def generate_permutations(nf_list):
    """Generate parameter permutations considering multi-NF structure"""
    all_params = {}

    for nf in nf_list:
        if "parameters" in nf:
            for key, value in nf["parameters"].items():
                if key in all_params:
                    print(f"[WARN] Parameter '{key}' defined in multiple NFs")
                all_params[key] = value

    if not all_params:
        return [{}]

    keys = []
    value_lists = []

    for key, value in all_params.items():
        keys.append(key)
        if isinstance(value, list):
            value_lists.append(value)
        else:
            value_lists.append([value])

    permutations = []
    for values in product(*value_lists):
        permutations.append(dict(zip(keys, values)))

    return permutations


def fetch_sideload_metrics(sideload_url, duration, test_id, exec_id, run_idx, param_set, ptp_interface=None):
    """Fetch all metrics from sideload and save raw dumps"""

    param_suffix = "_".join([f"{k}_{v}" for k, v in sorted(param_set.items())])
    metrics_dir = RESULTS_DIR / "sideload_dumps" / test_id / param_suffix / str(exec_id)
    metrics_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "cpu_thread": {"data": None, "raw_file": None, "status": None},
        "cpu_core": {"data": None, "raw_file": None, "status": None},
        "memory": {"data": None, "raw_file": None, "status": None},
        "disk": {"data": None, "raw_file": None, "status": None},
        "hugepages": {"data": None, "raw_file": None, "status": None},
        "power": {"data": None, "raw_file": None, "status": None},
        "network": {"data": None, "raw_file": None, "status": None},
        "ptp": {"data": None, "raw_file": None, "status": None},
    }

    def fetch_cpu_thread():
        try:
            resp = requests.post(
                f"{sideload_url}/process/threads",
                json={"duration": duration, "pgrep": "softmodem"},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["cpu_thread"]["data"] = data
                results["cpu_thread"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_cpu_thread.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["cpu_thread"]["raw_file"] = str(raw_file)
            else:
                results["cpu_thread"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["cpu_thread"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] Thread CPU failed: {e}")

    def fetch_cpu_cores():
        try:
            resp = requests.post(
                f"{sideload_url}/cpu/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["cpu_core"]["data"] = data
                results["cpu_core"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_cpu_core.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["cpu_core"]["raw_file"] = str(raw_file)
            else:
                results["cpu_core"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["cpu_core"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] CPU core failed: {e}")

    def fetch_memory():
        try:
            resp = requests.post(
                f"{sideload_url}/memory/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["memory"]["data"] = data
                results["memory"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_memory.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["memory"]["raw_file"] = str(raw_file)
            else:
                results["memory"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["memory"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] Memory failed: {e}")

    def fetch_disk():
        try:
            resp = requests.post(
                f"{sideload_url}/disk/monitor",
                json={"device": "sda", "duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["disk"]["data"] = data
                results["disk"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_disk.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["disk"]["raw_file"] = str(raw_file)
            else:
                results["disk"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["disk"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] Disk failed: {e}")

    def fetch_hugepages():
        try:
            resp = requests.post(
                f"{sideload_url}/hugepages/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["hugepages"]["data"] = data
                results["hugepages"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_hugepages.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["hugepages"]["raw_file"] = str(raw_file)
            else:
                results["hugepages"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["hugepages"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] Hugepages failed: {e}")

    def fetch_power():
        try:
            resp = requests.post(
                f"{sideload_url}/power/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["power"]["data"] = data
                results["power"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_power.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["power"]["raw_file"] = str(raw_file)
            else:
                results["power"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["power"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] Power failed: {e}")

    def fetch_network():
        try:
            resp = requests.post(
                f"{sideload_url}/network/monitor",
                json={"duration": duration, "interfaces": ["all"]},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["network"]["data"] = data
                results["network"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_network.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["network"]["raw_file"] = str(raw_file)
            else:
                results["network"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["network"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] Network failed: {e}")

    def fetch_ptp():
        if not ptp_interface:
            return

        try:
            resp = requests.post(
                f"{sideload_url}/ptp/monitor",
                json={"duration": duration, "interface": ptp_interface, "include_timeseries": True},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                results["ptp"]["data"] = data
                results["ptp"]["status"] = "SUCCESS"

                raw_file = metrics_dir / f"run_{run_idx}_ptp.json"
                with open(raw_file, 'w') as f:
                    json.dump(data, f, indent=2)
                results["ptp"]["raw_file"] = str(raw_file)
            else:
                results["ptp"]["status"] = f"FAIL_HTTP_{resp.status_code}"
        except Exception as e:
            results["ptp"]["status"] = f"ERROR_{str(e)}"
            print(f"[ERROR] PTP failed: {e}")

    threads = [
        threading.Thread(target=fetch_cpu_thread, daemon=True),
        threading.Thread(target=fetch_cpu_cores, daemon=True),
        threading.Thread(target=fetch_memory, daemon=True),
        threading.Thread(target=fetch_disk, daemon=True),
        threading.Thread(target=fetch_hugepages, daemon=True),
        threading.Thread(target=fetch_power, daemon=True),
        threading.Thread(target=fetch_network, daemon=True),
        threading.Thread(target=fetch_ptp, daemon=True),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=duration + 15)

    summary = {
        "total_metrics": len(results),
        "successful": sum(1 for r in results.values() if r["status"] == "SUCCESS"),
        "failed": sum(1 for r in results.values() if r["status"] and r["status"] != "SUCCESS"),
    }

    print(f"[INFO] Sideload metrics: {summary['successful']}/{summary['total_metrics']} successful")

    return results, summary


def collect_test_runs(test_case, param_set, exec_id, test_id):
    """Collect data from all test runs"""
    target = test_case.get("target", {})
    execution = test_case.get("execution", {})

    sideload_instance_id = target.get("sideloadInstanceId")
    ptp_interface = target.get("ptpInterface")
    iperf_duration = execution.get("iperfDuration", 10)
    monitor_duration = iperf_duration + 2
    runs_per_case = execution.get("runsPerCase", 3)

    sideload_url = None
    sideload_metadata = None

    if sideload_instance_id:
        sideload_info = db.get_sideload_ip(sideload_instance_id)
        if sideload_info:
            sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"
            sideload_metadata = {
                "instance_id": sideload_instance_id,
                "node_name": sideload_info.get("node_name"),
                "ip_address": sideload_info.get("ip_address"),
                "port": sideload_info.get("port"),
            }

            try:
                rt_resp = requests.get(f"{sideload_url}/report", timeout=10)
                if rt_resp.status_code == 200:
                    sideload_metadata["rt_config"] = rt_resp.json().get("rt_config", {})
            except Exception as e:
                print(f"[WARN] Failed to fetch RT config: {e}")

    runs = []

    for run_idx in range(runs_per_case):
        print(f"[INFO] Run {run_idx + 1}/{runs_per_case}")

        toggle_airplane_mode()

        attached, ue_status = check_ue_status()
        if not attached or not ue_status:
            print("[WARN] UE not attached")
            continue

        monitoring_results = {}
        monitoring_summary = {}

        if sideload_url:
            monitoring_results, monitoring_summary = fetch_sideload_metrics(
                sideload_url, monitor_duration, test_id, exec_id, run_idx, param_set, ptp_interface=ptp_interface
            )

        bandwidth_mbps = param_set.get("iperf_bandwidth_mbps", 50)
        iperf_result = run_iperf_test(bandwidth_mbps=bandwidth_mbps, duration=iperf_duration)

        if not iperf_result:
            print("[WARN] iperf failed")
            continue

        runs.append({
            "run_id": run_idx,
            "timestamp": datetime.utcnow().isoformat(),
            "ue_status": ue_status,
            "iperf": iperf_result,
            "monitoring": monitoring_results,
            "monitoring_summary": monitoring_summary,
        })

        time.sleep(3)

    return {
        "execution_id": exec_id,
        "sideload_url": sideload_url,
        "sideload_metadata": sideload_metadata,
        "parameters": param_set,
        "runs": runs,
        "total_runs": runs_per_case,
        "successful_runs": len(runs),
    }


def compute_averages(runs):
    """Compute average metrics from runs"""
    if not runs:
        return {}

    throughputs = []
    jitters = []
    losses = []
    rsrps = []
    rsrqs = []
    sinrs = []

    for run in runs:
        iperf = run.get("iperf", {})
        throughputs.append(iperf.get("throughput_mbps", 0))
        jitters.append(iperf.get("jitter_ms", 0))
        losses.append(iperf.get("lost_percent", 0))

        ue_status = run.get("ue_status", {})
        signal = ue_status.get("signal", {}) or {}
        rsrps.append(signal.get("rsrp", 0))
        rsrqs.append(signal.get("rsrq", 0))
        sinrs.append(signal.get("sinr", 0))

    avg_results = {
        "successful_runs": len(runs),
        "avg_throughput_mbps": float(np.mean(throughputs)),
        "avg_jitter_ms": float(np.mean(jitters)),
        "avg_loss_percent": float(np.mean(losses)),
        "avg_rsrp_dbm": float(np.mean(rsrps)),
        "avg_rsrq_db": float(np.mean(rsrqs)),
        "avg_sinr_db": float(np.mean(sinrs)),
    }

    cpu_breakdown = {}
    cpu_runs = 0

    for run in runs:
        monitoring = run.get("monitoring", {})
        cpu_thread = monitoring.get("cpu_thread")

        if cpu_thread and cpu_thread.get("threads"):
            cpu_runs += 1
            for thread in cpu_thread["threads"]:
                name = thread["name"]
                cpu_breakdown[name] = cpu_breakdown.get(name, 0) + thread["avg_cpu"]

    if cpu_runs > 0:
        for name in cpu_breakdown:
            cpu_breakdown[name] /= cpu_runs
        avg_results["avg_cpu_percent"] = sum(cpu_breakdown.values())
        avg_results["cpu_breakdown"] = cpu_breakdown

    return avg_results


def build_helm_values(nf_config, param_set, image_config):
    """Build Helm values for a single NF deployment"""
    # Start with baseline resources
    baseline_resources = nf_config.get("baseline", {}).copy()
    
    # Update baseline resources with parameter values if they exist
    if nf_config.get("parameters"):
        for key in nf_config["parameters"].keys():
            if key in param_set:
                baseline_resources[key] = param_set[key]
    
    helm_values = {
        "config": {},
        "resources": {
            "define": True,
            "limits": {"nf": baseline_resources},
            "requests": {"nf": baseline_resources.copy()},
        },
    }

    # NF-level image overrides top-level image
    # Translate to nfimage structure expected by Helm charts
    image_source = nf_config.get("image") or image_config
    if image_source:
        helm_values["nfimage"] = {
            "repository": image_source.get("repository", ""),
            "version": image_source.get("version", "latest")
        }

    if nf_config.get("extra"):
        helm_values["config"].update(nf_config["extra"])

    if nf_config.get("parameters"):
        for key in nf_config["parameters"].keys():
            if key in param_set:
                helm_values["config"][key] = param_set[key]

    return helm_values


def execute_single_test(test_case, param_set, test_id):
    """Execute single test run with multi-NF deployment"""

    start_time = time.time()
    nf_list = test_case.get("nf", [])
    if not nf_list:
        return {"error": "No NF definitions in test case", "parameters": param_set}

    target = test_case.get("target", {})
    image_config = test_case.get("image")

    deployments = []
    instance_ids = []

    for nf_config in nf_list:
        helm_values = build_helm_values(nf_config, param_set, image_config)

        nfo_config = {
            "name": f"test-{test_id}-{nf_config['artifactName']}-{int(time.time())}",
            "description": test_case.get("description", ""),
            "profile_type": "kubernetes",
            "artifact_repo_url": nf_config["artifactRepoUrl"],
            "artifact_name": nf_config["artifactName"],
            "artifact_repo_branch": nf_config.get("branch", "main"),
            "target_cluster": target.get("cluster"),
            "values": helm_values,
        }

        try:
            deployment = deploy_via_nfo(nfo_config)
            deployments.append({
                "nf_name": nf_config["artifactName"],
                "deployment": deployment
            })
            instance_ids.append(deployment["instance_id"])
            print(f"[SUCCESS] Deployed {nf_config['artifactName']}: {deployment['instance_id']}")
        except Exception as e:
            print(f"[ERROR] Failed to deploy {nf_config['artifactName']}: {e}")
            for prev_deployment in deployments:
                terminate_gnb(prev_deployment["deployment"]["instance_id"])
            return {
                "error": f"Deployment failed for {nf_config['artifactName']}: {e}",
                "parameters": param_set,
                "status": "deployment_failed",
                "execution_id": None,
                "execution_time": 0,
                "partial_deployments": deployments
            }

    primary_instance_id = instance_ids[0] if instance_ids else None
    oru_vendor = target.get("oduUrn", "unknown")

    exec_id = db.record_test_start(
        test_id=test_id,
        gnb_instance_id=primary_instance_id,
        sideload_instance_id=target.get("sideloadInstanceId"),
        oru_vendor=oru_vendor,
    )

    stabilization_time = test_case.get("execution", {}).get("stabilizationTime", 30)
    print(f"[INFO] Waiting {stabilization_time}s for stabilization")
    time.sleep(stabilization_time)

    run_results = collect_test_runs(test_case, param_set, exec_id, test_id)

    if run_results["runs"]:
        avg_results = compute_averages(run_results["runs"])
        db.record_test_results(
            exec_id,
            len(run_results["runs"]),
            avg_results["avg_throughput_mbps"],
            avg_results["avg_jitter_ms"],
            avg_results["avg_loss_percent"],
            avg_results["avg_rsrp_dbm"],
            avg_results["avg_rsrq_db"],
            avg_results["avg_sinr_db"],
            avg_results.get("avg_cpu_percent"),
            avg_results.get("cpu_breakdown"),
        )
        db.update_test_status(exec_id, "completed")
        status = "completed"
    else:
        status = "failed"
        db.update_test_status(exec_id, status)

    for instance_id in instance_ids:
        terminate_gnb(instance_id)

    execution_time = time.time() - start_time

    execution_data = {
        "test_id": test_id,
        "execution_id": exec_id,
        "parameters": param_set,
        "status": status,
        "deployments": deployments,
        "timestamp": datetime.utcnow().isoformat(),
        "execution_time": round(execution_time, 2),
        "raw_data": run_results
    }

    filepath = save_execution_results(test_id, exec_id, param_set, execution_data)

    print(f"[DEBUG] 30s between test")
    time.sleep(30)

    return {
        "parameters": param_set,
        "status": status,
        "execution_id": exec_id,
        "deployments": deployments,
        "results_file": filepath,
        "execution_time": round(execution_time, 2),
        "raw_data": run_results
    }


# ========== NFO ENDPOINTS ==========

@app.route("/nfo/deploy", methods=["POST"])
@app.route("/nfo/<version>/deploy", methods=["POST"])
def nfo_deploy(version=None):
    """Deploy via NFO"""
    config = request.json
    result = deploy_via_nfo(config)
    return jsonify(result)


@app.route("/nfo/status/<instance_id>", methods=["GET"])
@app.route("/nfo/<version>/status/<instance_id>", methods=["GET"])
def nfo_status(instance_id, version=None):
    """Get deployment status"""
    resp = requests.get(f"{NFO_BASE}/deployments/{instance_id}/")
    resp.raise_for_status()
    return jsonify(resp.json())


# ========== UE ENDPOINTS ==========

@app.route("/ue/status", methods=["GET"])
@app.route("/ue/<version>/status", methods=["GET"])
def ue_status(version=None):
    try:
        return jsonify({
            "attached": ue.is_attached(),
            "data_ip": ue.get_data_ip(),
            "nr_state": ue.get_nr_state(),
            "data_registration": ue.get_data_reg_state(),
            "network_type": ue.get_network_type(),
            "airplane_mode": ue.is_airplane_mode(),
            "signal": ue.get_signal(),
            "signal_level": ue.get_signal_level(),
            "cell": ue.get_cell_info(),
            "device": ue.get_device_info(),
            "android": ue.get_android_version(),
            "modem_baseband": ue.get_modem_baseband(),
        })
    finally:
        ue.close()


@app.route("/ue/iperf", methods=["POST"])
@app.route("/ue/<version>/iperf", methods=["POST"])
def ue_iperf(version=None):
    try:
        data = request.json or {}
        result = ue.run_iperf(
            bitrate=data.get("bitrate", 10),
            duration=data.get("duration", 20),
            target='10.45.100.1'
        )
        return jsonify(result)
    finally:
        ue.close()


@app.route('/ue/airplane/on', methods=['POST'])
@app.route('/ue/<version>/airplane/on', methods=['POST'])
def ue_airplane_on(version=None):
    """Enable airplane mode"""
    try:
        success = ue.enable_airplane_mode()
        return jsonify({'success': success, 'airplane_mode': True})
    finally:
        ue.close()


@app.route('/ue/airplane/off', methods=['POST'])
@app.route('/ue/<version>/airplane/off', methods=['POST'])
def ue_airplane_off(version=None):
    """Disable airplane mode"""
    try:
        success = ue.disable_airplane_mode()
        return jsonify({'success': success, 'airplane_mode': False})
    finally:
        ue.close()


@app.route("/ue/airplane/toggle", methods=["POST"])
@app.route("/ue/<version>/airplane/toggle", methods=["POST"])
def ue_airplane_toggle(version=None):
    """Toggle airplane mode"""
    try:
        current = ue.is_airplane_mode()
        success = ue.set_airplane_mode(not current)
        return jsonify({"success": success, "airplane_mode": not current})
    finally:
        ue.close()


# ========== SIDELOAD ENDPOINTS ==========

@app.route("/sideload/register", methods=["POST"])
@app.route("/sideload/<version>/register", methods=["POST"])
def sideload_register(version=None):
    """Register sideload - validate all IPs, use first working"""
    data = request.json

    node_name = data["node_name"]
    ip_addresses = data.get("ip_addresses", [])
    port = data.get("port", 8080)
    rt_config = data.get("rt_config", {})

    validated_ips = []
    first_working = None

    for ip in ip_addresses:
        url = f"http://{ip}:{port}/health"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                validated_ips.append({"ip": ip, "reachable": True})
                if not first_working:
                    first_working = ip
            else:
                validated_ips.append({"ip": ip, "reachable": False})
        except:
            validated_ips.append({"ip": ip, "reachable": False})

    if not first_working:
        return jsonify({"error": "no reachable IPs"}), 400

    instance_id = str(uuid.uuid4())

    final_id = db.register_sideload(
        instance_id=instance_id,
        node_name=node_name,
        ip_address=first_working,
        port=port,
    )

    db.record_sideload_ips(final_id, validated_ips)
    db.record_sideload_rt_report(instance_id=final_id, rt_config=rt_config)

    print(f"[INFO] Sideload registered: {final_id} on {node_name}")

    return jsonify({
        "registered": True,
        "instance_id": final_id,
        "node_name": node_name,
        "validated_ip": first_working,
        "all_ips": validated_ips,
        "endpoint": f"http://{first_working}:{port}",
    })


@app.route("/sideload/list", methods=["GET"])
@app.route("/sideload/<version>/list", methods=["GET"])
def sideload_list(version=None):
    """List all registered sideloads"""
    return jsonify(db.get_all_sideloads())


@app.route("/sideload/report/<instance_id>", methods=["GET"])
@app.route("/sideload/<version>/report/<instance_id>", methods=["GET"])
def sideload_report(instance_id, version=None):
    """Get RT report from sideload"""
    sideload_info = db.get_sideload_ip(instance_id)
    if not sideload_info:
        return jsonify({"error": "sideload not found"}), 404

    sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

    try:
        resp = requests.get(f"{sideload_url}/report", timeout=10)
        fresh_data = resp.json()

        db.record_sideload_rt_report(
            instance_id=instance_id,
            rt_config=fresh_data["rt_config"]
        )

        return jsonify(fresh_data)

    except Exception as e:
        return jsonify({"error": f"failed to get metrics: {str(e)}"}), 500


# ========== New sideloader endpoint

@app.route("/sideload/measure/thread_cpu", methods=["POST"])
def sideload_measure_thread_cpu():
    """Proxy: Thread CPU usage from sideloader"""
    data = request.json or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id required"}), 400

    sideload_info = db.get_sideload_ip(instance_id)
    if not sideload_info:
        return jsonify({"error": "sideload not found"}), 404

    sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

    try:
        resp = requests.post(
            f"{sideload_url}/process/threads",
            json={
                "duration": data.get("duration", 10),
                "pgrep": data.get("pgrep", "softmodem"),
                "include_timeseries": data.get("include_timeseries", True),
            },
            timeout=data.get("duration", 10) + 10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sideload/measure/cpu", methods=["POST"])
def sideload_measure_cpu():
    """Proxy: Per-core CPU usage from sideloader"""
    data = request.json or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id required"}), 400

    sideload_info = db.get_sideload_ip(instance_id)
    if not sideload_info:
        return jsonify({"error": "sideload not found"}), 404

    sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

    try:
        resp = requests.post(
            f"{sideload_url}/cpu/monitor",
            json={
                "duration": data.get("duration", 10),
                "include_timeseries": data.get("include_timeseries", True),
            },
            timeout=data.get("duration", 10) + 10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sideload/measure/power", methods=["POST"])
def sideload_measure_power():
    """Proxy: Power consumption (RAPL + iDRAC) from sideloader"""
    data = request.json or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id required"}), 400

    sideload_info = db.get_sideload_ip(instance_id)
    if not sideload_info:
        return jsonify({"error": "sideload not found"}), 404

    sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

    try:
        resp = requests.post(
            f"{sideload_url}/power/monitor",
            json={
                "duration": data.get("duration", 10),
                "include_timeseries": data.get("include_timeseries", True),
                "idrac_ip": data.get("idrac_ip"),
                "idrac_user": data.get("idrac_user", "root"),
                "idrac_pass": data.get("idrac_pass"),
            },
            timeout=data.get("duration", 10) + 10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/sideload/measure/ptp", methods=["POST"])
def sideload_measure_ptp():
    """Proxy: PTP synchronization status from sideloader"""
    data = request.json or {}
    instance_id = data.get("instance_id")
    if not instance_id:
        return jsonify({"error": "instance_id required"}), 400

    sideload_info = db.get_sideload_ip(instance_id)
    if not sideload_info:
        return jsonify({"error": "sideload not found"}), 404

    sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

    try:
        resp = requests.post(
            f"{sideload_url}/ptp/monitor",
            json={
                "duration": data.get("duration", 10),
                "interface": data.get("interface", "eth0"),
                "include_timeseries": data.get("include_timeseries", True),
            },
            timeout=data.get("duration", 10) + 10,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== TEST EXECUTION ==========

@app.route("/tests/load", methods=["POST"])
@app.route("/tests/<version>/load", methods=["POST"])
def tests_load(version=None):
    """Load test cases from YAML files"""
    loaded = []

    for root, dirs, files in os.walk(TEST_CASES_DIR):
        for f in files:
            if f.endswith(".yaml"):
                filepath = os.path.join(root, f)
                with open(filepath) as fh:
                    test = yaml.safe_load(fh)

                target = test.get("target", {})
                nf_list = test.get("nf", [])

                all_params = {}
                for nf in nf_list:
                    if "parameters" in nf:
                        all_params.update(nf["parameters"])

                db.register_test_case(
                    test["testId"],
                    test["testType"],
                    filepath,
                    target.get("oduUrn"),
                    json.dumps(all_params),
                )
                loaded.append(test["testId"])

    return jsonify({"loaded": loaded, "count": len(loaded)})


@app.route("/tests/list", methods=["GET"])
@app.route("/tests/<version>/list", methods=["GET"])
def tests_list(version=None):
    """List all test cases"""
    rows = db.list_test_cases()
    return jsonify({
        "tests": [{"testId": r[0], "testType": r[1], "targetOdu": r[2]} for r in rows]
    })


@app.route("/tests/run/<test_id>", methods=["POST"])
@app.route("/tests/<version>/run/<test_id>", methods=["POST"])
def tests_run(test_id, version=None):
    """Execute test case with multi-NF deployment"""
    row = db.get_test_case(test_id)
    if not row:
        return jsonify({"error": "Test not found"}), 404

    with open(row[0]) as f:
        test_case = yaml.safe_load(f)

    nf_list = test_case.get("nf", [])
    param_permutations = generate_permutations(nf_list)

    results_summary = {
        "test_id": test_id,
        "timestamp": datetime.utcnow().isoformat(),
        "total_permutations": len(param_permutations),
        "permutations": []
    }

    for param_set in param_permutations:
        result = execute_single_test(test_case, param_set, test_id)

        # Breathe Time between deployment
        time.sleep(3)

        results_summary["permutations"].append({
            "parameters": result.get("parameters", param_set),
            "status": result.get("status", "unknown"),
            "execution_id": result.get("execution_id"),
            "execution_time": result.get("execution_time", 0),
            "results_file": result.get("results_file"),
            "error": result.get("error")
        })

    return jsonify({
        "status": "OK",
        "summary": results_summary
    })


@app.route("/tests/results", methods=["GET"])
@app.route("/tests/<version>/results", methods=["GET"])
def tests_results(version=None):
    """Query test execution results"""
    limit = request.args.get("limit", 50, type=int)

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                te.id, te.test_id, te.timestamp, te.oru_vendor, te.status,
                tr.successful_runs, tr.avg_throughput_mbps, tr.avg_jitter_ms,
                tr.avg_loss_percent, tr.avg_rsrp_dbm, tr.avg_rsrq_db, tr.avg_sinr_db,
                tc.parameters_json
            FROM test_executions te
            LEFT JOIN test_results tr ON tr.test_execution_id = te.id
            LEFT JOIN test_cases tc ON tc.test_id = te.test_id
            ORDER BY te.timestamp DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                "execution_id": row[0],
                "test_id": row[1],
                "timestamp": row[2],
                "oru_vendor": row[3],
                "status": row[4],
                "successful_runs": row[5],
                "avg_throughput_mbps": row[6],
                "avg_jitter_ms": row[7],
                "avg_loss_percent": row[8],
                "avg_rsrp_dbm": row[9],
                "avg_rsrq_db": row[10],
                "avg_sinr_db": row[11],
                "parameters": json.loads(row[12]) if row[12] else {},
            })

        return jsonify({"results": results, "count": len(results)})


# ========== RESULTS MANAGEMENT ==========

@app.route("/results/export/<execution_id>", methods=["GET"])
@app.route("/results/<version>/export/<execution_id>", methods=["GET"])
def export_results(execution_id, version=None):
    """Export raw JSON results for processing"""
    files = list(RESULTS_DIR.glob(f"exec_{execution_id}_*.json"))
    if not files:
        return jsonify({"error": "Results not found"}), 404

    with open(files[0]) as f:
        data = json.load(f)

    return jsonify(data)


@app.route("/results/list", methods=["GET"])
@app.route("/results/<version>/list", methods=["GET"])
def list_results(version=None):
    """List all saved result files"""
    files = []
    for f in RESULTS_DIR.glob("exec_*.json"):
        files.append({
            "filename": f.name,
            "size_bytes": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        })

    return jsonify({"files": files, "count": len(files)})


@app.route("/results/analyze/<exec_id>", methods=["GET"])
@app.route("/results/<version>/analyze/<exec_id>", methods=["GET"])
def analyze_execution(exec_id, version=None):
    """Analyze execution with detailed breakdown"""
    files = list(RESULTS_DIR.glob(f"exec_{exec_id}_*.json"))
    if not files:
        return jsonify({"error": "Execution not found"}), 404

    with open(files[0]) as f:
        data = json.load(f)

    analysis = {
        "execution_id": exec_id,
        "test_id": data.get("test_id"),
        "timestamp": data.get("timestamp"),
        "permutations": [],
    }

    for perm in data.get("permutations", []):
        raw_data = perm.get("raw_data", {})

        perm_analysis = {
            "parameters": perm.get("parameters"),
            "status": perm.get("status"),
            "total_runs": raw_data.get("total_runs", 0),
            "successful_runs": raw_data.get("successful_runs", 0),
            "sideload_metadata": raw_data.get("sideload_metadata"),
            "runs_detail": []
        }

        for run in raw_data.get("runs", []):
            monitoring = run.get("monitoring", {})
            monitoring_summary = run.get("monitoring_summary", {})

            run_detail = {
                "run_id": run.get("run_id"),
                "timestamp": run.get("timestamp"),
                "iperf": run.get("iperf"),
                "signal": run.get("ue_status", {}).get("signal"),
                "monitoring_files": {
                    k: v.get("raw_file") for k, v in monitoring.items()
                    if v.get("raw_file")
                },
                "monitoring_status": {
                    k: v.get("status") for k, v in monitoring.items()
                },
                "monitoring_summary": monitoring_summary,
            }

            perm_analysis["runs_detail"].append(run_detail)

        analysis["permutations"].append(perm_analysis)

    return jsonify(analysis)


@app.route("/plot/throughput/<exec_id>", methods=["GET"])
@app.route("/plot/<version>/throughput/<exec_id>", methods=["GET"])
def plot_throughput(exec_id, version=None):
    """Get throughput timeseries for plotting"""
    files = list(RESULTS_DIR.glob(f"exec_{exec_id}_*.json"))
    if not files:
        return jsonify({"error": "Execution not found"}), 404

    with open(files[0]) as f:
        data = json.load(f)

    raw_data = data.get("raw_data", {})
    runs = raw_data.get("runs", [])

    if not runs:
        return jsonify({"error": "No run data"}), 404

    plot_data = {
        "runs": []
    }

    for run in runs:
        iperf = run.get("iperf", {})
        plot_data["runs"].append({
            "run_id": run.get("run_id"),
            "throughput_mbps": iperf.get("throughput_mbps", 0),
            "jitter_ms": iperf.get("jitter_ms", 0),
            "loss_percent": iperf.get("lost_percent", 0)
        })

    return jsonify(plot_data)


@app.route("/plot/cpu/<test_id>/<param_suffix>/<exec_id>/<run_id>", methods=["GET"])
@app.route("/plot/<version>/cpu/<test_id>/<param_suffix>/<exec_id>/<run_id>", methods=["GET"])
def plot_cpu(test_id, param_suffix, exec_id, run_id, version=None):
    """Get CPU timeseries data for plotting"""
    metrics_dir = RESULTS_DIR / "sideload_dumps" / test_id / param_suffix / exec_id
    cpu_file = metrics_dir / f"run_{run_id}_cpu_core.json"

    if not cpu_file.exists():
        return jsonify({"error": "CPU data not found"}), 404

    with open(cpu_file) as f:
        data = json.load(f)

    if "cpus" not in data:
        return jsonify({"error": "Invalid CPU data"}), 400

    plot_data = {
        "timestamps": [],
        "cpus": {}
    }

    for cpu_name, cpu_data in data["cpus"].items():
        if "usage" in cpu_data and "timeseries" in cpu_data["usage"]:
            ts = cpu_data["usage"]["timeseries"]
            plot_data["timestamps"] = ts["timestamps"]
            plot_data["cpus"][cpu_name] = ts["percent"]

    return jsonify(plot_data)


@app.route("/plot/power/<test_id>/<param_suffix>/<exec_id>/<run_id>", methods=["GET"])
@app.route("/plot/<version>/power/<test_id>/<param_suffix>/<exec_id>/<run_id>", methods=["GET"])
def plot_power(test_id, param_suffix, exec_id, run_id, version=None):
    """Get Power consumption data for plotting"""
    metrics_dir = RESULTS_DIR / "sideload_dumps" / test_id / param_suffix / exec_id
    power_file = metrics_dir / f"run_{run_id}_power.json"

    if not power_file.exists():
        return jsonify({"error": "Power data not found"}), 404

    try:
        with open(power_file) as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Corrupt power record: {str(e)}"}), 500

    return jsonify(data)


@app.route("/plot/memory/<test_id>/<param_suffix>/<exec_id>/<run_id>", methods=["GET"])
@app.route("/plot/<version>/memory/<test_id>/<param_suffix>/<exec_id>/<run_id>", methods=["GET"])
def plot_memory(test_id, param_suffix, exec_id, run_id, version=None):
    """Get Memory usage data for plotting"""
    metrics_dir = RESULTS_DIR / "sideload_dumps" / test_id / param_suffix / exec_id
    memory_file = metrics_dir / f"run_{run_id}_memory.json"

    if not memory_file.exists():
        return jsonify({"error": "Memory data not found"}), 404

    try:
        with open(memory_file) as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Corrupt memory record: {str(e)}"}), 500

    return jsonify(data)


@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({"status": "healthy"}), 200


# ========== DME ENDPOINTS ==========

@app.route("/dme/health", methods=["GET"])
def dme_health():
    """Minimal DME health endpoint for integration checks"""
    return jsonify({"status": "ok"}), 200


@app.route("/dme/info", methods=["GET"])
def dme_info():
    """Provide basic DME/rApp metadata for discovery"""
    return jsonify({
        "name": os.getenv("RAPP_NAME", "rapp-gnb-test"),
        "version": os.getenv("RAPP_VERSION", "1.0.0"),
        "endpoints": [
            {"path": "/health", "method": "GET"},
            {"path": "/dme/health", "method": "GET"}
        ]
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=True)
