.PHONY: lint syntax test

PYTHON ?= python3
ANSIBLE_PLAYBOOK ?= ansible-playbook
ANSIBLE_LINT ?= ansible-lint

syntax:
	cd ansible && $(ANSIBLE_PLAYBOOK) playbooks/preflight.yml --syntax-check
	cd ansible && $(ANSIBLE_PLAYBOOK) playbooks/site.yml --syntax-check
	cd ansible && $(ANSIBLE_PLAYBOOK) playbooks/verify.yml --syntax-check
	cd ansible && $(ANSIBLE_PLAYBOOK) playbooks/demo_company.yml --syntax-check
	cd ansible && $(ANSIBLE_PLAYBOOK) -i tests/smoke-inventory.yml tests/smoke-user.yml --syntax-check

lint:
	cd ansible && $(ANSIBLE_LINT) --profile production playbooks roles tests/*.yml inventories/ubuntu

test:
	cd ansible && $(PYTHON) -m unittest discover -s tests -v
