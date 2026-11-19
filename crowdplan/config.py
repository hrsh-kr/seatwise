"""Tunable assumptions. Every number here is an assumption, documented in docs/TECHNICAL_NOTE.md."""

# Bus capacity by body length (metres). seats = seated passengers, crush = crush-load capacity.
SEATS = {12: 35, 9: 25}
CRUSH = {12: 75, 9: 50}
DEFAULT_LENGTH_M = 12

# Level thresholds on average on-board load:
#   load <= seats                -> 0 "Seats available"
#   load <= STANDING_FRAC*crush  -> 1 "Standing room"
#   otherwise                    -> 2 "Crowded"
STANDING_FRAC = 0.8
LEVEL_LABELS = ["Seats available", "Standing room", "Crowded"]

# Riders that never appear in ticket data (monthly/student passes, ticketless).
# Multiplies the ticket-derived load. Unknown for Delhi: treat as a sensitivity parameter.
UNTRACKED_UPLIFT = 1.15

BUCKET_MIN = 30            # time-of-day bucket width
MAX_TRIP_MATCH_MIN = 20    # max gap between a ticket's implied trip start and a scheduled trip

# Planner
WALK_KMH = 4.5
WALK_DETOUR = 1.3          # straight-line -> walking distance
MAX_WALK_M = 1000
TRANSFER_BUFFER_S = 120
CROWD_WEIGHT = {0: 0.0, 1: 0.25, 2: 0.8, None: 0.15}   # penalty minutes per ride-minute
COMFORT_W = {"fastest": 0.0, "balanced": 1.0, "comfortable": 3.0}
