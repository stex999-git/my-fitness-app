import os
import sqlite3
import datetime
import numpy as np
import cv2
import pandas as pd
import streamlit as st
from PIL import Image
import requests
import zxingcpp
from google import genai
from google.genai import types

# Configurazione Client Gemini
client = genai.Client(
    api_key=st.secrets["GEMINI_API_KEY"]
)

# Configurazione Database
conn = sqlite3.connect("fitness.db", check_same_thread=False)
c = conn.cursor()

c.execute("""
    CREATE TABLE IF NOT EXISTS user_targets (
        id INTEGER PRIMARY KEY,
        cal_target INTEGER,
        prot_target INTEGER,
        carb_target INTEGER,
        fat_target INTEGER
    )
""")

q = "INSERT OR IGNORE INTO user_targets (id, cal_target, prot_target, carb_target, fat_target) VALUES (1, 2000, 150, 200, 65)"
c.execute(q)
conn.commit()

c.execute("""
    CREATE TABLE IF NOT EXISTS food_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        name TEXT,
        calories REAL,
        protein REAL,
        carbs REAL,
        fat REAL,
        meal TEXT DEFAULT 'Snack'
    )
""")
conn.commit()

# Funzioni Database
def add_food_to_db(name: str, calories: float, protein: float, carbs: float, fat: float, meal: str = "Snack") -> str:
    """Registra un alimento nel diario alimentare specificando il pasto (Colazione, Pranzo, Cena, Snack)."""
    today = str(datetime.date.today())
    valid_meals = ["Colazione", "Pranzo", "Cena", "Snack"]
    meal_formatted = meal.capitalize() if meal.capitalize() in valid_meals else "Snack"
    
    c.execute("INSERT INTO food_log (date, name, calories, protein, carbs, fat, meal) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (today, str(name), float(calories), float(protein), float(carbs), float(fat), meal_formatted))
    conn.commit()
    return f"OK: Registrato {name} per {meal_formatted} ({calories} kcal, P:{protein}g, C:{carbs}g, F:{fat}g)"

def update_food_meal(food_id: int, new_meal: str):
    c.execute("UPDATE food_log SET meal = ? WHERE id = ?", (new_meal, food_id))
    conn.commit()

def delete_food_from_db(food_id: int):
    c.execute("DELETE FROM food_log WHERE id = ?", (food_id,))
    conn.commit()

# Interfaccia Streamlit
st.set_page_config(page_title="Fitness & AI Nutrition Tracker", layout="wide")
st.title("🏋️‍♂️ Fitness & AI Nutrition Tracker")

# Sidebar Obiettivi
st.sidebar.header("🎯 I tuoi Obiettivi")
c.execute("SELECT cal_target, prot_target, carb_target, fat_target FROM user_targets WHERE id = 1")
target_row = c.fetchone()

cal_target = st.sidebar.number_input("Calorie (kcal)", value=target_row[0])
prot_target = st.sidebar.number_input("Proteine (g)", value=target_row[1])
carb_target = st.sidebar.number_input("Carboidrati (g)", value=target_row[2])
fat_target = st.sidebar.number_input("Grassi (g)", value=target_row[3])

if st.sidebar.button("Salva Obiettivi"):
    c.execute("""
        UPDATE user_targets 
        SET cal_target=?, prot_target=?, carb_target=?, fat_target=? 
        WHERE id=1
    """, (cal_target, prot_target, carb_target, fat_target))
    conn.commit()
    st.sidebar.success("Obiettivi aggiornati!")

tab1, tab2, tab3 = st.tabs(["📝 Diario Alimentare", "📸 Barcode Scanner", "🤖 Assistente Gemini (Testo, Foto & Voce)"])

MEALS = ["Colazione", "Pranzo", "Cena", "Snack"]

with tab1:
    st.header("Diario di Oggi")
    
    today_str = str(datetime.date.today())
    df_today = pd.read_sql_query("SELECT * FROM food_log WHERE date = ?", conn, params=(today_str,))
    
    st.subheader("📊 Progresso Giornaliero Totale")
    
    tot_cal = df_today["calories"].sum() if not df_today.empty else 0.0
    tot_prot = df_today["protein"].sum() if not df_today.empty else 0.0
    tot_carb = df_today["carbs"].sum() if not df_today.empty else 0.0
    tot_fat = df_today["fat"].sum() if not df_today.empty else 0.0

    col_p1, col_p2, col_p3, col_p4 = st.columns(4)
    
    with col_p1:
        st.metric("Calorie", f"{int(tot_cal)} / {cal_target} kcal")
        st.progress(min(tot_cal / cal_target, 1.0) if cal_target > 0 else 0.0)

    with col_p2:
        st.metric("Proteine", f"{int(tot_prot)} / {prot_target} g")
        st.progress(min(tot_prot / prot_target, 1.0) if prot_target > 0 else 0.0)

    with col_p3:
        st.metric("Carboidrati", f"{int(tot_carb)} / {carb_target} g")
        st.progress(min(tot_carb / carb_target, 1.0) if carb_target > 0 else 0.0)

    with col_p4:
        st.metric("Grassi", f"{int(tot_fat)} / {fat_target} g")
        st.progress(min(tot_fat / fat_target, 1.0) if fat_target > 0 else 0.0)

    st.markdown("---")
    
    with st.expander("➕ Aggiungi alimento manualmente"):
        with st.form("add_food"):
            col1, col2, col3, col4, col5, col6 = st.columns([3, 2, 2, 2, 2, 2])
            name = col1.text_input("Alimento")
            cals = col2.number_input("Calorie", min_value=0.0)
            prot = col3.number_input("Proteine (g)", min_value=0.0)
            carbs = col4.number_input("Carbo (g)", min_value=0.0)
            fat = col5.number_input("Grassi (g)", min_value=0.0)
            meal_choice = col6.selectbox("Pasto", MEALS)
            submit = st.form_submit_button("Aggiungi Alimento")
            
            if submit and name:
                add_food_to_db(name, cals, prot, carbs, fat, meal_choice)
                st.rerun()

    st.subheader("📋 Pasti del Giorno")
    
    for meal in MEALS:
        df_meal = df_today[df_today["meal"] == meal] if not df_today.empty else pd.DataFrame()
        
        m_cal = df_meal["calories"].sum() if not df_meal.empty else 0.0
        m_prot = df_meal["protein"].sum() if not df_meal.empty else 0.0
        m_carb = df_meal["carbs"].sum() if not df_meal.empty else 0.0
        m_fat = df_meal["fat"].sum() if not df_meal.empty else 0.0
        
        with st.expander(f"🍽️ **{meal}** — {int(m_cal)} kcal (P: {int(m_prot)}g | C: {int(m_carb)}g | F: {int(m_fat)}g)", expanded=True):
            if not df_meal.empty:
                for idx, row in df_meal.iterrows():
                    c_name, c_cal, c_prot, c_carb, c_fat, c_move, c_del = st.columns([3, 1.5, 1.5, 1.5, 1.5, 2.5, 1])
                    c_name.write(f"**{row['name']}**")
                    c_cal.write(f"{row['calories']} kcal")
                    c_prot.write(f"P: {row['protein']}g")
                    c_carb.write(f"C: {row['carbs']}g")
                    c_fat.write(f"F: {row['fat']}g")
                    
                    new_meal = c_move.selectbox(
                        "Sposta in",
                        MEALS,
                        index=MEALS.index(row["meal"]),
                        key=f"move_{row['id']}",
                        label_visibility="collapsed"
                    )
                    if new_meal != row["meal"]:
                        update_food_meal(row["id"], new_meal)
                        st.rerun()

                    if c_del.button("🗑️", key=f"del_{row['id']}"):
                        delete_food_from_db(row['id'])
                        st.rerun()
            else:
                st.caption(f"Nessun alimento registrato in {meal}.")

with tab2:
    st.header("Scanner Codice a Barre")
    st.info("💡 Suggerimento: Avvicina il codice a barre e assicurati che la luce sia buona.")
    img_file = st.camera_input("Scansiona un codice a barre con la fotocamera")
    
    if img_file:
        img = Image.open(img_file)
        
        # Pre-elaborazione per migliorare la rilevazione dei barcode sfocati o scuri
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        cv_img = cv2.equalizeHist(cv_img)
        
        # Scansione sull'immagine originale e pre-elaborata
        results = zxingcpp.read_barcodes(img)
        if not results:
            results = zxingcpp.read_barcodes(cv_img)
            
        if results:
            barcode = results[0].text
            st.success(f"Codice rilevato: {barcode}")
            
            url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
            res = requests.get(url).json()
            if res.get("status") == 1:
                product = res["product"]
                p_name = product.get("product_name", "Sconosciuto")
                nutriments = product.get("nutriments", {})
                
                cals = float(nutriments.get('energy-kcal_100g', 0))
                p = float(nutriments.get('proteins_100g', 0))
                c_val = float(nutriments.get('carbohydrates_100g', 0))
                f_val = float(nutriments.get('fat_100g', 0))

                st.write(f"**Prodotto:** {p_name}")
                st.write(f"Calorie / 100g: {cals} kcal")
                
                selected_meal = st.selectbox("Seleziona Pasto", MEALS, key="scan_meal")
                
                if st.button("Aggiungi al Diario"):
                    add_food_to_db(p_name, cals, p, c_val, f_val, selected_meal)
                    st.success(f"{p_name} aggiunto a {selected_meal}!")
                    st.rerun()
            else:
                st.warning("Prodotto non trovato nel database OpenFoodFacts.")
        else:
            st.error("Nessun codice a barre rilevato. Prova ad avvicinare il prodotto o ad aumentare la luminosità.")

with tab3:
    st.header("Chat Nutrizionale Multimodale (Testo, Foto e Audio)")
    
    if "chat" not in st.session_state:
        st.session_state.chat = client.chats.create(
            model='gemini-3.6-flash',
            config=types.GenerateContentConfig(
                tools=[add_food_to_db],
                system_instruction="Sei un assistente nutrizionista multimodale. Quando l'utente ti invia testo, audio o foto del cibo, identifica l'alimento, stima le calorie e i macronutrienti (proteine, carboidrati, grassi) e invoca SEMPRE la funzione add_food_to_db per salvarli nel database. Determina anche il pasto (Colazione, Pranzo, Cena o Snack)."
            )
        )
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Inserimenti Input Multimodali
    col_img, col_aud = st.columns(2)
    with col_img:
        uploaded_image = st.file_uploader("📸 Analizza foto piatto", type=["jpg", "png", "jpeg"])
    with col_aud:
        recorded_audio = st.audio_input("🎙️ Registra messaggio vocale")

    input_payload = None

    # Processa prima foto o audio se inseriti
    if uploaded_image:
        pil_img = Image.open(uploaded_image)
        st.image(pil_img, caption="Foto caricata", width=250)
        if st.button("Analizza Foto con Gemini"):
            input_payload = [pil_img, "Analizza questo piatto, stima le calorie/macro e inseriscilo nel diario nutrizionale tramite tool."]

    elif recorded_audio:
        audio_bytes = recorded_audio.read()
        if st.button("Invia Audio a Gemini"):
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")
            input_payload = [audio_part, "Ascolta questo vocale, ricava il cibo consumato, stima i nutrienti e inseriscilo nel diario tramite tool."]

    # Mostra la cronologia messaggi
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat Testuale Standard
    user_text = st.chat_input("Scrivi qui (es. Ho mangiato una mela per snack)...")
    if user_text:
        input_payload = user_text

    # Elaborazione Centrale delle Richieste Gemini
    if input_payload:
        if isinstance(input_payload, str):
            st.session_state.messages.append({"role": "user", "content": input_payload})
            with st.chat_message("user"):
                st.markdown(input_payload)

        with st.chat_message("assistant"):
            with st.spinner("Gemini sta elaborando il contenuto..."):
                response = st.session_state.chat.send_message(input_payload)
                
                food_added = False
                if response.function_calls:
                    for call in response.function_calls:
                        if call.name == "add_food_to_db":
                            args = call.args
                            res_msg = add_food_to_db(
                                name=args.get("name"),
                                calories=args.get("calories"),
                                protein=args.get("protein"),
                                carbs=args.get("carbs"),
                                fat=args.get("fat"),
                                meal=args.get("meal", "Snack")
                            )
                            confirm_response = st.session_state.chat.send_message(
                                types.Part.from_function_response(
                                    name="add_food_to_db",
                                    response={"result": res_msg}
                                )
                            )
                            st.markdown(confirm_response.text)
                            st.session_state.messages.append({"role": "assistant", "content": confirm_response.text})
                            food_added = True
                else:
                    st.markdown(response.text)
                    st.session_state.messages.append({"role": "assistant", "content": response.text})
                
                if food_added:
                    st.rerun()
