import random
import time
from dash import Dash, html, dcc
from dash.dependencies import Input, Output
from dash import callback_context
import plotly.graph_objs as go
import pandas as pd
from firebase_admin import credentials, firestore
import paho.mqtt.client as mqtt
import firebase_admin
from sklearn.linear_model import LinearRegression
from twilio.rest import Client
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Initialize Firebase
cred = credentials.Certificate("iot-energy-monitoring-------------------------------.json") #needed json file for certificate
firebase_admin.initialize_app(cred)
db = firestore.client()

# STEP MQTT setup
broker = "mqtt.eclipseprojects.io"
port = 1883
topic = "iot/energy"

EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'ttexample@gmail.com',
    'sender_password': 'vug94&&&&&7777777777777&&&77hfr', #its not your email pass, its app pass
    'recipient_email': 'Example@gmail.com' #تحتاج ايميل يرسل عليه الاشعارات
}

from twilio.rest import Client

# Twilio WhatsApp setup
account_sid = "###3333#333333333"  # Your Twilio SID
auth_token = "4fkokal;sdkls&&&&7&777718c3"     # Your Twilio Auth Token
twilio_whatsapp_number = "whatsapp:+141------6"    # Twilio Sandbox Number
recipient_whatsapp_number = "whatsapp:+90-------4" # Your WhatsApp number (with country code)

twilio_client = Client(account_sid, auth_token)


# Add rate-limiting to avoid hitting Twilio's limits
last_alert_time = {}


def send_whatsapp_alert(message, recipient="whatsapp:+9--------787"):
    global last_alert_time

    # Only send 1 alert per hour per device
    if recipient in last_alert_time and (time.time() - last_alert_time[recipient]) < 3600:
        print("Alert suppressed (rate limit)")
        return

    try:

        twilio_client.messages.create(
            body=message,
            from_=twilio_whatsapp_number,
            to=recipient
        )
        last_alert_time[recipient] = time.time()
        print("WhatsApp alert sent!")
    except Exception as e:
        print(f"Failed to send WhatsApp alert: {e}")
#Email
def send_email_alert(subject, message):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = EMAIL_CONFIG['recipient_email']
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))

        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
            server.send_message(msg)

        print("Email alert sent successfully.")
    except Exception as e:
        print(f"Failed to send email alert: {e}")

# STEP Global variables
energy_data = []
thresholds = {}  # Store thresholds for each location

# IoT Device Simulation
class SmartMeter:
    def __init__(self, device_id, location):
        self.device_id = device_id
        self.location = location
        self.is_on = True  # Device is initially on
        self.threshold = 4.0  # Default threshold

    def generate_data(self):
        if not self.is_on:
            return None  # Device is turned off
        energy_consumed = round(random.uniform(0.5, 5.0), 2)  # Simulate energy consumption (kWh)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        return {
            "device_id": self.device_id,
            "location": self.location,
            "timestamp": timestamp,
            "energy_consumed": energy_consumed
        }

def detect_anomaly(data):
    threshold = 4.0  # Example threshold for anomaly detection
    if data["energy_consumed"] > threshold:
        return True
    return False

# MQTT Client
def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT broker with result code {rc}")

def on_message(client, userdata, message):
    payload = message.payload.decode()
    print(f"Received MQTT message: {payload}")  # Debugging: Log received message

    if payload.startswith("TURN_OFF:"):
        location = payload.split(":")[1]
        for smart_meter in smart_meters:
            if smart_meter.location == location:
                print(f"Device in {location} received TURN_OFF command.")
                smart_meter.is_on = False  # Turn off the device
                print(f"Device in {location} has been turned off.")

    elif payload.startswith("RESTART:"):
        location = payload.split(":")[1]
        for smart_meter in smart_meters:
            if smart_meter.location == location:
                print(f"Device in {location} received RESTART command.")
                smart_meter.is_on = False  # Turn off the device first
                print(f"Device in {location} is turning off...")
                time.sleep(240)  # Delay to simulate restart
                smart_meter.is_on = True  # Turn the device back on
                print(f"Device in {location} has been restarted.")

    elif payload.startswith("SET_THRESHOLD:"):
        location, new_threshold = payload.split(":")[1], float(payload.split(":")[2])
        for smart_meter in smart_meters:
            if smart_meter.location == location:
                smart_meter.threshold = new_threshold
                print(f"Updated threshold for {location} to {new_threshold}")

mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(broker, port, 60)
mqtt_client.subscribe(topic)

# Create 5 smart meters with locations
smart_meters = [
    SmartMeter(device_id="meter_001", location="Living Room"),
    SmartMeter(device_id="meter_002", location="Kitchen"),
    SmartMeter(device_id="meter_003", location="Bedroom 1"),
    SmartMeter(device_id="meter_004", location="Bedroom 2"),
    SmartMeter(device_id="meter_005", location="Garage")
]

# Real-Time Dashboard (Dash)
app = Dash(__name__)

app.layout = html.Div([
    dcc.Graph(id='live-graph'),
    dcc.Graph(id='pie-chart'),
    dcc.Graph(id='forecast-graph'),  # New graph for regression forecast
    dcc.Interval(id='interval', interval=1000, n_intervals=0),
    html.Div([
        dcc.Input(id='device-location', type='text', placeholder='Enter Device Location'),
        html.Button('Turn Off Device', id='turn-off-button', n_clicks=0),
        html.Button('Restart Device', id='restart-button', n_clicks=0),
        dcc.Input(id='new-threshold', type='number', placeholder='Enter New Threshold'),
        html.Button('Adjust Threshold', id='adjust-threshold-button', n_clicks=0)
    ]),
    html.Div(id='output-message')
])

@app.callback(Output('live-graph', 'figure'), [Input('interval', 'n_intervals')])
def update_graph(n):
    global energy_data
    traces = []
    if not energy_data:  # Return empty graph if no data is available
        return {
            'data': [],
            'layout': go.Layout(title="Real-Time Energy Consumption by Location")
        }

    for location in set(d['location'] for d in energy_data):
        location_data = [d for d in energy_data if d['location'] == location]
        x_data = [d['timestamp'] for d in location_data]
        y_data = [d['energy_consumed'] for d in location_data]
        traces.append(go.Scatter(x=x_data, y=y_data, mode='lines+markers', name=location))

    return {
        'data': traces,
        'layout': go.Layout(title="Real-Time Energy Consumption by Location")
    }
@app.callback(Output('forecast-graph', 'figure'), [Input('interval', 'n_intervals')])
def update_forecast_graph(n):
    global energy_data
    if not energy_data:  # Check if energy_data is empty
        return {
            'data': [],
            'layout': go.Layout(title="Energy Consumption Forecast")
        }

    hours, predictions = predict_energy_consumption()
    return {
        'data': [go.Scatter(x=hours, y=predictions, mode='lines', name='Forecast')],
        'layout': go.Layout(
            title="Energy Consumption Forecast",
            xaxis={'title': 'Hour of the Day'},
            yaxis={'title': 'Energy Consumption (kWh)'}
        )
    }

@app.callback(Output('pie-chart', 'figure'), [Input('interval', 'n_intervals')])
def update_pie_chart(n):
    global energy_data
    if not energy_data:  # Return empty pie chart if no data is available
        return {
            'data': [],
            'layout': go.Layout(title="Energy Consumption Distribution by Location")
        }

    df = pd.DataFrame(energy_data)
    total_consumption = df.groupby('location')['energy_consumed'].sum().reset_index()
    return {
        'data': [go.Pie(labels=total_consumption['location'], values=total_consumption['energy_consumed'])],
        'layout': go.Layout(title="Energy Consumption Distribution by Location")
    }
@app.callback(
    Output('output-message', 'children'),
    [Input('turn-off-button', 'n_clicks'),
     Input('restart-button', 'n_clicks'),
     Input('adjust-threshold-button', 'n_clicks'),
     Input('device-location', 'value'),
     Input('new-threshold', 'value')]
)
def handle_commands(turn_off_clicks, restart_clicks, adjust_threshold_clicks, device_location, new_threshold):
    ctx = callback_context
    if not ctx.triggered:
        return ""

    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if button_id == 'turn-off-button' and device_location:
        command = f"TURN_OFF:{device_location}"
        mqtt_client.publish(topic, command)
        return f"Sent command to turn off device in {device_location}"
    elif button_id == 'restart-button' and device_location:
        command = f"RESTART:{device_location}"
        mqtt_client.publish(topic, command)
        return f"Sent command to restart device in {device_location}"
    elif button_id == 'adjust-threshold-button' and device_location and new_threshold:
        command = f"SET_THRESHOLD:{device_location}:{new_threshold}"
        mqtt_client.publish(topic, command)
        return f"Updated threshold for {device_location} to {new_threshold}"
    return ""

# Function to store data in Firestore
def store_data_in_firestore(data):
    try:
        db.collection("energy_data").add(data)
        print("Data stored in Firestore.")
    except Exception as e:
        print(f"Failed to store data in Firestore: {e}")

# Auto-Save Mode
def auto_save_mode():
    for smart_meter in smart_meters:
        data = smart_meter.generate_data()
        if data and data['energy_consumed'] > smart_meter.threshold:
            # Create alert message

            alert_message = (f"Warning: High energy consumption detected!\n"
                             f"Location: {smart_meter.location}\n"
                             f"Energy Consumed: {data['energy_consumed']} kWh\n"
                             f"Threshold: {smart_meter.threshold} kWh\n"
                             f"Action: Turning off the device.")

            # Send both SMS and email alerts
            send_whatsapp_alert(message=alert_message,
                recipient="whatsapp:+966569957794")  # Send via WhatsApp instead of SMS
            send_email_alert("Energy Alert", alert_message)

            # Turn off the device
            command = f"TURN_OFF:{smart_meter.location}"
            mqtt_client.publish(topic, command)
            print(f"Auto-save: Turned off device in {smart_meter.location}")


# Energy Consumption Forecasting
# Need little improvement for strong forcasting
def predict_energy_consumption():
    global energy_data
    if not energy_data:  # Return empty lists if no data is available
        return [], []

    df = pd.DataFrame(energy_data)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['hour'] = df['timestamp'].dt.hour

    # Ensure there's enough data for regression
    if len(df) < 2:
        return [], []

    model = LinearRegression()
    model.fit(df[['hour']], df['energy_consumed'])

    # Create future_hours with feature names
    future_hours = pd.DataFrame({'hour': range(24)})  # Add feature name 'hour'
    predictions = model.predict(future_hours)

    return list(range(24)), predictions.tolist()  # Return hours and predictions as lists



#Main Step:
# Main Function
def main():
    while True:
        for smart_meter in smart_meters:
            data = smart_meter.generate_data()
            if data:  # Only send data if the device is on
                mqtt_client.publish(topic, str(data))
                print(f"Published: {data}")
                energy_data.append(data)
                if len(energy_data) > 100:  # Keep only the last 100 data points
                    energy_data.pop(0)

                # Store data in Firestore
                store_data_in_firestore(data)

        auto_save_mode()  # Check for auto-save conditions
        time.sleep(20)  # Simulate data every 10 seconds

if __name__ == "__main__":
    # Start the dashboard in a separate thread
    import threading

    dashboard_thread = threading.Thread(target=app.run, kwargs={"debug": False})
    dashboard_thread.start()

    # Start the main simulation
    main()