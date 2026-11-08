# make all = generate -> load -> clean -> analyze -> figures -> dashboard -> report -> powerbi
PY ?= python3

.PHONY: all generate load clean analyze figures dashboard report powerbi test reset

all: generate load clean analyze figures dashboard report powerbi

generate:
	$(PY) src/generate_data.py > /dev/null

load:
	$(PY) src/load.py --raw-only

clean:
	$(PY) src/load.py --transform-only

analyze:
	$(PY) src/analysis.py

figures:
	$(PY) src/figures.py

dashboard:
	$(PY) src/dashboard.py

report:
	$(PY) src/report.py

powerbi:
	$(PY) src/export_powerbi.py

test:
	$(PY) -m pytest -q

# remove all generated data and outputs (keeps committed sample/truth until regenerated)
reset:
	rm -rf data/raw data/warehouse.duckdb reports/tables reports/results.json
