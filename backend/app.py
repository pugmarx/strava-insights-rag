from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from sql_rag import handle_rag_query, hybrid_query_handler
import os


# Initialize Flask app
app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    """Serve the frontend HTML file."""
    # Get the path to the frontend directory
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
    return send_from_directory(frontend_dir, 'index.html')

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "approach": "RAG"})

@app.route("/query", methods=["POST"])
def query():
    """API endpoint to handle user questions using RAG approach."""
    data = request.get_json()
    user_question = data.get("question", "").strip()
    if not user_question:
        return jsonify({"error": "No question provided"}), 400
    
    try:
        # Use RAG approach instead of SQL generation
        response = handle_rag_query(user_question, debug=True)
        print(f"RAG Response: {response}")
        
        return jsonify({
            "question": user_question,
            "response": response,
            "approach": "RAG"
        })
    
    except (ConnectionError, TimeoutError) as e:
        print(f"Connection error processing query: {e}")
        return jsonify({"error": "Service temporarily unavailable"}), 503
    except ValueError as e:
        print(f"Validation error processing query: {e}")
        return jsonify({"error": "Invalid query format"}), 400
    except Exception as e:
        print(f"Unexpected error processing query: {e}")
        return jsonify({"error": "Failed to process query"}), 500

@app.route("/hybrid-query", methods=["POST"])
def hybrid_query():
    """API endpoint for hybrid RAG+SQL approach."""
    data = request.get_json()
    user_question = data.get("question", "").strip()
    if not user_question:
        return jsonify({"error": "No question provided"}), 400
    
    try:
        # Use hybrid approach that combines RAG with SQL when needed
        response = hybrid_query_handler(user_question)
        print(f"Hybrid Response: {response}")
        
        return jsonify({
            "question": user_question,
            "response": response,
            "approach": "Hybrid RAG+SQL"
        })
    
    except (ConnectionError, TimeoutError) as e:
        print(f"Connection error processing hybrid query: {e}")
        return jsonify({"error": "Service temporarily unavailable"}), 503
    except ValueError as e:
        print(f"Validation error processing hybrid query: {e}")
        return jsonify({"error": "Invalid query format"}), 400
    except Exception as e:
        print(f"Unexpected error processing hybrid query: {e}")
        return jsonify({"error": "Failed to process query"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
