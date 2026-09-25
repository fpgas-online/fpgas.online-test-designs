include ../../mk/common.mk

.PHONY: test discover unittest clean

# No gateware: the demo board's RP2 is the stimulus. These targets are meant
# to be run on the Raspberry Pi that carries the board.

test:
	sudo python3 host/check_tt_pmod_wiring.py

discover:
	sudo python3 host/check_tt_pmod_wiring.py --discover

# Dev-machine tests against the simulated board.
unittest:
	uv run --extra dev pytest host/

clean:
	rm -rf host/__pycache__ .pytest_cache
