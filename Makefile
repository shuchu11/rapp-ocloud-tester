RAPPMGR ?= http://192.168.8.69:30096
PACKAGE_DIR := rapp-package
CSAR := rapp-gnb-test.csar

.PHONY: rapp-help list status csar upload prime instantiate deploy undeploy delete-instance deprime delete-rapp restart-manager

rapp-help:
	@echo "=== rApp Manager Deployment Targets ==="
	@echo "  make list              - List all rApps"
	@echo "  make status            - Show HTTP status for rapp-gnb-test"
	@echo "  make csar              - Build CSAR from $(PACKAGE_DIR)"
	@echo "  make upload            - Delete existing and upload CSAR"
	@echo "  make prime             - PRIME the rApp"
	@echo "  make instantiate       - Create rApp instance"
	@echo "  make deploy            - Deploy rApp instance"
	@echo "  make undeploy          - Undeploy rApp instance"
	@echo "  make delete-instance   - Delete rApp instance"
	@echo "  make deprime           - DEPRIME the rApp"
	@echo "  make delete-rapp       - Delete rApp completely"
	@echo "  make restart-manager   - Restart Rapp Manager deployment (kubectl)"
	@echo ""
	@echo "Full workflow: make upload && make prime && make instantiate && make deploy"

list:
	@echo "Using Rapp Manager: $(RAPPMGR)"
	curl -sS "$(RAPPMGR)/rapps" | jq '.'

status:
	@echo "Using Rapp Manager: $(RAPPMGR)"
	@curl -s -o /dev/null -w "%{http_code}\n" "$(RAPPMGR)/rapps/rapp-gnb-test" || true

ensure-zip:
	@command -v zip >/dev/null 2>&1 || (apt-get update && apt-get install -y zip)

csar: ensure-zip
	@echo "Packaging CSAR from $(PACKAGE_DIR)"
	cd "$(PACKAGE_DIR)" && zip -r "../$(CSAR)" TOSCA-Metadata Definitions Files asd.mf
	@ls -lh "$(CSAR)"

upload: csar
	@echo "Deleting existing rApp (if any)"
	@curl -sS -o /dev/null -w "%{http_code}\n" -X DELETE "$(RAPPMGR)/rapps/rapp-gnb-test" || true
	@echo "Uploading CSAR $(CSAR)"
	@curl -sS -X POST -F "file=@$(CSAR)" "$(RAPPMGR)/rapps/rapp-gnb-test" | jq '.'

prime:
	@echo "PRIME rapp-gnb-test"
	@curl -sS -X PUT -H "Content-Type: application/json" -d '{"primeOrder":"PRIME"}' "$(RAPPMGR)/rapps/rapp-gnb-test" | jq '.'

instantiate:
	@echo "Creating rApp instance"
	@curl -sS -X POST -H "Content-Type: application/json" \
		-d '{"rappInstanceId":"00000000-0000-0000-0000-000000000001","acm":{"instance":"instance"},"sme":{"providerFunction":"provider-function-1","serviceApis":"api-set-1","invokers":"invoker-app1"}}' \
		"$(RAPPMGR)/rapps/rapp-gnb-test/instance" | jq '.'

deploy:
	@echo "Deploying rApp instance"
	@curl -sS -X PUT -H "Content-Type: application/json" \
		-d '{"deployOrder":"DEPLOY"}' \
		"$(RAPPMGR)/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '.'

undeploy:
	@echo "Undeploying rApp instance"
	@curl -sS -X PUT -H "Content-Type: application/json" \
		-d '{"deployOrder":"UNDEPLOY"}' \
		"$(RAPPMGR)/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '.'

delete-instance:
	@echo "Deleting rApp instance"
	@curl -sS -X DELETE "$(RAPPMGR)/rapps/rapp-gnb-test/instance/00000000-0000-0000-0000-000000000001" | jq '.'

deprime:
	@echo "DEPRIME rapp-gnb-test"
	@curl -sS -X PUT -H "Content-Type: application/json" -d '{"primeOrder":"DEPRIME"}' "$(RAPPMGR)/rapps/rapp-gnb-test" | jq '.'

delete-rapp:
	@echo "Deleting rApp"
	@curl -sS -X DELETE "$(RAPPMGR)/rapps/rapp-gnb-test"

restart-manager:
	@echo "Restarting Rapp Manager (namespace: nonrtric)"
	kubectl -n nonrtric rollout restart deploy/rappmanager
	kubectl -n nonrtric rollout status deploy/rappmanager --timeout=120s
.PHONY: help build push chart-package chart-install chart-upgrade chart-uninstall csar-build csar-deploy all clean

REGISTRY ?= bmw.ece.ntust.edu.tw/infidel
IMAGE_NAME ?= rapp-gnb-test
TAG ?= latest
CHART_NAME = rapp-gnb-test
NAMESPACE ?= default
RELEASE_NAME ?= rapp-gnb-test
RAPP_MANAGER_URL ?= http://192.168.8.69:30096
CSAR_NAME ?= rapp-gnb-test.csar
RAPP_NAME ?= rapp-gnb-test

# Auto-detect container engine: prefer podman if both exist
CONTAINER_ENGINE := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)

help:
	@echo "Usage:"
	@echo "  make build              - Build Docker image"
	@echo "  make push               - Push Docker image to registry"
	@echo "  make chart-package      - Package Helm chart"
	@echo "  make chart-install      - Install Helm chart"
	@echo "  make chart-upgrade      - Upgrade Helm chart"
	@echo "  make chart-uninstall    - Uninstall Helm chart"
	@echo "  make csar-build         - Build rApp CSAR package"
	@echo "  make csar-deploy        - Deploy CSAR to rApp manager"
	@echo "  make csar-prime         - Prime the rApp"
	@echo "  make csar-instance      - Create rApp instance"
	@echo "  make csar-activate      - Deploy rApp instance"
	@echo "  make csar-full          - Full rApp deployment flow"
	@echo "  make all                - Build, push, and install"
	@echo "  make clean              - Clean generated files"
	@echo ""
	@echo "Variables:"
	@echo "  REGISTRY=$(REGISTRY)"
	@echo "  IMAGE_NAME=$(IMAGE_NAME)"
	@echo "  TAG=$(TAG)"
	@echo "  NAMESPACE=$(NAMESPACE)"
	@echo "  CONTAINER_ENGINE=$(CONTAINER_ENGINE)"

build:
	$(CONTAINER_ENGINE) build -t $(REGISTRY)/$(IMAGE_NAME):$(TAG) .

push: build
	$(CONTAINER_ENGINE) push $(REGISTRY)/$(IMAGE_NAME):$(TAG)

chart-package:
	helm package chart/
	@echo "Chart packaged: $(CHART_NAME)-*.tgz"

chart-install:
	helm install $(RELEASE_NAME) chart/ \
		--namespace $(NAMESPACE) \
		--create-namespace \
		--set image.repository=$(REGISTRY)/$(IMAGE_NAME) \
		--set image.tag=$(TAG)

chart-upgrade:
	helm upgrade $(RELEASE_NAME) chart/ \
		--namespace $(NAMESPACE) \
		--set image.repository=$(REGISTRY)/$(IMAGE_NAME) \
		--set image.tag=$(TAG)

chart-uninstall:
	helm uninstall $(RELEASE_NAME) --namespace $(NAMESPACE)

csar-build: push
	@echo "Building CSAR package..."
	@mkdir -p rapp-package/Artifacts/Deployment/HELM
	helm package chart/ --version 1.0.0 -d rapp-package/Artifacts/Deployment/HELM/
	@cd rapp-package && zip -r ../$(CSAR_NAME) . && cd ..
	@echo "CSAR created: $(CSAR_NAME)"
	@ls -lh $(CSAR_NAME)

csar-deploy: csar-build
	@echo "Uploading CSAR to rApp manager..."
	curl -X POST "$(RAPP_MANAGER_URL)/rapps/commission" \
		-F "file=@$(CSAR_NAME)"

csar-status:
	@echo "Checking rApp status..."
	curl -s "$(RAPP_MANAGER_URL)/rapps" | jq .

csar-prime:
	@echo "Priming rApp..."
	curl -i -X PUT "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)" \
		-H "Content-Type: application/json" \
		-d '{"primeOrder":"PRIME"}'

csar-instance:
	@echo "Creating rApp instance..."
	@echo "Note: Save the rappInstanceId from the response!"
	curl -X POST "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)/instance" \
		-H "Content-Type: application/json" \
		-d '{"acm":{"instance":"gnb-test-k8s-instance"},"sme":{"providerFunction":"provider-function-1","serviceApis":"api-set-1"}}' | jq .

csar-activate:
	@echo "Activating rApp instance..."
	@echo "Usage: make csar-activate INSTANCE_ID=<your-instance-id>"
	@test -n "$(INSTANCE_ID)" || (echo "ERROR: INSTANCE_ID not set" && exit 1)
	curl -i -X PUT "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)/instance/$(INSTANCE_ID)" \
		-H "Content-Type: application/json" \
		-d '{"deployOrder":"DEPLOY"}'

csar-instance-status:
	@echo "Checking instance status..."
	@echo "Usage: make csar-instance-status INSTANCE_ID=<your-instance-id>"
	@test -n "$(INSTANCE_ID)" || (echo "ERROR: INSTANCE_ID not set" && exit 1)
	curl -s "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)/instance/$(INSTANCE_ID)" | jq .

csar-undeploy:
	@echo "Undeploying rApp instance..."
	@echo "Usage: make csar-undeploy INSTANCE_ID=<your-instance-id>"
	@test -n "$(INSTANCE_ID)" || (echo "ERROR: INSTANCE_ID not set" && exit 1)
	curl -i -X PUT "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)/instance/$(INSTANCE_ID)" \
		-H "Content-Type: application/json" \
		-d '{"deployOrder":"UNDEPLOY"}'

csar-delete-instance:
	@echo "Deleting rApp instance..."
	@echo "Usage: make csar-delete-instance INSTANCE_ID=<your-instance-id>"
	@test -n "$(INSTANCE_ID)" || (echo "ERROR: INSTANCE_ID not set" && exit 1)
	curl -i -X DELETE "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)/instance/$(INSTANCE_ID)"

csar-deprime:
	@echo "Depriming rApp..."
	curl -i -X PUT "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)" \
		-H "Content-Type: application/json" \
		-d '{"primeOrder":"DEPRIME"}'

csar-delete:
	@echo "Deleting rApp..."
	curl -i -X DELETE "$(RAPP_MANAGER_URL)/rapps/$(RAPP_NAME)"

csar-full: csar-deploy
	@echo ""
	@echo "=== rApp commissioned ==="
	@echo "Next steps:"
	@echo "  1. Check status:  make csar-status"
	@echo "  2. Prime rApp:    make csar-prime"
	@echo "  3. Create instance: make csar-instance"
	@echo "  4. Deploy instance: make csar-activate INSTANCE_ID=<id-from-step-3>"

all: push chart-upgrade

clean:
	rm -f $(CHART_NAME)-*.tgz
	rm -f $(CSAR_NAME)
	rm -rf rapp-package/Artifacts
	$(CONTAINER_ENGINE) rmi $(REGISTRY)/$(IMAGE_NAME):$(TAG) 2>/dev/null || true
