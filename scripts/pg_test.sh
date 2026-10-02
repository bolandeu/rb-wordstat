#!/usr/bin/env bash
# Run the test suite against a throwaway PostgreSQL 16 in Docker: the PostgreSQL
# tests (tests/test_db.py) run only when TEST_DATABASE_URL is set, and this is the
# only way to set it. Arguments go to pytest: scripts/pg_test.sh -q tests/test_db.py
#
# Never a fixed port or a shared container: Docker picks a free port on 127.0.0.1
# and the container has a name of its own, so two tools testing at once can't reach
# (and drop tables in) each other's database. The container is removed on exit,
# whatever happens. TEST_DATABASE_URL is set only once the server answers over TCP.
set -euo pipefail

image="postgres:16-alpine"
name="pg-test-$(basename "$(pwd)")-$$-${RANDOM}"

docker run -d --rm --name "$name" -e POSTGRES_PASSWORD=test -p 127.0.0.1::5432 "$image" >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT INT TERM

port="$(docker port "$name" 5432/tcp | head -n 1 | sed 's/.*://')"
# Over TCP inside the container: during initdb the server listens on the socket only,
# so a socket check would pass before the real server is up.
for _ in $(seq 1 60); do
    if docker exec "$name" pg_isready -q -h 127.0.0.1 -U postgres; then
        ready=1
        break
    fi
    sleep 0.5
done
if [ -z "${ready:-}" ] || [ -z "$port" ]; then
    echo "pg_test: PostgreSQL in container $name did not come up" >&2
    docker logs "$name" 2>&1 | tail -n 20 >&2
    exit 1
fi

TEST_DATABASE_URL="postgresql://postgres:test@127.0.0.1:${port}/postgres" uv run pytest "$@"
