# rApp for gNB Test Orchestration

**Version**: 2.0.0  
**Status**: ✅ Production Ready  
**SME Gateway**: ✅ Fully Compatible  

## Overview

Automated test orchestration framework for O-RAN gNB deployments with:
- **NFO integration** - VNF lifecycle management
- **UE client** - Android device automation for 5G testing
- **Sideload monitoring** - Real-time RT metrics collection
- **Test orchestration** - Parameterized test execution with bandwidth/CPU scaling
- **InfluxDB integration** - Time-series result storage
- **O-RAN SME compliance** - Kong gateway service discovery

## Deployment via rApp Manager (Production Method)

### Prerequisites

1. **Cluster Access:**
   ```bash
   export KUBECONFIG=/root/l-smo.config
   ```

2. **Verify ACM Runtime:**
   ```bash
   kubectl get svc -n onap | grep policy-clamp-runtime-acm
   # Should show:
   # policy-clamp-runtime-acm      ClusterIP   10.104.91.120    <none>   http-api:6969
   # policy-clamp-runtime-acm-ext  NodePort    10.108.244.71    <none>   http-api:6969:30969
   ```

3. **rApp Manager Endpoints:**
   - NodePort: `http://192.168.8.69:30096`
   - ACM NodePort: `http://192.168.8.69:30969`
   
   **Note:** ACM runs in `onap` namespace, not `nonrtric`

### Step 1: Package and Upload rApp

```bash
# Set rApp Manager endpoint
export RAPPMGR=http://192.168.8.69:30096

# Package CSAR from rapp-package directory
cd rapp-package
zip -r ../rapp-gnb-test.csar TOSCA-Metadata Definitions Files asd.mf
cd ..

# Upload to rApp Manager (commissioning)
curl -X POST -F "file=@rapp-gnb-test.csar" "$RAPPMGR/rapps/rapp-gnb-test"

# Verify upload
curl -s "$RAPPMGR/rapps" | jq '.[] | {name, state}'
```

**Or use Makefile:**
```bash
make upload
make list
```

### Step 2: PRIME the rApp

Priming registers the ACM composition and prepares the rApp for instantiation:

```bash
# PRIME the rApp
curl -X PUT -H "Content-Type: application/json" \
  -d '{"primeOrder":"PRIME"}' \
  "$RAPPMGR/rapps/rapp-gnb-test" | jq '.'

# Check PRIMED state
curl -s "$RAPPMGR/rapps/rapp-gnb-test" | jq '{state, compositionId}'
# Should show: {"state": "PRIMED", "compositionId": "..."}
```

**Or use Makefile:**
```bash
make prime
```

### Step 3: Create rApp Instance

```bash
# Create instance with UUID
curl -X POST -H "Content-Type: application/json" \
  -d '{
    "rappInstanceId": "00000000-0000-0000-0000-000000000001",
    "acm": {"instance": "instance"},
    "sme": {
      "providerFunction": "provider-function-1",
      "serviceApis": "api-set-1",
      "invokers": "invoker-app1"
    }
  }' \
  "$RAPPMGR/rapps/rapp-gnb-test/instance" | jq '.'

# Verify instance created
curl -s "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '{state, sme, acm}'
```

**Or use Makefile:**
```bash
make instantiate
```

### Step 4: Deploy the Instance

```bash
# Deploy (triggers ACM and SME deployment)
curl -X PUT -H "Content-Type: application/json" \
  -d '{"deployOrder":"DEPLOY"}' \
  "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '.'

# Monitor deployment (wait 10-30 seconds)
watch -n 2 "curl -s $RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001 | jq '.state'"

# Check pod is running
kubectl -n nonrtric get pods | grep rapp-gnb-test
# Should show: rapp-gnb-test-xxxxx-xxxxx   1/1   Running
```

**Or use Makefile:**
```bash
make deploy

# Check status
kubectl -n nonrtric get pods -l app=rapp-gnb-test
```

### Step 5: Access Your rApp

**✅ Kong SME Gateway (Production - Recommended)**

All endpoints support both versioned and non-versioned paths:

```bash
# Set Kong base URL
export KONG_BASE="http://192.168.8.69:32080/gnb-test-api/port-5000-hash-5a42e08c-1f7e-5235-b97d-30d85c44275e"

# Health check (no version required)
curl "$KONG_BASE/health"

# Test management (versioned)
curl "$KONG_BASE/tests/1.0.0/list" | jq
curl -X POST "$KONG_BASE/tests/1.0.0/load" -H "Content-Type: application/json"
curl -X POST "$KONG_BASE/tests/1.0.0/run/f1-liteon-kepler-cpu-bandwidth"

# UE operations (versioned)
curl "$KONG_BASE/ue/1.0.0/status" | jq
curl -X POST "$KONG_BASE/ue/1.0.0/iperf" -H "Content-Type: application/json" \
  -d '{"bitrate": 100, "duration": 20}'

# Results and analysis (versioned)
curl "$KONG_BASE/results/1.0.0/list" | jq
curl "$KONG_BASE/tests/1.0.0/results?limit=10" | jq

# NFO VNF deployment (versioned)
curl -X POST "$KONG_BASE/nfo/1.0.0/deploy" -H "Content-Type: application/json" \
  -d '{"name": "oai-gnb-test", "artifact_name": "oai-gnb-fhi-72", ...}'

# Sideload monitoring (versioned)
curl "$KONG_BASE/sideload/1.0.0/list" | jq
```

**Direct Service Access (Development)**

For local development or debugging:

```bash
# Port-forward to local machine
kubectl -n nonrtric port-forward svc/rapp-gnb-test 5000:5000 &

# Access with or without version
curl http://localhost:5000/health
curl http://localhost:5000/tests/list | jq
curl http://localhost:5000/tests/1.0.0/list | jq  # Both work!
```

**In-Cluster Access**

From pods within the cluster:

```bash
# Direct service access
kubectl run -it --rm curl --image=curlimages/curl -- \
  curl http://rapp-gnb-test.nonrtric:5000/health

# Or from any pod
curl http://rapp-gnb-test.nonrtric:5000/tests/list
```

**Available Endpoints:**

All endpoints support both versioned (`/1.0.0/`) and non-versioned access:

- **Health & Info**
  - `GET /health` - Health check
  - `GET /dme/health` - DME health check
  - `GET /dme/info` - rApp metadata

- **Test Management**
  - `GET /tests/list` or `/tests/1.0.0/list` - List test cases
  - `POST /tests/load` or `/tests/1.0.0/load` - Load YAML test cases
  - `POST /tests/run/{test_id}` or `/tests/1.0.0/run/{test_id}` - Execute test
  - `GET /tests/results` or `/tests/1.0.0/results` - Query results

- **Results & Analysis**
  - `GET /results/list` or `/results/1.0.0/list` - List result files
  - `GET /results/analyze/{exec_id}` or `/results/1.0.0/analyze/{exec_id}` - Detailed analysis
  - `GET /results/export/{exec_id}` or `/results/1.0.0/export/{exec_id}` - Export raw JSON

- **Plotting & Visualization**
  - `GET /plot/throughput/{exec_id}` or `/plot/1.0.0/throughput/{exec_id}` - Throughput timeseries
  - `GET /plot/cpu/{test_id}/{param}/{exec_id}/{run_id}` - CPU usage plots
  - `GET /plot/memory/{test_id}/{param}/{exec_id}/{run_id}` - Memory usage plots
  - `GET /plot/power/{test_id}/{param}/{exec_id}/{run_id}` - Power consumption plots

- **UE Operations**
  - `GET /ue/status` or `/ue/1.0.0/status` - UE attachment & signal info
  - `POST /ue/iperf` or `/ue/1.0.0/iperf` - Run iperf throughput test
  - `POST /ue/airplane/toggle` or `/ue/1.0.0/airplane/toggle` - Toggle airplane mode
  - `POST /ue/airplane/on` or `/ue/1.0.0/airplane/on` - Enable airplane mode
  - `POST /ue/airplane/off` or `/ue/1.0.0/airplane/off` - Disable airplane mode

- **NFO VNF Management**
  - `POST /nfo/deploy` or `/nfo/1.0.0/deploy` - Deploy VNF
  - `GET /nfo/status/{instance_id}` or `/nfo/1.0.0/status/{instance_id}` - VNF status

- **Sideload Monitoring**
  - `POST /sideload/register` or `/sideload/1.0.0/register` - Register monitoring agent
  - `GET /sideload/list` or `/sideload/1.0.0/list` - List registered agents
  - `GET /sideload/report/{instance_id}` or `/sideload/1.0.0/report/{instance_id}` - Get RT metrics

**Kong Gateway Info:**

```bash
# View all Kong services for this rApp
curl http://192.168.8.69:32081/services | jq '.data[] | select(.name | contains("gnb-test-api"))'

# View all Kong routes
curl http://192.168.8.69:32081/routes | jq '.data[] | select(.name | contains("gnb-test-api")) | {name, paths}'

# Kong Admin API
curl http://192.168.8.69:32081/
```

### Management Commands

```bash
# List all rApps
curl -s "$RAPPMGR/rapps" | jq '.[] | {name, state}'

# Get specific rApp details
curl -s "$RAPPMGR/rapps/rapp-gnb-test" | jq '.'

# Get instance status
curl -s "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '{state, reason, acm, sme}'

# Undeploy instance
curl -X PUT -H "Content-Type: application/json" \
  -d '{"deployOrder":"UNDEPLOY"}' \
  "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001"

# Delete instance
curl -X DELETE "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001"

# DEPRIME rApp
curl -X PUT -H "Content-Type: application/json" \
  -d '{"primeOrder":"DEPRIME"}' \
  "$RAPPMGR/rapps/rapp-gnb-test"

# Delete rApp
curl -X DELETE "$RAPPMGR/rapps/rapp-gnb-test"
```

**Or use Makefile:**
```bash
make undeploy          # Undeploy instance
make delete-instance   # Delete instance
make deprime           # DEPRIME rApp
make delete-rapp       # Delete rApp completely
```

### rApp Manager Issues

**PRIME fails:**
```bash
# Check ACM runtime connectivity (ACM runs in onap namespace)
curl -s "http://192.168.8.69:30969/onap/policy/clamp/acm/v2/compositions" | jq

# Check rApp Manager logs (if running as pod)
kubectl logs -l app=rappmanager --tail=50 -n <namespace>

# Common issues:
# - ACM runtime not accessible from rApp Manager
# - Invalid TOSCA structure in compositions.json
# - ACM participant (kubernetes) not available
```

**Deploy fails with "Unable to deploy ACM":**
```bash
# 1. Verify ACM service exists
kubectl get svc -n onap policy-clamp-runtime-acm-ext
# Should show NodePort on :30969

# 2. Check if composition was created in ACM
COMPOSITION_ID=$(curl -s "$RAPPMGR/rapps/rapp-gnb-test" | jq -r '.compositionId')
curl -s "http://192.168.8.69:30969/onap/policy/clamp/acm/v2/compositions/$COMPOSITION_ID" | jq

# 3. Check ACM instance status
ACM_INSTANCE_ID=$(curl -s "$RAPPMGR/rapps/rapp-gnb-test/instance/<instance-id>" | jq -r '.acm.acmInstanceId')
curl -s "http://192.168.8.69:30969/onap/policy/clamp/acm/v2/compositions/$COMPOSITION_ID/instances/$ACM_INSTANCE_ID" | jq

# 4. Verify Helm participant is running
kubectl get pods -n onap | grep "clamp.*k8s"

# 5. Check if chart exists in ChartMuseum
curl -s http://chartmuseum.chartmuseum:8080/api/charts/rapp-gnb-test | jq

# Common issues:
# - Helm chart not uploaded to ChartMuseum
# - ACM kubernetes participant not configured
# - Namespace doesn't exist (should be 'nonrtric')
# - Image pull errors
```

**Deploy stuck in "DEPLOYING" state:**
```bash
# Check ACM deployment status
curl -s "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '{state, reason, acm}'

# Check pod status
kubectl -n nonrtric get pods -l app=rapp-gnb-test
kubectl -n nonrtric describe pod -l app=rapp-gnb-test

# Common issues:
# - Image pull errors (check registry access)
# - Chart not in ChartMuseum
# - Resource constraints
```

**SME registration fails:**
```bash
# Check Service Manager
kubectl -n nonrtric get pods | grep servicemanager

# Check Kong
kubectl -n nonrtric get pods | grep kong

# Verify routes created
curl http://192.168.8.69:32081/routes | jq '.data[] | select(.name | contains("gnb-test-api"))'
```

### rApp Pod Issues

**Pod not starting:**
```bash
# Check logs
kubectl -n nonrtric logs -l app=rapp-gnb-test --tail=50

# Check events
kubectl -n nonrtric get events --sort-by='.lastTimestamp' | grep rapp-gnb-test

# Common issues:
# - Database initialization failed
# - Missing environment variables
# - Connection to external services (NFO, InfluxDB)
```

**Database errors:**
```bash
# Initialize database manually
POD=$(kubectl -n nonrtric get pods -l app=rapp-gnb-test -o jsonpath='{.items[0].metadata.name}')
kubectl -n nonrtric exec $POD -- python -c "import db; db.init_db(); print('DB initialized')"
```

**Kong 404 errors:**
```bash
# Verify versioned endpoints are working
curl "http://192.168.8.69:32080/gnb-test-api/.../tests/1.0.0/list"

# Check pod version
kubectl -n nonrtric get pod -l app=rapp-gnb-test -o jsonpath='{.items[0].spec.containers[0].image}'
# Should show: bmw.ece.ntust.edu.tw/infidel/rapp-gnb-test:2.0.0

# If showing old version, redeploy
helm upgrade --install rapp-gnb-test chart/ --namespace nonrtric --set image.tag="2.0.0"
```

### Network Issues

**Cannot reach NFO:**
```bash
# Test connectivity from pod
kubectl -n nonrtric exec -it deployment/rapp-gnb-test -- \
  curl -v http://192.168.8.35:8080/api/o2dms/v2/health
```

**Cannot reach InfluxDB:**
```bash
# Test from pod
kubectl -n nonrtric exec -it deployment/rapp-gnb-test -- \
  curl -v http://192.168.8.69:30138/health
```

### Cleanup and Restart
### Cleanup and Restart

**Full cleanup:**
```bash
# Undeploy and delete instance
make undeploy
make delete-instance
make deprime
make delete-rapp

# Or manually
curl -X DELETE "$RAPPMGR/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001"
curl -X DELETE "$RAPPMGR/rapps/rapp-gnb-test"

# Clean pods
kubectl -n nonrtric delete deployment rapp-gnb-test
kubectl -n nonrtric delete svc rapp-gnb-test
```

**Restart rApp Manager (after failures):**
```bash
kubectl -n nonrtric delete pod rappmanager-0
# Wait for pod to restart
kubectl -n nonrtric wait --for=condition=ready pod rappmanager-0 --timeout=60s
```

**Redeploy from scratch:**
```bash
# Package, upload, prime, instantiate, deploy
make upload
make prime
make instantiate
make deploy

# Check status
make status
kubectl -n nonrtric get pods -l app=rapp-gnb-test
```

---

## References

- **O-RAN SC rApp Manager**: [GitHub](https://github.com/o-ran-sc/nonrtric-plt-rappmanager)
- **Kong Gateway**: [Documentation](https://docs.konghq.com/)
- **ACM Runtime**: ONAP Policy Framework
- **Service Manager**: O-RAN CAPIF-based service discovery

## Quick Reference

```bash
# Environment
export KUBECONFIG=/root/l-smo.config
export RAPPMGR=http://192.168.8.69:30096
export KONG_BASE="http://192.168.8.69:32080/gnb-test-api/port-5000-hash-5a42e08c-1f7e-5235-b97d-30d85c44275e"

# Status checks
make list                                          # List all rApps
make status                                        # Get instance status
kubectl -n nonrtric get pods -l app=rapp-gnb-test  # Pod status

# Access
curl "$KONG_BASE/health"                           # Via Kong (production)
kubectl port-forward -n nonrtric svc/rapp-gnb-test 5000:5000  # Direct access

# Management
make deploy        # Deploy instance
make undeploy      # Undeploy instance
make restart       # Restart pod
```

---

## Development & Local Testing

### Building New Image Version

```bash
# Build with podman
podman build -t rapp-gnb-test:2.0.0 .

# Tag and push to registry
podman tag rapp-gnb-test:2.0.0 bmw.ece.ntust.edu.tw/infidel/rapp-gnb-test:2.0.0
podman push bmw.ece.ntust.edu.tw/infidel/rapp-gnb-test:2.0.0

# Package and upload Helm chart
helm package chart/
curl -F "chart=@rapp-gnb-test-1.0.0.tgz" http://192.168.8.69:32344/api/charts

# Redeploy
helm upgrade --install rapp-gnb-test chart/ \
  --namespace nonrtric \
  --set image.tag="2.0.0" \
  --wait
```

### Direct Testing (No rApp Manager)

For quick local testing without rApp Manager:

```bash
# Deploy directly with Helm
export KUBECONFIG=/root/l-smo.config
helm upgrade --install rapp-gnb-test chart/ --namespace nonrtric --wait

# Port-forward and test
kubectl -n nonrtric port-forward svc/rapp-gnb-test 5000:5000 &
curl http://localhost:5000/health
curl http://localhost:5000/tests/list | jq

# Cleanup
helm uninstall rapp-gnb-test -n nonrtric
```

### Version Support

**v2.0.0** (Current):
- ✅ Kong SME gateway compatible
- ✅ Dual endpoint support: `/path` and `/1.0.0/path`
- ✅ O-RAN service discovery compliant
- ✅ Production ready

**v1.0.0** (Legacy):
- ❌ Kong incompatible (non-versioned endpoints only)
- ✅ Direct access only

---

## Alternative: Manual VNF Deployment via NFO

1. Deploy VNF via NFO

GNB

```bash
curl --request POST \
  --url http://localhost:5000/nfo/deploy \
  --header 'Content-Type: application/json' \
  --header 'User-Agent: insomnia/12.1.0' \
  --data '{
	"name": "oai-gnb-test",
	"description": "Another VNF Descriptor",
	"profile_type": "kubernetes",
	"artifact_repo_url": "https://github.com/motangpuar/ocloud-helm-templates.git",
	"artifact_name": "oai-gnb-fhi-72",
	"artifact_repo_branch": "starlingx/pegatron",
	"target_cluster": "cc1397ba-b1c4-4a3e-bc8d-6af58ef53818",
	"values": {}
}'

{
	"descriptor_id": "c4825777-23da-4045-a85b-1c4aa53556bd",
	"instance_id": "52669149-f23c-4566-86a9-40e3c403c879",
	"operation_id": "4000e18c-1ec6-4c80-ab8f-0b2d266001e2",
	"state": "COMPLETED"
}
```

Sideloader

```bash
curl --request POST \
  --url http://localhost:5000/nfo/deploy \
  --header 'Content-Type: application/json' \
  --header 'User-Agent: insomnia/12.1.0' \
  --data '{
	"name": "perf-audit-sideload",
	"description": "Performance audit sideload",
	"profile_type": "kubernetes",
	"artifact_repo_url": "https://github.com/motangpuar/cicd-charts.git",
	"artifact_name": ".",
	"artifact_repo_branch": "main",
	"target_cluster": "cc1397ba-b1c4-4a3e-bc8d-6af58ef53818",
	"values": {
		"nodeSelector": {
			"specialized": "radio",
			"kubernetes.io/hostname": "joule"
		},
		"tolerations": [
			{
				"key": "dedicated",
				"operator": "Equal",
				"value": "5g-radio",
				"effect": "NoSchedule"
			}
		],
		"image.pullPolicy": "Always"
	}
}'

# Response
{
	"descriptor_id": "a56d297c-1f82-46f5-b31a-b5e2cde3deed",
	"instance_id": "0ce8190a-435a-46a9-9cec-acbd06345bbe",
	"operation_id": "de0765a1-dccb-4a98-a395-dd977bdedc95",
	"state": "COMPLETED"
}
```

## UE Control

### Get UE Status

```bash
 curl -sS http://localhost:5000/ue/status
{
  "airplane_mode": true,
  "android": {
    "sdk": "30",
    "version": "11"
  },
  "attached": false,
  "cell": {
    "arfcn": 432030,
    "mcc": "466",
    "mnc": "92",
    "nci": 8250720462,
    "operator_long": "Chunghwa",
    "operator_short": "Chunghwa",
    "pci": 103,
    "tac": 0
  },
  "data_ip": null,
  "data_registration": {
    "code": 3,
    "state": "POWER_OFF"
  },
  "device": {
    "brand": "samsung",
    "manufacturer": "samsung",
    "model": "SM-G9860"
  },
  "modem_baseband": "G9860ZCU3DUJB,G9860ZCU3DUJB",
  "network_type": {
    "code": 0,
    "type": "Unknown"
  },
  "nr_state": "NONE",
  "signal": null,
  "signal_level": null
}
```

### UE Client Testing

Check UE status and run iperf tests:

```bash
# Via Kong (production)
export KONG_BASE="http://192.168.8.69:32080/gnb-test-api/port-5000-hash-5a42e08c-1f7e-5235-b97d-30d85c44275e"

# Get UE status
curl "$KONG_BASE/ue/1.0.0/status" | jq '{attached, data_ip, nr_state, signal}'

# Run iperf throughput test
curl -X POST "$KONG_BASE/ue/1.0.0/iperf" \
  -H "Content-Type: application/json" \
  -d '{"bitrate": 100, "duration": 20}' | jq '.end.sum_received.bits_per_second / 1000000'

# Toggle airplane mode (force reattachment)
curl -X POST "$KONG_BASE/ue/1.0.0/airplane/toggle"
```

---

## Architecture & Components

### rApp Manager Integration

- **ACM Deployer**: Manages Helm chart deployment via ACM runtime
- **SME Deployer**: Registers APIs with Kong gateway for service discovery
- **DME Deployer**: Placeholder integration (minimal implementation)

### Kong Gateway (SME)

- **Service Discovery**: All rApp APIs registered automatically
- **Routing**: Versioned paths (`/gnb-test-api/.../endpoint/1.0.0/path`)
- **Production Ready**: Gateway handles auth, rate limiting, monitoring

### Components

```
┌─────────────────────────────────────────────────────────┐
│                    rApp Manager                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │   ACM    │  │   SME    │  │   DME    │             │
│  │ Deployer │  │ Deployer │  │ Deployer │             │
│  └────┬─────┘  └────┬─────┘  └──────────┘             │
└───────┼─────────────┼────────────────────────────────────┘
        │             │
        ▼             ▼
   ┌─────────┐  ┌──────────┐
   │   ACM   │  │   Kong   │
   │ Runtime │  │ Gateway  │
   └────┬────┘  └────┬─────┘
        │            │
        ▼            ▼
   ┌────────────────────────┐
   │   rApp Pod (Helm)      │
   │  ┌──────────────────┐  │
   │  │  Flask App       │  │
   │  │  - Test Mgmt     │  │
   │  │  - NFO Client    │  │
   │  │  - UE Client     │  │
   │  │  - Sideload API  │  │
   │  │  - InfluxDB      │  │
   │  └──────────────────┘  │
   └────────────────────────┘
```

---

## Troubleshooting

### rApp Manager Issues

- Prerequisites:
  - SMO kubeconfig available at `/root/l-smo.config` (or export `KUBECONFIG` accordingly).
  - rApp chart packaged and commissioned (ChartMuseum contains `rapp-gnb-test-1.0.0.tgz`).
  - ACM Runtime service `policy-clamp-runtime-acm` running in `onap` namespace.

### Option A: Local port-forward

```bash
export KUBECONFIG=/root/l-smo.config
bash ./deploy-bypass.sh
```

This script:
- Port-forwards `policy-clamp-runtime-acm` to localhost:6969.
- Fetches ACM credentials from `policy-clamp-runtime-acm-ku` secret.
- Creates and primes the composition, creates an instance, and deploys.

### Option B: In-cluster curl pod

```bash
export KUBECONFIG=/root/l-smo.config
bash ./deploy-direct-acm.sh
```

This script uses ephemeral `curl` pods to call ACM Runtime inside the cluster, with basic auth from the same secret.

### Verify and test

```bash
kubectl get pods -n nonrtric | grep rapp-gnb-test
kubectl port-forward -n nonrtric svc/rapp-gnb-test 5000:5000
curl http://localhost:5000/health
curl http://localhost:5000/dme/health
```
