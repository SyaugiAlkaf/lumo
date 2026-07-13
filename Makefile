WASM_DIR := contracts/target/wasm32v1-none/release

.PHONY: gate-p0 gate-p1 build spec

gate-p0:
	acceptance/acceptance.sh --gate P0

gate-p1:
	acceptance/acceptance.sh --gate P1

build:
	cd contracts && stellar contract build

spec: build
	mkdir -p bindings
	stellar contract info interface --wasm $(WASM_DIR)/amanah_escrow.wasm \
		--output json-formatted > bindings/escrow.json
	stellar contract info interface --wasm $(WASM_DIR)/amanah_policy_account.wasm \
		--output json-formatted > bindings/policy_account.json
