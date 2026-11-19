#!/usr/bin/env bash
# Aggregate one GPS day (SQLite) into trips: route_id,trip_id,vehicle_id,first_ts,last_ts,n_positions (no header).
# Usage: scripts/gps_trips.sh 2026_10_14
set -euo pipefail
d="$1"; mkdir -p outputs/gps
sqlite3 -csv "data/gps/bus_movements_${d}.db" "select cast(route_id as integer), trip_id, vehicle_id, min(cast(timestamp as integer)), max(cast(timestamp as integer)), count(*) from vehicle_feed where route_id is not null group by 1,2,3;" > "outputs/gps/trips_${d}.csv"
