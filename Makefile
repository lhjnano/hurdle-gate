.PHONY: install test smoke check

install:
	pip install -e . --no-build-isolation

test:
	pytest -q

smoke:
	bash tests/run_smoke.sh

check: # self-dogfood — run the gate on this repo itself
	hurdle scan . --strict
