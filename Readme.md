# rAPP for VNF test Orchestration

## Deployment

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

### Trigger iperf3 test

```
curl -sS -X POST http://localhost:5000/ue/iperf -H "Content-Type: application/json" -d '{"duration": 20}' | jq '.end.sum_received.bits_per_second / 1000000'

```
