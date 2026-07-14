WASM_DIR := contracts/target/wasm32v1-none/release

.PHONY: gate-p0 gate-p1 gate-p2 gate-p3 gate-p4 demo live-check build spec

gate-p0:
	acceptance/acceptance.sh --gate P0

gate-p1:
	acceptance/acceptance.sh --gate P1

gate-p2:
	acceptance/acceptance.sh --gate P2

gate-p3:
	acceptance/acceptance.sh --gate P3

gate-p4:
	acceptance/acceptance.sh

demo:
	scripts/demo.sh

live-check:
	@test -n "$$LUMO_LLAMA_URL" || { echo "set LUMO_LLAMA_URL to the llama-server base URL"; exit 1; }
	.venv/bin/python -m pytest tests/test_llm_live.py -q

build:
	cd contracts && stellar contract build

spec: build
	mkdir -p bindings
	stellar contract info interface --wasm $(WASM_DIR)/lumo_escrow.wasm \
		--output json-formatted > bindings/escrow.json
	stellar contract info interface --wasm $(WASM_DIR)/lumo_policy_account.wasm \
		--output json-formatted > bindings/policy_account.json
