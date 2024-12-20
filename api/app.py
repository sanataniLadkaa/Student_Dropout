import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import joblib
from sklearn.preprocessing import LabelEncoder
from fastapi import Request

app = FastAPI()

# Static files (for storing generated charts and prediction results)
# app.mount("/static", StaticFiles(directory="static"), name="static")
# templates = Jinja2Templates(directory="templates")

# # Create directories if they do not exist
# os.makedirs('temp', exist_ok=True)

import os

# Get current file directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Update paths
MODEL_DIR = os.path.join(BASE_DIR, "models")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Load models and label encoders
model_rf = joblib.load(os.path.join(MODEL_DIR, "random_forest_model.pkl"))
label_encoder_qualification = joblib.load(os.path.join(MODEL_DIR, "label_encoder_qualification.pkl"))
label_encoder_area = joblib.load(os.path.join(MODEL_DIR, "label_encoder_area.pkl"))

# Mount static files and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Safe Label Encoding
def safe_label_encode(label_encoder, data_column):
    if not hasattr(label_encoder, 'classes_'):
        label_encoder.fit(data_column)

    known_classes = set(label_encoder.classes_)
    data_column = data_column.apply(lambda x: x if x in known_classes else 'Unknown')
    
    if 'Unknown' not in label_encoder.classes_:
        label_encoder.classes_ = np.append(label_encoder.classes_, 'Unknown')

    return label_encoder.transform(data_column)

# Function to preprocess uploaded data
def preprocess_uploaded_data_for_prediction(data):
    data['parents_qualification'] = safe_label_encode(label_encoder_qualification, data['parents_qualification'])
    data['area'] = safe_label_encode(label_encoder_area, data['area'])
    return data

# Function to scale dropout probabilities
def scale_probabilities_to_10(probabilities, threshold=0.5):
    scaled = probabilities.copy()
    scaled[scaled <= threshold] = 0  # Non-dropout, set to 0
    scaled[scaled > threshold] = (scaled[scaled > threshold] - threshold) / (1 - threshold) * 10
    return scaled

# Function to plot the distribution of scaled probabilities
def plot_scaled_probability_distribution(data):
    sorted_data = data['Scaled_Dropout_Probability'].sort_values()

    plt.figure(figsize=(8, 5))
    plt.plot(sorted_data.values, range(len(sorted_data)), color='blue', label='Scaled Dropout Probability')
    plt.title('Progressive Line Graph of Scaled Dropout Probabilities', fontsize=14)
    plt.xlabel('Scaled Probability (1 to 10)', fontsize=12)
    plt.ylabel('Index (Sorted by Probability)', fontsize=12)
    plt.legend()
    plt.grid(axis='x', linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig("static/prediction_chart.png")
    plt.close()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/predict", response_class=HTMLResponse)
async def predict(request: Request, file: UploadFile = File(...)):
    try:
        # Read uploaded file content
        file_content = file.file.read()
        data = pd.read_csv(pd.compat.StringIO(file_content.decode("utf-8")))
        
        # Preprocess data and make predictions
        processed_data = preprocess_uploaded_data_for_prediction(data)
        probabilities = model_rf.predict_proba(processed_data)
        predictions = model_rf.predict(processed_data)

        # Scale probabilities and save results
        dropout_probabilities = probabilities[:, 1]
        scaled_probabilities = scale_probabilities_to_10(dropout_probabilities)
        data['Dropout_Prediction'] = predictions
        data['Scaled_Dropout_Probability'] = scaled_probabilities
        
        # Save results to a CSV in memory
        result_csv = data.to_csv(index=False)

        # Generate plot in memory
        plot_scaled_probability_distribution(data)

        # Return results
        return templates.TemplateResponse("results.html", {
            "request": request,
            "prediction_done": True,
            "result_file": result_csv,
            "chart_file": "/static/prediction_chart.png"
        })

    except Exception as e:
        return {"error": str(e)}


@app.post("/get_student_details", response_class=HTMLResponse)
async def get_student_details_endpoint(
    request: Request,
    student_index: int = Form(None),
    student_id: str = Form(None)
):
    try:
        # Load the results from the previously saved CSV
        data = pd.read_csv("static/dropout_predictions_scaled.csv")
        
        # Retrieve student details
        if student_index is not None:
            student_details = data.iloc[student_index].to_dict()
        elif student_id is not None and 'Student_ID' in data.columns:
            student_details = data[data['Student_ID'] == student_id].to_dict(orient='records')
            student_details = student_details[0] if student_details else None
        else:
            student_details = None

        # If student details are found, pass them to the template
        if student_details:
            return templates.TemplateResponse("student_details.html", {
                "request": request,
                "student_details": student_details,
                "student_found": True
            })
        else:
            return templates.TemplateResponse("student_details.html", {
                "request": request,
                "student_found": False,
                "error_message": "Student not found. Please check the input."
            })

    except Exception as e:
        return {"error": str(e)}

