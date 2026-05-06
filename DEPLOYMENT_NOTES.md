# rApp Deployment Notes - Current Environment

**Date**: February 4, 2026  
**Cluster**: inoue / galileo  
**Provider**: Nino

## Infrastructure Overview

### ACM (Automation Composition Management)
- **Namespace**: `onap` (NOT `nonrtric`)
- **Service**: `policy-clamp-runtime-acm`
- **ClusterIP**: `10.104.91.120:6969`
- **NodePort**: `policy-clamp-runtime-acm-ext` on `10.108.244.71:30969`
- **External Access**: `http://192.168.8.69:30969`

### rApp Manager
- **Access**: `http://192.168.8.69:30096` (NodePort)
- **No pod running** - Exposed directly via NodePort
- **Actuator**: `http://192.168.8.69:30096/actuator/health`

### Current rApp Status
- **Name**: rapp-gnb-test
- **Provider**: Nino
- **State**: PRIMED
- **Composition ID**: `00cef02c-8597-4aee-8d88-8a08b69f4311`
- **Instance**: `6e19db67-978f-4a0b-8f63-0f68836b8a87` (DEPLOYING - stuck)

## Deployment Method

### 1. Package and Upload
```bash
export RAPPMGR=http://192.168.8.69:30096

# Clean up previous attempts
curl -s -X DELETE "$RAPPMGR/rapps/rapp-gnb-test"

# Package CSAR
cd rapp-package
zip -r ../rapp-gnb-test.csar TOSCA-Metadata Definitions Files asd.mf
cd ..

# Upload
curl -X POST -F "file=@rapp-gnb-test.csar" "$RAPPMGR/rapps/rapp-gnb-test"
```

### 2. PRIME the rApp
```bash
curl -X PUT -H "Content-Type: application/json" \
  -d '{"primeOrder":"PRIME"}' \
  "$RAPPMGR/rapps/rapp-gnb-test" | jq
```

### 3. Create Instance (Auto-generated ID)
```bash
rapp_id=$(curl -s -X POST "$RAPPMGR/rapps/rapp-gnb-test/instance" \
  -H "Content-Type: application/json" \
  -d '{
    "acm": {"instance": "instance"},
    "sme": {
      "providerFunction": "provider-function-1",
      "serviceApis": "api-set-1",
      "invokers": "invoker-app1"
    }
  }' | jq -r '.rappInstanceId')

echo "rApp Instance ID: $rapp_id"
```

### 4. Deploy Instance
```bash
curl -i -X PUT "$RAPPMGR/rapps/rapp-gnb-test/instance/$rapp_id" \
  -H "Content-Type: application/json" \
  -d '{"deployOrder":"DEPLOY"}'
```

### 5. Monitor Deployment
```bash
# Check status
watch -n 2 "curl -s $RAPPMGR/rapps/rapp-gnb-test/instance/$rapp_id | jq '{state, reason, acm, sme}'"

# Check if pod is created (should be in nonrtric namespace)
kubectl get pods -A | grep rapp-gnb-test
```

## Known Issues

### Issue 1: Deployment Stuck in "DEPLOYING" State
**Symptoms:**
- Instance state shows "DEPLOYING"
- Reason: "Unable to deploy SME"
- ACM instance ID is created
- But no pod is running

**Root Cause:**
- ACM composition is created successfully
- ACM instance transitions through states but Helm deployment doesn't complete
- Possible causes:
  1. Helm chart not in ChartMuseum
  2. ACM Kubernetes participant not properly configured
  3. Target namespace doesn't exist
  4. Image pull issues

**Investigation:**
```bash
# 1. Check ACM composition
COMP_ID=$(curl -s "$RAPPMGR/rapps/rapp-gnb-test" | jq -r '.compositionId')
curl -s "http://192.168.8.69:30969/onap/policy/clamp/acm/v2/compositions/$COMP_ID" | jq

# 2. Check ACM instance
ACM_INST=$(curl -s "$RAPPMGR/rapps/rapp-gnb-test/instance/$rapp_id" | jq -r '.acm.acmInstanceId')
curl -s "http://192.168.8.69:30969/onap/policy/clamp/acm/v2/compositions/$COMP_ID/instances/$ACM_INST" | jq

# 3. Verify Helm releases
helm list -A | grep rapp-gnb-test

# 4. Check ChartMuseum
curl -s http://chartmuseum.chartmuseum:8080/api/charts | jq 'keys'
```

**Workaround:**
If ACM deployment doesn't work, deploy directly via Helm:
```bash
# Build Docker image
make build

# Push to registry
make push

# Deploy via Helm
helm upgrade --install rapp-gnb-test ./chart/rapp-gnb-test \
  --namespace nonrtric \
  --create-namespace \
  --set image.repository=bmw.ece.ntust.edu.tw/infidel/rapp-gnb-test \
  --set image.tag=latest
```

### Issue 2: Cannot Delete Stuck Instance
**Problem:**
- Instance stuck in DEPLOYING state
- Cannot undeploy (not in DEPLOYED state)
- Cannot delete (not in UNDEPLOYED state)
- Cannot DEPRIME (has active instances)

**Solution:**
Requires admin intervention to:
1. Restart rApp Manager service
2. Or manually clean up database entries
3. Or force delete via direct database access

## Makefile Commands

```bash
# Full deployment workflow
make upload && make prime && make instantiate && make deploy

# Cleanup
make undeploy          # Undeploy instance
make delete-instance   # Delete instance
make deprime          # DEPRIME rApp
make delete-rapp      # Delete completely

# Status checks
make list             # List all rApps
make status           # HTTP status check
```

## Verification Checklist

- [ ] ACM runtime accessible at http://192.168.8.69:30969
- [ ] rApp Manager accessible at http://192.168.8.69:30096
- [ ] rApp uploaded and state = PRIMED
- [ ] Instance created with auto-generated ID
- [ ] ACM composition created (check compositionId in rApp)
- [ ] ACM instance created (check acmInstanceId in instance)
- [ ] Pod running in nonrtric namespace
- [ ] Kong routes created for SME
- [ ] Service accessible via Kong gateway

## Contact

If issues persist, contact cluster admin for:
- rApp Manager service restart
- ACM configuration review
- Database cleanup
- ChartMuseum access
