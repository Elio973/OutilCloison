
import streamlit as st
import pandas as pd
import fitz
import pytesseract
from PIL import Image
import io
import re

pytesseract.pytesseract.tesseract_cmd = r"C:\Users\slaym\Desktop\PFE EliotTIREL\Tesseract\tesseract.exe"

piece_principale = ["séjour", "salon", "chambre"]
piece_service = ["cuisine", "entrée", "bureau", "sanitaire", "wc", "toilette", "salle de bain", "sdb", "salle d'eau", "sde", "buanderie"]
circulation = ["circulation", "dégagement"]

def classer_piece(nom):
    nom = str(nom).lower()
    if nom in piece_principale:
        return "pièce principale"
    elif nom in piece_service:
        return "pièce de service"
    elif nom in circulation:
        return "circulation"
    return "autre"

def convertir_feu_en_min(exigence):
    mapping = {"1/4h": 15, "1/2h": 30, "3/4h": 45, "1h": 60, "2h": 120}
    return mapping.get(str(exigence).strip().lower(), None)

def chercher_exigence_acoustique(df, type1, type2):
    ligne = df[(df["Type de pièce"].str.lower() == type1.lower()) &
               (df["pièce collée"].str.lower() == type2.lower())]
    if not ligne.empty:
        return ligne.iloc[0]["DnT,A [dB]"]
    return None

@st.cache_data
def charger_fichiers():
    df_acou = pd.read_excel("exigence_acoustique_logement.xlsx")
    df_acou.columns = df_acou.columns.str.strip()
    df_feu = pd.read_excel("exigence_coupe_feu_logement.xlsx")
    df_feu.columns = df_feu.columns.str.strip()
    df_cloisons = pd.read_excel("cloisons_siniat_nettoye.xlsx")
    df_cloisons["Résistance feu (min)"] = pd.to_numeric(df_cloisons["Résistance feu (min)"], errors="coerce")
    df_cloisons["Rw+C avec isolant (dB)"] = pd.to_numeric(df_cloisons["Rw+C avec isolant (dB)"], errors="coerce")
    return df_acou, df_feu, df_cloisons

df_acou, df_feu, df_cloisons = charger_fichiers()

st.title("🏗️ Assistant Cloison - Version Finale")

type_batiment = st.selectbox("Quel est le type de bâtiment ?", [
    "Logement", "ERP [non disponible]", "École [non disponible]", "Hôpital [non disponible]", "Bureau [non disponible]", "Autre [non disponible]"
])

if type_batiment == "Logement":
    logement_type = st.radio("Type de logement :", ["Individuel", "Collectif"])
    mitoyennete = st.checkbox("Le logement est-il collé à un autre bâtiment (mitoyen ou ERP) ?")
    famille = st.selectbox("Famille réglementaire :", ["1", "2"] if logement_type == "Individuel" else ["2", "3A", "3B", "4"])
elif type_batiment == "ERP (Établissement Recevant du Public)":
    erp_classe = st.selectbox("Classe de l'ERP :", ["1ère", "2e", "3e", "4e", "5e"])
    erp_type = st.selectbox("Type d'ERP :", ["Salle de spectacle", "Hôtel", "Restaurant", "Commerce", "Autre"])
    famille = st.text_input("Famille réglementaire applicable (si connue)")
elif type_batiment == "École":
    niveau = st.selectbox("Niveau de l'école :", ["Maternelle", "Primaire", "Collège / Lycée"])
    famille = st.text_input("Famille réglementaire applicable (si connue)")
else:
    famille = st.text_input("Famille réglementaire applicable (si connue)")

uploaded_file = st.file_uploader("📥 Uploader un plan (PDF ou image)", type=["pdf", "png", "jpg", "jpeg"])

if uploaded_file:
    st.info("🔍 Traitement OCR en cours...")
    if uploaded_file.type == "application/pdf":
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = [Image.open(io.BytesIO(page.get_pixmap(dpi=300).tobytes())) for page in doc]
    else:
        images = [Image.open(uploaded_file)]

    ocr_texts, pieces = [], []
    keywords = ["Bureau", "Salle", "Local", "Chambre", "Cuisine", "Entrée", "Sanitaires", "WC", "Open space", "Local technique", "Salon"]
    for idx, img in enumerate(images):
        text = pytesseract.image_to_string(img, lang="fra")
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if any(k.lower() in line.lower() for k in keywords):
                context = " ".join(lines[max(0, i-2):i+5])
                s = re.search(r"(\d{1,3}[,.]?\d*)\s*(m²|m2|m,|m 2)", context, re.IGNORECASE)
                h = re.search(r"hsp\s*[:= -]?\s*(\d{1,2}[,.]?\d*)\s*m", context, re.IGNORECASE)
                surface = s.group(1).replace(",", ".") if s else ""
                hsp = h.group(1).replace(",", ".") if h else ""
                pieces.append({"page": idx+1, "ligne": line, "surface": surface, "hsp": hsp})

    if "pieces_man" not in st.session_state:
        st.session_state.pieces_man = []

    nom_manuel = st.text_input("Nom pièce manuelle")
    surf_manuel = st.text_input("Surface pièce")
    hsp_manuel = st.text_input("HSP")
    if st.button("Ajouter pièce manuelle"):
        st.session_state.pieces_man.append({"page": 0, "ligne": nom_manuel, "surface": surf_manuel, "hsp": hsp_manuel})

    table_out = []
    all_pieces = pieces + st.session_state.pieces_man
    for i, p in enumerate(all_pieces):
        table_out.append({
            "Nom": p["ligne"],
            "Surface_m2": p["surface"],
            "HSP_m": p["hsp"],
            "Page": p["page"]
        })

    noms = [p["Nom"] for p in table_out]
    st.header("✳️ Séparations entre pièces")
    if "separations" not in st.session_state:
        st.session_state.separations = []
    col1, col2 = st.columns(2)
    with col1:
        p1 = st.selectbox("Pièce 1", noms, key="s1")
    with col2:
        p2 = st.selectbox("Pièce 2", noms, key="s2")
    long = st.text_input("Longueur cloison (m)", key="s3")
    if st.button("➕ Ajouter séparation"):
        st.session_state.separations.append({"Pièce 1": p1, "Pièce 2": p2, "Longueur cloison (m)": long})

    if st.session_state.separations:
        df_sep = pd.DataFrame(st.session_state.separations)
        st.data_editor(df_sep, use_container_width=True, num_rows="dynamic", key="table_sep")

    if st.button("▶️ Lancer l’analyse") and famille and st.session_state.separations:
        df_detect = []
        for sep in st.session_state.separations:
            p1 = next((p for p in table_out if p["Nom"] == sep["Pièce 1"]), {})
            p2 = next((p for p in table_out if p["Nom"] == sep["Pièce 2"]), {})
            df_detect.append({
                "Pièce 1": sep["Pièce 1"],
                "Surface 1 (m²)": p1.get("Surface_m2", ""),
                "HSP 1 (m)": p1.get("HSP_m", ""),
                "Pièce 2": sep["Pièce 2"],
                "Surface 2 (m²)": p2.get("Surface_m2", ""),
                "HSP 2 (m)": p2.get("HSP_m", ""),
                "Longueur cloison (m)": sep["Longueur cloison (m)"]
            })
        df_detect = pd.DataFrame(df_detect)
        df_detect["Type Pièce 1"] = df_detect["Pièce 1"].apply(classer_piece)
        df_detect["Type Pièce 2"] = df_detect["Pièce 2"].apply(classer_piece)
        df_detect["Exigence DnT,A (dB)"] = df_detect.apply(
            lambda row: chercher_exigence_acoustique(df_acou, row["Type Pièce 1"], row["Type Pièce 2"]), axis=1)
        exig_feu = df_feu[df_feu["Famille"].astype(str) == famille]["Exigence coupe-feu"].values[0]
        feu_min = convertir_feu_en_min(exig_feu)
        df_detect["Exigence Feu"] = exig_feu
        df_detect["Exigence Feu (min)"] = feu_min

        def filtrer(row):
            if pd.isna(row["Exigence DnT,A (dB)"]) or pd.isna(row["Exigence Feu (min)"]):
                return []
            compatibles = df_cloisons[
                (df_cloisons["Résistance feu (min)"] >= row["Exigence Feu (min)"]) &
                (df_cloisons["Rw+C avec isolant (dB)"] >= row["Exigence DnT,A (dB)"])
            ]
            return compatibles["Type et épaisseur"].dropna().unique().tolist()

        df_detect["Cloisons compatibles"] = df_detect.apply(filtrer, axis=1)

        def calculer_nombre_plaques(row):
            try:
                long = float(row["Longueur cloison (m)"])
                hsp = float(row["HSP 1 (m)"])
                surface = long * hsp
                return round(surface / (0.9 * 2.6), 1)
            except:
                return None

        df_detect["Plaques BA18 à commander"] = df_detect.apply(calculer_nombre_plaques, axis=1)

        st.subheader("📊 Résultat de l'analyse")
        st.dataframe(df_detect)

        from io import BytesIO
        output = BytesIO()
        df_detect.to_excel(output, index=False)
        st.download_button(
            label="📥 Télécharger le fichier Excel final",
            data=output.getvalue(),
            file_name="résultat_meilleure_cloison.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
