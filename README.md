# 🌱 SEEDRA | Agroclimatic Intelligence for the Altiplano

### 🌐 Live Interactive App: [Launch SEEDRA on Streamlit Cloud](https://nasa-space-apps-2026-seedra.streamlit.app/)


**NASA Space Apps Challenge 2026 · Pilot in Puno, Peru (3,800 m a.s.l.)**

SEEDRA transforms open satellite data from **NASA POWER** into simple, actionable planting and crop rotation (*Aynoca*) recommendations for smallholder farmers in the Andes.

## 🚀 What Problem Does It Solve?
In the Peruvian Altiplano, early frosts and erratic rainfall threaten food security. SEEDRA translates complex satellite agroclimatic variables into practical field decisions without requiring technical expertise.

## ✨ Key Features
- **Daily Water Balance (FAO-56 / FAO-33):** Computes reference evapotranspiration (Penman-Monteith) and crop-specific water stress.
- **Risk Traffic Light & Farmer Mode:** Delivers clear planting alerts with one-click WhatsApp sharing and downloadable campaign cards.
- **Aynoca Planner:** Combines traditional 4-season Andean crop rotation with historical water risk data.
- **Agroclimatic Time Machine:** Reconstructs past agricultural seasons, rainfall onset dates, and frost events.
- **Multilingual Accessibility:** Available in Spanish, English, and Aymar aru (beta).

## 🛰️ Data & Tech Stack
- **Data Source:** NASA POWER API (precipitation, max/min temperature, solar radiation, and relative humidity).
- **Tech Stack:** Python, Streamlit, Pandas, NumPy, SciPy, Altair, and Folium.

## 🛠️ How to Run Locally
1. Clone the repository:
   ```bash
   git clone https://github.com
   cd nasa-space-apps-2026
   ```
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the application:
   ```bash
   streamlit run app.py
   ```
