# app.py
from flask import Flask, jsonify, request
from ue_client import UEClient
import requests
import os
import db
import time

app = Flask(__name__)
ue = UEClient()
db.init_db()

NFO_BASE = "http://192.168.8.35:8080/api/o2dms/v2"

@app.route('/nfo/deploy', methods=['POST'])
def nfo_deploy():
    """Deploy via NFO - 3 step process"""
    config = request.json

    # Step 1: Create VNF descriptor
    descriptor_payload = {
        "name": config['name'],
        "description": config.get('description', ''),
        "profile_type": config['profile_type'],
        "artifact_repo_url": config['artifact_repo_url'],
        "artifact_name": config['artifact_name'],
        "artifact_repo_branch": config.get('artifact_repo_branch', 'main'),
        "target_cluster": config['target_cluster'],
        "values": config.get('values', {})
    }

    resp = requests.post(f"{NFO_BASE}/vnf_instances/", json=descriptor_payload)
    resp.raise_for_status()
    descriptor_id = resp.json()['descriptor_id']

    # Step 2: Create deployment
    deployment_payload = {
        "descriptor": descriptor_id,
        "name": config['name']
    }

    resp = requests.post(f"{NFO_BASE}/deployments/", json=deployment_payload)
    resp.raise_for_status()
    instance_id = resp.json()['instance_id']

    # Step 3: Instantiate
    instantiate_payload = {
        "instantiation_params": config.get('instantiation_params', {})
    }

    resp = requests.post(f"{NFO_BASE}/deployments/{instance_id}/instantiate/",
                        json=instantiate_payload)
    resp.raise_for_status()

    return jsonify({
        'descriptor_id': descriptor_id,
        'instance_id': instance_id,
        'operation_id': resp.json()['vnfLcmOpOccId'],
        'state': resp.json()['operationState']
    })

@app.route('/nfo/status/<instance_id>', methods=['GET'])
def nfo_status(instance_id):
    """Get deployment status"""
    resp = requests.get(f"{NFO_BASE}/deployments/{instance_id}/")
    resp.raise_for_status()
    return jsonify(resp.json())

@app.route('/ue/status', methods=['GET'])
def ue_status():
    try:
        return jsonify({
            'attached': ue.is_attached(),
            'data_ip': ue.get_data_ip(),
            'nr_state': ue.get_nr_state(),
            'data_registration': ue.get_data_reg_state(),
            'network_type': ue.get_network_type(),
            'airplane_mode': ue.is_airplane_mode(),
            'signal': ue.get_signal(),
            'signal_level': ue.get_signal_level(),
            'cell': ue.get_cell_info(),
            'device': ue.get_device_info(),
            'android': ue.get_android_version(),
            'modem_baseband': ue.get_modem_baseband()
        })
    finally:
        ue.close()
@app.route('/ue/cells', methods=['GET'])
def ue_cells():
    """Get detected cellular stations"""
    try:
        return jsonify(ue.get_detected_cells())
    finally:
        ue.close()

@app.route('/ue/iperf', methods=['POST'])
def ue_iperf():
    try:
        data = request.json or {}
        result = ue.run_iperf(duration=data.get('duration', 20))
        return jsonify(result)
    finally:
        ue.close()
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

@app.route('/ue/airplane/toggle', methods=['POST'])
def ue_airplane_toggle():
    """Toggle airplane mode"""
    try:
        current = ue.is_airplane_mode()
        success = ue.set_airplane_mode(not current)
        return jsonify({'success': success, 'airplane_mode': not current})
    finally:
        ue.close()

@app.route('/ue/data/on', methods=['POST'])
def ue_data_on():
    """Enable mobile data"""
    try:
        success = ue.enable_mobile_data()
        return jsonify({'success': success, 'mobile_data': True})
    finally:
        ue.close()

@app.route('/ue/data/off', methods=['POST'])
def ue_data_off():
    """Disable mobile data"""
    try:
        success = ue.disable_mobile_data()
        return jsonify({'success': success, 'mobile_data': False})
    finally:
        ue.close()

# app.py - add sideload endpoints
from sideload_client import SideloadClient

sideload = SideloadClient()

@app.route('/sideload/rt_status', methods=['GET'])
def sideload_rt_status():
    """Check worker RT configuration"""
    return jsonify(sideload.get_worker_rt_status())

@app.route('/sideload/perf/start', methods=['POST'])
def sideload_perf_start():
    """Trigger perf profiling"""
    data = request.json or {}
    result = sideload.trigger_perf_record(
        duration=data.get('duration', 15),
        frequency=data.get('frequency', 99)
    )
    return jsonify(result)

@app.route('/sideload/perf/flamegraph', methods=['POST'])
def sideload_perf_flamegraph():
    """Generate flamegraph from perf data"""
    data = request.json
    svg_file = sideload.generate_flamegraph(data['perf_file'])
    return jsonify({'flamegraph': svg_file})

@app.route('/sideload/deploy', methods=['POST'])
def sideload_deploy():
    """Deploy sideload pod via NFO"""
    data = request.json

    config = {
        "name": "perf-audit",
        "profile_type": "kubernetes",
        "artifact_repo_url": data.get('repo_url'),
        "artifact_name": "perf-audit-pod",
        "target_cluster": data['cluster_id'],
        "values": {
            "nodeSelector": {"kubernetes.io/hostname": data['node_name']}
        }
    }

    resp = requests.post(f"{NFO_BASE}/vnf_instances/", json=config)
    print(resp)
    desc_id = resp.json()['id']

    resp = requests.post(f"{NFO_BASE}/deployments/",
                        json={"descriptor": desc_id, "name": f"sideload-{int(time.time())}"})
    deploy_id = resp.json()['id']

    requests.post(f"{NFO_BASE}/deployments/{deploy_id}/instantiate/",
                 json={"instantiation_params": {}})

    return jsonify({'deployment_id': deploy_id})

@app.route('/sideload/register', methods=['POST'])
def sideload_register():
    """Register sideload pod"""
    data = request.json
    db.register_sideload(
        instance_id=data['instance_id'],
        node_name=data['node_name'],
        ip_address=data['ip_address'],
        port=data.get('port', 8080)
    )
    return jsonify({'registered': True})

@app.route('/sideload/list', methods=['GET'])
def sideload_list():
    """List registered sideloads"""
    return jsonify(db.get_history('sideload_registry'))

@app.route('/ue/radio/log/enable', methods=['POST'])
def ue_radio_log_enable():
    """Enable radio logging"""
    try:
        success = ue.enable_radio_logging()
        return jsonify({'enabled': success})
    finally:
        ue.close()

@app.route('/ue/radio/log/disable', methods=['POST'])
def ue_radio_log_disable():
    """Disable radio logging"""
    try:
        success = ue.disable_radio_logging()
        return jsonify({'disabled': success})
    finally:
        ue.close()

@app.route('/ue/radio/log/capture', methods=['POST'])
def ue_radio_log_capture():
    """Capture radio log"""
    try:
        data = request.json or {}
        duration = data.get('duration', 10)
        log = ue.capture_radio_log(duration)

        if log:
            # Save to file
            import os
            os.makedirs('logs', exist_ok=True)
            filename = f"logs/radio_log_{int(time.time())}.txt"
            with open(filename, 'w') as f:
                f.write(log)
            return jsonify({'log_file': filename, 'log_preview': log[:500]})
        else:
            return jsonify({'error': 'failed to capture log'}), 500
    finally:
        ue.close()

@app.route('/ue/connectivity', methods=['GET'])
def ue_connectivity():
    """Get connectivity state"""
    try:
        return jsonify(ue.get_connectivity_state())
    finally:
        ue.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
