# OutilCloison

## Présentation

**OutilCloison** est un assistant d’aide de sélection de cloisons pour les logements.  
L’application permet, à partir de fichiers Excel (réglementations, base produits) et d’un plan reconnu (tableau),  
de recommander automatiquement la cloison conforme réglementairement la moins chère selon l’acoustique, le feu et la hauteur.

- Interface web simple via [Streamlit](https://streamlit.io/)
- 100% Python, aucun logiciel à installer côté utilisateur final
- Export Excel des résultats pour utilisation projet ou CCTP

---

## Fonctionnalités principales

- **Upload d’un tableau Excel issu d’un plan (ou d’un outil IA type Roboflow)**
- **Lecture automatique des exigences acoustiques et coupe-feu** (selon pièces, réglementations fournies)
- **Sélection de la cloison optimale** : conforme, économique, compatible avec la hauteur sous plafond et la réglementation
- **Tableau récapitulatif exportable**
