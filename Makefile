PYTHON ?= python
IMAGE  ?= lux-ledger

.PHONY: install data run run-dirty test lint docker-build docker-run clean

install:
	$(PYTHON) -m pip install -r requirements.txt

data:
	$(PYTHON) -m src.generate_data

run:
	$(PYTHON) -m src.main --journal data/journal_clean.csv --faia

run-dirty:
	$(PYTHON) -m src.main --journal data/journal_dirty.csv --faia

test:
	$(PYTHON) -m pytest

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm \
		-v "$(CURDIR)/data:/app/data" \
		-v "$(CURDIR)/output:/app/output" \
		$(IMAGE) --journal data/journal_dirty.csv --faia

clean:
	rm -rf output/*.xlsx output/*.txt output/*.xml
	find . -name '__pycache__' -type d -exec rm -rf {} +
