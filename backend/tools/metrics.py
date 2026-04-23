def simulate_traffic():
    return []  # no longer needed but kept for compatibility


def compute_metrics(pods):
    total = len(pods)

    if total == 0:
        return {
            "error_rate": 0,
            "latency": 0,
            "throughput": 0
        }

    failed = sum(1 for p in pods if p["status"] != "Running")

    error_rate = (failed / total) * 100

    latency = sum(
        300 if "Crash" in p["status"]
        else 50 if p["status"] == "Running"
        else 150
        for p in pods
    ) / total

    return {
        "error_rate": round(error_rate, 2),
        "latency": round(latency, 2),
        "throughput": total
    }