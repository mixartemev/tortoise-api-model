PACKAGE := x_model
VENV := venv
VPYTHON := . $(VENV)/bin/activate && python

.PHONY: all install pre-commit test clean build twine patch

all:
	make install test clean build

install: $(VENV)
	$(VPYTHON) -m pip install -e .[dev]; make pre-commit
pre-commit: .pre-commit-config.yaml
	pre-commit install -t pre-commit -t post-commit -t pre-push

test:
	$(VPYTHON) -m pytest

clean: .pytest_cache dist $(PACKAGE).egg-info
	rm -rf .pytest_cache dist/* $(PACKAGE).egg-info $(PACKAGE)/__pycache__ dist/__pycache__

build:
	$(VPYTHON) -m build; make twine
twine: dist
	$(VPYTHON) -m twine upload dist/* --skip-existing

patch:
	git tag `$(VPYTHON) -m setuptools_scm --strip-dev`; git push --tags --prune -f