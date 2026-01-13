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

NFO_BASE = os.getenv("NFO_BASE_URL", "")
RAPP_URL = os.getenv("RAPP_URL", "")
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

@app.route('/ue/airplane/on', methods=['POST'])
def ue_airplane_on():
    """Enable airplane mode"""
    try:
        success = ue.enable_airplane_mode()
        return jsonify({'success': success, 'airplane_mode': True})
    finally:
        ue.close()

@app.route('/ue/airplane/off', methods=['POST'])
def ue_airplane_off():
    """Disable airplane mode"""
    try:
        success = ue.disable_airplane_mode()
        return jsonify({'success': success, 'airplane_mode': False})
    finally:
        ue.close()

def terminate_gnb(instance_id):
    """Terminate gNB deployment"""
    try:
        resp = requests.post(f"{NFO_BASE}/deployments/{instance_id}/terminate/", timeout=60)
        print(f"[DEBUG] Termination: {resp.json()}")
    except Exception as e:
        print(f"[ERROR] Termination failed: {e}")


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


# ========== NFO ENDPOINTS ==========

@app.route("/nfo/deploy", methods=["POST"])
def nfo_deploy():
    """Deploy via NFO"""
    config = request.json
    result = deploy_via_nfo(config)
    return jsonify(result)


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
def ue_iperf():
    try:
        data = request.json or {}
        result = ue.run_iperf(
            bitrate=data.get("bitrate", 10),
            duration=data.get("duration", 20)
        )
        return jsonify(result)
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
def sideload_list():
    """List all registered sideloads"""
    return jsonify(db.get_all_sideloads())


@app.route("/sideload/report/<instance_id>", methods=["GET"])
def sideload_report(instance_id):
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


# ========== TEIV ENDPOINTS ==========

@app.route("/teiv/sync", methods=["POST"])
def teiv_sync():
    """Refresh TEIV cache"""
    count = teiv.load_cache()

    for record in teiv.to_db_format():
        db.upsert_teiv_cache(
            record["entity_type"],
            record["entity_urn"],
            record["attributes_json"]
        )

    return jsonify({"status": "OK", "entities": count})


@app.route("/teiv/odus", methods=["GET"])
def teiv_list_odus():
    """List all ODUs from TEIV"""
    return jsonify({"odus": teiv.list_odus()})


@app.route("/teiv/sync_to_influx", methods=["POST"])
def teiv_sync_to_influx():
    """Sync TEIV topology to InfluxDB"""
    count = teiv.load_cache()

    entities = []
    for entity_urn, entity_data in teiv.cache.items():
        entity_type = entity_data.get("type")
        data = entity_data.get("data", {})
        attributes = data.get("attributes", {})

        if entity_type == "ODU":
            entities.append({
                "type": "ODUFunction",
                "urn": entity_urn,
                "attributes": attributes
            })
        elif entity_type == "Cell":
            entities.append({
                "type": "NRCellDU",
                "urn": entity_urn,
                "attributes": attributes
            })

    try:
        if entities:
            influx.write_teiv_snapshot(entities)

        return jsonify({
            "status": "OK",
            "entities_synced": len(entities),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ========== TEST EXECUTION ==========

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
                    test.get("target", {}).get("oduUrn"),
                    json.dumps(test.get("parameters", {})),
                )
                loaded.append(test["testId"])

    return jsonify({"loaded": loaded, "count": len(loaded)})


@app.route("/tests/list", methods=["GET"])
def tests_list():
    """List all test cases"""
    rows = db.list_test_cases()
    return jsonify({
        "tests": [{"testId": r[0], "testType": r[1], "targetOdu": r[2]} for r in rows]
    })


@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    return jsonify({"status": "healthy"}), 200


@app.route("/tests/run/<test_id>", methods=["POST"])
def tests_run(test_id):
    """Execute test case"""
    row = db.get_test_case(test_id)
    if not row:
        return jsonify({"error": "Test not found"}), 404

    with open(row[0]) as f:
        test_case = yaml.safe_load(f)

    # Optional TEIV lookup for metadata
    odu_name = test_case.get("target", {}).get("oduName", "unknown")
    if test_case.get("target", {}).get("oduUrn"):
        odu = teiv.get_odu(test_case["target"]["oduUrn"])
        if odu:
            odu_name = odu.get("attributes", {}).get("gNBDUName", odu_name)

    params = test_case.get("parameters", {})
    param_permutations = generate_permutations(params)

    results = []
    for param_set in param_permutations:
        result = execute_single_test(test_case, odu_name, param_set, test_id)
        results.append(result)

    return jsonify({"status": "OK", "results": results})


def generate_permutations(params):
    """Generate all permutations from parameter arrays"""
    keys = []
    value_lists = []

    for key, value in params.items():
        keys.append(key)
        if isinstance(value, list):
            value_lists.append(value)
        else:
            value_lists.append([value])

    permutations = []
    for values in product(*value_lists):
        permutations.append(dict(zip(keys, values)))

    return permutations


def execute_single_test(test_case, odu_name, param_set, test_id):
    """Execute single test run"""

    # Build Helm values from test case
    helm_values = {
        "config": test_case.get("config", {}),
        "resources": {
            "define": True,
            "limits": {"nf": test_case.get("baseline", {})},
            "requests": {"nf": test_case.get("baseline", {})},
        },
    }

    if test_case.get("extra"):
        helm_values["config"].update(test_case["extra"])

    # Override with parameter set
    helm_values["config"].update(param_set)

    nfo_config = {
        "name": f"test-{test_id}-{int(time.time())}",
        "description": test_case.get("description", ""),
        "profile_type": "kubernetes",
        "artifact_repo_url": test_case["target"]["artifactRepoUrl"],
        "artifact_name": test_case["target"]["artifactName"],
        "artifact_repo_branch": test_case["target"]["branch"],
        "target_cluster": test_case["target"]["cluster"],
        "values": helm_values,
    }

    deployment = deploy_via_nfo(nfo_config)

    if not deployment.get("instance_id"):
        return {"error": "Deployment failed", "parameters": param_set}

    exec_id = db.record_test_start(
        test_id=test_id,
        gnb_instance_id=deployment["instance_id"],
        sideload_instance_id=test_case.get("target", {}).get("sideloadInstanceId"),
        oru_vendor=odu_name,
    )

    time.sleep(test_case.get("execution", {}).get("stabilizationTime", 30))

    results = []
    sideload_instance_id = test_case.get("target", {}).get("sideloadInstanceId")
    iperf_duration = test_case.get("execution", {}).get("iperfDuration", 10)
    monitor_duration = iperf_duration + 2
    runs_per_case = test_case.get("execution", {}).get("runsPerCase", 3)

    for run in range(runs_per_case):
        print(f"[DEBUG] Run {run + 1}/{runs_per_case}")

        toggle_airplane_mode()

        attached, ue_status = check_ue_status()
        if not attached or not ue_status or "signal" not in ue_status:
            print("[WARN] UE not attached, skipping run")
            continue

        # Start monitoring
        monitoring_results = {
            "cpu_thread": {"data": None},
            "cpu_core": {"data": None},
            "memory": {"data": None},
            "disk": {"data": None},
            "hugepages": {"data": None},
        }

        if sideload_instance_id:
            sideload_info = db.get_sideload_ip(sideload_instance_id)
            if sideload_info:
                sideload_url = f"http://{sideload_info['ip_address']}:{sideload_info['port']}"
                start_monitoring(sideload_url, monitor_duration, monitoring_results)

        # Run iperf
        bandwidth_mbps = param_set.get("iperf_bandwidth_mbps", 50)
        iperf = run_iperf_test(bandwidth_mbps=bandwidth_mbps, duration=iperf_duration)
        if not iperf:
            print("[WARN] iperf failed, skipping run")
            continue

        signal = ue_status.get("signal", {}) or {}

        results.append({
            "throughput": iperf["throughput_mbps"],
            "jitter": iperf["jitter_ms"],
            "loss": iperf["lost_percent"],
            "rsrp": signal.get("rsrp", 0),
            "rsrq": signal.get("rsrq", 0),
            "sinr": signal.get("sinr", 0),
            "cpu_thread_data": monitoring_results["cpu_thread"]["data"],
            "cpu_core_data": monitoring_results["cpu_core"]["data"],
            "memory_data": monitoring_results["memory"]["data"],
            "disk_data": monitoring_results["disk"]["data"],
            "hugepages_data": monitoring_results["hugepages"]["data"],
        })

        # Write monitoring to InfluxDB
        write_monitoring_to_influx(test_id, exec_id, run, odu_name, monitoring_results)

        time.sleep(3)

    # Aggregate and record results
    if results:
        avg_results = compute_averages(results)

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

        influx.write_test_execution(
            test_id=test_id,
            execution_id=exec_id,
            oru_vendor=odu_name,
            results=avg_results,
        )

        db.update_test_status(exec_id, "completed")
    else:
        avg_results = {"successful_runs": 0}
        db.update_test_status(exec_id, "failed")

    terminate_gnb(deployment["instance_id"])

    return {
        "parameters": param_set,
        "status": "completed",
        "execution_id": exec_id,
        "results": avg_results,
    }


def start_monitoring(sideload_url, duration, results_dict):
    """Start monitoring threads"""

    def fetch_cpu_thread():
        try:
            resp = requests.post(
                f"{sideload_url}/perf/thread_cpu_monitor",
                json={"duration": duration, "pgrep": "softmodem"},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                results_dict["cpu_thread"]["data"] = resp.json()
        except Exception as e:
            print(f"[WARN] Thread CPU failed: {e}")

    def fetch_cpu_cores():
        try:
            resp = requests.post(
                f"{sideload_url}/cpu/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                results_dict["cpu_core"]["data"] = resp.json()
        except Exception as e:
            print(f"[WARN] CPU core failed: {e}")

    def fetch_memory():
        try:
            resp = requests.post(
                f"{sideload_url}/memory/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                results_dict["memory"]["data"] = resp.json()
        except Exception as e:
            print(f"[WARN] Memory failed: {e}")

    def fetch_disk():
        try:
            resp = requests.post(
                f"{sideload_url}/disk/monitor",
                json={"device": "sda", "duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                results_dict["disk"]["data"] = resp.json()
        except Exception as e:
            print(f"[WARN] Disk failed: {e}")

    def fetch_hugepages():
        try:
            resp = requests.post(
                f"{sideload_url}/hugepages/monitor",
                json={"duration": duration},
                timeout=duration + 10,
            )
            if resp.status_code == 200:
                results_dict["hugepages"]["data"] = resp.json()
        except Exception as e:
            print(f"[WARN] Hugepages failed: {e}")

    threads = [
        threading.Thread(target=fetch_cpu_thread, daemon=True),
        threading.Thread(target=fetch_cpu_cores, daemon=True),
        threading.Thread(target=fetch_memory, daemon=True),
        threading.Thread(target=fetch_disk, daemon=True),
        threading.Thread(target=fetch_hugepages, daemon=True),
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=duration + 10)


def write_monitoring_to_influx(test_id, exec_id, run_id, oru_vendor, monitoring_results):
    """Write monitoring data to InfluxDB"""

    # Thread CPU
    cpu_thread_data = monitoring_results["cpu_thread"]["data"]
    if cpu_thread_data and cpu_thread_data.get("threads"):
        for thread in cpu_thread_data["threads"]:
            try:
                influx.write_thread_cpu_sample(
                    test_id=test_id,
                    execution_id=exec_id,
                    run_id=run_id,
                    oru_vendor=oru_vendor,
                    thread_name=thread["name"],
                    cpu_percent=thread["avg_cpu"],
                    core=thread.get("core"),
                )
            except Exception as e:
                print(f"[WARN] Thread write failed: {e}")

    # Other monitoring
    try:
        if monitoring_results["cpu_core"]["data"]:
            influx.write_cpu_monitor(test_id, exec_id, run_id, monitoring_results["cpu_core"]["data"])

        if monitoring_results["memory"]["data"]:
            influx.write_memory_monitor(test_id, exec_id, run_id, monitoring_results["memory"]["data"])

        if monitoring_results["disk"]["data"]:
            influx.write_disk_monitor(test_id, exec_id, run_id, monitoring_results["disk"]["data"])

        if monitoring_results["hugepages"]["data"]:
            influx.write_hugepages_monitor(test_id, exec_id, run_id, monitoring_results["hugepages"]["data"])
    except Exception as e:
        print(f"[WARN] InfluxDB write failed: {e}")


def compute_averages(results):
    """Compute average metrics"""
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

    return avg_results


@app.route("/tests/results", methods=["GET"])
def tests_results():
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
