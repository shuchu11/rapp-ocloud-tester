# app.py
import json
import os
import threading
import time
import uuid
from datetime import datetime
from itertools import product

import numpy as np
import requests
import yaml
from flask import Flask, jsonify, request

import db
from influx_writer import InfluxWriter
from sideload_client import SideloadClient
from teiv_client import TEIVClient
from ue_client import UEClient

influx = InfluxWriter()
teiv = TEIVClient()
db.init_db()
teiv.load_cache()

print(f"[STARTUP] Cached {len(teiv.cache)} entities")
app = Flask(__name__)
ue = UEClient()
sideload = SideloadClient()

NFO_BASE = os.getenv("NFO_BASE_URL","")
print(f"[DEBUG] NFO URL {NFO_BASE}")
RAPP_URL = os.getenv("RAPP_URL","")
TEST_CASES_DIR = "test_cases"


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
    """Execute iperf throughput test"""
    try:
        result = ue.run_iperf(bitrate=bandwidth_mbps, duration=duration)
        if not result or "end" not in result:
            return None
        return {
            "throughput_mbps": result["end"]["sum"]["bits_per_second"] / 1_000_000,
            "jitter_ms": result["end"]["sum"]["jitter_ms"],
            "lost_percent": result["end"]["sum"]["lost_percent"],
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
    terminate_request = requests.post(
        f"{NFO_BASE}/deployments/{instance_id}/terminate/", timeout=60
    )
    print(f"[DEBUG] Termination: {terminate_request.json()}")


def get_sideload_url(instance_id=None, node_name=None):
    """Get sideload URL and validate accessibility"""
    if instance_id:
        info = db.get_sideload_ip(instance_id)
    elif node_name:
        info = db.get_sideload_by_node(node_name)
    else:
        return None

    if not info:
        return None

    url = f"http://{info['ip_address']}:{info['port']}"

    try:
        resp = requests.get(f"{url}/health", timeout=5)
        return url if resp.status_code == 200 else None
    except:
        return None


# ========== NFO ENDPOINTS ==========


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
        "instantiation_params": config.get(
            "instantiation_params", {"namespace": "oai-test"}
        )
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


@app.route("/nfo/deploy", methods=["POST"])
def nfo_deploy():
    """Deploy via NFO - 3 step process"""
    config = request.json

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
        "instantiation_params": config.get(
            "instantiation_params", {"namespace": "oai-test"}
        )
    }

    resp = requests.post(
        f"{NFO_BASE}/deployments/{instance_id}/instantiate/", json=instantiate_payload
    )
    resp.raise_for_status()

    return jsonify(
        {
            "descriptor_id": descriptor_id,
            "instance_id": instance_id,
            "operation_id": resp.json()["vnfLcmOpOccId"],
            "state": resp.json()["operationState"],
        }
    )


@app.route("/nfo/status/<instance_id>", methods=["GET"])
def nfo_status(instance_id):
    """Get deployment status"""
    resp = requests.get(f"{NFO_BASE}/deployments/{instance_id}/")
    resp.raise_for_status()
    return jsonify(resp.json())


# ========== UE ENDPOINTS ==========


@app.route("/ue/status", methods=["GET"])
def ue_status():
    try:
        return jsonify(
            {
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
            }
        )
    finally:
        ue.close()


@app.route("/ue/cells", methods=["GET"])
def ue_cells():
    """Get detected cellular stations"""
    try:
        return jsonify(ue.get_detected_cells())
    finally:
        ue.close()


@app.route("/ue/connectivity", methods=["GET"])
def ue_connectivity():
    """Get connectivity state"""
    try:
        return jsonify(ue.get_connectivity_state())
    finally:
        ue.close()


@app.route("/ue/iperf", methods=["POST"])
def ue_iperf():
    try:
        data = request.json or {}
        result = ue.run_iperf(
            bitrate=data.get("bitrate", 10), duration=data.get("duration", 20)
        )
        return jsonify(result)
    finally:
        ue.close()


@app.route("/ue/airplane/on", methods=["POST"])
def ue_airplane_on():
    """Enable airplane mode"""
    try:
        success = ue.enable_airplane_mode()
        return jsonify({"success": success, "airplane_mode": True})
    finally:
        ue.close()


@app.route("/ue/airplane/off", methods=["POST"])
def ue_airplane_off():
    """Disable airplane mode"""
    try:
        success = ue.disable_airplane_mode()
        return jsonify({"success": success, "airplane_mode": False})
    finally:
        ue.close()


@app.route("/ue/airplane/toggle", methods=["POST"])
def ue_airplane_toggle():
    """Toggle airplane mode"""
    try:
        current = ue.is_airplane_mode()
        success = ue.set_airplane_mode(not current)
        return jsonify({"success": success, "airplane_mode": not current})
    finally:
        ue.close()


@app.route("/ue/data/on", methods=["POST"])
def ue_data_on():
    """Enable mobile data"""
    try:
        success = ue.enable_mobile_data()
        return jsonify({"success": success, "mobile_data": True})
    finally:
        ue.close()


@app.route("/ue/data/off", methods=["POST"])
def ue_data_off():
    """Disable mobile data"""
    try:
        success = ue.disable_mobile_data()
        return jsonify({"success": success, "mobile_data": False})
    finally:
        ue.close()


@app.route("/ue/radio/log/enable", methods=["POST"])
def ue_radio_log_enable():
    """Enable radio logging"""
    try:
        success = ue.enable_radio_logging()
        return jsonify({"enabled": success})
    finally:
        ue.close()


@app.route("/ue/radio/log/disable", methods=["POST"])
def ue_radio_log_disable():
    """Disable radio logging"""
    try:
        success = ue.disable_radio_logging()
        return jsonify({"disabled": success})
    finally:
        ue.close()


@app.route("/ue/radio/log/capture", methods=["POST"])
def ue_radio_log_capture():
    """Capture radio log"""
    try:
        data = request.json or {}
        duration = data.get("duration", 10)
        log = ue.capture_radio_log(duration)

        if log:
            os.makedirs("logs", exist_ok=True)
            filename = f"logs/radio_log_{int(time.time())}.txt"
            with open(filename, "w") as f:
                f.write(log)
            return jsonify({"log_file": filename, "log_preview": log[:500]})
        else:
            return jsonify({"error": "failed to capture log"}), 500
    finally:
        ue.close()


# ========== SIDELOAD ENDPOINTS ==========


@app.route("/sideload/register", methods=["POST"])
def sideload_register():
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

    print(f"[INFO] Sideload registered: {final_id}")
    print(f"[INFO] Node: {node_name}, Primary IP: {first_working}")
    print(
        f"[INFO] Validated: {len([ip for ip in validated_ips if ip['reachable']])}/{len(validated_ips)}"
    )

    return jsonify(
        {
            "registered": True,
            "instance_id": final_id,
            "node_name": node_name,
            "validated_ip": first_working,
            "all_ips": validated_ips,
            "endpoint": f"http://{first_working}:{port}",
        }
    )


@app.route("/sideload/list", methods=["GET"])
def sideload_list():
    """List all registered sideloads"""
    return jsonify(db.get_all_sideloads())


@app.route("/sideload/report/<instance_id>", methods=["GET"])
def sideload_report(instance_id):
    """Get RT report - triggers fresh measurement from sideload"""
    sideload_info = db.get_sideload_ip(instance_id)
    if not sideload_info:
        return jsonify({"error": "sideload not found"}), 404

    sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

    try:
        resp = requests.get(f"{sideload_url}/report", timeout=10)
        fresh_data = resp.json()

        db.record_sideload_rt_report(
            instance_id=instance_id, rt_config=fresh_data["rt_config"]
        )

        return jsonify(fresh_data)

    except Exception as e:
        return jsonify({"error": f"failed to get fresh metrics: {str(e)}"}), 500


@app.route("/sideload/rt_status", methods=["GET"])
def sideload_rt_status():
    """Check worker RT configuration"""
    return jsonify(sideload.get_worker_rt_status())


@app.route("/sideload/perf/start", methods=["POST"])
def sideload_perf_start():
    """Trigger perf profiling"""
    data = request.json or {}
    result = sideload.trigger_perf_record(
        duration=data.get("duration", 15), frequency=data.get("frequency", 99)
    )
    return jsonify(result)


@app.route("/sideload/perf/flamegraph", methods=["POST"])
def sideload_perf_flamegraph():
    """Generate flamegraph from perf data"""
    data = request.json
    svg_file = sideload.generate_flamegraph(data["perf_file"])
    return jsonify({"flamegraph": svg_file})


@app.route("/sideload/measure/context_switches", methods=["POST"])
def sideload_measure_context_switches():
    """Trigger context switch measurement"""
    data = request.json
    instance_id = data.get("instance_id")

    url = get_sideload_url(instance_id)
    if not url:
        return jsonify({"error": "sideload not found"}), 404

    resp = requests.post(f"{url}/perf/context_switches", json=data)
    result = resp.json()

    db.record_sideload_operation("context_switches", url, data, result)
    return jsonify(result)


@app.route("/sideload/measure/cpu_usage", methods=["POST"])
def sideload_measure_cpu_usage():
    """Trigger CPU usage measurement"""
    data = request.json
    instance_id = data.get("instance_id")

    url = get_sideload_url(instance_id)
    if not url:
        return jsonify({"error": "sideload not found"}), 404

    resp = requests.post(f"{url}/perf/cpu_usage", json=data)
    result = resp.json()

    db.record_sideload_operation("cpu_usage", url, data, result)
    return jsonify(result)


@app.route("/sideload/measure/offcpu", methods=["POST"])
def sideload_measure_offcpu():
    """Trigger off-CPU profiling"""
    data = request.json
    instance_id = data.get("instance_id")

    url = get_sideload_url(instance_id)
    if not url:
        return jsonify({"error": "sideload not found"}), 404

    resp = requests.post(f"{url}/perf/offcpu", json=data)
    result = resp.json()

    db.record_sideload_operation("offcpu", url, data, result)
    return jsonify(result)


@app.route("/sideload/measure/thread_cpu", methods=["POST"])
def sideload_measure_thread_cpu():
    """Trigger per-thread CPU measurement"""
    data = request.json
    instance_id = data.get("instance_id")

    url = get_sideload_url(instance_id)
    if not url:
        return jsonify({"error": "sideload not found"}), 404

    resp = requests.post(f"{url}/perf/thread_cpu_affinity", json=data)
    result = resp.json()

    db.record_sideload_operation("thread_cpu", url, data, result)
    return jsonify(result)


@app.route("/sideload/measure/latency_histogram", methods=["POST"])
def sideload_measure_latency():
    """Trigger scheduler latency measurement"""
    data = request.json
    instance_id = data.get("instance_id")

    url = get_sideload_url(instance_id)
    if not url:
        return jsonify({"error": "sideload not found"}), 404

    resp = requests.post(f"{url}/perf/latency_histogram", json=data)
    result = resp.json()

    db.record_sideload_operation("latency_histogram", url, data, result)
    return jsonify(result)


@app.route("/sideload/measure/cpu_heatmap", methods=["POST"])
def sideload_measure_cpu_heatmap():
    """Trigger CPU heatmap data collection"""
    data = request.json
    instance_id = data.get("instance_id")

    url = get_sideload_url(instance_id)
    if not url:
        return jsonify({"error": "sideload not found"}), 404

    resp = requests.post(f"{url}/perf/cpu_heatmap", json=data)
    result = resp.json()

    db.record_sideload_operation("cpu_heatmap", url, data, result)
    return jsonify(result)


# ========== TEIV ENDPOINTS ==========


@app.route("/teiv/sync", methods=["POST"])
def teiv_sync():
    """Refresh TEIV cache and store in SQLite"""
    count = teiv.load_cache()

    for record in teiv.to_db_format():
        db.upsert_teiv_cache(
            record["entity_type"], record["entity_urn"], record["attributes_json"]
        )

    return jsonify({"status": "OK", "entities": count})


@app.route("/teiv/odus", methods=["GET"])
def teiv_list_odus():
    """List all O-RUs from TEIV"""
    return jsonify({"odus": teiv.list_odus()})


# ========== TEST EXECUTION ENDPOINTS ==========


@app.route("/tests/load", methods=["POST"])
def tests_load():
    """Load test cases from YAML files"""
    loaded = []

    for root, dirs, files in os.walk(TEST_CASES_DIR):
        for f in files:
            if f.endswith(".yaml"):
                filepath = os.path.join(root, f)
                with open(filepath) as fh:
                    test = yaml.safe_load(fh)

                db.register_test_case(
                    test["testId"],
                    test["testType"],
                    filepath,
                    test["target"]["oduUrn"],
                    json.dumps(test["parameters"]),
                )
                loaded.append(test["testId"])

    return jsonify({"loaded": loaded, "count": len(loaded)})


@app.route("/tests/list", methods=["GET"])
def tests_list():
    """List all registered test cases"""
    rows = db.list_test_cases()
    return jsonify(
        {"tests": [{"testId": r[0], "testType": r[1], "targetOdu": r[2]} for r in rows]}
    )

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for K8s liveness/readiness probes"""
    try:
        # Basic sanity checks
        db_ok = db.check_connection() if hasattr(db, 'check_connection') else True
        return jsonify({
            "status": "healthy",
            "database": "ok" if db_ok else "degraded"
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e)
        }), 503

@app.route("/tests/run/<test_id>", methods=["POST"])
def tests_run(test_id):
    """Execute test case with parallel system monitoring"""
    row = db.get_test_case(test_id)
    if not row:
        return jsonify({"error": "Test not found"}), 404

    with open(row[0]) as f:
        test_case = yaml.safe_load(f)

    odu = teiv.get_odu(test_case["target"]["oduUrn"])
    print(f"[DEBUG] test_case keys: {test_case.keys()}")
    print(f"[DEBUG] target keys: {test_case['target'].keys()}")
    cell = teiv.get_cell(test_case["target"]["cellUrn"])

    print(f"[DEBUG] odu result: {odu}")
    print(f"[DEBUG] cell result: {cell}")

    if not odu or not cell:
        return jsonify({"error": "Target not found in TEIV"}), 404

    params = test_case.get("parameters", {})
    param_permutations = generate_permutations(params)

    results = []
    for param_set in param_permutations:
        print(f"[DEBUG] Current Param set: {param_set}")
        result = execute_single_test(test_case, odu, cell, param_set, test_id)
        results.append(result)

    return jsonify({"status": "OK", "results": results})


def generate_permutations(params):
    """Generate all permutations from parameter arrays"""
    # Separate scalar and array parameters
    keys = []
    value_lists = []

    for key, value in params.items():
        keys.append(key)
        if isinstance(value, list):
            value_lists.append(value)
        else:
            value_lists.append([value])  # Wrap scalar in list

    # Generate cartesian product
    permutations = []
    for values in product(*value_lists):
        permutations.append(dict(zip(keys, values)))
    print(f"[DEBUG] Permutations: {permutations}")
    return permutations


def execute_single_test(test_case, odu, cell, param_set, test_id):
    odu_attrs = odu["attributes"]
    cell_attrs = cell["attributes"]
    print(f"[DEBUG] cell_attrs: {cell_attrs}")
    print(f"[DEBUG] nRTAC value: {cell_attrs.get('nRTAC')}")

    print(f"[DEBUG] cell_attrs: {cell_attrs}")
    print(f"[DEBUG] nRTAC value: {cell_attrs.get('nRTAC')}")

    params = test_case.get("parameters", {})



    helm_values = {
        "config": {
            "mcc": odu["attributes"]["mcc"],
            "mnc": odu["attributes"]["mnc"],
            "tac": cell["attributes"]["nRTAC"],
            "physCellId": cell["attributes"]["nRPCI"],

        },
        "resources": {
            "define": True,
            "limits": {
                "nf": test_case['baseline'],
            },
            "requests": {
                "nf": test_case['baseline'],
            },
        },
    }


    if test_case['extra']:
        helm_values['config'].update(test_case['extra'])

    config = {
        "name": f"test-{test_id}",
        "description": test_case["description"],
        "profile_type": "kubernetes",
        "artifact_repo_url": "https://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@github.com/motangpuar/ocloud-helm-templates.git",
        "artifact_name": "oai-gnb-fhi-72",
        "artifact_repo_branch": teiv.get_helm_branch_for_odu(
            test_case["target"]["oduUrn"]
        ),
        "artifact_repo_branch": test_case['target']['branch'],
        "target_cluster": test_case["target"]["cluster"],
        "values": helm_values,
    }

    deployment = deploy_via_nfo(config)

    if not deployment.get("instance_id"):
        return jsonify({"error": "Deployment failed"}), 500

    exec_id = db.record_test_start(
        test_id=test_id,
        gnb_instance_id=deployment["instance_id"],
        sideload_instance_id=None,
        oru_vendor=odu_attrs.get("gNBDUName"),
    )

    time.sleep(test_case["execution"]["stabilizationTime"])

    results = []
    SIDELOAD_INSTANCE_ID = test_case.get("target", {}).get(
        "sideloadInstanceId", "be0cc18b-1b8e-4b58-a2bc-9f4681ac6142"
    )
    IPERF_DURATION = 10
    MONITOR_DURATION = IPERF_DURATION + 2

    for run in range(test_case["execution"]["runsPerCase"]):
        print(f"[DEBUG] Run {run + 1}/{test_case['execution']['runsPerCase']}")

        toggle_airplane_mode()

        attached, ue_status = check_ue_status()
        print(f"[DEBUG] UE attached: {attached}")

        if not attached or not ue_status or "signal" not in ue_status:
            print("[DEBUG] UE not attached or invalid status, skipping")
            continue

        sideload_info = db.get_sideload_ip(SIDELOAD_INSTANCE_ID)
        if not sideload_info:
            print("[WARN] Sideload not found")
            continue

        sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"

        monitoring_results = {
            "cpu_thread": {"data": None, "error": None},
            "cpu_core": {"data": None, "error": None},
            "memory": {"data": None, "error": None},
            "disk": {"data": None, "error": None},
            "hugepages": {"data": None, "error": None},
        }

        def fetch_cpu_thread():
            """Thread CPU monitoring over time"""
            try:
                print(f"[DEBUG] Thread profiling: Starting...")
                resp = requests.post(
                    f"{sideload_url}/perf/thread_cpu_monitor",  # NEW endpoint
                    json={"duration": MONITOR_DURATION, "pgrep": "softmodem"},
                    timeout=MONITOR_DURATION + 10,
                )
                if resp.status_code == 200:
                    monitoring_results["cpu_thread"]["data"] = resp.json()
                    print(f"[DEBUG] Thread profiling: Complete")
                else:
                    monitoring_results["cpu_thread"]["error"] = (
                        f"HTTP {resp.status_code}"
                    )
            except Exception as e:
                monitoring_results["cpu_thread"]["error"] = str(e)
                print(f"[WARN] Thread profiling failed: {e}")

        def fetch_cpu_cores():
            """CPU core usage monitoring"""
            try:
                print(f"[DEBUG] CPU cores: Starting...")
                resp = requests.post(
                    f"{sideload_url}/cpu/monitor",
                    json={"duration": MONITOR_DURATION},
                    timeout=MONITOR_DURATION + 10,
                )
                if resp.status_code == 200:
                    monitoring_results["cpu_core"]["data"] = resp.json()
                    print(f"[DEBUG] CPU cores: Complete")
                else:
                    monitoring_results["cpu_core"]["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                monitoring_results["cpu_core"]["error"] = str(e)
                print(f"[WARN] CPU cores failed: {e}")

        def fetch_memory():
            """Memory usage monitoring"""
            try:
                print(f"[DEBUG] Memory: Starting...")
                resp = requests.post(
                    f"{sideload_url}/memory/monitor",
                    json={"duration": MONITOR_DURATION},
                    timeout=MONITOR_DURATION + 10,
                )
                if resp.status_code == 200:
                    monitoring_results["memory"]["data"] = resp.json()
                    print(f"[DEBUG] Memory: Complete")
                else:
                    monitoring_results["memory"]["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                monitoring_results["memory"]["error"] = str(e)
                print(f"[WARN] Memory failed: {e}")

        def fetch_disk():
            """Disk I/O monitoring"""
            try:
                print(f"[DEBUG] Disk I/O: Starting...")
                resp = requests.post(
                    f"{sideload_url}/disk/monitor",
                    json={"device": "sda", "duration": MONITOR_DURATION},
                    timeout=MONITOR_DURATION + 10,
                )
                if resp.status_code == 200:
                    monitoring_results["disk"]["data"] = resp.json()
                    print(f"[DEBUG] Disk I/O: Complete")
                else:
                    monitoring_results["disk"]["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                monitoring_results["disk"]["error"] = str(e)
                print(f"[WARN] Disk I/O failed: {e}")

        def fetch_hugepages():
            """Hugepages monitoring"""
            try:
                print(f"[DEBUG] Hugepages: Starting...")
                resp = requests.post(
                    f"{sideload_url}/hugepages/monitor",
                    json={"duration": MONITOR_DURATION},
                    timeout=MONITOR_DURATION + 10,
                )
                if resp.status_code == 200:
                    monitoring_results["hugepages"]["data"] = resp.json()
                    print(f"[DEBUG] Hugepages: Complete")
                else:
                    monitoring_results["hugepages"]["error"] = (
                        f"HTTP {resp.status_code}"
                    )
            except Exception as e:
                monitoring_results["hugepages"]["error"] = str(e)
                print(f"[WARN] Hugepages failed: {e}")

        print(f"[DEBUG] Starting monitoring threads ({MONITOR_DURATION}s)")

        threads = [
            threading.Thread(target=fetch_cpu_thread, daemon=True, name="cpu-thread"),
            threading.Thread(target=fetch_cpu_cores, daemon=True, name="cpu-cores"),
            threading.Thread(target=fetch_memory, daemon=True, name="memory"),
            threading.Thread(target=fetch_disk, daemon=True, name="disk"),
            threading.Thread(target=fetch_hugepages, daemon=True, name="hugepages"),
        ]

        for t in threads:
            t.start()

        time.sleep(1)

        print(f"[DEBUG] Running iperf ({IPERF_DURATION}s)")
        bandwidth_mbps = test_case["parameters"].get("iperf_bandwidth_mbps", 50)
        iperf = run_iperf_test(bandwidth_mbps=bandwidth_mbps)
        print(f"[DEBUG] iperf complete: {iperf is not None}")

        if not iperf:
            print("[DEBUG] iperf failed, skipping")
            for t in threads:
                t.join(timeout=5)
            continue

        print(f"[DEBUG] Waiting for monitoring threads")
        for t in threads:
            t.join(timeout=MONITOR_DURATION + 10)

        cpu_thread_data = monitoring_results["cpu_thread"]["data"]
        if cpu_thread_data and cpu_thread_data.get("threads"):
            print(
                f"[DEBUG] Writing {len(cpu_thread_data['threads'])} thread samples to InfluxDB"
            )
            for thread in cpu_thread_data["threads"]:
                try:
                    influx.write_thread_cpu_sample(
                        test_id=test_id,
                        execution_id=exec_id,
                        run_id=run,
                        oru_vendor=odu_attrs.get("gNBDUName", "unknown"),
                        thread_name=thread["name"],
                        cpu_percent=thread["avg_cpu"],
                        core=thread.get(
                            "core", "unknown"
                        ),  # If sideload provides core info
                    )
                except Exception as e:
                    print(f"[WARN] Failed to write thread {thread['name']}: {e}")
        signal = ue_status.get("signal", {})
        if signal is None:
            signal = {}
            _, ue_status = check_ue_status()
            signal = ue_status.get("signal", {})

        results.append(
            {
                "throughput": iperf["throughput_mbps"],
                "jitter": iperf["jitter_ms"],
                "loss": iperf["lost_percent"],
                "rsrp": signal.get("rsrp", 0),
                "rsrq": signal.get("rsrq", 0),
                "sinr": signal.get("sinr", 0),
                "cpu_thread_data": cpu_thread_data,
                "cpu_core_data": monitoring_results["cpu_core"]["data"],
                "memory_data": monitoring_results["memory"]["data"],
                "disk_data": monitoring_results["disk"]["data"],
                "hugepages_data": monitoring_results["hugepages"]["data"],
            }
        )

        try:
            if monitoring_results["cpu_core"]["data"]:
                influx.write_cpu_monitor(
                    test_id, exec_id, run, monitoring_results["cpu_core"]["data"]
                )

            if monitoring_results["memory"]["data"]:
                influx.write_memory_monitor(
                    test_id, exec_id, run, monitoring_results["memory"]["data"]
                )

            if monitoring_results["disk"]["data"]:
                influx.write_disk_monitor(
                    test_id, exec_id, run, monitoring_results["disk"]["data"]
                )

            if monitoring_results["hugepages"]["data"]:
                influx.write_hugepages_monitor(
                    test_id, exec_id, run, monitoring_results["hugepages"]["data"]
                )

        except Exception as e:
            print(f"[WARN] InfluxDB monitoring write failed: {e}")

        print(f"[DEBUG] Run {run + 1} complete")
        time.sleep(3)

    print(f"[DEBUG] Collected {len(results)} successful runs")

    if results:
        avg_results = {
            "successful_runs": len(results),
            "avg_throughput_mbps": float(np.mean([r["throughput"] for r in results])),
            "avg_jitter_ms": float(np.mean([r["jitter"] for r in results])),
            "avg_loss_percent": float(np.mean([r["loss"] for r in results])),
            "avg_rsrp_dbm": float(np.mean([r["rsrp"] for r in results])),
            "avg_rsrq_db": float(np.mean([r["rsrq"] for r in results])),
            "avg_sinr_db": float(np.mean([r["sinr"] for r in results])),
        }

        cpu_breakdown = {}
        cpu_runs = 0

        for r in results:
            if r.get("cpu_thread_data") and r["cpu_thread_data"].get("threads"):
                cpu_runs += 1
                for thread in r["cpu_thread_data"]["threads"]:
                    name = thread["name"]
                    cpu_breakdown[name] = cpu_breakdown.get(name, 0) + thread["avg_cpu"]

        if cpu_runs > 0:
            for name in cpu_breakdown:
                cpu_breakdown[name] /= cpu_runs

            avg_results["avg_cpu_percent"] = sum(cpu_breakdown.values())
            avg_results["cpu_breakdown"] = cpu_breakdown

        db.record_test_results(
            exec_id,
            len(results),
            avg_results["avg_throughput_mbps"],
            avg_results["avg_jitter_ms"],
            avg_results["avg_loss_percent"],
            avg_results["avg_rsrp_dbm"],
            avg_results["avg_rsrq_db"],
            avg_results["avg_sinr_db"],
            avg_results.get("avg_cpu_percent"),
            avg_results.get("cpu_breakdown"),
        )

        try:
            influx.write_test_execution(
                test_id=test_id,
                execution_id=exec_id,
                oru_vendor=odu_attrs.get("gNBDUName"),
                results=avg_results,
                cpu_breakdown=avg_results.get("cpu_breakdown"),
            )
        except Exception as e:
            print(f"[WARN] InfluxDB test execution write failed: {e}")

        db.update_test_status(exec_id, "completed")
    else:
        avg_results = {"successful_runs": 0}
        db.update_test_status(exec_id, "failed")

    terminate_gnb(deployment["instance_id"])

    return {
        "parameters": param_set,
        "status": "completed",
        "execution_id": exec_id,
        "test_id": test_id,
        "results": avg_results,
    }


@app.route("/tests/results", methods=["GET"])
def tests_results():
    """Query test execution results"""
    limit = request.args.get("limit", 50)

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                te.id,
                te.test_id,
                te.timestamp,
                te.oru_vendor,
                te.status,
                tr.successful_runs,
                tr.avg_throughput_mbps,
                tr.avg_jitter_ms,
                tr.avg_loss_percent,
                tr.avg_rsrp_dbm,
                tr.avg_rsrq_db,
                tr.avg_sinr_db,
                tc.parameters_json
            FROM test_executions te
            LEFT JOIN test_results tr ON tr.test_execution_id = te.id
            LEFT JOIN test_cases tc ON tc.test_id = te.test_id
            ORDER BY te.timestamp DESC
            LIMIT ?
        """,
            (limit,),
        )

        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append(
                {
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
                }
            )

        return jsonify({"results": results, "count": len(results)})


@app.route("/teiv/sync_to_influx", methods=["POST"])
def teiv_sync_to_influx():
    """Sync TEIV data to InfluxDB for Grafana"""
    # Reload TEIV cache
    count = teiv.load_cache()

    print(f"[DEBUG] TEIV cache has {len(teiv.cache)} entries")

    entities = []

    # Iterate through cache - structure is {urn: {'type': 'ODU'/'Cell', 'data': {...}}}
    for entity_urn, entity_data in teiv.cache.items():
        entity_type = entity_data.get("type")
        data = entity_data.get("data", {})
        attributes = data.get("attributes", {})

        if entity_type == "ODU":
            entities.append(
                {"type": "ODUFunction", "urn": entity_urn, "attributes": attributes}
            )
            print(f"[DEBUG] Added ODU: {entity_urn}")
        elif entity_type == "Cell":
            entities.append(
                {"type": "NRCellDU", "urn": entity_urn, "attributes": attributes}
            )
            print(f"[DEBUG] Added Cell: {entity_urn}")

    print(f"[DEBUG] Total entities to sync: {len(entities)}")

    # Write to InfluxDB
    try:
        if entities:
            influx.write_teiv_snapshot(entities)

            # Write relationships
            odu_urns = [e["urn"] for e in entities if e["type"] == "ODUFunction"]
            cell_urns = [e["urn"] for e in entities if e["type"] == "NRCellDU"]

            for cell_urn in cell_urns:
                for odu_urn in odu_urns:
                    if "pegatron" in cell_urn.lower() and "pegatron" in odu_urn.lower():
                        influx.write_teiv_relationship(odu_urn, cell_urn)
                        break
                    elif "liteon" in cell_urn.lower() and "liteon" in odu_urn.lower():
                        influx.write_teiv_relationship(odu_urn, cell_urn)
                        break
                    elif "jura" in cell_urn.lower() and "jura" in odu_urn.lower():
                        influx.write_teiv_relationship(odu_urn, cell_urn)
                        break

        return jsonify(
            {

                "status": "OK",
                "entities_synced": len(entities),
                "odus": len([e for e in entities if e["type"] == "ODUFunction"]),
                "cells": len([e for e in entities if e["type"] == "NRCellDU"]),
                "influxdb_bucket": "test-results",
            }
        )
    except Exception as e:
        import traceback

        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
