import psycopg2
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from dotenv import load_dotenv
import os
import ast

# Load env vars
load_dotenv()
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")

def fetch_activities():
    conn = psycopg2.connect(
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        host=POSTGRES_HOST,
        port=POSTGRES_PORT
    )
    cur = conn.cursor()
    cur.execute("SELECT activity_id, activity_type, embedding FROM activities")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    # Convert to DataFrame
    data = pd.DataFrame(rows, columns=["activity_id", "activity_type", "embedding"])
    #data["embedding"] = data["embedding"].apply(lambda x: np.array(x))
    data["embedding"] = data["embedding"].apply(
        lambda x: np.array(ast.literal_eval(x)) if isinstance(x, str) else x
    )
    return data

def reduce_and_plot(data, method="pca", filename="embedding_plot.png"):
    embeddings = np.stack(data["embedding"].values)
    
    if method == "pca":
        reducer = PCA(n_components=2)
    elif method == "tsne":
        reducer = TSNE(n_components=2, perplexity=5, random_state=42)
    else:
        raise ValueError("Method must be 'pca' or 'tsne'")
    
    reduced = reducer.fit_transform(embeddings)
    data["x"] = reduced[:, 0]
    data["y"] = reduced[:, 1]

    # Plot
    plt.figure(figsize=(10, 6))
    sns.scatterplot(data=data, x="x", y="y", hue="activity_type", palette="tab10", s=80)
    plt.title(f"{method.upper()} Projection of Activity Embeddings")
    plt.xlabel("Component 1")
    plt.ylabel("Component 2")
    plt.legend(title="Activity Type")
    plt.tight_layout()
    #plt.show()
    plt.savefig(filename, dpi=300)
    plt.close()
    print(f"✅ Saved plot to {filename}")

# Run it
data = fetch_activities()
reduce_and_plot(data, method="pca", filename="pca.png") 
reduce_and_plot(data, method="tsne", filename="tsne.png") 
