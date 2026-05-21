from typing import List, Dict
import statistics


def detect_anomalies(weekly_values: List[float]) -> Dict:
    """Simple anomaly detection: flag weeks that are > 50% away from the 4-week mean.

    Returns a dict with mean, stdev, and list of anomaly indices/values.
    """
    if not weekly_values:
        return {"mean": 0.0, "stdev": 0.0, "anomalies": []}
    mean = statistics.mean(weekly_values)
    stdev = statistics.pstdev(weekly_values) if len(weekly_values) > 1 else 0.0
    anomalies = []
    for idx, v in enumerate(weekly_values):
        if mean == 0:
            continue
        if abs(v - mean) / mean > 0.5:
            anomalies.append({"index": idx, "value": v, "deviation_pct": round((v-mean)/mean, 3)})
    return {"mean": mean, "stdev": stdev, "anomalies": anomalies}


def recommend_rules(weekly_values: List[float], adjustments: Dict = None, deductions: Dict = None) -> Dict:
    """Very small rules recommender: suggests checks based on variance and totals."""
    adjustments = adjustments or {}
    deductions = deductions or {}
    recs = []
    if len(weekly_values) >= 2:
        mean = statistics.mean(weekly_values)
        variance = statistics.pstdev(weekly_values)
        if variance / (mean if mean else 1) > 0.25:
            recs.append("High variance in weekly pay — verify hours/overtime and reporting.")
    if sum(adjustments.values()) > 500:
        recs.append("Large adjustments total — confirm approval and reason codes.")
    if deductions.get("tax", 0) / (mean if (mean:= (statistics.mean(weekly_values) if weekly_values else 1)) else 1) > 0.3:
        recs.append("Tax seems unusually high relative to weekly mean.")
    if not recs:
        recs.append("No immediate rule recommendations — data looks normal.")
    return {"recommendations": recs}
