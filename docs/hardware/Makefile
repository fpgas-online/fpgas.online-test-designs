# Makefile for docs/hardware/ — download/update embedded images

ACORN_PINMAP_RPI5_URL := https://docs.google.com/drawings/d/e/2PACX-1vSgm27sxCnNBl1z-YXBQwRjnwbQ4rn_oTPVdNCXS6lP88Txsvgq6D5eqQHUqY_RC0g1kgFqWFuoeGWw/pub?w=960&h=720
ACORN_PINMAP_RPI5_EDIT := https://docs.google.com/drawings/d/1HCOHrvFzj1fIf6DqDMzcqoQgjaD5ZvM39MtgvrAjqEU/edit

ACORN_PINMAP_CB_URL := https://docs.google.com/drawings/d/e/2PACX-1vRHU8JcM0a6r9LVoegaXp-qnnH0VYNzWQm6r0OkAlmZU2ZktYgYAY4bpSCpImWey2TzYIjer41MRgRH/pub?w=1340&h=833
ACORN_PINMAP_CB_EDIT := https://docs.google.com/drawings/d/1hKt7O_IR60R6uT8VOg2O9PEAp4a8fNmp7BFqi3YYjgQ/edit

.PHONY: all clean

all: acorn-pinmap-rpi5-wiring.png acorn-pinmap-computeblade-wiring.png

acorn-pinmap-rpi5-wiring.png:
	curl -sL '$(ACORN_PINMAP_RPI5_URL)' -o $@
	@echo "Downloaded $@ from Google Drawings"
	@echo "Edit: $(ACORN_PINMAP_RPI5_EDIT)"

acorn-pinmap-computeblade-wiring.png:
	curl -sL '$(ACORN_PINMAP_CB_URL)' -o $@
	@echo "Downloaded $@ from Google Drawings"
	@echo "Edit: $(ACORN_PINMAP_CB_EDIT)"

clean:
	rm -f acorn-pinmap-rpi5-wiring.png acorn-pinmap-computeblade-wiring.png
