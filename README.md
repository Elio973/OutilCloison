# Outil cloison

## Présentation

**Outil cloison** est un assistant d’aide de sélection de cloisons intérieures pour les logements.  
L’application permet, à partir de fichiers Excel (réglementations acoutisque/incendie + base produits) et d’un plan architecte,  
de recommander automatiquement la cloison conforme réglementairement la moins chère selon l’acoustique, le feu et la hauteur.

- Interface web simple via [Streamlit](https://streamlit.io/)
- 100% Python, aucun logiciel à installer côté utilisateur final
- Export Excel des résultats pour utilisation projet ou rédaction de document (CCTP, DCE, etc)

---

## Fonctionnalités principales

- **Reconnaissance automatique des pièces d’un plan via OCR ~Tesseract ici (remplacé par un outil IA type Roboflow dans le futur)**
- **Lecture automatique des exigences acoustiques et coupe-feu** (selon pièces, réglementations fournies)
- **Sélection de la cloison optimale** : conforme, (économique), compatible avec la hauteur sous plafond et la réglementation
- **Tableau récapitulatif exportable**


## Fonctionnalités à implémenter 

- **Amélioration de la base produit, notamment du coût des cloisons pour choix final**
- **Prise en compte des cloisons hydrofuges**
- **Utilisation outil IA pour reconnaissance plan + combiner OCR et IA** 
