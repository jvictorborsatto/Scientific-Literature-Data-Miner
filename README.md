SLDM — Scientific Literature Data Miner

A professional desktop application for mining scientific literature, extracting quantitative data, and generating exploratory visualizations.

Installation
1. Requirements
Python 3.8 or newer (you already have this ✓)
2. Install dependencies

Open a terminal in the SLDM folder and run:

pip install PyQt5 matplotlib pandas PyMuPDF


Or all at once:

pip install PyQt5 matplotlib pandas PyMuPDF


Note: PyMuPDF enables real PDF text extraction. Without it, you can still add articles manually and paste text for scanning.

Running
python main.py


Or double-click run.bat (Windows) / run.sh (macOS/Linux).

Modules
Tab	Purpose
Object List	Define scientific objects (compounds, genes, species…) with categories and synonyms. Import from CSV.
Article Mining	Mendeley-style article library. Add PDFs or manually. "Scan" detects which objects appear in each article.
Visualization	Dashboard + custom interactive charts. Bar, line, scatter, heatmap, pie. Exportable.
Data Compiler	Manage quantitative review data (LC50, EC50…). Standardize parameter names. Build compiled summary tables.
Project files

Projects are saved as .sldm files (SQLite database). All data lives in a single file — easy to share or back up.

CSV Formats

Objects CSV (File → Import Objects CSV or Object List tab):

object,category,subcategory,synonyms,notes
atrazine,pesticide,triazine,"ATZ, 2-chloro-4-ethylamine",
caffeine,drug,stimulant,,


Review Data CSV (Data Compiler tab):

object,parameter,value,unit,species,article,notes
atrazine,LC50,4.5,mg/L,Daphnia magna,Smith_2015,
diclofenac,LC50,1.2,mg/L,Danio rerio,Jones_2018,
