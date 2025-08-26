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
piece_principale = ["séjour", "salon", "chambre"]
piece_service = ["cuisine", "entrée", "bureau", "sanitaire", "wc", "toilette", "salle de bain", "sdb", "salle d'eau", "sde", "buanderie"]
circulation = ["circulation", "dégagement"]

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

# =========================
# Chargement des fichiers
# =========================
@st.cache_data
def charger_fichiers():
    """
    Charge les 3 Excel depuis ./data/ si dispo, sinon depuis la racine.
    Normalise les colonnes numériques.
    """
    # Cherche un dossier 'data' proche du script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    root_dir = base_dir

    def _read_xlsx(fname: str):
        candidates = [
            os.path.join(data_dir, fname),
            os.path.join(root_dir, fname),
        ]
        for path in candidates:
            if os.path.exists(path):
                return pd.read_excel(path)
        raise FileNotFoundError(f"Fichier introuvable : {fname} (cherché dans ./data et à la racine)")

    df_acou = _read_xlsx("exigence_acoustique_logement.xlsx")
    df_acou.columns = df_acou.columns.str.strip()

    df_feu = _read_xlsx("exigence_coupe_feu_logement.xlsx")
    df_feu.columns = df_feu.columns.str.strip()

    df_cloisons = _read_xlsx("cloisons_siniat_nettoye.xlsx")
    df_cloisons.columns = df_cloisons.columns.str.strip()
    # Colonnes numériques robustes
    if "Résistance feu (min)".lower() in [c.lower() for c in df_cloisons.columns]:
        df_cloisons["Résistance feu (min)"] = pd.to_numeric(df_cloisons.filter(regex="(?i)^Résistance feu \(min\)$"), errors="coerce").squeeze()
    else:
        # fallback si le nom diffère
        if "Résistance feu (min)" in df_cloisons.columns:
            df_cloisons["Résistance feu (min)"] = pd.to_numeric(df_cloisons["Résistance feu (min)"], errors="coerce")

    if "Rw+C avec isolant (dB)" in df_cloisons.columns:
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

    noms = [p["Nom"] for p in table_out] if table_out else []
    st.header("✳️ Séparations entre pièces")

    if "separations" not in st.session_state:
        st.session_state.separations = []

    col1, col2 = st.columns(2)
    with col1:
        p1 = st.selectbox("Pièce 1", noms, key="s1") if noms else st.text_input("Pièce 1 (saisir le nom)")
    with col2:
        p2 = st.selectbox("Pièce 2", noms, key="s2") if noms else st.text_input("Pièce 2 (saisir le nom)")

    long_cloison = st.text_input("Longueur cloison (m)", key="s3")

    if st.button("➕ Ajouter séparation"):
        if p1 and p2 and long_cloison:
            st.session_state.separations.append({"Pièce 1": p1, "Pièce 2": p2, "Longueur cloison (m)": long_cloison})
        else:
            st.warning("Renseigne Pièce 1, Pièce 2 et Longueur cloison.")

    if st.session_state.separations:
        df_sep = pd.DataFrame(st.session_state.separations)
        st.data_editor(df_sep, use_container_width=True, num_rows="dynamic", key="table_sep")

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
                "Longueur cloison (m)": sep["Longueur cloison (m)"]
            })
        df_detect = pd.DataFrame(df_detect)

        # Typage des pièces & exigences acoustiques
        df_detect["Type Pièce 1"] = df_detect["Pièce 1"].apply(classer_piece)
        df_detect["Type Pièce 2"] = df_detect["Pièce 2"].apply(classer_piece)
        df_detect["Exigence DnT,A (dB)"] = df_detect.apply(
            lambda row: chercher_exigence_acoustique(df_acou, row["Type Pièce 1"], row["Type Pièce 2"]), axis=1
        )

        # Exigence feu depuis la famille
        feu_rows = df_feu[df_feu["Famille"].astype(str) == str(famille)]
        if feu_rows.empty:
            st.error(f"Aucune exigence feu trouvée pour la famille '{famille}'. Vérifie ton fichier 'exigence_coupe_feu_logement.xlsx'.")
            st.stop()
        exig_feu = feu_rows.iloc[0]["Exigence coupe-feu"]
        feu_min = convertir_feu_en_min(exig_feu)

        df_detect["Exigence Feu"] = exig_feu
        df_detect["Exigence Feu (min)"] = feu_min

        # Filtrage cloisons compatibles
        def filtrer(row):
            if pd.isna(row["Exigence DnT,A (dB)"]) or pd.isna(row["Exigence Feu (min)"]):
                return []
            compatibles = df_cloisons[
                (df_cloisons["Résistance feu (min)"] >= row["Exigence Feu (min)"]) &
                (df_cloisons["Rw+C avec isolant (dB)"] >= row["Exigence DnT,A (dB)"])
            ]
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
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df_detect.to_excel(writer, index=False, sheet_name="Résultats")
        st.download_button(
            label="📥 Télécharger le fichier Excel final",
            data=output.getvalue(),
            file_name="résultat_meilleure_cloison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("Charge un plan (PDF/PNG/JPG) pour lancer l’OCR et l’analyse.")

