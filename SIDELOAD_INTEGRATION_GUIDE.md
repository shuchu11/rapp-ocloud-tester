# Sideload Integration with rApp via Kong SME Gateway

**Date**: February 3, 2026  
**rApp**: rapp-gnb-test v2.0.0  
**Sideload Node**: inoue (192.168.8.60:8080)  

---

## Overview

This guide demonstrates how the **rApp (behind Kong SME gateway)** integrates with **sideload instances** for real-time system profiling and monitoring during gNB test orchestration.

### Architecture

```
┌────────────────────┐
│  Sideload Agent    │
│  (inoue node)      │
│  192.168.8.60:8080 │
└─────────┬──────────┘
          │
          │ 1. Register (R1-compliant)
          │    POST /sideload/1.0.0/register
          │
          ▼
┌──────────────────────────────────┐
│      Kong SME Gateway            │
│   192.168.8.69:32080             │
│   /gnb-test-api/.../             │
└─────────┬────────────────────────┘
          │
          │ 2. Forward to rApp
          │
          ▼
┌──────────────────────────────────┐
│  rApp (Flask)                    │
│  rapp-gnb-test:5000              │
│  • Stores sideload metadata      │
│  • Returns validated IP          │
└─────────┬────────────────────────┘
          │
          │ 3. Direct profiling
          │    (uses stored IP)
          │
          ▼
┌────────────────────┐
│  Sideload Agent    │
│  Monitoring APIs   │
│  /cpu/monitor      │
│  /memory/monitor   │
│  /disk/monitor     │
│  /power/monitor    │
│  /ptp/monitor      │
└────────────────────┘
```

---

## Phase 1: Sideload Registration (via Kong SME)

### 1.1 Sideload Configuration

The sideload agent must use the **Kong gateway URL** for R1-compliant registration:

```bash
# Sideload environment variables
export RAPP_URL="http://192.168.8.69:32080/gnb-test-api/port-5000-hash-5a42e08c-1f7e-5235-b97d-30d85c44275e"
export NODE_NAME="inoue"
export SVC_PORT="8080"

# Start sideload agent (with registration loop)
python app.py
```

### 1.2 Registration Process

The sideload's `register_loop()` calls:

```python
POST $RAPP_URL/sideload/1.0.0/register
Content-Type: application/json

{
  "node_name": "inoue",
  "ip_addresses": ["192.168.8.60", "10.244.1.5"],
  "port": 8080,
  "rt_config": {
    "isolated_cpus": "8-15",
    "tuned_profile": "cpu-partitioning"
  }
}
```

**Response:**
```json
{
  "registered": true,
  "instance_id": "e2d5b9c9-b805-4492-a702-85fec46e20be",
  "node_name": "inoue",
  "validated_ip": "192.168.8.60",
  "all_ips": [
    {"ip": "192.168.8.60", "reachable": true},
    {"ip": "10.244.1.5", "reachable": false}
  ],
  "endpoint": "http://192.168.8.60:8080"
}
```

### 1.3 Verification

List registered sideloads via Kong:

```bash
export KONG_BASE="http://192.168.8.69:32080/gnb-test-api/port-5000-hash-5a42e08c-1f7e-5235-b97d-30d85c44275e"

curl -s "$KONG_BASE/sideload/1.0.0/list" | jq
```

**Result:**
```json
[
  {
    "id": 1,
    "instance_id": "e2d5b9c9-b805-4492-a702-85fec46e20be",
    "ip_address": "192.168.8.60",
    "node_name": "inoue",
    "port": 8080,
    "status": "active",
    "registered_at": "2026-02-03T15:23:10.406196",
    "last_seen": "2026-02-03T15:23:10.406196"
  }
]
```

---

## Phase 2: Test Case Configuration

Create a test case that references the sideload instance:

```yaml
# test_cases/sideload-demo.yaml
name: gnb-test-with-sideload
description: "gNB test with real-time profiling via sideload"

target:
  oduId: "odu-test-123"
  cellId: "cell-456"
  sideloadInstanceId: "e2d5b9c9-b805-4492-a702-85fec46e20be"  # inoue node
  ptpInterface: "ens1f0"

execution:
  iperfDuration: 10        # 10s iperf test
  runsPerCase: 3           # 3 runs per parameter set
  
parameters:
  cpus:
    - 8
    - 14
  iperf_bandwidth_mbps:
    - 100
    - 400
    - 700
```

Upload via Kong:

```bash
curl -X POST "$KONG_BASE/tests/1.0.0/load" \
  -F "file=@test_cases/sideload-demo.yaml" | jq
```

---

## Phase 3: Test Execution with Profiling

When the test runs, the rApp:

1. **Retrieves sideload metadata** from database (using `sideloadInstanceId`)
2. **Constructs direct URL**: `http://192.168.8.60:8080`
3. **Starts monitoring** before iperf test
4. **Collects metrics** during test execution
5. **Saves raw dumps** to `test_results/sideload_dumps/`

### 3.1 Profiling APIs Called

The rApp calls sideload endpoints directly (bypasses Kong for performance):

#### Memory Monitoring
```bash
POST http://192.168.8.60:8080/memory/monitor
Content-Type: application/json

{
  "duration": 12,
  "include_timeseries": true
}
```

**Sample Response:**
```json
{
  "duration": 3,
  "samples": 3,
  "unit": "kB",
  "memory": {
    "total": {"avg": 131599460.0, "min": 131599460, "max": 131599460},
    "used": {"avg": 46147784.0, "min": 46146720, "max": 46149648},
    "used_percent": {"avg": 35.07, "min": 35.07, "max": 35.07},
    "available": {"avg": 86657785.33, "min": 86655932, "max": 86658844},
    "free": {"avg": 50835121.33, "min": 50833228, "max": 50836180},
    "cached": {"avg": 34612654.67, "min": 34612620, "max": 34612684},
    "buffers": {"avg": 3900.0, "min": 3900, "max": 3900},
    "slab": {"avg": 2108105.33, "min": 2108092, "max": 2108124}
  }
}
```

#### Disk I/O Monitoring
```bash
POST http://192.168.8.60:8080/disk/monitor
Content-Type: application/json

{
  "duration": 12,
  "device": "sda"
}
```

**Sample Response:**
```json
{
  "device": "sda",
  "duration": 3,
  "samples": 3,
  "io": {
    "read_iops": {"avg": 0.0, "min": 0, "max": 0},
    "read_kb": {"avg": 0.0, "min": 0.0, "max": 0.0},
    "write_iops": {"avg": 26.33, "min": 0, "max": 61},
    "write_kb": {"avg": 265.83, "min": 0.0, "max": 601.5}
  }
}
```

#### Hugepages Monitoring
```bash
POST http://192.168.8.60:8080/hugepages/monitor
Content-Type: application/json

{
  "duration": 12
}
```

**Sample Response:**
```json
{
  "duration": 2,
  "samples": 2,
  "hugepages": {
    "size_1048576kB": {
      "total": {"avg": 32.0, "min": 32, "max": 32},
      "free": {"avg": 32.0, "min": 32, "max": 32},
      "used": {"avg": 0.0, "min": 0, "max": 0},
      "used_percent": {"avg": 0.0, "min": 0.0, "max": 0.0},
      "reserved": {"avg": 0.0, "min": 0, "max": 0}
    },
    "size_2048kB": {
      "total": {"avg": 0.0, "min": 0, "max": 0},
      "free": {"avg": 0.0, "min": 0, "max": 0},
      "used": {"avg": 0.0, "min": 0, "max": 0},
      "used_percent": {"avg": 0.0, "min": 0.0, "max": 0.0},
      "reserved": {"avg": 0.0, "min": 0, "max": 0}
    }
  }
}
```

#### CPU Monitoring
```bash
POST http://192.168.8.60:8080/cpu/monitor
Content-Type: application/json

{
  "duration": 12,
  "breakdown": true,
  "include_timeseries": true
}
```

#### PTP Monitoring (if configured)
```bash
POST http://192.168.8.60:8080/ptp/monitor
Content-Type: application/json

{
  "duration": 12,
  "interface": "ens1f0",
  "include_timeseries": true
}
```

#### Power Monitoring (RAPL)
```bash
POST http://192.168.8.60:8080/power/monitor
Content-Type: application/json

{
  "duration": 12,
  "include_timeseries": true
}
```

#### Network Interface Monitoring
```bash
POST http://192.168.8.60:8080/network/monitor
Content-Type: application/json

{
  "duration": 12,
  "interfaces": ["ens1f0", "ens1f1"]
}
```

---

## Phase 4: Results Storage

### 4.1 Directory Structure

```
test_results/
├── exec_400_gnb-test-with-sideload_cpus_8_iperf_bandwidth_mbps_100_1738847200.json
└── sideload_dumps/
    └── gnb-test-with-sideload/
        └── cpus_8_iperf_bandwidth_mbps_100/
            └── 400/
                ├── thread_cpu_0.json
                ├── cpu_1.json
                ├── memory_2.json
                ├── disk_3.json
                ├── hugepages_4.json
                ├── power_5.json
                ├── network_6.json
                └── ptp_7.json
```

### 4.2 Execution Result

The main execution result includes sideload metadata:

```json
{
  "execution_id": 400,
  "test_id": "gnb-test-with-sideload",
  "timestamp": "2026-02-03T15:30:00Z",
  "sideload_url": "http://192.168.8.60:8080",
  "sideload_metadata": {
    "instance_id": "e2d5b9c9-b805-4492-a702-85fec46e20be",
    "node_name": "inoue",
    "ip_address": "192.168.8.60",
    "port": 8080,
    "rt_config": {
      "isolated_cpus": "8-15",
      "tuned_profile": "cpu-partitioning"
    }
  },
  "parameters": {
    "cpus": 8,
    "iperf_bandwidth_mbps": 100
  },
  "runs": [
    {
      "run_id": 0,
      "timestamp": "2026-02-03T15:30:10Z",
      "ue_status": {...},
      "iperf": {...},
      "monitoring_summary": {
        "successful": 8,
        "failed": 0,
        "total_metrics": 8
      }
    }
  ]
}
```

---

## API Reference

### Sideload Registration Endpoints (via Kong)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sideload/1.0.0/register` | Register sideload instance |
| GET | `/sideload/1.0.0/list` | List all registered sideloads |
| GET | `/sideload/1.0.0/report/<id>` | Get RT report from sideload |

### Direct Profiling Endpoints (sideload)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/cpu/monitor` | CPU usage per-core |
| POST | `/memory/monitor` | System memory usage |
| POST | `/disk/monitor` | Disk I/O statistics |
| POST | `/hugepages/monitor` | Hugepages allocation |
| POST | `/power/monitor` | RAPL power consumption |
| POST | `/network/monitor` | Network interface stats |
| POST | `/ptp/monitor` | PTP synchronization |
| POST | `/process/threads` | Per-thread CPU and affinity |
| GET | `/irq/affinity` | IRQ affinity mapping |

---

## Troubleshooting

### Sideload Registration Fails

**Symptom:** `{"error": "no reachable IPs"}`

**Solution:**
1. Verify sideload health: `curl http://192.168.8.60:8080/health`
2. Check network connectivity from rApp pod to sideload
3. Ensure correct IP addresses in registration request
4. Verify firewall rules allow port 8080

### Non-Versioned Endpoint Errors

**Symptom:** `{"message": "no Route matched with those values"}`

**Solution:** Always use versioned endpoints:
- ❌ `/sideload/register`
- ✅ `/sideload/1.0.0/register`

Update sideload's `utils/registration.py`:
```python
url = f"{RAPP_URL}/sideload/1.0.0/register"  # Add version
```

### Profiling Metrics Missing

**Symptom:** Monitoring returns null values

**Causes:**
- Insufficient permissions (need privileged pod or nsenter access)
- RAPL not available (power monitoring)
- Device not found (disk/network interfaces)

**Solution:** Run sideload as privileged pod:
```yaml
securityContext:
  privileged: true
volumeMounts:
  - name: host-proc
    mountPath: /host/proc
  - name: host-sys
    mountPath: /host/sys
```

---

## Performance Considerations

### Registration Path
- **Via Kong SME**: Service discovery, authentication, rate limiting
- **Overhead**: ~10-20ms per request
- **Use case**: Initial registration (R1 compliance)

### Profiling Path
- **Direct IP**: Low-latency, high-frequency polling
- **Overhead**: ~1-5ms per request
- **Use case**: Real-time monitoring during tests

### Data Volume
- Typical test (3 runs × 10s × 8 metrics): ~200KB raw JSON
- With timeseries (1Hz sampling): ~2MB per test
- Hugepages contain multiple sizes: 1GB, 2MB pages tracked separately

---

## Summary

✅ **R1-Compliant Registration**: Sideload registers via Kong SME  
✅ **Direct Profiling**: High-performance metric collection  
✅ **Comprehensive Monitoring**: 8+ metric types supported  
✅ **Automated Storage**: Raw dumps saved per execution  
✅ **Flexible Configuration**: Test cases reference sideload instances  

**Status**: Production-ready sideload integration with Kong SME gateway
