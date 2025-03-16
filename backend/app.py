from flask import Flask, request, jsonify
from sql_generator import generate_sql_query, execute_sql_query

# Initialize Flask app
app = Flask(__name__)

@app.route("/query", methods=["POST"])
def query():
    """API endpoint to handle user questions."""
    data = request.get_json()
    user_question = data.get("question", "").strip()

    if not user_question:
        return jsonify({"error": "No question provided"}), 400

    sql_query = generate_sql_query(user_question)
    print(f"Generated SQL: {sql_query}")

    if sql_query.lower().startswith("error"):
        return jsonify({"error": sql_query}), 400  # Changed from 500 to 400

    results = execute_sql_query(sql_query)

    if results is None:
        return jsonify({"error": "Failed to execute query"}), 500

    return jsonify({"sql_query": sql_query, "results": results})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
