from flask import Flask, render_template, request, jsonify
import pandas as pd
import os
from datetime import datetime
from groq import Groq
import requests
from bs4 import BeautifulSoup

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# Ensure the uploads folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Set Groq API key
os.environ["GROQ_API_KEY"] = ""
client = Groq()

# Global variable to store transactions
transactions = []

# Define routes and functions below
@app.route('/', methods=['GET', 'POST'])
def index():
    global transactions
    if request.method == 'POST':
        file = request.files['file']
        if file:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)

            if file.filename.endswith('.csv'):
                data = pd.read_csv(filepath)
            elif file.filename.endswith('.xlsx'):
                # Read the Excel file, skipping metadata rows
                data = pd.read_excel(filepath, skiprows=5)  # Skip the first 5 rows
            else:
                return "Unsupported file format. Please upload a CSV or Excel file."

            # Rename columns to lowercase for consistency
            data.rename(columns=lambda x: x.strip().lower(), inplace=True)

            # Check if required columns are present
            required_columns = ['date', 'amount']
            missing_columns = [col for col in required_columns if col not in data.columns]
            if missing_columns:
                return f"The uploaded file is missing the following required columns: {', '.join(missing_columns)}"

            # Convert the 'date' column to datetime
            data['date'] = pd.to_datetime(data['date'])

            # Convert the 'amount' column to numeric (handle currency symbols and commas)
            data['amount'] = data['amount'].replace(r'[\$,]', '', regex=True).astype(float)

            # Store the transactions globally
            transactions = data.to_dict('records')

            # Perform analysis
            monthly_expenses = data.groupby(data['date'].dt.to_period('M'))['amount'].sum()
            monthly_income = data[data['amount'] > 0]['amount'].sum()
            savings_rate = (monthly_income - data[data['amount'] < 0]['amount'].sum()) / monthly_income

            # Prepare summary
            summary = {
                "total_income": float(monthly_income),
                "total_expenses": float(data[data['amount'] < 0]['amount'].sum()),
                "savings_rate": float(savings_rate * 100),
                "monthly_expenses": monthly_expenses.to_dict()
            }

            # Render results
            return render_template('index.html', summary=summary, uploaded=True)

    return render_template('index.html', summary=None, uploaded=False)

@app.route('/chat', methods=['POST'])
def chat():
    global transactions
    user_input = request.json.get('message')

    # Handle financial queries
    if any(keyword in user_input.lower() for keyword in ["income", "expenses", "savings", "transactions"]):
        if "total income" in user_input.lower():
            total_income = sum(t['amount'] for t in transactions if t['amount'] > 0)
            return jsonify({"response": f"Your total income is ${total_income:.2f}."})
        elif "total expenses" in user_input.lower():
            total_expenses = sum(t['amount'] for t in transactions if t['amount'] < 0)
            return jsonify({"response": f"Your total expenses are ${total_expenses:.2f}."})
        else:
            # Use Groq for complex financial queries
            response = query_groq(user_input)
            return jsonify({"response": response})
    else:
        # Handle general queries
        web_answer = fetch_web_answer(user_input)
        if web_answer.startswith("Error"):
            # Fallback to Groq if web scraping fails
            response = query_groq(user_input)
            return jsonify({"response": response})
        else:
            return jsonify({"response": web_answer})

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    global transactions
    new_transaction = request.json

    # Validate the new transaction
    try:
        new_transaction['date'] = datetime.strptime(new_transaction['date'], '%Y-%m-%d')
        new_transaction['amount'] = float(new_transaction['amount'])
        transactions.append(new_transaction)
        return jsonify({"status": "success", "message": "Transaction added successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

def query_groq(prompt):
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="mixtral-8x7b-32768",  # Use the Groq model
            temperature=0.7,
            max_tokens=1024,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error querying Groq: {str(e)}"

def fetch_web_answer(query):
    try:
        # Search Google and fetch the first result
        url = f"https://www.google.com/search?q={query}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract the first result snippet
        result = soup.find("div", class_="BNeawe").text
        return result
    except Exception as e:
        return f"Error fetching web answer: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)
