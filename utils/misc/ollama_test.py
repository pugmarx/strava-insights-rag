import requests
import json

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "mistral"  # Update if using a different model

def query_ollama(prompt):
    """Send a query to the local Ollama LLM and return the response."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        return response.json().get("response", "No response received")
    except requests.exceptions.RequestException as e:
        return f"Error querying Ollama: {e}"

# Example usage
question = "Why is the sky blue?"
answer = query_ollama(question)
print("Ollama response:", answer)
