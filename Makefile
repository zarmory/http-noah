SHELL = /bin/bash

.PHONY: release
release: test
	bump2version --verbose $${PART:-patch}
	git push
	git push --tags

.PHONY: upload
upload:
	./setup.py sdist upload

.PHONY: restview
restview:
	restview README.rst -w README.rst

.PHONY: test
test:
	nosetests --quiet --nocapture --nologcapture tests
	python setup.py checkdocs
	pre-commit run --all-files

bootstrap:
	ln -sf .envrc.tmpl .envrc
	direnv allow
	pipenv install --dev
	pipenv run pip install -e .
	pipenv run pre-commit install
