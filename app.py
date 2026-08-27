import json
import sqlite3
import datetime
import requests
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image

try:
    from pyzbar.pyzbar import decode
except ImportError:
    import zxingcpp
    decode = None

st.set_page_config(page_title="Agent Fitness AI - Pro Tracker", page_icon="🥗", layout="wide")

# --- DATABASE MANAGEMENT (SQLite) ---
DB_FILE = "fitness_tracker.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Table for Daily Targets
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_targets (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cal_target REAL,
            prot_target REAL,
            carb_target REAL,
            fat_target REAL
        )
    """)
    # Set default targets if empty
    c.execute("INSERT OR IGNORE INTO user_targets (id, cal_target, prot_target, carb_target, fat_target) VALUES (1, 2000, 150, 
200, 65)")
    
    # Table for Food Logs
    c.execute("""
        CREATE TABLE IF NOT EXISTS food_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT,
            meal_type TEXT,
            food_name TEXT,
            grams REAL,
            calories REAL,
            proteins REAL,
            carbs REAL,
            fats REAL
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_targets():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT cal_target, prot_target, carb_target, fat_target FROM user_targets WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return {"cal": row[0], "prot": row[1], "carb": row[2], "fat": row[3]}

def update_targets(cal, prot, carb, fat):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE user_targets SET cal_target = ?, prot_target = ?, carb_target = ?, fat_target = ? WHERE id = 1", (cal, prot, 
carb, fat))
    conn.commit()
    conn.close()

def save_log_entry(log_date, meal_type, food_name, grams, calories, proteins, carbs, fats):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO food_logs (log_date, meal_type, food_name, grams, calories, proteins, carbs, fats)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (log_date, meal_type, food_name, grams, calories, proteins, carbs, fats))
    conn.commit()
    conn.close()

def delete_log_entry(entry_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM food_logs WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

def get_logs_by_date(log_date):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, meal_type, food_name, grams, calories, proteins, carbs, fats FROM food_logs WHERE log_date = ?", 
(log_date,))
    rows = c.fetchall()
    conn.close()
    
    logs = {"Colazione": [], "Pranzo": [], "Cena": [], "Snack": []}
    for row in rows:
        meal = row[1]
        if meal in logs:
            logs[meal].append({
                "id": row[0],
                "nome": row[2],
                "grammi": row[3],
                "cal": row[4],
                "prot": row[5],
                "carb": row[6],
                "fat": row[7]
            })
    return logs

def get_weekly_summary(end_date):
    start_date = end_date - datetime.timedelta(days=6)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT log_date, SUM(calories), SUM(proteins), SUM(carbs), SUM(fats)
        FROM food_logs
        WHERE log_date BETWEEN ? AND ?
        GROUP BY log_date
    """, (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
    rows = c.fetchall()
    conn.close()
    
    data_map = {row[0]: {"cal": row[1] or 0, "prot": row[2] or 0, "carb": row[3] or 0, "fat": row[4] or 0} for row in rows}
    
    dates, cals, prots, carbs, fats = [], [], [], [], []
    for i in range(7):
        d = (start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        dates.append(d)
        cals.append(data_map.get(d, {}).get("cal", 0))
        prots.append(data_map.get(d, {}).get("prot", 0))
        carbs.append(data_map.get(d, {}).get("carb", 0))
        fats.append(data_map.get(d, {}).get("fat", 0))
        
    return dates, cals, prots, carbs, fats


# --- API & AI INTEGRATION ---
import os
from google import genai

client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
)

tools = [
    {
        'type': 'google_search',
    },
]

generation_config = {
    'temperature': 1,
    'max_output_tokens': 65536,
    'top_p': 0.95,
    'thinking_level': 'high',
}

interaction = client.interactions.create(
    model='models/gemini-3-flash-preview',
    input='INSERT_INPUT_HERE',
    tools=tools,
    generation_config=generation_config,
)

print(interaction.steps[-1])




@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=API_KEY)

client = get_gemini_client()

def cerca_per_barcode(barcode):
    url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
    try:
        res = requests.get(url).json()
        if res.get("status") == 1:
            p = res["product"]
            n = p.get("nutriments", {})
            return {
                "nome": p.get("product_name", "Prodotto sconosciuto"),
                "calorie_100g": n.get("energy-kcal_100g", 0),
                "proteine_100g": n.get("proteins_100g", 0),
                "carboidrati_100g": n.get("carbohydrates_100g", 0),
                "grassi_100g": n.get("fat_100g", 0)
            }
    except Exception:
        pass
    return None

def cerca_per_nome(nome_alimento):
    url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {"search_terms": nome_alimento, "search_simple": 1, "action": "process", "json": 1, "page_size": 1}
    try:
        res = requests.get(url, params=params).json()
        if res.get("products"):
            p = res["products"][0]
            n = p.get("nutriments", {})
            return {
                "nome": p.get("product_name", nome_alimento),
                "calorie_100g": n.get("energy-kcal_100g", 0),
                "proteine_100g": n.get("proteins_100g", 0),
                "carboidrati_100g": n.get("carbohydrates_100g", 0),
                "grassi_100g": n.get("fat_100g", 0)
            }
    except Exception:
        pass
    return None

def scansiona_barcode_da_immagine(image_file):
    img = Image.open(image_file)
    if decode:
        decoded_objects = decode(img)
        if decoded_objects:
            return decoded_objects[0].data.decode("utf-8")
    else:
        results = zxingcpp.read_barcodes(img)
        if results:
            return results[0].text
    return None

def analizza_testo_o_audio(input_data, is_audio=False):
    prompt = """
    Analizza l'input fornito dall'utente.
    Estrai gli alimenti e la quantità in grammi in formato JSON valido.
    Esempio output:
    [
        {"alimento": "pane", "grammi": 100},
        {"alimento": "mela", "grammi": 150}
    ]
    Rispondi SOLO ed esclusivamente con il JSON valido, senza blocchi di codice markdown extra.
    """
    if is_audio:
        audio_bytes = input_data.read()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"), prompt]
        )
    else:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f'Input utente: "{input_data}"\n{prompt}'
        )
    testo_pulito = response.text.strip().replace("```json", "").replace("```", "")
    return json.loads(testo_pulito)


# --- NAVIGATION (SIDEBAR) ---
st.sidebar.title("📌 Navigation")
page = st.sidebar.radio("Go to:", ["📥 Daily Logger", "📅 History Log", "📊 Weekly Charts", "⚙️ Setup Targets"])

targets = get_targets()

# ==========================================
# PAGE 1: DAILY LOGGER
# ==========================================
if page == "📥 Daily Logger":
    st.title("🥗 Daily Food Logger")
    
    selected_date = st.date_input("Log date:", datetime.date.today())
    date_str = selected_date.strftime("%Y-%m-%d")

    col_input, col_summary = st.columns([1, 1], gap="large")

    with col_input:
        st.header("Add Food")
        categoria_pasto = st.selectbox("Select Meal:", ["Colazione", "Pranzo", "Cena", "Snack"])
        
        tab1, tab2, tab3 = st.tabs(["✍️ Text", "🎙️ Audio Voice", "📷 Barcode Scan"])

        alimenti_da_salvare = []

        with tab1:
            testo_input = st.text_area("What did you eat?", placeholder="Es: 100g di riso e 150g di petto di pollo")
            if st.button("Add from Text"):
                if testo_input:
                    with st.spinner("Processing..."):
                        alimenti_da_salvare = analizza_testo_o_audio(testo_input, is_audio=False)

        with tab2:
            audio_val = st.audio_input("Record Voice")
            if audio_val and st.button("Process Audio"):
                with st.spinner("Gemini is listening..."):
                    alimenti_da_salvare = analizza_testo_o_audio(audio_val, is_audio=True)

        with tab3:
            foto_barcode = st.camera_input("Scan Barcode")
            if foto_barcode:
                barcode = scansiona_barcode_da_immagine(foto_barcode)
                if barcode:
                    st.info(f"Detected EAN: {barcode}")
                    info_b = cerca_per_barcode(barcode)
                    if info_b:
                        grammi = st.number_input(f"Grams of '{info_b['nome']}':", value=100, step=10)
                        if st.button("Add Product"):
                            alimenti_da_salvare = [{"alimento": info_b["nome"], "grammi": grammi, "info_diretta": info_b}]
                    else:
                        st.error("Product not found.")

        # Save extracted items to Database
        if alimenti_da_salvare:
            for item in alimenti_da_salvare:
                nome = item["alimento"]
                grammi = item["grammi"]
                info = item.get("info_diretta") or cerca_per_nome(nome)
                if info:
                    molt = grammi / 100.0
                    save_log_entry(
                        date_str, categoria_pasto, info["nome"], grammi,
                        info["calorie_100g"] * molt,
                        info["proteine_100g"] * molt,
                        info["carboidrati_100g"] * molt,
                        info["grassi_100g"] * molt
                    )
            st.success("Item(s) saved to Database!")
            st.rerun()

    with col_summary:
        st.header(f"📊 Summary for {date_str}")
        daily_logs = get_logs_by_date(date_str)

        tot_cal = sum(item["cal"] for meal in daily_logs.values() for item in meal)
        tot_prot = sum(item["prot"] for meal in daily_logs.values() for item in meal)
        tot_carb = sum(item["carb"] for meal in daily_logs.values() for item in meal)
        tot_fat = sum(item["fat"] for meal in daily_logs.values() for item in meal)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Calories", f"{tot_cal:.0f} / {targets['cal']:.0f} kcal", delta=f"{tot_cal - targets['cal']:.0f} kcal", 
delta_color="inverse")
        m2.metric("Proteins", f"{tot_prot:.1f} / {targets['prot']:.0f} g")
        m3.metric("Carbs", f"{tot_carb:.1f} / {targets['carb']:.0f} g")
        m4.metric("Fats", f"{tot_fat:.1f} / {targets['fat']:.0f} g")

        st.divider()

        for pasto_nome in ["Colazione", "Pranzo", "Cena", "Snack"]:
            alimenti_pasto = daily_logs[pasto_nome]
            cal_pasto = sum(x["cal"] for x in alimenti_pasto)

            with st.expander(f"**{pasto_nome}** — `{cal_pasto:.0f} kcal`", expanded=True):
                if not alimenti_pasto:
                    st.caption("No entries for this meal.")
                else:
                    for elem in alimenti_pasto:
                        c_col1, c_col2 = st.columns([4, 1])
                        c_col1.markdown(f"• **{elem['nome']}** ({elem['grammi']}g) — `{elem['cal']:.0f} kcal` | P: 
{elem['prot']:.1f}g | C: {elem['carb']:.1f}g | G: {elem['fat']:.1f}g")
                        if c_col2.button("❌", key=f"del_{elem['id']}"):
                            delete_log_entry(elem['id'])
                            st.rerun()


# ==========================================
# PAGE 2: HISTORY LOG
# ==========================================
elif page == "📅 History Log":
    st.title("📅 Daily History Lookup")
    
    lookup_date = st.date_input("Select Date to Recall:", datetime.date.today())
    lookup_str = lookup_date.strftime("%Y-%m-%d")

    history_logs = get_logs_by_date(lookup_str)

    tot_cal = sum(item["cal"] for meal in history_logs.values() for item in meal)
    tot_prot = sum(item["prot"] for meal in history_logs.values() for item in meal)
    tot_carb = sum(item["carb"] for meal in history_logs.values() for item in meal)
    tot_fat = sum(item["fat"] for meal in history_logs.values() for item in meal)

    st.subheader(f"Log Details for {lookup_str}")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Calories", f"{tot_cal:.0f} kcal")
    m2.metric("Total Proteins", f"{tot_prot:.1f} g")
    m3.metric("Total Carbs", f"{tot_carb:.1f} g")
    m4.metric("Total Fats", f"{tot_fat:.1f} g")

    st.divider()

    for pasto_nome in ["Colazione", "Pranzo", "Cena", "Snack"]:
        alimenti_pasto = history_logs[pasto_nome]
        cal_pasto = sum(x["cal"] for x in alimenti_pasto)

        st.markdown(f"### {pasto_nome} (`{cal_pasto:.0f} kcal`)")
        if not alimenti_pasto:
            st.info("No logs registered for this meal.")
        else:
            for elem in alimenti_pasto:
                st.markdown(f"- **{elem['nome']}** ({elem['grammi']}g): **{elem['cal']:.0f} kcal** | P: {elem['prot']:.1f}g | C: 
{elem['carb']:.1f}g | G: {elem['fat']:.1f}g")
        st.write("")


# ==========================================
# PAGE 3: WEEKLY CHARTS
# ==========================================
elif page == "📊 Weekly Charts":
    st.title("📊 Weekly Nutrition Overview & Target Comparison")
    
    ref_date = st.date_input("Select End Date of 7-Day Window:", datetime.date.today())
    
    dates, cals, prots, carbs, fats = get_weekly_summary(ref_date)

    st.subheader("🔥 Daily Calories vs Target")
    df_cals = pd.DataFrame({
        "Date": dates,
        "Calories Consumed": cals,
        "Daily Target": [targets["cal"]] * 7
    }).set_index("Date")

    st.bar_chart(df_cals, color=["#FF4B4B", "#CCCCCC"])

    st.divider()

    st.subheader("🥩 Daily Macros Overview (g)")
    df_macros = pd.DataFrame({
        "Date": dates,
        "Proteins": prots,
        "Carbs": carbs,
        "Fats": fats
    }).set_index("Date")

    st.bar_chart(df_macros)

    st.caption(f"Targets Reference -> Calories: {targets['cal']} kcal | Proteins: {targets['prot']}g | Carbs: {targets['carb']}g | 
Fats: {targets['fat']}g")


# ==========================================
# PAGE 4: SETUP TARGETS
# ==========================================
elif page == "⚙️ Setup Targets":
    st.title("⚙️ Set Daily Nutrition Targets")
    st.write("Configure your personal daily caloric and macronutrient goals. These targets will be reflected across your weekly 
charts and logs.")

    with st.form("targets_form"):
        new_cal = st.number_input("Daily Calorie Target (kcal):", value=float(targets["cal"]), step=50.0)
        new_prot = st.number_input("Daily Protein Target (g):", value=float(targets["prot"]), step=5.0)
        new_carb = st.number_input("Daily Carbohydrates Target (g):", value=float(targets["carb"]), step=5.0)
        new_fat = st.number_input("Daily Fats Target (g):", value=float(targets["fat"]), step=5.0)
        
        save_btn = st.form_submit_button("Save Targets")
        
        if save_btn:
            update_targets(new_cal, new_prot, new_carb, new_fat)
            st.success("Targets updated successfully!")
            st.rerun()
