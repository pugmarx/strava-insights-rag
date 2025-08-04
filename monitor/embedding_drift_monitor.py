import ast
import json
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sklearn.metrics.pairwise import cosine_distances

load_dotenv()


# Load DB config from environment
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT", 5432),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
    "dbname": os.getenv("POSTGRES_DB"),
}

def fetch_embeddings_by_year():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT EXTRACT(YEAR FROM timestamp) AS yr, embedding
        FROM activities
        WHERE embedding IS NOT NULL
    """)
    rows = cursor.fetchall()
    conn.close()

    data = {}
    for year, vector in rows:
        # Convert string representation to numpy array
        if isinstance(vector, str):
            try:
                # Try parsing as JSON first
                vector = json.loads(vector)
            except json.JSONDecodeError:
                # If JSON fails, try ast.literal_eval (safer than eval)
                try:
                    vector = ast.literal_eval(vector)
                except (ValueError, SyntaxError):
                    print(f"Warning: Could not parse vector for year {year}, skipping...")
                    continue
        
        vector = np.array(vector, dtype=np.float32)
        year = int(year)
        data.setdefault(year, []).append(vector)

    return {year: np.stack(vectors) for year, vectors in data.items() if len(vectors) > 0}

def compute_centroids(year_embeddings):
    centroids = {}
    for year, vectors in year_embeddings.items():
        centroids[year] = vectors.mean(axis=0)
    return centroids

def plot_drift(drift_series, baseline_year):
    plt.figure(figsize=(10, 5))
    plt.plot(drift_series.index, drift_series.values, marker="o")
    plt.axhline(0.3, color="red", linestyle="--", label="drift alert threshold")
    plt.title(f"Embedding Drift from Baseline Year {baseline_year}")
    plt.xlabel("Year")
    plt.ylabel("Cosine Distance from Baseline")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("embedding_drift_plot.png")
    print(">> Saved plot as embedding_drift_plot.png")

def main():
    print(">> Fetching embeddings from database...")
    year_embeddings = fetch_embeddings_by_year()
    if not year_embeddings:
        print("** Warning: No embeddings found.")
        return

    print(">> Computing yearly centroids...")
    centroids = compute_centroids(year_embeddings)

    # Choose baseline year = peak activity year
    activity_counts = {yr: len(vectors) for yr, vectors in year_embeddings.items()}
    baseline_year = max(activity_counts, key=activity_counts.get)
    print(f">> Using {baseline_year} as baseline (most active year)")

    baseline_vector = centroids[baseline_year]
    drift_values = {
        year: cosine_distances([baseline_vector], [centroid])[0][0]
        for year, centroid in centroids.items()
    }

    drift_series = pd.Series(drift_values).sort_index()
    print(">> Drift values:")
    print(drift_series)

    # Alert if any drift exceeds threshold (e.g., 0.3)
    threshold = 0.3
    alerts = drift_series[drift_series > threshold]
    if not alerts.empty:
        print("** Drift Alert: The following years exceed the threshold:")
        print(alerts)

    plot_drift(drift_series, baseline_year)

if __name__ == "__main__":
    main()
