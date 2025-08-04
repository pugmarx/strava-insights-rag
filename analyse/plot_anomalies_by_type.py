import json
import matplotlib.pyplot as plt
import pandas as pd
import math

# Load anomaly data
with open("univariate_anomalies.json", "r") as f:
    data = json.load(f)

summary = data["summary"]

# Units for plot labels
units = {"distance": "km", "duration": "min", "avg_speed": "km/h"}

# Filter relevant entries
filtered_entries = [
    entry for entry in summary
    if entry["outliers"] and len(entry["outliers"]) >= 10
]

# Setup grid layout
n = len(filtered_entries)
cols = 2
rows = math.ceil(n / cols)
fig, axes = plt.subplots(rows, cols, figsize=(14, rows * 4))
axes = axes.flatten() if n > 1 else [axes]

for i, entry in enumerate(filtered_entries):
    activity_type = entry["activity_type"]
    metric = entry["metric"]
    df_outliers = pd.DataFrame(entry["outliers"])

    ids = df_outliers["id"].tolist()
    values = df_outliers[metric].tolist()

    ax = axes[i]
    ax.set_title(f"{activity_type} — {metric.capitalize()} (anomalies)")
    ax.set_xlabel("Outlier Index")
    ax.set_ylabel(f"{metric} ({units[metric]})")

    ax.scatter(range(len(values)), values, color="red")
    for j, val in enumerate(values):
        ax.annotate(str(ids[j]), (j, val), fontsize=7, xytext=(5, 3), textcoords="offset points")

    ax.grid(True)

# Hide unused subplots
for j in range(i + 1, len(axes)):
    fig.delaxes(axes[j])

plt.tight_layout()
plt.savefig("combined_anomaly_plots.png")
plt.close()
print("Saved: combined_anomaly_plots.png")
