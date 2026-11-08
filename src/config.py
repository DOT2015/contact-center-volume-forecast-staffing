"""Planning assumptions shared by the generator and the analysis (simulated values)."""
CENTER_TZ = "America/Chicago"
OPEN_HOUR, CLOSE_HOUR = 7, 21          # local; 28 half-hour intervals per open day
INTERVAL_MIN = 30
SL_TARGET, SL_SECONDS = 0.80, 60       # answer 80% of calls within 60 seconds
SHRINKAGE = 0.32                       # breaks, training, meetings, absence, PTO
HOURS_PER_FTE_WEEK = 40.0
ROSTER_FTE = 48                        # simulated current agent roster (Q4-2025 scheduled hours imply ~48 FTE)
TRAINING_WEEKS = 6
OT_RATE = 38.0                         # $ per overtime hour, loaded
HISTORY_START, HISTORY_END = "2024-01-01", "2025-12-31"
FORECAST_START, FORECAST_END = "2026-01-01", "2026-03-31"
PRICE_NOTICE_2025, PRICE_NOTICE_2026 = "2025-09-15", "2026-02-02"
QUEUES = ["billing", "tech_support", "moves_new_service", "cancellations", "outage"]
