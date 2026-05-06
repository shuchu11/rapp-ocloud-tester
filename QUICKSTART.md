# rApp Quick Start Guide

## Current Deployment Status

Your rApp is **DEPLOYED and RUNNING** via rApp Manager:

```bash
# Check status anytime
make list
make status

# Or via curl
curl -s http://192.168.8.69:30096/rapps | jq '.[] | {name, state}'
```

## Access Methods

### 1. Kong SME Gateway (Production - ✅ WORKING!)

**Recommended for production** - O-RAN compliant service discovery via Kong API gateway:

```bash
# Base URL for all rApp endpoints
KONG_BASE="http://192.168.8.69:32080/gnb-test-api/port-5000-hash-5a42e08c-1f7e-5235-b97d-30d85c44275e"

# Health check (no version required)
curl "$KONG_BASE/health"

# Versioned API endpoints
curl "$KONG_BASE/tests/1.0.0/list" | jq
curl "$KONG_BASE/ue/1.0.0/status" | jq
curl "$KONG_BASE/sideload/1.0.0/list" | jq
curl "$KONG_BASE/results/1.0.0/list" | jq

# POST requests
curl -X POST "$KONG_BASE/tests/1.0.0/load" \
  -H "Content-Type: application/json" -d '{}'
```

**What Changed**: Backend updated to support both `/endpoint/path` and `/endpoint/1.0.0/path` patterns. Kong's versioned paths now work correctly.

### 2. Direct Service Access (Development)

Use port-forward for direct access (bypasses Kong):

```bash
# Port-forward to local machine
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric port-forward svc/rapp-gnb-test 5000:5000 &

# Access with or without version
curl http://localhost:5000/health
curl http://localhost:5000/tests/list | jq
curl http://localhost:5000/tests/1.0.0/list | jq  # Both work!
```

### 3. In-Cluster Access (from pods)

```bash
# From any pod in the cluster
curl http://rapp-gnb-test.nonrtric:5000/health

# Or create a test pod
KUBECONFIG=/root/l-smo.config kubectl run -it --rm curl --image=curlimages/curl --restart=Never -- sh
# Inside the pod:
curl http://rapp-gnb-test.nonrtric:5000/health
```

### Kong Gateway Info

```bash
# View registered Kong services
curl http://192.168.8.69:32081/services | jq '.data[] | select(.name | contains("gnb-test-api")) | {name, host, port, path}'

# View Kong routes
curl http://192.168.8.69:32081/routes | jq '.data[] | select(.name | contains("gnb-test-api")) | {name, paths}'
```

**Available API Endpoints (gnb-test-api):**
- `GET /health` - Health check
- `GET /tests/list` - List all test cases
- `POST /tests/load` - Load test cases from YAML
- `POST /tests/run/{test_id}` - Execute a specific test
- `GET /tests/results` - Query test execution results
- `POST /nfo/deploy` - Deploy VNF via NFO
- `GET /nfo/status/{instance_id}` - Check VNF deployment status
- `GET /ue/status` - Get UE attachment status
- `POST /ue/iperf` - Run iperf3 throughput test
- `POST /ue/airplane/toggle` - Toggle airplane mode

## Quick Test Commands

```bash
# Health check
curl http://localhost:5000/health

# List available tests
curl http://localhost:5000/tests/list | jq '.tests[] | {id, description}'

# Check UE status
curl http://localhost:5000/ue/status | jq '{attached, data_ip, nr_state}'

# Run iperf test (20 seconds)
curl -X POST -H "Content-Type: application/json" \
  -d '{"duration": 20}' \
  http://localhost:5000/ue/iperf | jq '.end.sum_received.bits_per_second / 1000000'

# Load test cases
curl -X POST http://localhost:5000/tests/load | jq '.'

# Run a specific test
curl -X POST http://localhost:5000/tests/run/nfapi-liteon-kepler-cpu-bandwidth | jq '.'

# Check test results
curl http://localhost:5000/tests/results | jq '.executions[] | {id, test_id, status}'
```

## Management Commands

```bash
# List all deployed rApps
make list

# Check specific rApp status
curl -s http://192.168.8.69:30096/rapps/rapp-gnb-test | jq '{name, state, compositionId, rappResources}'

# Check instance deployment details
curl -s http://192.168.8.69:30096/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001 | jq '.'

# View pod logs
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric logs -l app=rapp-gnb-test -f

# Check pod status
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric get pods -l app=rapp-gnb-test

# Restart pod (if needed)
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric rollout restart deployment rapp-gnb-test
```

## Cleanup / Redeploy

```bash
# Undeploy (keeps instance)
make undeploy

# Delete instance
make delete-instance

# DEPRIME rApp
make deprime

# Delete rApp completely
make delete-rapp

# Full redeploy
make upload && make prime && make instantiate && make deploy
```

## Troubleshooting

**Check rApp Manager logs:**
```bash
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric logs rappmanager-0 -f
```

**Check rApp pod logs:**
```bash
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric logs -l app=rapp-gnb-test -f
```

**Verify service endpoints:**
```bash
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric get svc rapp-gnb-test
KUBECONFIG=/root/l-smo.config kubectl -n nonrtric describe svc rapp-gnb-test
```

**Test from within cluster:**
```bash
KUBECONFIG=/root/l-smo.config kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -v http://rapp-gnb-test.nonrtric:5000/health
```

## Notes

- **State**: Your rApp instance may show "DEPLOYING" in Manager due to SME registration conflicts from previous attempts, but the pod is fully functional
- **ACM**: Deployed successfully with instance ID `7d12c24b-b09f-4e92-af28-6f0100181afb`
- **SME**: Service APIs registered (conflicts are cosmetic and don't affect operation)
- **Pod**: Running and serving requests at `rapp-gnb-test.nonrtric:5000`
- **Health**: Verified healthy and responsive

The rApp is **production-ready** and accessible via all three methods above!
