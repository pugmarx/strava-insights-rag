import json
import matplotlib.pyplot as plt
import pandas as pd

# Load anomaly data
with open("univariate_anomalies.json", "r") as f:
    data = json.load(f)

summary = data["summary"]

# Define unit conversions
def convert_metric(metric, value):
    if metric == "distance":
        return value / 1000  # meters to km
    elif metric == "duration":
        return value / 60    # seconds to minutes
    else:
        return value         # leave avg_speed as-is (meters/sec)

# For each metric, generate a separate plot
for metric_result in summary:
    metric = metric_result["metric"]
    outliers = metric_result["outliers"]

    if not outliers:
        print(f"No outliers found for '{metric}'. Skipping plot.")
        continue

    df_outliers = pd.DataFrame(outliers)
    outlier_ids = df_outliers["id"].tolist()

    # Apply conversions
    df_outliers[metric] = df_outliers[metric].apply(lambda x: convert_metric(metric, x))

    # Prepare values for plotting
    values = df_outliers[metric].tolist()

    # Plotting
    plt.figure(figsize=(10, 5))
    unit = "km" if metric == "distance" else "min" if metric == "duration" else "m/s"
    plt.title(f"{metric.capitalize()} (in {unit}) — Outlier Activity IDs")
    plt.xlabel("Activity Index")
    plt.ylabel(f"{metric} ({unit})")

    plt.scatter(range(len(values)), values, color="blue", label="Outlier values")
    plt.scatter(range(len(values)), values, color="red", zorder=3)

    for i, val in enumerate(values):
        plt.annotate(str(outlier_ids[i]), (i, val), fontsize=8, xytext=(5, 3), textcoords="offset points")

    plt.grid(True)
    plt.tight_layout()

    filename = f"{metric}_outliers.png"
    plt.savefig(filename)
    plt.close()

    print(f"Saved: {filename}")
