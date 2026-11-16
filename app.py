# -*- coding: utf-8 -*-
"""SEEDRA: apoyo a la decisión de siembra y rotación de cultivos con NASA POWER (piloto Puno, Perú)."""
import base64
import inspect
import math
import os
import urllib.parse
from datetime import date, timedelta

import altair as alt
import folium
from folium.plugins import LocateControl
import numpy as np
import pandas as pd
import requests
import streamlit as st
from scipy.stats import gamma as gamma_dist, linregress, norm
from streamlit_folium import st_folium

st.set_page_config(page_title="SEEDRA | Inteligencia Agroclimática", page_icon="🌱", layout="wide")

# ==============================================================================
# 1. CONSTANTES Y SUPUESTOS (todo supuesto vive aquí y se muestra en la app)
# ==============================================================================
PUNO = (-15.8402, -70.0219)
BOUNDS = (-17.5, -13.0, -71.8, -68.0)
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
SNAPSHOT = "puno_snapshot.csv"          # copia local para la demo si falla internet
ELEV_M = 3800                           # altitud de referencia (Puno)
TAW = 100.0                             # agua útil en la zona de raíces (mm): SUPUESTO
TAW_RANGE = (70.0, 100.0, 130.0)        # análisis de sensibilidad del suelo
LOSS_THRESHOLD = 60                     # rendimiento (%) bajo el cual una campaña es "mala"
GREEN_MAX, YELLOW_MAX = 0.15, 0.35      # umbrales del semáforo
ONSET_MM, ONSET_DAYS = 25, 15           # definición operativa del inicio de lluvias
NO_PREV = "Nada / descanso"

DISTRITOS = {
    "Puno (Centro)": (-15.8402, -70.0219), "Juliaca": (-15.4997, -70.1333), "Ilave": (-16.0833, -69.6389),
    "Azángaro": (-14.9072, -70.1964), "Huancané": (-15.2036, -69.7578), "Ayaviri": (-14.8786, -70.5914),
    "Lampa": (-15.3606, -70.3689), "Moho": (-15.3578, -69.4953), "Juli": (-16.2161, -69.4608),
    "Yunguyo": (-16.2461, -69.0903), "Macusani": (-14.0681, -70.4336), "Sandia": (-14.2917, -69.4425),
}

# sow = (mes, día) y days = ciclo: SUPUESTOS a reemplazar con su calendario SENAMHI.
# kc / ky: verifiquen cada valor contra FAO-56 / FAO-33 y cítenlo.
CROPS = {
    "Papa":   {"kc": 1.15, "ky": 1.10, "fam": "tuberculo",    "sow": (10, 15), "days": 180},
    "Quinua": {"kc": 0.80, "ky": 0.80, "fam": "grano_andino", "sow": (10, 15), "days": 170},
    "Habas":  {"kc": 0.90, "ky": 0.90, "fam": "leguminosa",   "sow": (9, 25),  "days": 160},
    "Cebada": {"kc": 0.85, "ky": 0.85, "fam": "cereal",       "sow": (11, 1),  "days": 150},
    "Avena":  {"kc": 0.80, "ky": 0.85, "fam": "cereal",       "sow": (11, 1),  "days": 150},
}

# Reglas de rotación (familia previa, familia candidata) -> (puntaje, clave del motivo). Simplificadas, a validar con INIA.
ROT = {
    ("tuberculo", "leguminosa"):    (1.0, "r_t_leg"),
    ("tuberculo", "grano_andino"):  (0.9, "r_t_gr"),
    ("tuberculo", "cereal"):        (0.85, "r_t_cer"),
    ("leguminosa", "cereal"):       (1.0, "r_leg_cer"),
    ("leguminosa", "tuberculo"):    (0.95, "r_leg_t"),
    ("leguminosa", "grano_andino"): (0.85, "r_leg_gr"),
    ("cereal", "leguminosa"):       (1.0, "r_cer_leg"),
    ("cereal", "tuberculo"):        (0.9, "r_cer_t"),
    ("cereal", "grano_andino"):     (0.8, "r_cer_gr"),
    ("grano_andino", "leguminosa"): (1.0, "r_gr_leg"),
    ("grano_andino", "tuberculo"):  (0.9, "r_gr_t"),
    ("grano_andino", "cereal"):     (0.8, "r_gr_cer"),
}

LANGS = {"es": "Español", "en": "English", "ay": "Aymar aru (beta)"}

# ==============================================================================
# 2. TRADUCCIONES. Si falta una clave en un idioma se usa español.
#    AYMARA = traducción PRELIMINAR de interfaz y Modo Agricultor; requiere revisión de un hablante nativo.
#    Los textos técnicos largos caen a español a propósito (no se inventa Aymara técnico).
# ==============================================================================
I18N = {
"es": {
 "hero_badge": "NASA Space Apps Challenge · Puno, Perú · 3,800 m s. n. m.",
 "hero_sub": "Memoria ambiental y rotación inteligente para el Altiplano",
 "dark_label": "Modo oscuro",
 "sidebar_tag": "NASA Space Apps",
 "prev_label": "¿Qué sembraste la campaña pasada en esta parcela?",
 "none": "Nada / descanso",
 "farmer_mode": "👨‍🌾 Modo Agricultor",
 "sidebar_adv": "Opciones avanzadas", "sidebar_years": "Historial NASA (años)",
 "sidebar_analogs": "Ajustar a campañas parecidas",
 "sidebar_analogs_help": "Usa solo los años históricos cuya humedad del suelo en los últimos 30 días fue más parecida a la actual.",
 "sidebar_refresh": "Actualizar datos", "sidebar_loc": "Parcela seleccionada",
 "spinner": "Consultando satélites NASA POWER y calculando balance hídrico…",
 "err_power": "No pudimos conectar con NASA POWER y no hay copia guardada para esta ubicación. Reintenta en unos segundos.",
 "err_bounds": "Las coordenadas están fuera del Altiplano de Puno.",
 "err_nodata": "No hay suficientes campañas completas para simular.",
 "src_live": "NASA POWER (en vivo)", "src_off": "copia guardada de NASA POWER (sin conexión)",
 "tabs": ["Análisis", "Aynoca (Rotación)", "Máquina del Tiempo", "Índices", "Ciencia y fuentes", "Nosotros"],
 "crops": {"Papa": "Papa", "Quinua": "Quinua", "Habas": "Habas", "Cebada": "Cebada", "Avena": "Avena"},
 "fams": {"tuberculo": "Tubérculo", "grano_andino": "Grano andino", "leguminosa": "Leguminosa", "cereal": "Cereal"},
 "r_fallow": "La parcela estuvo en descanso: cualquier cultivo es válido.",
 "r_same": "Repetir el mismo cultivo acumula plagas y enfermedades del suelo.",
 "r_samefam": "Es de la misma familia botánica: rotas poco.",
 "r_t_leg": "La leguminosa repone el nitrógeno que extrae la papa.",
 "r_t_gr": "Rompe el ciclo de plagas clave de la papa (como el gorgojo de los Andes).",
 "r_t_cer": "El cereal rompe el ciclo de plagas de la papa y cubre el suelo.",
 "r_leg_cer": "El cereal aprovecha el nitrógeno que dejaron las habas.",
 "r_leg_t": "La papa aprovecha el nitrógeno que dejaron las habas.",
 "r_leg_gr": "La quinua aprovecha el nitrógeno residual de las habas.",
 "r_cer_leg": "Las habas recuperan la fertilidad del suelo después de un cereal.",
 "r_cer_t": "La papa entra bien después de un cereal.",
 "r_cer_gr": "Diversifica el sistema después de un cereal.",
 "r_gr_leg": "Las habas recuperan el suelo después de la quinua.",
 "r_gr_t": "La papa entra bien después de la quinua.",
 "r_gr_cer": "Diversifica el sistema después de la quinua.",
 "district_pick": "Ir rápido a un distrito de Puno", "district_custom": "Punto personalizado (clic en el mapa)",
 "map_streets": "Calles", "map_sat": "Satélite HD", "map_ndvi": "NDVI (vegetación de la zona, NASA MODIS)",
 "map_hint": "Haz clic en cualquier punto del mapa o usa el GPS para recalcular. El NDVI de MODIS (≥250 m) muestra la vegetación de la zona, no una parcela individual.",
 "analysis_title": "Análisis de decisión", "farmer_title": "Tu decisión de campaña",
 "badge_green": "Riesgo bajo: Siembra {crop}",
 "badge_yellow": "Riesgo medio: Siembra {crop} con cuidado",
 "badge_red": "Riesgo alto: Falta de agua",
 "chip_green": "Riesgo bajo", "chip_yellow": "Riesgo medio", "chip_red": "Riesgo alto",
 "farmer_sub_green": "En la mayoría de las campañas pasadas hubo agua suficiente para {crop}.",
 "farmer_sub_yellow": "Algunas campañas pasadas tuvieron falta de agua: vigila la humedad al sembrar y cubre el suelo.",
 "farmer_sub_red": "La mejor opción disponible es {crop}. Sin riego, considera dejar la parcela en descanso este año.",
 "why_label": "Por qué", "alt_label": "Alternativa",
 "bad_years": "En {n} de {t} campañas pasadas, la falta de agua habría reducido la cosecha de {crop} en más de {p}%.",
 "rain_now": "Desde el 1 de octubre ha llovido el {p}% de lo normal para estas fechas.",
 "kpi_yield": "Rendimiento esperado", "kpi_p20": "Año adverso (P20)", "kpi_risk": "Riesgo de pérdida", "kpi_frost": "Heladas esperadas",
 "kpi_days": "días", "kpi_range": "según el suelo: {a}–{b}%",
 "kpi_rain": "Lluvia desde 1-oct", "kpi_rain_s": "{p}% de lo normal", "kpi_sm": "Saturación de raíz", "kpi_sm_s": "normal: {v}",
 "kpi_frost2": "Días con helada (≤0 °C)", "kpi_frost2_s": "normal a la fecha: {n}",
 "farmer_comp_title": "Comparación rápida de tus opciones",
 "farmer_share": "Compartir por WhatsApp",
 "farmer_share_msg": "SEEDRA Puno: para mi parcela ({lat:.3f}, {lon:.3f}), la mejor opción es {crop}. {msg}.",
 "btn_card": "Descargar cartilla de campaña",
 "card_title": "CARTILLA DE CAMPAÑA SEEDRA", "card_date": "Fecha", "card_plot": "Parcela", "card_before": "Sembré antes",
 "card_sow": "SIEMBRA RECOMENDADA", "card_reason": "Motivo", "card_bad": "Campañas malas en el historial", "card_alt": "Alternativa",
 "card_disc": "Herramienta exploratoria con datos NASA POWER. No reemplaza al técnico agrario.",
 "col_crop": "Cultivo", "col_yield": "Rend. típico (P50) %", "col_p20": "Año malo (P20) %", "col_risk": "Campañas malas %",
 "col_frost": "Heladas (días)", "col_rot": "Rotación", "yes": "Óptima", "mid": "Media", "no": "Baja",
 "chart_t1_title": "Rendimiento esperado y riesgo por cultivo", "chart_t1_x": "Rendimiento mediano (%)", "chart_t1_color": "Riesgo (%)",
 "tt_crop": "Cultivo", "tt_p50": "Mediana P50 (%)", "tt_p20": "Escenario seco P20 (%)", "tt_risk": "Campañas malas (%)", "tt_frost": "Heladas (días)", "tt_agro": "Índice de rotación",
 "analogs_active": "Modo análogos activo: evaluado sobre {n} campañas parecidas a la actual.",
 "src_cap": "Fuente: {src}. Estimación relativa para comparar cultivos y campañas; no es un pronóstico de cosecha.",
 "n_hist": "Análisis con {n} campañas históricas.",
 "aynoca_title": "Planificador comunal Aynoca (rotación a 4 campañas)",
 "aynoca_desc": "El sistema ancestral Aynoca organiza el territorio en turnos para cortar plagas y recuperar el suelo. SEEDRA mantiene esa lógica (primero el cultivo anterior) y la filtra con el riesgo de agua de la campaña.",
 "aynoca_step": "Campaña", "aynoca_current": "Campaña base (anterior)",
 "aynoca_matrix_title": "Matriz agronómica de compatibilidad", "aynoca_matrix_x": "Cultivo candidato", "aynoca_matrix_y": "Cultivo anterior",
 "aynoca_matrix_score": "Compatibilidad", "aynoca_tt_reason": "Fundamento",
 "aynoca_cap": "Reglas agronómicas simplificadas y clima histórico. Deben validarse con técnicos locales (INIA, UNA Puno).",
 "all_high": "Todas las opciones tienen riesgo alto de falta de agua: el descanso (barbecho) también es una decisión válida este año.",
 "tm_title": "Máquina del Tiempo agroclimática", "tm_subtitle": "Reconstrucción histórica mediante balance hídrico FAO-56 / FAO-33: qué habría pasado en cada campaña pasada.",
 "tm_crop_select": "Cultivo a inspeccionar",
 "tm_kpi_slope": "Tendencia de rendimiento", "tm_kpi_onset": "Inicio de lluvias", "tm_kpi_frost": "Tendencia de heladas", "tm_kpi_r2": "Significancia (R² / p)",
 "tm_per_decade": "% por década", "tm_days_decade": "días por década", "tm_onset_hint": "(+) = más tarde",
 "tm_chart1_title": "Serie histórica y tendencia — {crop}", "tm_chart1_sub": "Pendiente: {slope:+.2f}% por década | R² = {r2:.3f}",
 "tm_chart1_y": "Rendimiento simulado (%)", "tm_chart1_x": "Campaña agrícola",
 "tm_status_ok": "Campaña viable (≥60%)", "tm_status_loss": "Pérdida hídrica (<60%)",
 "tm_chart2_title": "Inicio de la temporada de lluvias", "tm_chart2_y": "Días desde el 1 de septiembre",
 "tm_chart3_title": "Lluvia (mm) y heladas por campaña", "tm_chart3_rain": "Lluvia estacional (mm)", "tm_chart3_frost": "Días con helada",
 "tm_tt_year": "Campaña", "tm_tt_yield": "Rendimiento (%)", "tm_tt_rain": "Lluvia (mm)", "tm_tt_eta": "ET real / ETc (%)", "tm_tt_frost": "Heladas (días)", "tm_tt_onset": "Día de inicio",
 "tm_sig_no": "La tendencia no es estadísticamente significativa (p ≥ 0.10): lo que sí cambia mucho es la variabilidad entre años.",
 "tm_sig_yes": "La tendencia es estadísticamente significativa (p < 0.10).",
 "tm_def": "Inicio de lluvias: primer día desde el 1-sep en que la lluvia de {d} días suma al menos {mm} mm.",
 "idx_title": "Índices hidrometeorológicos y humedad satelital", "idx_desc": "Diagnóstico de sequía (SPI estacional) y humedad del suelo derivada de NASA POWER.",
 "idx_sm_surf": "Humedad superficial", "idx_sm_root": "Humedad radicular", "idx_spi_now": "SPI última campaña (sep–abr)", "idx_wb_now": "Balance anual (P − ET₀)",
 "idx_spi_wet": "Húmedo", "idx_spi_norm": "Normal", "idx_spi_dry": "Déficit",
 "idx_chart_spi_title": "Índice estandarizado de precipitación (SPI) por campaña", "idx_chart_spi_y": "Desviaciones estándar",
 "idx_chart_wb_title": "Balance hídrico mensual promedio", "idx_chart_wb_y": "Lámina (mm/mes)", "idx_chart_wb_x": "Mes",
 "idx_precip": "Precipitación", "idx_et0": "ET₀", "idx_var": "Variable",
 "idx_months": ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
 "just_title": "Fundamentos científicos y agronómicos",
 "just_fao56_h": "1. Evapotranspiración (FAO-56 Penman-Monteith)",
 "just_fao56_p": "No usamos solo la lluvia. Calculamos la demanda evaporativa de la atmósfera (ET₀) con radiación solar, temperatura máxima y mínima, viento y humedad relativa de NASA POWER, usando radiación neta y ajustando por la altitud de Puno. Luego la convertimos en demanda del cultivo (ETc = Kc × ET₀) con una curva de Kc por etapas.",
 "just_fao33_h": "2. Respuesta del rendimiento al estrés hídrico (FAO-33)",
 "just_fao33_p": "Simulamos un balance de agua diario con un \"tanque\" de agua útil en la raíz (supuesto: 100 mm, con análisis de sensibilidad entre 70 y 130 mm). Cuando el agua disponible no alcanza la demanda, el cultivo recibe menos agua (ETa < ETc) y el rendimiento relativo cae según FAO-33: Rend. = 100 × [1 − Ky × (1 − ETa/ETc)].",
 "just_kc_title": "Curva del coeficiente de cultivo (Kc) — {crop}", "just_kc_x": "Avance de la campaña (%)", "just_kc_y": "Kc",
 "just_check_title": "Verificación cruzada de la ET₀",
 "just_check_p": "Contrastamos Penman-Monteith con Hargreaves (solo temperatura), un método independiente: si ambos coinciden, el cálculo es consistente.",
 "just_check_pm": "Penman-Monteith (mm/año)", "just_check_hg": "Hargreaves (mm/año)", "just_check_diff": "Diferencia",
 "as_title": "Supuestos y límites del modelo (transparencia)",
 "as_1": "Datos: NASA POWER (rejilla modelada de ~50 km). **No sustituyen mediciones en la parcela** y aún no están validados con estaciones del SENAMHI.",
 "as_2": "Balance de agua diario con un tanque de **{taw} mm** de agua útil en la raíz (sensibilidad: {lo}–{hi} mm); lo que excede se pierde por drenaje o escorrentía.",
 "as_3": "Curva de Kc de forma genérica FAO-56 (25 % inicial, 25 % desarrollo, 30 % media, 20 % final) con el Kc de referencia de cada cultivo.",
 "as_4": "Siembra y ciclo por cultivo (supuestos a confirmar con el calendario SENAMHI): {cycles}.",
 "as_5": "Rendimiento relativo con FAO-33. Solo estrés hídrico: **no modela helada, granizo, plagas ni fertilidad del suelo**.",
 "as_6": "Heladas: días con temperatura mínima ≤ 0 °C en la rejilla. La rejilla suele subestimar el frío local; úsalo para comparar años, no como valor absoluto.",
 "as_7": "Campaña mala = rendimiento < {thr} %. Semáforo: verde ≤ {g} % de campañas malas, amarillo ≤ {y} %, rojo si más.",
 "as_8": "Reglas de rotación simplificadas, pendientes de validación con técnicos locales. El resultado es un riesgo climático histórico, no un pronóstico.",
 "why5_title": "¿Por qué solo 5 cultivos?",
 "why5_txt": "Para calcular el agua (Kc) y la respuesta al déficit (Ky) usamos coeficientes publicados por la FAO. Para cultivos andinos como la **cañihua** o el **tarwi** no encontramos coeficientes públicos suficientemente validados y preferimos no inventar datos. Nuestra hoja de ruta es validarlos con técnicos locales (INIA, UNA Puno).",
 "bib_title": "Bibliografía científica", "bib_acc": "Consultado el {d}.",
 "bib_c1": "Datos y observación satelital", "bib_c2": "Métodos agroclimáticos", "bib_c3": "Índices de sequía",
 "bib_c4": "Información local", "bib_c5": "Contexto e inspiración",
 "us_hero": "Datos de la NASA al servicio de quien siembra en los Andes",
 "us_hero_sub": "Somos dos jóvenes peruanos apasionados por usar la tecnología para mejorar la calidad de la agricultura en el Perú y, por qué no, en el mundo.",
 "us_mission_t": "Misión",
 "us_mission": "Convertir datos satelitales abiertos de la NASA en decisiones simples, confiables y gratuitas de siembra y rotación para los pequeños agricultores andinos, en un formato que puedan usar hoy mismo en su chacra.",
 "us_vision_t": "Visión",
 "us_vision": "Un Altiplano resiliente al clima, donde cada familia agricultora tenga inteligencia agroclimática comprensible y respetuosa de su saber ancestral, y donde esta herramienta pueda replicarse en otras regiones de los Andes.",
 "us_values_t": "Nuestros principios",
 "us_values": ["Datos abiertos y verificables", "Ciencia transparente: supuestos visibles", "Diseñado para el agricultor", "Respeto por el saber andino (aynoca)"],
 "us_how_t": "Cómo funciona SEEDRA",
 "us_how": [("Ubica tu parcela", "Elige un distrito, haz clic en el mapa o usa el GPS."),
            ("Cuéntanos qué sembraste", "La rotación aynoca parte de tu cultivo anterior."),
            ("Recibe una decisión clara", "Semáforo de riesgo, alternativa y mensaje listo para WhatsApp.")],
 "us_road_t": "Hoja de ruta (planes)",
 "us_road": ["Validar el modelo con estaciones del SENAMHI y técnicos del INIA y la UNA Puno.",
             "Incorporar cultivos andinos (cañihua, tarwi) cuando existan coeficientes validados.",
             "Quechua y aimara con revisión de hablantes nativos y mensajes de audio.",
             "Alertas por WhatsApp o SMS para zonas con poca conectividad.",
             "Replicar el piloto de Puno en otras regiones andinas."],
 "us_team_t": "Equipo fundador",
 "us_team": [{"initials": "FC", "name": "Equipo SEEDRA", "role": "Ciencia y datos", "bio": "Teledetección y modelos hídricos.", "color": "linear-gradient(135deg, #1B4332, #40916C)"},
             {"initials": "AQ", "name": "Equipo SEEDRA", "role": "Desarrollo y agronomía", "bio": "Producto útil y real para el agricultor.", "color": "linear-gradient(135deg, #9A6B2F, #D4A373)"}],
 "us_honest": "SEEDRA es una herramienta exploratoria de apoyo a la decisión. No reemplaza al técnico agrario y no pronostica cosechas: resume el riesgo climático histórico de cada cultivo en un lugar.",
 "footer": "SEEDRA · NASA Space Apps Challenge 2026 · Puno, Altiplano Peruano",
},
"en": {
 "hero_badge": "NASA Space Apps Challenge · Puno, Peru · 3,800 m a.s.l.",
 "hero_sub": "Environmental memory and smart crop rotation for the Altiplano",
 "dark_label": "Dark mode",
 "sidebar_tag": "NASA Space Apps",
 "prev_label": "What did you plant last season on this plot?",
 "none": "Nothing / fallow",
 "farmer_mode": "👨‍🌾 Farmer Mode",
 "sidebar_adv": "Advanced options", "sidebar_years": "NASA history (years)",
 "sidebar_analogs": "Match similar seasons",
 "sidebar_analogs_help": "Uses only the historical years whose soil moisture over the last 30 days was closest to the current one.",
 "sidebar_refresh": "Refresh data", "sidebar_loc": "Selected plot",
 "spinner": "Querying NASA POWER satellites and computing the water balance…",
 "err_power": "We could not reach NASA POWER and there is no saved copy for this location. Please retry in a few seconds.",
 "err_bounds": "The coordinates are outside the Puno Altiplano.",
 "err_nodata": "Not enough complete seasons to simulate.",
 "src_live": "NASA POWER (live)", "src_off": "saved NASA POWER copy (offline)",
 "tabs": ["Analysis", "Aynoca (Rotation)", "Time Machine", "Indices", "Science & sources", "About us"],
 "crops": {"Papa": "Potato", "Quinua": "Quinoa", "Habas": "Faba bean", "Cebada": "Barley", "Avena": "Oat"},
 "fams": {"tuberculo": "Tuber", "grano_andino": "Andean grain", "leguminosa": "Legume", "cereal": "Cereal"},
 "r_fallow": "The plot was fallow: any crop is valid.",
 "r_same": "Repeating the same crop builds up soil pests and diseases.",
 "r_samefam": "Same botanical family: little rotation benefit.",
 "r_t_leg": "The legume restores the nitrogen that potato removes.",
 "r_t_gr": "Breaks the key potato pest cycle (such as the Andean potato weevil).",
 "r_t_cer": "The cereal breaks the potato pest cycle and covers the soil.",
 "r_leg_cer": "The cereal uses the nitrogen left by the faba beans.",
 "r_leg_t": "Potato uses the nitrogen left by the faba beans.",
 "r_leg_gr": "Quinoa uses the residual nitrogen from the faba beans.",
 "r_cer_leg": "Faba beans restore soil fertility after a cereal.",
 "r_cer_t": "Potato fits well after a cereal.",
 "r_cer_gr": "Diversifies the system after a cereal.",
 "r_gr_leg": "Faba beans restore the soil after quinoa.",
 "r_gr_t": "Potato fits well after quinoa.",
 "r_gr_cer": "Diversifies the system after quinoa.",
 "district_pick": "Jump to a Puno district", "district_custom": "Custom point (click on the map)",
 "map_streets": "Streets", "map_sat": "HD satellite", "map_ndvi": "NDVI (area vegetation, NASA MODIS)",
 "map_hint": "Click anywhere on the map or use GPS to recalculate. MODIS NDVI (≥250 m) shows area-wide vegetation, not an individual plot.",
 "analysis_title": "Decision analysis", "farmer_title": "Your season decision",
 "badge_green": "Low risk: Plant {crop}",
 "badge_yellow": "Medium risk: Plant {crop} with care",
 "badge_red": "High risk: Water shortage",
 "chip_green": "Low risk", "chip_yellow": "Medium risk", "chip_red": "High risk",
 "farmer_sub_green": "In most past seasons there was enough water for {crop}.",
 "farmer_sub_yellow": "Some past seasons ran short of water: watch soil moisture at sowing and cover the soil.",
 "farmer_sub_red": "The best available option is {crop}. Without irrigation, consider letting the plot rest this year.",
 "why_label": "Why", "alt_label": "Alternative",
 "bad_years": "In {n} of {t} past seasons, water shortage would have cut the {crop} harvest by more than {p}%.",
 "rain_now": "Since October 1 it has rained {p}% of normal for this date.",
 "kpi_yield": "Expected yield", "kpi_p20": "Adverse year (P20)", "kpi_risk": "Loss risk", "kpi_frost": "Expected frosts",
 "kpi_days": "days", "kpi_range": "depending on soil: {a}–{b}%",
 "kpi_rain": "Rain since Oct 1", "kpi_rain_s": "{p}% of normal", "kpi_sm": "Root-zone saturation", "kpi_sm_s": "normal: {v}",
 "kpi_frost2": "Frost days (≤0 °C)", "kpi_frost2_s": "normal to date: {n}",
 "farmer_comp_title": "Quick comparison of your options",
 "farmer_share": "Share via WhatsApp",
 "farmer_share_msg": "SEEDRA Puno: for my plot ({lat:.3f}, {lon:.3f}), the best option is {crop}. {msg}.",
 "btn_card": "Download season card",
 "card_title": "SEEDRA SEASON CARD", "card_date": "Date", "card_plot": "Plot", "card_before": "Planted before",
 "card_sow": "RECOMMENDED CROP", "card_reason": "Reason", "card_bad": "Bad seasons in the record", "card_alt": "Alternative",
 "card_disc": "Exploratory tool using NASA POWER data. It does not replace an agricultural technician.",
 "col_crop": "Crop", "col_yield": "Typical yield (P50) %", "col_p20": "Bad year (P20) %", "col_risk": "Bad seasons %",
 "col_frost": "Frosts (days)", "col_rot": "Rotation", "yes": "Optimal", "mid": "Medium", "no": "Low",
 "chart_t1_title": "Expected yield and risk by crop", "chart_t1_x": "Median yield (%)", "chart_t1_color": "Risk (%)",
 "tt_crop": "Crop", "tt_p50": "Median P50 (%)", "tt_p20": "Dry scenario P20 (%)", "tt_risk": "Bad seasons (%)", "tt_frost": "Frosts (days)", "tt_agro": "Rotation index",
 "analogs_active": "Analog mode on: evaluated over {n} seasons similar to the current one.",
 "src_cap": "Source: {src}. Relative estimate to compare crops and seasons; not a harvest forecast.",
 "n_hist": "Based on {n} historical seasons.",
 "aynoca_title": "Aynoca community planner (4-season rotation)",
 "aynoca_desc": "The ancestral Aynoca system organizes land in turns to break pest cycles and restore the soil. SEEDRA keeps that logic (previous crop first) and filters it with the season's water risk.",
 "aynoca_step": "Season", "aynoca_current": "Base season (previous)",
 "aynoca_matrix_title": "Agronomic compatibility matrix", "aynoca_matrix_x": "Candidate crop", "aynoca_matrix_y": "Previous crop",
 "aynoca_matrix_score": "Compatibility", "aynoca_tt_reason": "Rationale",
 "aynoca_cap": "Simplified agronomic rules and historical climate. To be validated with local technicians (INIA, UNA Puno).",
 "all_high": "All options carry a high risk of water shortage: letting the plot rest (fallow) is also a valid decision this year.",
 "tm_title": "Agroclimatic Time Machine", "tm_subtitle": "Historical reconstruction with the FAO-56 / FAO-33 water balance: what would have happened in each past season.",
 "tm_crop_select": "Crop to inspect",
 "tm_kpi_slope": "Yield trend", "tm_kpi_onset": "Rain onset", "tm_kpi_frost": "Frost trend", "tm_kpi_r2": "Significance (R² / p)",
 "tm_per_decade": "% per decade", "tm_days_decade": "days per decade", "tm_onset_hint": "(+) = later",
 "tm_chart1_title": "Historical series and trend — {crop}", "tm_chart1_sub": "Slope: {slope:+.2f}% per decade | R² = {r2:.3f}",
 "tm_chart1_y": "Simulated yield (%)", "tm_chart1_x": "Growing season",
 "tm_status_ok": "Viable season (≥60%)", "tm_status_loss": "Water loss (<60%)",
 "tm_chart2_title": "Start of the rainy season", "tm_chart2_y": "Days since September 1",
 "tm_chart3_title": "Rainfall (mm) and frosts per season", "tm_chart3_rain": "Seasonal rainfall (mm)", "tm_chart3_frost": "Frost days",
 "tm_tt_year": "Season", "tm_tt_yield": "Yield (%)", "tm_tt_rain": "Rain (mm)", "tm_tt_eta": "Actual ET / ETc (%)", "tm_tt_frost": "Frosts (days)", "tm_tt_onset": "Onset day",
 "tm_sig_no": "The trend is not statistically significant (p ≥ 0.10): what does change a lot is the variability between years.",
 "tm_sig_yes": "The trend is statistically significant (p < 0.10).",
 "tm_def": "Rain onset: first day since Sep 1 when {d}-day rainfall adds up to at least {mm} mm.",
 "idx_title": "Hydrometeorological indices and satellite soil moisture", "idx_desc": "Drought diagnosis (seasonal SPI) and soil moisture derived from NASA POWER.",
 "idx_sm_surf": "Surface moisture", "idx_sm_root": "Root-zone moisture", "idx_spi_now": "SPI last season (Sep–Apr)", "idx_wb_now": "Annual balance (P − ET₀)",
 "idx_spi_wet": "Wet", "idx_spi_norm": "Normal", "idx_spi_dry": "Deficit",
 "idx_chart_spi_title": "Standardized Precipitation Index (SPI) per season", "idx_chart_spi_y": "Standard deviations",
 "idx_chart_wb_title": "Average monthly water balance", "idx_chart_wb_y": "Depth (mm/month)", "idx_chart_wb_x": "Month",
 "idx_precip": "Precipitation", "idx_et0": "ET₀", "idx_var": "Variable",
 "idx_months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
 "just_title": "Scientific and agronomic foundations",
 "just_fao56_h": "1. Evapotranspiration (FAO-56 Penman-Monteith)",
 "just_fao56_p": "We do not use rainfall alone. We compute the atmosphere's evaporative demand (ET₀) from NASA POWER solar radiation, maximum and minimum temperature, wind and relative humidity, using net radiation and adjusting for Puno's altitude. We then convert it into crop demand (ETc = Kc × ET₀) with a stage-based Kc curve.",
 "just_fao33_h": "2. Yield response to water stress (FAO-33)",
 "just_fao33_p": "We simulate a daily water balance with a root-zone \"bucket\" of available water (assumption: 100 mm, with a sensitivity analysis between 70 and 130 mm). When available water does not meet demand, the crop receives less water (ETa < ETc) and relative yield drops following FAO-33: Yield = 100 × [1 − Ky × (1 − ETa/ETc)].",
 "just_kc_title": "Crop coefficient (Kc) curve — {crop}", "just_kc_x": "Season progress (%)", "just_kc_y": "Kc",
 "just_check_title": "ET₀ cross-check",
 "just_check_p": "We compare Penman-Monteith against Hargreaves (temperature only), an independent method: if both agree, the calculation is consistent.",
 "just_check_pm": "Penman-Monteith (mm/yr)", "just_check_hg": "Hargreaves (mm/yr)", "just_check_diff": "Difference",
 "as_title": "Model assumptions and limits (transparency)",
 "as_1": "Data: NASA POWER (~50 km modeled grid). **They do not replace on-plot measurements** and are not yet validated against SENAMHI stations.",
 "as_2": "Daily water balance with a **{taw} mm** root-zone bucket of available water (sensitivity: {lo}–{hi} mm); any excess is lost to drainage or runoff.",
 "as_3": "Generic FAO-56 Kc curve shape (25 % initial, 25 % development, 30 % mid, 20 % late) using each crop's reference Kc.",
 "as_4": "Sowing date and cycle per crop (assumptions to confirm with the SENAMHI calendar): {cycles}.",
 "as_5": "Relative yield with FAO-33. Water stress only: **it does not model frost, hail, pests or soil fertility**.",
 "as_6": "Frost: days with minimum temperature ≤ 0 °C on the grid. The grid tends to underestimate local cold; use it to compare years, not as an absolute value.",
 "as_7": "Bad season = yield < {thr} %. Traffic light: green ≤ {g} % bad seasons, yellow ≤ {y} %, red above.",
 "as_8": "Simplified rotation rules, pending validation with local technicians. The result is a historical climate risk, not a forecast.",
 "why5_title": "Why only 5 crops?",
 "why5_txt": "To compute water use (Kc) and the response to deficit (Ky) we use coefficients published by FAO. For Andean crops such as **cañihua** or **tarwi** we did not find sufficiently validated public coefficients and prefer not to invent data. Our roadmap is to validate them with local technicians (INIA, UNA Puno).",
 "bib_title": "Scientific references", "bib_acc": "Accessed {d}.",
 "bib_c1": "Satellite data and observation", "bib_c2": "Agroclimatic methods", "bib_c3": "Drought indices",
 "bib_c4": "Local information", "bib_c5": "Context and inspiration",
 "us_title": "About us",
 "us_hero": "NASA data in the hands of those who farm the Andes",
 "us_hero_sub": "We are two passionate young Peruvians using technology to improve the quality of agriculture in Peru and, why not, around the world.",
 "us_mission_t": "Mission",
 "us_mission": "To turn NASA's open satellite data into simple, reliable and free planting and rotation decisions for smallholder Andean farmers, in a format they can use today on their own plot.",
 "us_vision_t": "Vision",
 "us_vision": "A climate-resilient Altiplano where every farming family has agroclimatic intelligence that is understandable and respectful of their ancestral knowledge, and where this tool can be replicated in other Andean regions.",
 "us_values_t": "Our principles",
 "us_values": ["Open and verifiable data", "Transparent science: visible assumptions", "Designed for the farmer", "Respect for Andean knowledge (aynoca)"],
 "us_how_t": "How SEEDRA works",
 "us_how": [("Locate your plot", "Pick a district, click on the map or use GPS."),
            ("Tell us what you planted", "Aynoca rotation starts from your previous crop."),
            ("Get a clear decision", "Risk traffic light, an alternative and a WhatsApp-ready message.")],
 "us_road_t": "Roadmap (plans)",
 "us_road": ["Validate the model with SENAMHI stations and INIA and UNA Puno technicians.",
             "Add Andean crops (cañihua, tarwi) once validated coefficients exist.",
             "Quechua and Aymara, reviewed by native speakers, plus audio messages.",
             "WhatsApp or SMS alerts for low-connectivity areas.",
             "Replicate the Puno pilot in other Andean regions."],
 "us_team_t": "Founding team",
 "us_team": [{"initials": "FC", "name": "SEEDRA Team", "role": "Science & data", "bio": "Remote sensing and water models.", "color": "linear-gradient(135deg, #1B4332, #40916C)"},
             {"initials": "AQ", "name": "SEEDRA Team", "role": "Development & agronomy", "bio": "A useful, real product for the farmer.", "color": "linear-gradient(135deg, #9A6B2F, #D4A373)"}],
 "us_honest": "SEEDRA is an exploratory decision-support tool. It does not replace an agricultural technician and does not forecast harvests: it summarizes the historical climate risk of each crop at a location.",
 "footer": "SEEDRA · NASA Space Apps Challenge 2026 · Puno, Peruvian Altiplano",
},
"ay": {
 # REVISAR CON HABLANTE NATIVO ANTES DE PUBLICAR. Solo interfaz y Modo Agricultor; lo demás cae a español.
 "hero_sub": "Kuna yapuchañäni jichha mara: NASA yatiyawinakampi",
 "dark_label": "Ch'iyara",
 "prev_label": "Aka yapuruxa nayra marana kuna yapuchata?",
 "none": "Janiw kunas · samarata",
 "farmer_mode": "Yapuchiri",
 "sidebar_adv": "Juk'ampinaka", "sidebar_years": "NASA nayra yatiyawi (mara)",
 "sidebar_analogs": "Kikpa maranakampi", "sidebar_refresh": "Machaqar tukuyaña", "sidebar_loc": "Yapu uñt'ayata",
 "spinner": "NASA satélitempi yatiyawi thaqhaña…",
 "err_power": "NASA POWER ukar janiw puriyasiwa. Mayampi yant'am.",
 "err_nodata": "Yatiyawixa juk'awa.",
 "src_live": "NASA POWER (jichha)", "src_off": "NASA POWER imata (jan internet)",
 "tabs": ["Uñakipaña", "Aynuqa (muytaña)", "Nayra pacha", "Chimpunaka", "Yatiyawi", "Jiwasanaka"],
 "crops": {"Papa": "Ch'uqi (Papa)", "Quinua": "Jupha (Quinua)", "Habas": "Habas", "Cebada": "Siwara (Cebada)", "Avena": "Awina (Avena)"},
 "fams": {"tuberculo": "Ch'uqi laya", "grano_andino": "Jawira laya", "leguminosa": "Habas laya", "cereal": "Cereal"},
 "r_fallow": "Yapux samarataynaw: kunatï yapuchañas waliki.",
 "r_same": "Kikpa yapuchañax laq'a ch'amanak jilayi.",
 "r_samefam": "Kikpa layawa: juk'a muytaña.",
 "r_t_leg": "Habas ukax uraqir nitrógeno kutiyi.",
 "r_t_gr": "Mayni laya yapuchañax laq'a ch'amanak tukuyi.",
 "r_t_cer": "Cereal ukax laq'a ch'amanak tukuyi.",
 "r_leg_cer": "Cereal ukax habas nitrógeno apnaqi.",
 "r_leg_t": "Ch'uqix habas nitrógeno apnaqi.",
 "r_leg_gr": "Jupha ukax habas nitrógeno apnaqi.",
 "r_cer_leg": "Habas ukax uraqi walichi.",
 "r_cer_t": "Ch'uqix cereal qhipatxa waliki.",
 "r_cer_gr": "Waljaki yapuchañawa.",
 "r_gr_leg": "Habas ukax uraqi walichi.",
 "r_gr_t": "Ch'uqix jupha qhipatxa waliki.",
 "r_gr_cer": "Waljaki yapuchañawa.",
 "district_pick": "Marka ajlliña", "district_custom": "Mapa ukan clic lurañani",
 "map_streets": "Thakinaka", "map_sat": "Satélite HD",
 "farmer_title": "Mara yapuchäwi amtawi",
 "badge_green": "Waliki: {crop} yapuchañawa",
 "badge_yellow": "Amuyasiña: {crop} yapuchañawa, sum uñjasa",
 "badge_red": "Jan waliki: uma pisiwa",
 "chip_green": "Waliki", "chip_yellow": "Amuyasiña", "chip_red": "Jan waliki",
 "farmer_sub_red": "Aka maraxa waliki: {crop}. Jan umachasiñamax utjani ukhaxa, aka mara yapu samarayañ amtam.",
 "why_label": "Kunatsa", "alt_label": "Mayni yapuchaña",
 "bad_years": "Nayra {t} maratxa, {n} maranxa uma pisiwa {crop} ukataki.",
 "rain_now": "1 octubre ukata jichhakama jallu: {p}% (sapa maranjam).",
 "kpi_yield": "Apthapi", "kpi_risk": "Jan waliki mara", "kpi_frost": "Juyphi", "kpi_days": "uru",
 "farmer_comp_title": "Aka yapurux kuna yapuchañanaka waliki",
 "farmer_share": "WhatsAppampi apayaña",
 "btn_card": "Cartilla katuqaña",
 "col_crop": "Yapuchaña", "col_yield": "Apthapi %", "col_risk": "Jan waliki maranaka %",
 "us_title": "Jiwasanaka",
},
}

def get_text(lang):
    base = dict(I18N["es"])
    base.update(I18N.get(lang, {}))
    return base

# ==============================================================================
# 3. ESTADO, IDIOMA Y TEMA
# ==============================================================================
for k, v in {"map_center": [PUNO[0], PUNO[1]], "map_zoom": 10, "selected_lat": PUNO[0], "selected_lon": PUNO[1],
             "lang": "es", "dark_mode": False, "district": "__custom__", "pending_custom": False}.items():
    st.session_state.setdefault(k, v)
if st.session_state.pop("pending_custom", False):
    st.session_state["district"] = "__custom__"

L = st.session_state["lang"]
T = get_text(L)
DARK = st.session_state["dark_mode"]

def t_crop(key):
    return T["none"] if key == NO_PREV else T["crops"].get(key, key)

def t_fam(key):
    return T["fams"].get(key, key)

if DARK:
    THEME = {
        "bg_app": "#0B1210", "bg_sidebar": "#101A17", "bg_card": "#14221D", "bg_card_alt": "#1A2B25",
        "text_main": "#ECF3EF", "text_muted": "#9BB0A5", "border": "rgba(155,176,165,0.22)",
        "accent": "#34D399", "accent_gold": "#E3B374", "accent_blue": "#60A5FA", "accent_red": "#F87171", "accent_amber": "#FBBF24",
        "badge_g_bg": "#0F291E", "badge_g_tx": "#A7F3D0", "badge_g_bd": "#10B981",
        "badge_y_bg": "#2B1F0A", "badge_y_tx": "#FDE68A", "badge_y_bd": "#F59E0B",
        "badge_r_bg": "#2D1215", "badge_r_tx": "#FECACA", "badge_r_bd": "#EF4444",
        "footer_bg": "#080D0B", "footer_tx": "#8DA196", "input_bg": "#182822", "shadow": "0 6px 24px rgba(0,0,0,0.45)",
    }
else:
    THEME = {
        "bg_app": "#F6F8F5", "bg_sidebar": "#ECF1EC", "bg_card": "#FFFFFF", "bg_card_alt": "#F1F6F2",
        "text_main": "#13261C", "text_muted": "#4C6055", "border": "rgba(26,60,52,0.16)",
        "accent": "#1B5E20", "accent_gold": "#B87A2B", "accent_blue": "#1D4ED8", "accent_red": "#C62828", "accent_amber": "#D97706",
        "badge_g_bg": "#E8F5E9", "badge_g_tx": "#144D19", "badge_g_bd": "#2E7D32",
        "badge_y_bg": "#FFF6E5", "badge_y_tx": "#8A3C00", "badge_y_bd": "#F57C00",
        "badge_r_bg": "#FFEBEE", "badge_r_tx": "#8E1616", "badge_r_bd": "#C62828",
        "footer_bg": "#15221C", "footer_tx": "#B8C7BF", "input_bg": "#FFFFFF", "shadow": "0 6px 24px rgba(19,38,28,0.08)",
    }

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');
/* Ocultar solo el menú de 3 puntos y el botón de Deploy, NO el header completo */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stDecoration"] { display: none !important; }

/* Hacer el header transparente pero funcional */
[data-testid="stHeader"] { 
    background: transparent !important; 
    display: flex !important; /* Obliga a que el header exista */
}

/* Forzar que la flechita para abrir el sidebar siempre esté visible */
[data-testid="stSidebarCollapsedControl"] { 
    display: block !important; 
    visibility: visible !important;
    color: [[text_main]] !important;
    background-color: [[bg_card]] !important;
    border-radius: 8px;
    border: 1px solid [[border]] !important;
    margin-top: 10px;
    margin-left: 10px;
}
.block-container { padding-top: 1rem !important; padding-bottom: 1.5rem !important; max-width: 1320px; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background-color: [[bg_app]] !important; color: [[text_main]] !important; font-family: 'Inter', sans-serif !important; }
[data-testid="stSidebar"], [data-testid="stSidebarContent"] { background-color: [[bg_sidebar]] !important; border-right: 1px solid [[border]] !important; }
[data-testid="stSidebar"] * { color: [[text_main]] !important; }
p, label, div, li { font-family: 'Inter', sans-serif !important; color: [[text_main]]; }
span:not([data-testid="stIconMaterial"]) { font-family: 'Inter', sans-serif !important; color: [[text_main]]; }
[data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons, [data-testid="stSidebarCollapseButton"] span { 
    font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important; 
}
h1, h2, h3, h4 { font-family: 'Playfair Display', serif !important; color: [[text_main]] !important; font-weight: 700; letter-spacing: -0.4px; }
a { color: [[accent]] !important; }
[data-testid="stCaptionContainer"] * { color: [[text_muted]] !important; }
div[data-testid="stHorizontalBlock"]:has(.topbar-anchor) { flex-wrap: nowrap !important; align-items: center !important; gap: 0.6rem !important; }
div[data-testid="stHorizontalBlock"]:has(.topbar-anchor) > div { min-width: 0 !important; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div { background-color: [[input_bg]] !important; color: [[text_main]] !important; border-color: [[border]] !important; }
div[data-baseweb="select"] * { color: [[text_main]] !important; }
div[data-baseweb="select"] svg { fill: [[text_main]] !important; }
div[data-baseweb="popover"] > div, ul[data-baseweb="menu"], div[data-baseweb="popover"] ul { background-color: [[bg_card]] !important; color: [[text_main]] !important; }
li[role="option"] { background-color: [[bg_card]] !important; color: [[text_main]] !important; }
li[role="option"]:hover, li[aria-selected="true"] { background-color: [[bg_card_alt]] !important; }
[data-testid="stExpander"] { background-color: [[bg_card]] !important; border: 1px solid [[border]] !important; border-radius: 10px !important; }
[data-testid="stExpander"] summary * { color: [[text_main]] !important; }
[data-testid="stTabs"] button[role="tab"] { color: [[text_muted]] !important; font-weight: 600 !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: [[accent]] !important; }
div[data-baseweb="tab-highlight"] { background-color: [[accent]] !important; }
div[data-baseweb="tab-border"] { background-color: [[border]] !important; }
.stButton > button, .stDownloadButton > button { background-color: [[bg_card]] !important; color: [[text_main]] !important; border: 1px solid [[border]] !important; border-radius: 8px !important; font-weight: 600 !important; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: [[accent]] !important; color: [[accent]] !important; }
.carousel-container { position: relative; width: 100%; height: 270px; overflow: hidden; border-radius: 16px; margin: 8px 0 18px 0; box-shadow: [[shadow]]; border: 1px solid [[border]]; }
.carousel-slide { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background-size: cover; background-position: center; opacity: 0; animation: fade 24s infinite; }
.carousel-slide:nth-child(1) { animation-delay: 0s; background-image: url('https://images.unsplash.com/photo-1526392060635-9d6019884377?q=80&w=1600&auto=format&fit=crop'); }
.carousel-slide:nth-child(2) { animation-delay: 6s; background-image: url('https://images.unsplash.com/photo-1590682680695-43b964a3ae17?q=80&w=1600&auto=format&fit=crop'); }
.carousel-slide:nth-child(3) { animation-delay: 12s; background-image: url('https://images.unsplash.com/photo-1580619305218-8423a7ef79b4?q=80&w=1600&auto=format&fit=crop'); }
.carousel-slide:nth-child(4) { animation-delay: 18s; background-image: url('https://images.unsplash.com/photo-1500382017468-9049fed747ef?q=80&w=1600&auto=format&fit=crop'); }
@keyframes fade { 0% { opacity: 0; } 10% { opacity: 1; } 33% { opacity: 1; } 43% { opacity: 0; } 100% { opacity: 0; } }
.carousel-overlay { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(10,34,25,0.35) 0%, rgba(10,34,25,0.88) 100%); display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; z-index: 10; padding: 0 20px; }
.carousel-title { color: #FFFFFF !important; font-size: 3.2rem; margin: 0; text-shadow: 0 4px 18px rgba(0,0,0,0.65); }
.carousel-subtitle { color: #E2E8F0 !important; font-size: 1.1rem; font-weight: 500; text-shadow: 0 2px 10px rgba(0,0,0,0.65); margin-top: 6px; }
.data-card { background-color: [[bg_card]]; border: 1px solid [[border]]; border-radius: 14px; padding: 16px 20px; margin-bottom: 14px; box-shadow: [[shadow]]; }
.kpi-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; color: [[text_muted]] !important; font-weight: 600; }
.data-value { font-family: 'Playfair Display', serif !important; font-size: 2rem; font-weight: 700; color: [[text_main]] !important; margin-top: 4px; line-height: 1.15; }
.kpi-sub { font-size: 0.8rem; color: [[text_muted]] !important; margin-top: 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 11px; border-radius: 999px; font-weight: 600; font-size: 0.78rem; white-space: nowrap; }
.chip::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.chip-green { background: [[badge_g_bg]]; color: [[badge_g_tx]] !important; border: 1px solid [[badge_g_bd]]; }
.chip-yellow { background: [[badge_y_bg]]; color: [[badge_y_tx]] !important; border: 1px solid [[badge_y_bd]]; }
.chip-red { background: [[badge_r_bg]]; color: [[badge_r_tx]] !important; border: 1px solid [[badge_r_bd]]; }
.chip-plain { border: 1px solid [[border]]; color: [[text_muted]] !important; }
.chip-plain::before { display: none; }
.badge-green { background-color: [[badge_g_bg]]; color: [[badge_g_tx]] !important; border-left: 6px solid [[badge_g_bd]]; }
.badge-yellow { background-color: [[badge_y_bg]]; color: [[badge_y_tx]] !important; border-left: 6px solid [[badge_y_bd]]; }
.badge-red { background-color: [[badge_r_bg]]; color: [[badge_r_tx]] !important; border-left: 6px solid [[badge_r_bd]]; }
.badge-green *, .badge-yellow *, .badge-red * { color: inherit !important; }
.farmer-hero { border-radius: 16px; padding: 22px; margin-bottom: 14px; display: flex; align-items: center; gap: 18px; }
.farmer-light { width: 58px; height: 58px; min-width: 58px; border-radius: 50%; box-shadow: 0 0 0 6px rgba(255,255,255,0.10), 0 0 24px rgba(0,0,0,0.25); }
.farmer-title { font-family: 'Playfair Display', serif !important; font-size: 1.45rem; font-weight: 700; line-height: 1.25; }
.farmer-sub { font-size: 0.95rem; font-weight: 500; opacity: 0.92; margin-top: 4px; }
.lines { margin: 6px 0 12px 0; padding-left: 1.1rem; } .lines li { margin-bottom: 6px; }
.tbl-wrap { overflow-x: auto; margin-bottom: 10px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.tbl th { text-align: left; color: [[text_muted]]; font-weight: 600; font-size: 0.75rem; letter-spacing: 0.4px; padding: 8px 10px; border-bottom: 1px solid [[border]]; }
.tbl td { padding: 9px 10px; border-bottom: 1px solid [[border]]; }
.tbl tr:last-child td { border-bottom: none; }
.wa-btn { display: inline-block; background-color: #25D366; color: #06240F !important; padding: 10px 18px; border-radius: 10px; font-weight: 700; text-decoration: none; margin: 8px 8px 8px 0; }
.us-hero { background: linear-gradient(135deg, #1B4332, #40916C 60%, #D4A373); border-radius: 20px; padding: 36px 30px; margin-bottom: 18px; box-shadow: [[shadow]]; }
.us-hero h2, .us-hero p { color: #FFFFFF !important; margin: 0; text-shadow: 0 1px 8px rgba(0,0,0,0.3); }
.us-hero p { margin-top: 10px; font-size: 1.05rem; line-height: 1.6; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin-bottom: 14px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; margin-bottom: 14px; }
.panel-accent { border-top: 4px solid [[accent]]; }
.panel-gold { border-top: 4px solid [[accent_gold]]; }
.step-num { width: 34px; height: 34px; border-radius: 50%; background: linear-gradient(135deg, [[accent]], [[accent_gold]]); color: #FFFFFF !important; display: flex; align-items: center; justify-content: center; font-weight: 700; margin-bottom: 10px; }
.road-item { display: flex; gap: 12px; align-items: flex-start; padding: 10px 0; border-bottom: 1px solid [[border]]; }
.road-item:last-child { border-bottom: none; }
.team-card { background-color: [[bg_card]]; border: 1px solid [[border]]; border-radius: 16px; padding: 22px 18px; text-align: center; height: 100%; box-shadow: [[shadow]]; }
.avatar-circle { width: 72px; height: 72px; border-radius: 50%; margin: 0 auto 12px auto; display: flex; align-items: center; justify-content: center; font-family: 'Playfair Display', serif !important; font-size: 1.5rem; font-weight: 700; color: #FFFFFF !important; box-shadow: 0 6px 18px rgba(0,0,0,0.20); }
.refs { padding-left: 1.3rem; } .refs li { margin-bottom: 10px; line-height: 1.5; font-size: 0.92rem; }
.custom-footer { background-color: [[footer_bg]]; text-align: center; padding: 26px; border-radius: 12px; margin-top: 36px; border: 1px solid [[border]]; }
.custom-footer * { color: [[footer_tx]] !important; }
#vg-tooltip-element { background: [[bg_card]] !important; color: [[text_main]] !important; border: 1px solid [[border]] !important; border-radius: 10px !important; box-shadow: [[shadow]] !important; font-family: 'Inter', sans-serif !important; }
#vg-tooltip-element .key { color: [[text_muted]] !important; } #vg-tooltip-element .value { color: [[text_main]] !important; }
</style>
"""
for _k, _v in THEME.items():
    CSS = CSS.replace("[[" + _k + "]]", _v)
st.markdown(CSS, unsafe_allow_html=True)

STRETCH = {"width": "stretch"} if "width" in inspect.signature(st.button).parameters else {"use_container_width": True}

def show_chart(ch):
    try:
        st.altair_chart(ch, theme=None, width="stretch")
    except TypeError:
        st.altair_chart(ch, theme=None, use_container_width=True)

def style_altair(chart, height=340, padding=None):
    kw = {"height": height, "background": "transparent"}
    if padding:
        kw["padding"] = padding
    return (chart.properties(**kw)
            .configure_view(strokeWidth=0, fill="transparent")
            .configure_axis(grid=False, gridOpacity=0, domainColor=THEME["border"], tickColor=THEME["border"],
                            labelColor=THEME["text_muted"], titleColor=THEME["text_main"], labelFont="Inter", titleFont="Inter",
                            labelFontSize=11, titleFontSize=12, titlePadding=10)
            .configure_legend(labelColor=THEME["text_main"], titleColor=THEME["text_main"], labelFont="Inter", titleFont="Inter", orient="top")
            .configure_title(color=THEME["text_main"], subtitleColor=THEME["text_muted"], font="Playfair Display",
                             subtitleFont="Inter", fontSize=16, subtitleFontSize=12, anchor="start"))

def chip(level, text):
    return '<span class="chip chip-' + level + '">' + text + "</span>"

def kpi(label, value, sub=""):
    return '<div class="data-card"><div class="kpi-label">' + label + '</div><div class="data-value">' + value + '</div><div class="kpi-sub">' + sub + "</div></div>"

def html_table(headers, rows):
    th = "".join("<th>" + h + "</th>" for h in headers)
    body = "".join("<tr>" + "".join("<td>" + str(c) + "</td>" for c in r) + "</tr>" for r in rows)
    return '<div class="tbl-wrap"><table class="tbl"><thead><tr>' + th + "</tr></thead><tbody>" + body + "</tbody></table></div>"

def level_of(risk):
    if risk <= GREEN_MAX: return "green"
    if risk <= YELLOW_MAX: return "yellow"
    return "red"

def fmt(v, d=0, suf=""):
    return "N/D" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{d}f}{suf}"

def get_b64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

# ==============================================================================
# 4. BARRA SUPERIOR (idioma + modo oscuro), BANNER Y CONTROLES
# ==============================================================================
bar = st.columns([5, 2.4, 2])
with bar[0]:
    st.markdown('<span class="topbar-anchor"></span><div style="padding-top:6px; font-size:0.85rem; opacity:0.85; font-weight:600; letter-spacing:0.04em;">' + T["hero_badge"] + "</div>", unsafe_allow_html=True)
with bar[1]:
    st.selectbox("Language", list(LANGS), format_func=lambda c: LANGS[c], key="lang", label_visibility="collapsed")
with bar[2]:
    st.toggle(T["dark_label"], key="dark_mode")

st.markdown('<div class="carousel-container"><div class="carousel-slide"></div><div class="carousel-slide"></div><div class="carousel-slide"></div><div class="carousel-slide"></div>'
            '<div class="carousel-overlay"><h1 class="carousel-title">SEEDRA</h1><p class="carousel-subtitle">' + T["hero_sub"] + "</p></div></div>", unsafe_allow_html=True)

with st.sidebar:
    try:
        st.image("NASA.svg", width=110)
    except Exception:
        st.markdown("### " + T["sidebar_tag"])
    logo_b64 = get_b64("logo.png")
    if logo_b64:
        st.image("data:image/png;base64," + logo_b64, width=130)
    else:
        st.markdown("## SEEDRA")
    st.divider()
    with st.expander(T["sidebar_adv"], expanded=True):
        years = st.selectbox(T["sidebar_years"], [10, 15, 20, 25, 30, 40], index=4, key="opt_years")
        usar_analogos = st.checkbox(T["sidebar_analogs"], value=False, help=T["sidebar_analogs_help"], key="opt_analog")
        if st.button(T["sidebar_refresh"], key="btn_refresh"):
            st.cache_data.clear()
    st.markdown('<div class="data-card"><div class="kpi-label">' + T["sidebar_loc"] + '</div><div style="font-weight:700; margin-top:4px;">'
                + f"{st.session_state['selected_lat']:.4f}°, {st.session_state['selected_lon']:.4f}°" + "</div></div>", unsafe_allow_html=True)

# Controles principales en la página (en el celular la barra lateral está oculta)
cc1, cc2 = st.columns([3, 1])
with cc1:
    prev = st.selectbox(T["prev_label"], [NO_PREV] + list(CROPS), index=1, format_func=t_crop, key="prev")
with cc2:
    st.write("")
    modo_agricultor = st.toggle(T["farmer_mode"], key="farmer")

# ==============================================================================
# 5. MOTOR CIENTÍFICO: NASA POWER, ET0 (FAO-56), BALANCE DE AGUA, FAO-33, HINDCAST, SPI (OMM)
# ==============================================================================
def near_puno(lat, lon):
    return abs(lat - PUNO[0]) <= 0.15 and abs(lon - PUNO[1]) <= 0.15

def in_puno(lat, lon):
    a, b, c, d = BOUNDS
    return a <= lat <= b and c <= lon <= d

@st.cache_data(ttl=21600, show_spinner=False)
def get_power(lat, lon, start, end):
    """Sin try/except interno a propósito: si falla, Streamlit NO guarda el error en caché."""
    params = {"parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,ALLSKY_SFC_SW_DWN,WS2M,RH2M,GWETTOP,GWETROOT", "community": "AG",
              "longitude": lon, "latitude": lat, "start": start, "end": end, "format": "JSON"}
    r = requests.get(POWER_URL, params=params, timeout=(10, 90))
    r.raise_for_status()
    p = r.json().get("properties", {}).get("parameter", {})
    if "PRECTOTCORR" not in p:
        raise ValueError("Respuesta de NASA POWER sin precipitación")
    dates = sorted(p["PRECTOTCORR"])
    out = pd.DataFrame({"fecha": pd.to_datetime(dates, format="%Y%m%d")})
    mapping = {"PRECTOTCORR": "precip_mm", "T2M_MAX": "tmax_c", "T2M_MIN": "tmin_c", "ALLSKY_SFC_SW_DWN": "solar",
               "WS2M": "wind_ms", "RH2M": "rh_pct", "GWETTOP": "sm_surface", "GWETROOT": "sm_root"}
    for src, dst in mapping.items():
        vals = p.get(src, {})
        out[dst] = pd.to_numeric([vals.get(d, np.nan) for d in dates], errors="coerce")
        out.loc[out[dst] < -900, dst] = np.nan
    return out

def load_climate(lat, lon, start, end):
    # La rejilla de POWER es de ~50 km: redondear a 0.1° no pierde información y evita repetir pedidos.
    lat, lon = round(lat, 1), round(lon, 1)
    try:
        df = get_power(lat, lon, start, end)
        if near_puno(lat, lon) and not os.path.exists(SNAPSHOT):
            try:
                df.to_csv(SNAPSHOT, index=False)
            except Exception:
                pass
        return df, "src_live"
    except Exception:
        if near_puno(lat, lon) and os.path.exists(SNAPSHOT):
            return pd.read_csv(SNAPSHOT, parse_dates=["fecha"]), "src_off"
        raise

def ra_fao56(lat_deg, doy):
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(np.clip(-math.tan(phi) * math.tan(delta), -1, 1))
    return max(0, (24 * 60 / math.pi) * 0.0820 * dr * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws)))

def add_et0(df, lat):
    """ET0 FAO-56 Penman-Monteith (radiación neta) y, aparte, Hargreaves para verificación cruzada."""
    x = df.copy()
    ra = np.array([ra_fao56(lat, d) for d in x.fecha.dt.dayofyear])  # MJ/m2/día
    tmax, tmin = x.tmax_c.to_numpy(float), x.tmin_c.to_numpy(float)
    tmean = (tmax + tmin) / 2
    hg = 0.0023 * (tmean + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0)) * (0.408 * ra)  # Ra en mm/día
    x["et0_hg"] = np.maximum(hg, 0)
    has_pm = all(c in x.columns for c in ("solar", "wind_ms", "rh_pct")) and x["solar"].notna().mean() > 0.5
    if has_pm:
        rs = x.solar.to_numpy(float)
        if np.nanmedian(rs) < 10:          # por seguridad: si viniera en kWh/m2/día
            rs = rs * 3.6
        u2, rh = x.wind_ms.to_numpy(float), x.rh_pct.to_numpy(float)
        es_f = lambda t: 0.6108 * np.exp(17.27 * t / (t + 237.3))
        es = (es_f(tmax) + es_f(tmin)) / 2
        ea = es * rh / 100
        delta = 4098 * es_f(tmean) / (tmean + 237.3) ** 2
        gam = 0.000665 * (101.3 * ((293 - 0.0065 * ELEV_M) / 293) ** 5.26)
        rso = (0.75 + 2e-5 * ELEV_M) * ra
        ratio = np.clip(rs / np.maximum(rso, 1e-6), 0.3, 1.0)
        rns = 0.77 * rs
        rnl = 4.903e-9 * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2) * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0))) * (1.35 * ratio - 0.35)
        et0 = (0.408 * delta * (rns - rnl) + gam * (900 / (tmean + 273)) * u2 * (es - ea)) / (delta + gam * (1 + 0.34 * u2))
        x["et0_mm_d"] = np.maximum(et0, 0)
    else:
        x["et0_mm_d"] = x["et0_hg"]
    return x

def kc_curve(n, kc_mid):
    """Forma genérica FAO-56: inicial -> desarrollo -> media -> final (25/25/30/20 %)."""
    f = np.linspace(0, 1, n)
    return kc_mid * np.interp(f, [0, 0.25, 0.5, 0.8, 1.0], [0.5, 0.5, 1.0, 1.0, 0.7])

def run_season(d, crop, taw=TAW):
    """Balance diario con un tanque de `taw` mm. Rendimiento relativo FAO-33: 1-Ya/Ym = Ky(1-ETa/ETc)."""
    c = CROPS[crop]
    etc = kc_curve(len(d), c["kc"]) * np.nan_to_num(d.et0_mm_d.to_numpy(float))
    p = np.nan_to_num(d.precip_mm.to_numpy(float))
    s, eta = 0.5 * taw, 0.0
    for pi, ei in zip(p, etc):
        s = min(taw, s + pi)
        use = min(ei, s)
        s -= use
        eta += use
    etc_sum = float(etc.sum())
    yld = 100 * max(0.0, 1 - c["ky"] * (1 - eta / etc_sum)) if etc_sum > 0 else np.nan
    return yld, float(p.sum()), etc_sum, float(eta)

def hindcast(z, taw=TAW):
    rows, first, last = [], z.index.min(), z.index.max()
    for y in range(first.year, last.year + 1):
        for crop, c in CROPS.items():
            s = pd.Timestamp(y, *c["sow"])
            e = s + pd.Timedelta(days=c["days"] - 1)
            if s < first or e > last:
                continue
            d = z.loc[s:e]
            if d.precip_mm.count() < 0.95 * c["days"] or d.et0_mm_d.count() < 0.95 * c["days"]:
                continue
            yld, p, etc, eta = run_season(d, crop, taw)
            rows.append({"campana": y, "cultivo": crop, "rend": yld, "lluvia": p, "etc": etc, "eta": eta, "heladas": int((d.tmin_c <= 0).sum())})
    return pd.DataFrame(rows)

def agro_score(prev_crop, cand):
    """Devuelve (puntaje, clave del motivo)."""
    if prev_crop == NO_PREV:
        return 1.0, "r_fallow"
    if prev_crop == cand:
        return 0.1, "r_same"
    fp, fc = CROPS[prev_crop]["fam"], CROPS[cand]["fam"]
    if fp == fc:
        return 0.4, "r_samefam"
    return ROT[(fp, fc)]

def summarize(hc, prev_crop, only_years=None):
    h = hc if only_years is None else hc[hc.campana.isin(only_years)]
    rows = []
    for crop, g in h.groupby("cultivo"):
        r = g.rend.dropna()
        if len(r) < 5:
            continue
        agro, why = agro_score(prev_crop, crop)
        rows.append({"cultivo": crop, "p50": float(r.median()), "p20": float(r.quantile(0.2)), "riesgo": float((r < LOSS_THRESHOLD).mean()),
                     "n": len(r), "agro": agro, "motivo": why, "heladas": float(g.heladas.median())})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["elegible"] = out.agro >= 0.5
    return out.sort_values(["elegible", "p20"], ascending=[False, False]).reset_index(drop=True)

def risk_range(z, prev_crop, only_years):
    """Sensibilidad del riesgo al agua útil del suelo (TAW)."""
    rng = {}
    for taw in TAW_RANGE:
        s = summarize(hindcast(z, taw), prev_crop, only_years)
        for _, r in s.iterrows():
            lo, hi = rng.get(r.cultivo, (1.0, 0.0))
            rng[r.cultivo] = (min(lo, r.riesgo), max(hi, r.riesgo))
    return rng

def plan_4y(prev_crop, summ):
    p20 = dict(zip(summ.cultivo, summ.p20))
    plan, cur, recent = [], prev_crop, [prev_crop]
    for _ in range(4):
        best, bs = None, -1.0
        for c in CROPS:
            if c in recent[-2:]:
                continue
            s = agro_score(cur, c)[0] * (p20.get(c, 0) / 100)
            if s > bs:
                best, bs = c, s
        plan.append((cur, best))
        recent.append(best)
        cur = best
    return plan

def campaign_year_of(ts):
    return ts.year if ts.month >= 9 else ts.year - 1

def analog_years(z, window_days=30):
    """Años históricos con humedad de raíz parecida a la actual en la misma ventana del calendario."""
    last = z.index.max()
    if 5 <= last.month <= 8 or z.sm_root.dropna().empty:
        return None
    cur = z.loc[last - pd.Timedelta(days=window_days - 1):last].sm_root.mean()
    if np.isnan(cur):
        return None
    rows = []
    for y in range(z.index.min().year, last.year):
        e = last - pd.DateOffset(years=last.year - y)
        w = z.loc[e - pd.Timedelta(days=window_days - 1):e].sm_root
        if w.count() >= 0.8 * window_days:
            rows.append((campaign_year_of(e), abs(float(w.mean()) - float(cur))))
    if len(rows) < 8:
        return None
    rows.sort(key=lambda t: t[1])
    return [y for y, _ in rows[:max(6, len(rows) // 2)]]

def current_signal(z):
    """Cómo va la campaña en curso (desde el 1 de octubre) frente a la historia."""
    last = z.index.max()
    if not (last.month >= 10 or last.month <= 4):
        return None
    y = last.year if last.month >= 10 else last.year - 1
    cur = z.loc[pd.Timestamp(y, 10, 1):last]
    n = len(cur)
    if n < 10:
        return None
    hist = []
    for yy in range(z.index.min().year, y):
        h = z.loc[pd.Timestamp(yy, 10, 1):pd.Timestamp(yy, 10, 1) + pd.Timedelta(days=n - 1)]
        if len(h) >= 0.9 * n:
            hist.append({"rain": h.precip_mm.sum(), "sm": h.sm_root.mean(), "frost": int((h.tmin_c <= 0).sum())})
    if len(hist) < 10:
        return None
    H = pd.DataFrame(hist)
    return {"rain": float(cur.precip_mm.sum()), "rain_norm": float(H.rain.median()),
            "sm": float(cur.sm_root.mean()) if cur.sm_root.notna().any() else np.nan, "sm_norm": float(H.sm.median()),
            "frost": int((cur.tmin_c <= 0).sum()), "frost_norm": float(H.frost.median())}

def onset_series(z):
    rows = []
    for y in range(z.index.min().year, z.index.max().year):
        w = z.loc[pd.Timestamp(y, 9, 1):pd.Timestamp(y + 1, 1, 31)].precip_mm
        if len(w) < 140 or w.count() < 0.95 * len(w):
            continue
        hit = w.rolling(ONSET_DAYS).sum()
        hit = hit[hit >= ONSET_MM]
        if len(hit):
            rows.append({"campana": y, "dia": (hit.index[0] - pd.Timestamp(y, 9, 1)).days})
    return pd.DataFrame(rows)

def compute_spi_series(z):
    """SPI estacional (sep–abr) con distribución Gamma ajustada a la serie de campañas."""
    rows = []
    for y in range(z.index.min().year, z.index.max().year):
        seg = z.loc[pd.Timestamp(y, 9, 1):pd.Timestamp(y + 1, 4, 30)].precip_mm
        if len(seg) < 200 or seg.count() < 0.90 * len(seg):
            continue
        rows.append({"campana": y, "precip": float(seg.sum())})
    df_spi = pd.DataFrame(rows)
    if len(df_spi) < 6:
        return pd.DataFrame()
    vals = df_spi["precip"].to_numpy(float)
    pos = vals[vals > 0]
    if len(pos) < 5 or np.std(pos) == 0:
        df_spi["spi"] = 0.0
        return df_spi
    q = np.mean(vals <= 0)
    alpha, _, scale = gamma_dist.fit(pos, floc=0)
    cdf_vals = np.where(vals <= 0, q, q + (1 - q) * gamma_dist.cdf(vals, alpha, loc=0, scale=scale))
    df_spi["spi"] = norm.ppf(np.clip(cdf_vals, 1e-4, 1 - 1e-4))
    return df_spi

# ==============================================================================
# 6. CARGA DE DATOS Y CÁLCULOS
# ==============================================================================
lat, lon = st.session_state["selected_lat"], st.session_state["selected_lon"]
end = date.today() - timedelta(days=7)
start = max(date(1981, 1, 1), end - timedelta(days=int(365.25 * years)))

raw, fuente_key, error = None, "src_live", None
try:
    with st.spinner(T["spinner"]):
        raw, fuente_key = load_climate(lat, lon, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        raw = add_et0(raw, lat)
except Exception as e:
    error = str(e)

ready = raw is not None and len(raw) > 365 * 8
if error:
    st.markdown('<div class="data-card">' + chip("red", "NASA POWER") + " " + T["err_power"] + "</div>", unsafe_allow_html=True)
if not in_puno(lat, lon):
    st.markdown('<div class="data-card">' + chip("yellow", "!") + " " + T["err_bounds"] + "</div>", unsafe_allow_html=True)

only, sig, rng = None, None, {}
z, hc, summ = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
if ready:
    z = raw.set_index("fecha").sort_index()
    hc = hindcast(z)
    sig = current_signal(z)
    if usar_analogos:
        only = analog_years(z)
    summ = summarize(hc, prev, only) if not hc.empty else pd.DataFrame()
    if only is not None and summ.empty:
        only = None
        summ = summarize(hc, prev, None) if not hc.empty else pd.DataFrame()
    ready = not summ.empty
    if ready:
        rng = risk_range(z, prev, only)

t1, t2, t3, t4, t5, t6 = st.tabs(T["tabs"])

# ==============================================================================
# 7. ANÁLISIS
# ==============================================================================
with t1:
    col_map, col_ctrl = st.columns([1.15, 1.05], gap="large")
    with col_map:
        def on_district():
            n = st.session_state["district"]
            if n in DISTRITOS:
                la, lo = DISTRITOS[n]
                st.session_state["selected_lat"], st.session_state["selected_lon"] = la, lo
                st.session_state["map_center"], st.session_state["map_zoom"] = [la, lo], 12

        st.selectbox(T["district_pick"], ["__custom__"] + list(DISTRITOS), key="district", on_change=on_district,
                     format_func=lambda n: T["district_custom"] if n == "__custom__" else n)

        fmap = folium.Map(location=st.session_state["map_center"], zoom_start=st.session_state["map_zoom"], tiles=None, control_scale=True, max_zoom=19)
        folium.TileLayer("OpenStreetMap", name=T["map_streets"]).add_to(fmap)
        folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                         attr="Esri", name=T["map_sat"], max_zoom=19, max_native_zoom=19).add_to(fmap)
        folium.WmsTileLayer(url="https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi", layers="MODIS_Terra_L3_NDVI_16Day",
                            name=T["map_ndvi"], fmt="image/png", transparent=True, opacity=0.6, overlay=True, show=False).add_to(fmap)
        folium.LayerControl(position="topright").add_to(fmap)
        LocateControl(auto_start=False, position="topleft").add_to(fmap)
        folium.Marker([st.session_state["selected_lat"], st.session_state["selected_lon"]],
                      icon=folium.DivIcon(html='<div style="font-size: 24px; text-shadow: 0 2px 4px rgba(0,0,0,0.5);">🌱</div>', icon_size=(24, 24), icon_anchor=(12, 24))).add_to(fmap)
        mapdata = st_folium(fmap, height=420, width=None, key="seedra_map", returned_objects=["last_clicked", "center", "zoom"])
        if mapdata:
            if mapdata.get("center") and mapdata.get("zoom"):
                st.session_state["map_center"] = [mapdata["center"]["lat"], mapdata["center"]["lng"]]
                st.session_state["map_zoom"] = mapdata["zoom"]
            pt = mapdata.get("last_clicked")
            if pt:
                la, lo = float(pt["lat"]), float(pt["lng"])
                same = (round(la, 4), round(lo, 4)) == (round(st.session_state["selected_lat"], 4), round(st.session_state["selected_lon"], 4))
                if not same:
                    if in_puno(la, lo):
                        st.session_state["selected_lat"], st.session_state["selected_lon"] = la, lo
                        st.session_state["pending_custom"] = True
                        st.rerun()
                    else:
                        st.markdown('<div class="data-card">' + chip("yellow", "!") + " " + T["err_bounds"] + "</div>", unsafe_allow_html=True)
        st.caption(T["map_hint"])

    with col_ctrl:
        if ready:
            best = summ.iloc[0]
            alt_row = summ.iloc[1] if len(summ) > 1 else None
            lvl = level_of(best.riesgo)
            bcrop = t_crop(best.cultivo)
            bad_n = int(round(best.riesgo * best.n))
            msg = T["badge_" + lvl].format(crop=bcrop)
            sub = T["farmer_sub_" + lvl].format(crop=bcrop)
            lo_r, hi_r = rng.get(best.cultivo, (best.riesgo, best.riesgo))
            rain_line = T["rain_now"].format(p=f"{sig['rain'] / sig['rain_norm'] * 100:.0f}") if (sig and sig["rain_norm"] > 0) else ""
            if only is not None:
                st.markdown('<div class="data-card">' + chip("green", "") + " " + T["analogs_active"].format(n=len(only)) + "</div>", unsafe_allow_html=True)

            if modo_agricultor:
                st.markdown("### " + T["farmer_title"])
                color = THEME["badge_" + {"green": "g", "yellow": "y", "red": "r"}[lvl] + "_bd"]
                st.markdown('<div class="badge-' + lvl + ' farmer-hero"><div class="farmer-light" style="background:' + color + ';"></div><div><div class="farmer-title">'
                            + msg + '</div><div class="farmer-sub">' + sub + "</div></div></div>", unsafe_allow_html=True)
                items = ["<b>" + T["why_label"] + ":</b> " + T[best.motivo],
                         T["bad_years"].format(n=bad_n, t=int(best.n), crop=bcrop, p=100 - LOSS_THRESHOLD)]
                if rain_line:
                    items.append(rain_line)
                if alt_row is not None:
                    al = level_of(alt_row.riesgo)
                    items.append("<b>" + T["alt_label"] + ":</b> " + t_crop(alt_row.cultivo) + " " + chip(al, T["chip_" + al]))
                st.markdown('<ul class="lines">' + "".join("<li>" + i + "</li>" for i in items) + "</ul>", unsafe_allow_html=True)
                f1, f2 = st.columns(2)
                f1.markdown(kpi(T["kpi_yield"], f"{best.p50:.0f}%", bcrop), unsafe_allow_html=True)
                f2.markdown(kpi(T["kpi_frost"], f"{best.heladas:.0f} " + T["kpi_days"], T["kpi_risk"] + f": {best.riesgo * 100:.0f}%"), unsafe_allow_html=True)
                st.markdown("**" + T["farmer_comp_title"] + "**")
                rows = []
                for _, r in summ.iterrows():
                    rl = level_of(r.riesgo)
                    rows.append([t_crop(r.cultivo), f"{r.p50:.0f}%", chip(rl, T["chip_" + rl])])
                st.markdown(html_table([T["col_crop"], T["col_yield"], T["kpi_risk"]], rows), unsafe_allow_html=True)
                share = T["farmer_share_msg"].format(lat=lat, lon=lon, crop=bcrop, msg=msg)
                st.markdown('<a href="https://wa.me/?text=' + urllib.parse.quote(share) + '" target="_blank" rel="noopener" class="wa-btn">' + T["farmer_share"] + "</a>", unsafe_allow_html=True)
                card = [T["card_title"], T["card_date"] + ": " + date.today().strftime("%d/%m/%Y"), T["card_plot"] + ": " + f"{lat:.3f}, {lon:.3f}",
                        T["card_before"] + ": " + t_crop(prev), "", T["card_sow"] + ": " + bcrop + " (" + T["chip_" + lvl] + ")", T["card_reason"] + ": " + T[best.motivo],
                        T["card_bad"] + ": " + f"{bad_n}/{int(best.n)}"]
                if alt_row is not None:
                    card.append(T["card_alt"] + ": " + t_crop(alt_row.cultivo))
                if rain_line:
                    card.append(rain_line)
                card += ["", T["card_disc"]]
                st.download_button(T["btn_card"], "\n".join(card), file_name="cartilla_seedra.txt", mime="text/plain", **STRETCH)
            else:
                st.markdown("### " + T["analysis_title"])
                st.markdown('<div class="badge-' + lvl + ' farmer-hero" style="padding:14px 18px;"><div class="farmer-title" style="font-size:1.2rem;">' + msg + "</div></div>", unsafe_allow_html=True)
                st.markdown("**" + T["why_label"] + ":** " + T[best.motivo])
                k1, k2 = st.columns(2)
                k1.markdown(kpi(T["kpi_yield"], f"{best.p50:.0f}%", T["kpi_p20"] + f": {best.p20:.0f}%"), unsafe_allow_html=True)
                k2.markdown(kpi(T["kpi_risk"], f"{best.riesgo * 100:.0f}%", T["kpi_range"].format(a=f"{lo_r * 100:.0f}", b=f"{hi_r * 100:.0f}")), unsafe_allow_html=True)
                if sig:
                    k3, k4, k5 = st.columns(3)
                    k3.markdown(kpi(T["kpi_rain"], f"{sig['rain']:.0f} mm", T["kpi_rain_s"].format(p=f"{sig['rain'] / sig['rain_norm'] * 100:.0f}")), unsafe_allow_html=True)
                    k4.markdown(kpi(T["kpi_sm"], fmt(sig["sm"] * 100, 0, "%"), T["kpi_sm_s"].format(v=fmt(sig["sm_norm"] * 100, 0, "%"))), unsafe_allow_html=True)
                    k5.markdown(kpi(T["kpi_frost2"], str(sig["frost"]), T["kpi_frost2_s"].format(n=f"{sig['frost_norm']:.0f}")), unsafe_allow_html=True)
                rows = []
                for _, r in summ.iterrows():
                    rb = chip("green", T["yes"]) if r.agro >= 0.8 else (chip("yellow", T["mid"]) if r.agro >= 0.5 else chip("red", T["no"]))
                    rl = level_of(r.riesgo)
                    a, b = rng.get(r.cultivo, (r.riesgo, r.riesgo))
                    rows.append([t_crop(r.cultivo), rb, f"{r.p50:.0f}", f"{r.p20:.0f}", chip(rl, f"{r.riesgo * 100:.0f}% ({a * 100:.0f}–{b * 100:.0f})"), f"{r.heladas:.0f}"])
                st.markdown(html_table([T["col_crop"], T["col_rot"], T["col_yield"], T["col_p20"], T["col_risk"], T["col_frost"]], rows), unsafe_allow_html=True)
                cdf = summ.copy()
                cdf["crop_tr"] = [t_crop(c) for c in cdf.cultivo]
                cdf["risk_pct"] = (cdf["riesgo"] * 100).round(1)
                cdf["p50_r"] = cdf["p50"].round(1)
                cdf["p20_r"] = cdf["p20"].round(1)
                bars = (alt.Chart(cdf).mark_bar(cornerRadiusEnd=6, height=24).encode(
                    x=alt.X("p50_r:Q", title=T["chart_t1_x"], scale=alt.Scale(domain=[0, 105])),
                    y=alt.Y("crop_tr:N", sort="-x", title=None),
                    color=alt.Color("risk_pct:Q", title=T["chart_t1_color"], scale=alt.Scale(domain=[0, 15, 35, 70], range=[THEME["accent"], THEME["accent_amber"], THEME["accent_red"], "#991B1B"])),
                    tooltip=[alt.Tooltip("crop_tr:N", title=T["tt_crop"]), alt.Tooltip("p50_r:Q", title=T["tt_p50"], format=".1f"),
                             alt.Tooltip("p20_r:Q", title=T["tt_p20"], format=".1f"), alt.Tooltip("risk_pct:Q", title=T["tt_risk"], format=".1f"),
                             alt.Tooltip("heladas:Q", title=T["tt_frost"], format=".0f")]).properties(title=T["chart_t1_title"]))
                show_chart(style_altair(bars, height=240, padding={"left": 10, "top": 10, "right": 50, "bottom": 10}))
            st.caption(T["src_cap"].format(src=T[fuente_key]) + " " + T["n_hist"].format(n=int(best.n)))
        else:
            st.markdown('<div class="data-card">' + chip("yellow", "!") + " " + T["err_nodata"] + "</div>", unsafe_allow_html=True)

# ==============================================================================
# 8. AYNOCA (ROTACIÓN)
# ==============================================================================
with t2:
    st.markdown("### " + T["aynoca_title"])
    st.markdown('<p style="color:' + THEME["text_muted"] + ';">' + T["aynoca_desc"] + "</p>", unsafe_allow_html=True)
    if ready:
        steps = plan_4y(prev, summ)
        cols_a = st.columns(5)
        fam_prev = t_fam(CROPS[prev]["fam"]) if prev != NO_PREV else "-"
        with cols_a[0]:
            st.markdown('<div class="data-card" style="border-top:4px solid ' + THEME["text_muted"] + ';"><div class="kpi-label">' + T["aynoca_current"] + '</div><div style="font-size:1.25rem; font-weight:700; margin-top:8px;">'
                        + t_crop(prev) + '</div><div class="kpi-sub">' + fam_prev + "</div></div>", unsafe_allow_html=True)
        p50 = dict(zip(summ.cultivo, summ.p50))
        for i, (from_c, to_c) in enumerate(steps):
            with cols_a[i + 1]:
                st.markdown('<div class="data-card" style="border-top:4px solid ' + THEME["accent"] + ';"><div class="kpi-label">' + T["aynoca_step"] + " +" + str(i + 1)
                            + '</div><div style="font-size:1.25rem; font-weight:700; margin-top:8px; color:' + THEME["accent"] + ' !important;">' + t_crop(to_c)
                            + '</div><div class="kpi-sub">' + t_fam(CROPS[to_c]["fam"]) + " · P50 " + f"{p50.get(to_c, 0):.0f}%"
                            + '</div><div style="font-size:0.8rem; margin-top:8px;">' + T[agro_score(from_c, to_c)[1]] + "</div></div>", unsafe_allow_html=True)
        if (summ[summ.elegible].riesgo > YELLOW_MAX).all():
            st.markdown('<div class="data-card">' + chip("red", T["chip_red"]) + " " + T["all_high"] + "</div>", unsafe_allow_html=True)
        mat_rows = []
        for p_k in [NO_PREV] + list(CROPS):
            for c_k in CROPS:
                sc, why = agro_score(p_k, c_k)
                mat_rows.append({"prev_tr": t_crop(p_k), "cand_tr": t_crop(c_k), "score": round(sc, 2), "reason": T[why]})
        mat_df = pd.DataFrame(mat_rows)
        order_prev = [t_crop(k) for k in [NO_PREV] + list(CROPS)]
        heat = (alt.Chart(mat_df).mark_rect(cornerRadius=6, stroke=THEME["bg_app"], strokeWidth=2).encode(
            x=alt.X("cand_tr:N", title=T["aynoca_matrix_x"], axis=alt.Axis(labelAngle=0), sort=[t_crop(k) for k in CROPS]),
            y=alt.Y("prev_tr:N", title=T["aynoca_matrix_y"], sort=order_prev),
            color=alt.Color("score:Q", title=T["aynoca_matrix_score"], scale=alt.Scale(domain=[0.1, 0.5, 1.0], range=[THEME["accent_red"], THEME["accent_amber"], THEME["accent"]])),
            tooltip=[alt.Tooltip("prev_tr:N", title=T["aynoca_matrix_y"]), alt.Tooltip("cand_tr:N", title=T["aynoca_matrix_x"]),
                     alt.Tooltip("score:Q", title=T["aynoca_matrix_score"], format=".2f"), alt.Tooltip("reason:N", title=T["aynoca_tt_reason"])]).properties(title=T["aynoca_matrix_title"]))
        text_mat = alt.Chart(mat_df).mark_text(fontWeight="bold", fontSize=12).encode(
            x=alt.X("cand_tr:N", sort=[t_crop(k) for k in CROPS]), y=alt.Y("prev_tr:N", sort=order_prev), text=alt.Text("score:Q", format=".2f"),
            color=alt.condition("datum.score > 0.3 && datum.score < 0.85", alt.value("#111111"), alt.value("#FFFFFF")))
        show_chart(style_altair(heat + text_mat, height=320))
        st.caption(T["aynoca_cap"])
    else:
        st.markdown('<div class="data-card">' + chip("yellow", "!") + " " + T["err_nodata"] + "</div>", unsafe_allow_html=True)

# ==============================================================================
# 9. MÁQUINA DEL TIEMPO
# ==============================================================================
with t3:
    st.markdown("### " + T["tm_title"])
    st.markdown('<p style="color:' + THEME["text_muted"] + ';">' + T["tm_subtitle"] + "</p>", unsafe_allow_html=True)
    if ready and not hc.empty:
        crop_list = list(CROPS)
        default_crop = summ.iloc[0].cultivo
        sel_tm = st.selectbox(T["tm_crop_select"], crop_list, index=crop_list.index(default_crop), format_func=t_crop, key="tm_crop_picker")
        df_tm = hc[hc.cultivo == sel_tm].sort_values("campana").copy()
        df_tm["ma5"] = df_tm["rend"].rolling(5, min_periods=2, center=True).mean()
        df_tm["eta_pct"] = (100.0 * df_tm["eta"] / np.maximum(df_tm["etc"], 1e-6)).round(1)
        df_tm["status"] = np.where(df_tm["rend"] >= LOSS_THRESHOLD, T["tm_status_ok"], T["tm_status_loss"])
        df_tm["rend_r"] = df_tm["rend"].round(1)
        df_tm["lluvia_r"] = df_tm["lluvia"].round(1)
        slope_dec, r2_val, p_val = 0.0, 0.0, 1.0
        if len(df_tm) >= 3 and df_tm["campana"].nunique() >= 3:
            res = linregress(df_tm["campana"].to_numpy(float), df_tm["rend"].to_numpy(float))
            slope_dec, r2_val, p_val = res.slope * 10.0, res.rvalue ** 2, res.pvalue
            df_tm["trend"] = res.intercept + res.slope * df_tm["campana"]
        else:
            df_tm["trend"] = df_tm["rend"].mean()
        df_on = onset_series(z)
        onset_dec = 0.0
        if len(df_on) >= 3 and df_on["campana"].nunique() >= 3:
            res_on = linregress(df_on["campana"].to_numpy(float), df_on["dia"].to_numpy(float))
            onset_dec = res_on.slope * 10.0
            df_on["trend"] = res_on.intercept + res_on.slope * df_on["campana"]
        frost_dec = 0.0
        if len(df_tm) >= 3:
            frost_dec = linregress(df_tm["campana"].to_numpy(float), df_tm["heladas"].to_numpy(float)).slope * 10.0
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(kpi(T["tm_kpi_slope"], f"{slope_dec:+.1f}%", T["tm_per_decade"]), unsafe_allow_html=True)
        m2.markdown(kpi(T["tm_kpi_onset"], f"{onset_dec:+.1f}", T["tm_days_decade"] + " " + T["tm_onset_hint"]), unsafe_allow_html=True)
        m3.markdown(kpi(T["tm_kpi_frost"], f"{frost_dec:+.1f}", T["tm_days_decade"]), unsafe_allow_html=True)
        m4.markdown(kpi(T["tm_kpi_r2"], f"{r2_val:.2f}", f"p = {p_val:.3f}"), unsafe_allow_html=True)
        st.markdown(chip("green" if p_val < 0.10 else "yellow", "p = " + f"{p_val:.2f}") + " " + (T["tm_sig_yes"] if p_val < 0.10 else T["tm_sig_no"]), unsafe_allow_html=True)

        df_tm["band_low"], df_tm["band_high"], df_tm["thresh"] = float(df_tm["rend"].quantile(0.20)), float(df_tm["rend"].quantile(0.80)), LOSS_THRESHOLD
        band = alt.Chart(df_tm).mark_area(opacity=0.14, color=THEME["accent"]).encode(x="campana:O", y="band_low:Q", y2="band_high:Q")
        rule = alt.Chart(df_tm).mark_rule(strokeDash=[6, 4], strokeWidth=1.8, color=THEME["accent_red"]).encode(y="thresh:Q")
        ma = alt.Chart(df_tm.dropna(subset=["ma5"])).mark_line(strokeWidth=2.6, color=THEME["accent_blue"]).encode(
            x=alt.X("campana:O", title=T["tm_chart1_x"]), y=alt.Y("ma5:Q", title=T["tm_chart1_y"], scale=alt.Scale(domain=[0, 108])))
        ols = alt.Chart(df_tm).mark_line(strokeDash=[4, 3], strokeWidth=2.2, color=THEME["accent_gold"]).encode(x="campana:O", y="trend:Q")
        pts = alt.Chart(df_tm).mark_circle(size=85, opacity=0.92, stroke=THEME["bg_app"], strokeWidth=1.2).encode(
            x=alt.X("campana:O", title=T["tm_chart1_x"], axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("rend_r:Q", title=T["tm_chart1_y"], scale=alt.Scale(domain=[0, 108])),
            color=alt.Color("status:N", title=None, scale=alt.Scale(domain=[T["tm_status_ok"], T["tm_status_loss"]], range=[THEME["accent"], THEME["accent_red"]])),
            tooltip=[alt.Tooltip("campana:O", title=T["tm_tt_year"]), alt.Tooltip("rend_r:Q", title=T["tm_tt_yield"], format=".1f"),
                     alt.Tooltip("lluvia_r:Q", title=T["tm_tt_rain"], format=".1f"), alt.Tooltip("eta_pct:Q", title=T["tm_tt_eta"], format=".1f"),
                     alt.Tooltip("heladas:Q", title=T["tm_tt_frost"], format=".0f")])
        master = alt.layer(band, rule, ma, ols, pts).properties(title={"text": T["tm_chart1_title"].format(crop=t_crop(sel_tm)), "subtitle": T["tm_chart1_sub"].format(slope=slope_dec, r2=r2_val)})
        show_chart(style_altair(master, height=370))

        cl, cr = st.columns(2, gap="large")
        with cl:
            if not df_on.empty:
                on_bars = alt.Chart(df_on).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, opacity=0.82, color=THEME["accent_blue"]).encode(
                    x=alt.X("campana:O", title=T["tm_chart1_x"], axis=alt.Axis(labelAngle=-45)), y=alt.Y("dia:Q", title=T["tm_chart2_y"]),
                    tooltip=[alt.Tooltip("campana:O", title=T["tm_tt_year"]), alt.Tooltip("dia:Q", title=T["tm_tt_onset"], format=".0f")])
                layers = [on_bars]
                if "trend" in df_on.columns:
                    layers.append(alt.Chart(df_on).mark_line(color=THEME["accent_gold"], strokeWidth=2.5).encode(x="campana:O", y="trend:Q"))
                show_chart(style_altair(alt.layer(*layers).properties(title=T["tm_chart2_title"]), height=280))
                st.caption(T["tm_def"].format(d=ONSET_DAYS, mm=ONSET_MM))
        with cr:
            rain_bars = alt.Chart(df_tm).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, opacity=0.65, color=THEME["accent"]).encode(
                x=alt.X("campana:O", title=T["tm_chart1_x"], axis=alt.Axis(labelAngle=-45)), y=alt.Y("lluvia_r:Q", title=T["tm_chart3_rain"]),
                tooltip=[alt.Tooltip("campana:O", title=T["tm_tt_year"]), alt.Tooltip("lluvia_r:Q", title=T["tm_chart3_rain"], format=".1f"),
                         alt.Tooltip("heladas:Q", title=T["tm_chart3_frost"], format=".0f")])
            frost_line = alt.Chart(df_tm).mark_line(point=True, strokeWidth=2.3, color=THEME["accent_amber"]).encode(
                x="campana:O", y=alt.Y("heladas:Q", title=T["tm_chart3_frost"]),
                tooltip=[alt.Tooltip("campana:O", title=T["tm_tt_year"]), alt.Tooltip("heladas:Q", title=T["tm_chart3_frost"], format=".0f")])
            show_chart(style_altair(alt.layer(rain_bars, frost_line).resolve_scale(y="independent").properties(title=T["tm_chart3_title"]), height=280))
    else:
        st.markdown('<div class="data-card">' + chip("yellow", "!") + " " + T["err_nodata"] + "</div>", unsafe_allow_html=True)

# ==============================================================================
# 10. ÍNDICES
# ==============================================================================
with t4:
    st.markdown("### " + T["idx_title"])
    st.markdown('<p style="color:' + THEME["text_muted"] + ';">' + T["idx_desc"] + "</p>", unsafe_allow_html=True)
    if ready:
        sm_s, sm_r = z["sm_surface"].dropna(), z["sm_root"].dropna()
        df_spi = compute_spi_series(z)
        spi_now = f"{df_spi.iloc[-1].spi:+.2f}" if not df_spi.empty else "N/D"
        wb_annual = float(z["precip_mm"].sum() - z["et0_mm_d"].sum()) / max(1.0, (z.index.max() - z.index.min()).days / 365.25)
        i1, i2, i3, i4 = st.columns(4)
        i1.markdown(kpi(T["idx_sm_surf"], f"{sm_s.tail(14).mean() * 100:.0f}%" if len(sm_s) else "N/D"), unsafe_allow_html=True)
        i2.markdown(kpi(T["idx_sm_root"], f"{sm_r.tail(14).mean() * 100:.0f}%" if len(sm_r) else "N/D"), unsafe_allow_html=True)
        i3.markdown(kpi(T["idx_spi_now"], spi_now), unsafe_allow_html=True)
        i4.markdown(kpi(T["idx_wb_now"], f"{wb_annual:+.0f} mm"), unsafe_allow_html=True)
        cs, cw = st.columns(2, gap="large")
        with cs:
            if not df_spi.empty:
                df_spi["spi_r"], df_spi["precip_r"] = df_spi["spi"].round(2), df_spi["precip"].round(0)
                df_spi["cat"] = np.where(df_spi["spi"] >= 0.5, T["idx_spi_wet"], np.where(df_spi["spi"] <= -0.5, T["idx_spi_dry"], T["idx_spi_norm"]))
                spi_chart = alt.Chart(df_spi).mark_bar(cornerRadius=4).encode(
                    x=alt.X("campana:O", title=T["tm_chart1_x"], axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("spi_r:Q", title=T["idx_chart_spi_y"], scale=alt.Scale(domain=[-2.8, 2.8])),
                    color=alt.Color("cat:N", title=None, scale=alt.Scale(domain=[T["idx_spi_wet"], T["idx_spi_norm"], T["idx_spi_dry"]], range=[THEME["accent"], THEME["accent_blue"], THEME["accent_red"]])),
                    tooltip=[alt.Tooltip("campana:O", title=T["tm_tt_year"]), alt.Tooltip("spi_r:Q", title="SPI", format="+.2f"),
                             alt.Tooltip("precip_r:Q", title=T["idx_precip"] + " (mm)", format=".0f")]).properties(title=T["idx_chart_spi_title"])
                show_chart(style_altair(spi_chart, height=320))
        with cw:
            monthly = z.groupby(z.index.month)[["precip_mm", "et0_mm_d"]].mean() * 30.4
            m_rows = []
            for mi in range(1, 13):
                if mi in monthly.index:
                    m_rows.append({"month": T["idx_months"][mi - 1], "var": T["idx_precip"], "mm": round(float(monthly.loc[mi, "precip_mm"]), 1)})
                    m_rows.append({"month": T["idx_months"][mi - 1], "var": T["idx_et0"], "mm": round(float(monthly.loc[mi, "et0_mm_d"]), 1)})
            wb_chart = alt.Chart(pd.DataFrame(m_rows)).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("month:N", sort=T["idx_months"], title=T["idx_chart_wb_x"], axis=alt.Axis(labelAngle=0)),
                y=alt.Y("mm:Q", title=T["idx_chart_wb_y"]), xOffset="var:N",
                color=alt.Color("var:N", title=None, scale=alt.Scale(domain=[T["idx_precip"], T["idx_et0"]], range=[THEME["accent"], THEME["accent_gold"]])),
                tooltip=[alt.Tooltip("month:N", title=T["idx_chart_wb_x"]), alt.Tooltip("var:N", title=T["idx_var"]), alt.Tooltip("mm:Q", title="mm", format=".1f")]).properties(title=T["idx_chart_wb_title"])
            show_chart(style_altair(wb_chart, height=320))
    else:
        st.markdown('<div class="data-card">' + chip("yellow", "!") + " " + T["err_nodata"] + "</div>", unsafe_allow_html=True)

# ==============================================================================
# 11. CIENCIA Y FUENTES
# ==============================================================================
with t5:
    st.markdown("### " + T["just_title"])
    j1, j2 = st.columns(2, gap="large")
    j1.markdown('<div class="data-card"><h4>' + T["just_fao56_h"] + '</h4><p style="color:' + THEME["text_muted"] + '; line-height:1.6;">' + T["just_fao56_p"] + "</p></div>", unsafe_allow_html=True)
    j2.markdown('<div class="data-card"><h4>' + T["just_fao33_h"] + '</h4><p style="color:' + THEME["text_muted"] + '; line-height:1.6;">' + T["just_fao33_p"] + "</p></div>", unsafe_allow_html=True)
    if ready:
        kc_crop = summ.iloc[0].cultivo
        n_days = CROPS[kc_crop]["days"]
        kc_df = pd.DataFrame({"pct": np.linspace(0, 100, n_days), "kc": np.round(kc_curve(n_days, CROPS[kc_crop]["kc"]), 3)})
        kc_area = alt.Chart(kc_df).mark_area(line={"color": THEME["accent"], "strokeWidth": 3}, color=THEME["accent"], opacity=0.18).encode(
            x=alt.X("pct:Q", title=T["just_kc_x"]), y=alt.Y("kc:Q", title=T["just_kc_y"], scale=alt.Scale(domain=[0, 1.35])),
            tooltip=[alt.Tooltip("pct:Q", title=T["just_kc_x"], format=".0f"), alt.Tooltip("kc:Q", title="Kc", format=".2f")]).properties(title=T["just_kc_title"].format(crop=t_crop(kc_crop)))
        show_chart(style_altair(kc_area, height=250))
        yrs = max(1.0, (z.index.max() - z.index.min()).days / 365.25)
        pm_y, hg_y = float(z.et0_mm_d.sum()) / yrs, float(z.et0_hg.sum()) / yrs
        st.markdown("#### " + T["just_check_title"])
        st.markdown('<p style="color:' + THEME["text_muted"] + ';">' + T["just_check_p"] + "</p>", unsafe_allow_html=True)
        q1, q2, q3 = st.columns(3)
        q1.markdown(kpi(T["just_check_pm"], f"{pm_y:.0f}"), unsafe_allow_html=True)
        q2.markdown(kpi(T["just_check_hg"], f"{hg_y:.0f}"), unsafe_allow_html=True)
        q3.markdown(kpi(T["just_check_diff"], f"{(hg_y - pm_y) / pm_y * 100:+.1f}%"), unsafe_allow_html=True)
    with st.expander(T["as_title"], expanded=True):
        cycles = ", ".join(t_crop(c) + " " + str(v["sow"][1]) + "/" + str(v["sow"][0]) + " (" + str(v["days"]) + " d)" for c, v in CROPS.items())
        lines = [T["as_1"], T["as_2"].format(taw=f"{TAW:.0f}", lo=f"{TAW_RANGE[0]:.0f}", hi=f"{TAW_RANGE[-1]:.0f}"), T["as_3"], T["as_4"].format(cycles=cycles), T["as_5"], T["as_6"],
                 T["as_7"].format(thr=LOSS_THRESHOLD, g=f"{GREEN_MAX * 100:.0f}", y=f"{YELLOW_MAX * 100:.0f}"), T["as_8"]]
        st.markdown("\n".join("- " + s for s in lines))
    st.markdown("#### " + T["why5_title"])
    st.markdown(T["why5_txt"])

    st.markdown("### " + T["bib_title"])
    acc = T["bib_acc"].format(d=date.today().strftime("%d/%m/%Y"))
    REFS = [
        ("bib_c1", [
            "NASA Langley Research Center (LaRC). (n.d.). <i>Prediction Of Worldwide Energy Resources (POWER) Project: Agroclimatology (AG) community, daily point API</i>. NASA Earth Science / Applied Science Program. <a href='https://power.larc.nasa.gov' target='_blank'>https://power.larc.nasa.gov</a>. " + acc,
            "Gelaro, R., McCarty, W., Suárez, M. J., et al. (2017). The Modern-Era Retrospective Analysis for Research and Applications, Version 2 (MERRA-2). <i>Journal of Climate, 30</i>(14), 5419–5454. <a href='https://doi.org/10.1175/JCLI-D-16-0758.1' target='_blank'>https://doi.org/10.1175/JCLI-D-16-0758.1</a>",
            "NASA Earthdata. (n.d.). <i>Global Imagery Browse Services (GIBS): MODIS Terra NDVI layer</i>. <a href='https://gibs.earthdata.nasa.gov' target='_blank'>https://gibs.earthdata.nasa.gov</a>. " + acc]),
        ("bib_c2", [
            "Allen, R. G., Pereira, L. S., Raes, D., &amp; Smith, M. (1998). <i>Crop evapotranspiration: Guidelines for computing crop water requirements</i> (FAO Irrigation and Drainage Paper 56). FAO, Rome. <a href='https://www.fao.org/3/x0490e/x0490e00.htm' target='_blank'>https://www.fao.org/3/x0490e/x0490e00.htm</a>",
            "Doorenbos, J., &amp; Kassam, A. H. (1979). <i>Yield response to water</i> (FAO Irrigation and Drainage Paper 33). FAO, Rome.",
            "Hargreaves, G. H., &amp; Samani, Z. A. (1985). Reference crop evapotranspiration from temperature. <i>Applied Engineering in Agriculture, 1</i>(2), 96–99."]),
        ("bib_c3", [
            "World Meteorological Organization (WMO). (2012). <i>Standardized Precipitation Index User Guide</i> (WMO-No. 1090; M. Svoboda, M. Hayes &amp; D. Wood). Geneva: WMO.",
            "McKee, T. B., Doesken, N. J., &amp; Kleist, J. (1993). The relationship of drought frequency and duration to time scales. <i>Proceedings of the 8th Conference on Applied Climatology</i> (pp. 179–184). American Meteorological Society."]),
        ("bib_c4", [
            "Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI). (n.d.). <i>Información agrometeorológica y calendario de siembra, región Puno</i>. <a href='https://www.senamhi.gob.pe' target='_blank'>https://www.senamhi.gob.pe</a>. " + acc]),
    ]
    for ck, items in REFS:
        st.markdown("#### " + T[ck])
        st.markdown('<ol class="refs">' + "".join("<li>" + it + "</li>" for it in items) + "</ol>", unsafe_allow_html=True)
    st.markdown('<div class="data-card">' + T["bib_insp"] + "</div>", unsafe_allow_html=True)

# ==============================================================================
# 12. NOSOTROS (misión, visión, principios, hoja de ruta)
# ==============================================================================
with t6:
    st.markdown('<div class="us-hero"><h2>' + T["us_hero"] + "</h2><p>" + T["us_hero_sub"] + "</p></div>", unsafe_allow_html=True)
    st.markdown('<div class="grid-2"><div class="data-card panel-accent"><div class="kpi-label">' + T["us_mission_t"] + '</div><p style="font-size:1.05rem; line-height:1.65; margin:8px 0 0 0;">' + T["us_mission"]
                + '</p></div><div class="data-card panel-gold"><div class="kpi-label">' + T["us_vision_t"] + '</div><p style="font-size:1.05rem; line-height:1.65; margin:8px 0 0 0;">' + T["us_vision"] + "</p></div></div>", unsafe_allow_html=True)
    st.markdown("#### " + T["us_values_t"])
    st.markdown("".join('<span class="chip chip-plain" style="margin:3px;">' + v + "</span>" for v in T["us_values"]), unsafe_allow_html=True)
    st.markdown("#### " + T["us_how_t"])
    hw = ""
    for i, (h, d) in enumerate(T["us_how"]):
        hw += '<div class="data-card"><div class="step-num">' + str(i + 1) + '</div><div style="font-weight:700;">' + h + '</div><div class="kpi-sub" style="font-size:0.9rem;">' + d + "</div></div>"
    st.markdown('<div class="grid-3">' + hw + "</div>", unsafe_allow_html=True)
    st.markdown("#### " + T["us_road_t"])
    road = "".join('<div class="road-item">' + chip("yellow", str(i + 1)) + "<div>" + r + "</div></div>" for i, r in enumerate(T["us_road"]))
    st.markdown('<div class="data-card">' + road + "</div>", unsafe_allow_html=True)
    st.markdown("#### " + T["us_team_t"])
    team_cols = st.columns(len(T["us_team"]), gap="medium")
    for col, m in zip(team_cols, T["us_team"]):
        with col:
            st.markdown('<div class="team-card"><div class="avatar-circle" style="background:' + m["color"] + ';">' + m["initials"] + '</div><div style="font-weight:700;">' + m["name"]
                        + '</div><div style="color:' + THEME["accent"] + '; font-weight:600; font-size:0.9rem; margin:2px 0 6px 0;">' + m["role"] + '</div><div class="kpi-sub">' + m["bio"] + "</div></div>", unsafe_allow_html=True)
    st.markdown('<div class="data-card" style="margin-top:14px;">' + chip("yellow", "") + " " + T["us_honest"] + "</div>", unsafe_allow_html=True)

st.markdown('<div class="custom-footer"><strong>SEEDRA</strong> · ' + T["footer"] + "</div>", unsafe_allow_html=True)
