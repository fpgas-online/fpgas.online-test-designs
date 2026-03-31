# Makefile for docs/hardware/ — download/update embedded images

ACORN_WIRING_DIAGRAM_URL := https://docs.google.com/drawings/d/e/2PACX-1vSgm27sxCnNBl1z-YXBQwRjnwbQ4rn_oTPVdNCXS6lP88Txsvgq6D5eqQHUqY_RC0g1kgFqWFuoeGWw/pub?w=960&h=720
ACORN_WIRING_DIAGRAM_EDIT := https://docs.google.com/drawings/d/1HCOHrvFzj1fIf6DqDMzcqoQgjaD5ZvM39MtgvrAjqEU/edit

.PHONY: all clean

all: acorn-wiring-diagram.png

acorn-wiring-diagram.png:
	curl -sL '$(ACORN_WIRING_DIAGRAM_URL)' -o $@
	@echo "Downloaded $@ from Google Drawings"
	@echo "Edit: $(ACORN_WIRING_DIAGRAM_EDIT)"

clean:
	rm -f acorn-wiring-diagram.png
