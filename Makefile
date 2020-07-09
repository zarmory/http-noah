SHELL = /bin/bash

.PHONY: release
release: test
	bump2version --verbose $${PART:-patch} --tag-message "Release {new_version}"
	git push
	git push --tags

.PHONY: upload
upload:
	./setup.py sdist upload

.PHONY: restview
restview:
	restview README.rst -w README.rst

.PHONY: test-python
test-python:
	nosetests --quiet --nocapture --nologcapture tests

.PHONY: test-style
test-style:
	pre-commit run --all-files

.PHONY: test-docs
test-docs:
	python setup.py checkdocs

.PHONY: test
test: test-python test-style test-docs

bootstrap:
	ln -sf .envrc.linkme .envrc
	direnv allow
	pipenv install --dev
	pipenv run pip install -e .
	pipenv run pre-commit install
