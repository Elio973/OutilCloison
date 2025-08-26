#installation de tesseract pour le déploiement sur streamlit
import os, shutil, platform, warnings
import pytesseract

def setup_tesseract():
    """
    Configure le chemin vers l'exécutable Tesseract de manière portable.
    - Cloud (Streamlit): on s'appuie sur le PATH (packages.txt installe tesseract-ocr).
    - Local Windows/Linux/macOS: on trouve automatiquement si possible.
    - Option: respecter la variable d'env TESSERACT_CMD si définie.
    """
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd and os.path.exists(env_cmd):
        pytesseract.pytesseract.tesseract_cmd = env_cmd
        return env_cmd
      
#fonction pour trouver les chemins classique
    which = shutil.which("tesseract")
    if which:
        pytesseract.pytesseract.tesseract_cmd = which
        return which
      
#test les chemins 
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                pytesseract.pytesseract.tesseract_cmd = c
                return c

# si rien trouvé
    raise RuntimeError(
        "Tesseract introuvable.\n"
        "- En Cloud: ajoute 'tesseract-ocr' (et 'tesseract-ocr-fra') dans packages.txt.\n"
        "- En local: installe Tesseract et/ou ajoute-le au PATH."
    )

def pick_lang(preferred="fra", fallback="eng"):
    """
    Vérifie que le pack de langue souhaité est dispo, sinon bascule en fallback.
    """
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        # Certaines versions peuvent remonter une erreur ; on tente quand même la langue préférée
        langs = set()

    if preferred in langs or not langs:
        return preferred
    warnings.warn(
        f"Pack de langue '{preferred}' non trouvé. Utilisation de '{fallback}'. "
        "En Cloud, ajoute 'tesseract-ocr-fra' dans packages.txt."
    )
    return fallback
