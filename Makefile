PYTHON ?= python
LOCAL = $(PYTHON) infra/local/manage.py
.PHONY: init doctor config infra-up up down destroy db-reset db-load test e2e fmt sample build infra-test status logs
init doctor config infra-up up down test e2e fmt sample build infra-test status logs:
	$(LOCAL) $@
destroy:
	$(LOCAL) destroy $(if $(filter 1,$(CONFIRM)),--yes,)
db-reset:
	$(LOCAL) db-reset $(if $(filter 1,$(CONFIRM)),--yes,)
db-load:
	$(LOCAL) db-load --file "$(BTS_FILE)"
