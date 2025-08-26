import os
import io
import re

import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from utils_ocr import setup_tesseract, pick_lang

# =========================
# Config app & OCR portable
# =========================
st.set_page_config(page_title="🏗️ Assistant Cloison – Version Finale", layout="wide")

setup_tesseract()                  # auto-détection (local + cloud)
LANG_OCR = pick_lang("fra", "eng") # utilise FRA si dispo, sinon ENG

st.title("🏗️ Assistant Cloison - Version Finale")

# =========================
# Listes & petits helpers
# =========================
piece_principale = ["séjour", "salon", "chambre", "salle à manger"]
piece_service = ["cuisine", "entrée", "bureau", "sanitaire", "wc", "toilette", "salle de bain", "sdb", "salle d'eau", "sde", "buanderie"]
circulation = ["circulation", "dégagement"]
# liste des pièces à implémenter (on pourrait traduire en anglais aussi)

def classer_piece(nom: str) -> str:
    nom = str(nom).lower()
    if nom in piece_principale:
        return "pièce principale"
    elif nom in piece_service:
        return "pièce de service"
    elif nom in circulation:
        return "circulation"
    return "autre"

def convertir_feu_en_min(exigence: str | None):
    if not exigence:
        return None
    key = str(exigence).strip().lower()
    mapping = {"1/4h": 15, "1/2h": 30, "3/4h": 45, "1h": 60, "2h": 120,
               "ei15": 15, "ei30": 30, "ei45": 45, "ei60": 60, "ei120": 120,
               "rei15": 15, "rei30": 30, "rei45": 45, "rei60": 60, "rei120": 120}
    return mapping.get(key, None)

def chercher_exigence_acoustique(df, type1, type2):
    mask = (df["Type de pièce"].str.lower() == str(type1).lower()) & \
           (df["pièce collée"].str.lower() == str(type2).lower())
    ligne = df[mask]
    if not ligne.empty:
        return ligne.iloc[0]["DnT,A [dB]"]
    return None

# 👉 Règles “contexte de séparation” (entre logements / circulation / interne)
def exigence_acoustique_contexte(type1: str, type2: str, contexte: str, df_acou: pd.DataFrame):
    """Retourne l’exigence DnT,A en dB selon le contexte réglementaire."""
    if contexte == "Entre logements":
        return 53.0  # arrêté logements : isolement minimal entre logements
    if contexte == "Logement ↔ circulation commune":
        return 30.0  # seuil minimal logements-circulations
    # sinon, cas “interne au logement” : on garde le tableau df_acou (logique existante)
    return chercher_exigence_acoustique(df_acou, type1, type2)

def exigence_feu_contexte(contexte: str, famille: str, mitoyennete: bool):
    """
    Retourne ((libellé_EI, minutes), note) ou (None, None) si pas d’exigence applicable.
    Règles fournies par toi :
      - Cat. 1 & 2 : EI 15 (sauf cat.2 si mitoyenneté — cas particulier à confirmer)
      - Cat. 3A/3B : EI 30
      - Cat. 4     : EI 60
      - Cat. 5     : EI 120 (+ protection structurelle)
    """
    if contexte != "Entre logements":
        return (None, None), None  # pas d’exigence feu pour interne/circulations
    fam = str(famille).upper()
    note = None
    if fam in ["1", "2"]:
        if fam == "2" and mitoyennete:
            note = "Cas particulier: catégorie 2 mitoyenne — vérifier l’exigence locale."
        return ("EI 15", 15), note
    if fam in ["3A", "3B"]:
        return ("EI 30", 30), note
    if fam == "4":
        return ("EI 60", 60), note
    if fam == "5":
        return ("EI 120", 120), note
    # par défaut (famille inconnue)
    return (None, None), note

# =========================
# Chargement des fichiers
# =========================
@st.cache_data
def charger_fichiers():
    df_acou = pd.read_excel("exigence_acoustique_logement.xlsx")
    df_acou.columns = df_acou.columns.str.strip()

    df_feu = pd.read_excel("exigence_coupe_feu_logement.xlsx")
    df_feu.columns = df_feu.columns.str.strip()

    df_cloisons = pd.read_excel("cloisons_siniat_nettoye.xlsx")
    df_cloisons.columns = df_cloisons.columns.str.strip()

    # Conversion des colonnes utiles en numérique
    df_cloisons["Résistance feu (min)"] = pd.to_numeric(df_cloisons["Résistance feu (min)"], errors="coerce")
    df_cloisons["Rw+C avec isolant (dB)"] = pd.to_numeric(df_cloisons["Rw+C avec isolant (dB)"], errors="coerce")

    return df_acou, df_feu, df_cloisons


try:
    df_acou, df_feu, df_cloisons = charger_fichiers()
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()


# =========================
# Paramètres de bâtiment
# =========================
type_batiment = st.selectbox(
    "Quel est le type de bâtiment ?",
    ["Logement", "ERP [non disponible]", "École [non disponible]", "Hôpital [non disponible]", "Bureau [non disponible]", "Autre [non disponible]"]
)

if type_batiment == "Logement":
    logement_type = st.radio("Type de logement :", ["Individuel", "Collectif"])
    mitoyennete = st.checkbox("Le logement est-il collé à un autre bâtiment (mitoyen ou ERP) ?")
    famille = st.selectbox("Famille réglementaire :", ["1", "2"] if logement_type == "Individuel" else ["2", "3A", "3B", "4"])
else:
    famille = st.text_input("Famille réglementaire applicable (si connue)")
    mitoyennete = False  # 👉 évite les NameError si on n’est pas en 'Logement'

# =========================
# Uploader plan & OCR
# =========================
uploaded_file = st.file_uploader("📥 Uploader un plan (PDF ou image)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file:
    st.info("🔍 Traitement OCR en cours…")

    images = []
    try:
        if uploaded_file.type == "application/pdf":
            pdf_bytes = uploaded_file.read()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                for page in doc:
                    pix = page.get_pixmap(dpi=300)
                    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                    images.append(img)
            finally:
                doc.close()
        else:
            images = [Image.open(uploaded_file).convert("RGB")]
    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier : {e}")
        st.stop()

    pieces = []
    keywords = ["Bureau", "Salle", "Local", "Chambre", "Cuisine", "Entrée", "Sanitaires", "WC", "Open space", "Local technique", "Salon"]

    for idx, img in enumerate(images):
        try:
            text = pytesseract.image_to_string(img, lang=LANG_OCR)
        except Exception as e:
            st.error(f"OCR échoué (page {idx+1}) : {e}")
            continue

        lines = text.split("\n")
        for i, line in enumerate(lines):
            if any(k.lower() in line.lower() for k in keywords):
                context = " ".join(lines[max(0, i-2):i+5])
                s = re.search(r"(\d{1,3}[,.]?\d*)\s*(m²|m2|m,|m 2)", context, re.IGNORECASE)
                h = re.search(r"hsp\s*[:= -]?\s*(\d{1,2}[,.]?\d*)\s*m", context, re.IGNORECASE)
                surface = s.group(1).replace(",", ".") if s else ""
                hsp = h.group(1).replace(",", ".") if h else ""
                pieces.append({"page": idx+1, "ligne": line.strip(), "surface": surface, "hsp": hsp})

    # 👉 Aperçu des pièces détectées automatiquement (utile pour contrôle visuel)
    if pieces:
        st.subheader("🧭 Pièces détectées par l’OCR (aperçu)")
        st.dataframe(pd.DataFrame(pieces), use_container_width=True)
    else:
        st.info("Aucune pièce détectée automatiquement. Tu peux en ajouter manuellement ci-dessous.")

    # =========================
    # Ajouts manuels utilisateur
    # =========================
    if "pieces_man" not in st.session_state:
        st.session_state.pieces_man = []

    colm1, colm2, colm3, colm4 = st.columns([2,1,1,1])
    with colm1:
        nom_manuel = st.text_input("Nom pièce (ajout manuel)")
    with colm2:
        surf_manuel = st.text_input("Surface (m²)")
    with colm3:
        hsp_manuel = st.text_input("HSP (m)")
    with colm4:
        if st.button("➕ Ajouter pièce"):
            st.session_state.pieces_man.append({"page": 0, "ligne": nom_manuel, "surface": surf_manuel, "hsp": hsp_manuel})

    # =========================
    # Table des pièces
    # =========================
    table_out = []
    all_pieces = pieces + st.session_state.pieces_man
    for p in all_pieces:
        table_out.append({
            "Nom": p["ligne"],
            "Surface_m2": p["surface"],
            "HSP_m": p["hsp"],
            "Page": p["page"]
        })

    # 👉 Affichage de la table fusionnée (OCR + manuel)
    st.subheader("📋 Pièces (OCR + ajouts)")
    if table_out:
        st.dataframe(pd.DataFrame(table_out), use_container_width=True)
    else:
        st.info("Ajoute au moins une pièce pour créer des séparations.")

    noms = [p["Nom"] for p in table_out] if table_out else []
    st.header("✳️ Séparations entre pièces")

    if "separations" not in st.session_state:
        st.session_state.separations = []

    # 👉 Ajout du “Contexte de séparation” (3 catégories demandées)
    CONTEXT_OPTIONS = ["Interne au logement", "Entre logements", "Logement ↔ circulation commune"]

    col1, col2 = st.columns(2)
    with col1:
        p1 = st.selectbox("Pièce 1", noms, key="s1") if noms else st.text_input("Pièce 1 (saisir le nom)")
    with col2:
        p2 = st.selectbox("Pièce 2", noms, key="s2") if noms else st.text_input("Pièce 2 (saisir le nom)")

    col3, col4 = st.columns(2)
    with col3:
        long_cloison = st.text_input("Longueur cloison (m)", key="s3")
    with col4:
        contexte = st.selectbox("Contexte de séparation", CONTEXT_OPTIONS, index=0)

    if st.button("➕ Ajouter séparation"):
        if p1 and p2 and long_cloison:
            st.session_state.separations.append({
                "Pièce 1": p1,
                "Pièce 2": p2,
                "Longueur cloison (m)": long_cloison,
                "Contexte": contexte
            })
        else:
            st.warning("Renseigne Pièce 1, Pièce 2, Longueur cloison et Contexte.")

    if st.session_state.separations:
        df_sep = pd.DataFrame(st.session_state.separations)
        # 👉 Éditeur avec Selectbox sur “Contexte” pour corriger après coup
        st.data_editor(
            df_sep,
            use_container_width=True,
            num_rows="dynamic",
            key="table_sep",
            column_config={
                "Contexte": st.column_config.SelectboxColumn(
                    "Contexte",
                    options=CONTEXT_OPTIONS,
                    required=True,
                    help="Choisir le type de cloison"
                )
            }
        )

    # =========================
    # Analyse
    # =========================
    if st.button("▶️ Lancer l’analyse") and famille and st.session_state.separations:
        # Table de détection
        df_detect = []
        for sep in st.session_state.separations:
            p1_row = next((p for p in table_out if p["Nom"] == sep["Pièce 1"]), {})
            p2_row = next((p for p in table_out if p["Nom"] == sep["Pièce 2"]), {})
            df_detect.append({
                "Pièce 1": sep["Pièce 1"],
                "Surface 1 (m²)": p1_row.get("Surface_m2", ""),
                "HSP 1 (m)": p1_row.get("HSP_m", ""),
                "Pièce 2": sep["Pièce 2"],
                "Surface 2 (m²)": p2_row.get("Surface_m2", ""),
                "HSP 2 (m)": p2_row.get("HSP_m", ""),
                "Longueur cloison (m)": sep["Longueur cloison (m)"],
                "Contexte": sep.get("Contexte", "Interne au logement")
            })
        df_detect = pd.DataFrame(df_detect)

        # Typage des pièces & exigences acoustiques
        df_detect["Type Pièce 1"] = df_detect["Pièce 1"].apply(classer_piece)
        df_detect["Type Pièce 2"] = df_detect["Pièce 2"].apply(classer_piece)

        # 👉 Exigences acoustiques selon le contexte (53 / 30 / tableau)
        df_detect["Exigence DnT,A (dB)"] = df_detect.apply(
            lambda row: exigence_acoustique_contexte(row["Type Pièce 1"], row["Type Pièce 2"], row["Contexte"], df_acou),
            axis=1
        )

        # 👉 Exigences feu : seulement “Entre logements”
        feu_info = df_detect.apply(
            lambda row: exigence_feu_contexte(row["Contexte"], famille, mitoyennete),
            axis=1
        )
        # feu_info = [ ((label, minutes), note), ... ]
        df_detect["Exigence Feu"] = feu_info.apply(lambda x: x[0][0] if x and x[0] else None)
        df_detect["Exigence Feu (min)"] = feu_info.apply(lambda x: x[0][1] if x and x[0] else None)
        df_detect["Note"] = feu_info.apply(lambda x: x[1] if x else None)

        # Filtrage cloisons compatibles
        def filtrer(row):
            # 👉 on n’impose un critère que s’il est défini (évite de filtrer à tort)
            mask = pd.Series(True, index=df_cloisons.index)
            if pd.notna(row["Exigence DnT,A (dB)"]):
                try:
                    mask &= (df_cloisons["Rw+C avec isolant (dB)"] >= float(row["Exigence DnT,A (dB)"]))
                except Exception:
                    pass
            if pd.notna(row["Exigence Feu (min)"]):
                try:
                    mask &= (df_cloisons["Résistance feu (min)"] >= float(row["Exigence Feu (min)"]))
                except Exception:
                    pass
            compatibles = df_cloisons[mask]
            return compatibles["Type et épaisseur"].dropna().unique().tolist()

        df_detect["Cloisons compatibles"] = df_detect.apply(filtrer, axis=1)

        # Estimation simple de plaques (BA18 supposé, 0.9 x 2.6 m -> ~2.34 m²)
        def calculer_nombre_plaques(row):
            try:
                long_m = float(str(row["Longueur cloison (m)"]).replace(",", "."))
                hsp_m  = float(str(row["HSP 1 (m)"] or row["HSP 2 (m)"]).replace(",", "."))
                surface = long_m * hsp_m
                return round(surface / (0.9 * 2.6), 1)
            except Exception:
                return None

        df_detect["Plaques BA18 à commander"] = df_detect.apply(calculer_nombre_plaques, axis=1)

        # Résultats
        st.subheader("📊 Résultat de l'analyse")
        st.dataframe(df_detect, use_container_width=True)

        # Export
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_detect.to_excel(writer, index=False, sheet_name="Résultats")
        st.download_button(
            label="📥 Télécharger le fichier Excel final",
            data=output.getvalue(),
            file_name="résultat_meilleure_cloison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("Charge un plan (PDF/PNG/JPG) pour lancer l’OCR et l’analyse.")
