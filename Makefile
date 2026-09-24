.PHONY: install test smoke check

install:
	pip install -e . --no-build-isolation

test:
	pytest -q

smoke:
	bash tests/run_smoke.sh

check: # self-dogfood — 자기 자신을 게이트
	hurdle scan . --strict
