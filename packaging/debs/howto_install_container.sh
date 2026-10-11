#!/bin/sh
# Runs packaging/debs/howto_install_check.py in a throwaway Debian container of the release under test, with the
# repository mounted read-only at /src (#307):
#
#   docker run --rm -v "$PWD:/src:ro" debian:bookworm sh /src/packaging/debs/howto_install_container.sh rpios32
#
# First the few tools the check needs come from the container's own archive (its own architecture); then the
# check turns the container into the target system and runs the pages' commands.
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -qq -y --no-install-recommends python3 curl ca-certificates gnupg > /var/log/howto-tools.log 2>&1 \
  || { cat /var/log/howto-tools.log; exit 1; }
exec python3 /src/packaging/debs/howto_install_check.py "$@"
