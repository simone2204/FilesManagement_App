# Customer Management - File Uploader with AI Analysis

This project is a desktop application developed in Python with Tkinter for managing customer documents. The app allows you to upload, organise and analyse PDF files and other types of documents, with advanced keyword search capabilities and automatic content analysis using artificial intelligence (AI) via Hugging Face / OpenAI.

---

## Main features

- **Customer management**
  - Creation and management of customers with name, surname and tax code.
  - Automatic check of consistency between tax code and name/surname.
  - Deletion of customers and related files.

- **File management**
  - Uploading and organisation of files for each customer.
  - Direct opening of files from the programme.
  - Deletion of individual files or all files for a customer.
  - Quick file search via search bar.

- **Advanced search and filtering**
  - Search for PDF pages containing specific keywords.
  - Automatic extraction of relevant pages and creation of a new filtered PDF.
  - OCR support via **Tesseract** to extract text from scanned PDFs.

- **AI analysis of PDFs**
  - Automatic extraction of key information from customer PDFs.
  - Division of the document into manageable blocks and analysis with the **LLaMA 3.2-3B Instruct** model via Hugging Face.
  - Generation of clear, structured summaries with relevant data such as income, document type, tax data, and insurance.

- **Multithreading**
  - PDF analysis and AI calls performed in separate threads to keep the interface responsive.

---

## Dipendenze

- Python 3.x
- [Tkinter](https://docs.python.org/3/library/tkinter.html)
- [PyPDF2](https://pypi.org/project/PyPDF2/)
- [pdf2image](https://pypi.org/project/pdf2image/)
- [pytesseract](https://pypi.org/project/pytesseract/)
- [Requests](https://pypi.org/project/requests/)
- [OpenAI Python SDK](https://pypi.org/project/openai/)
- Poppler e Tesseract OCR installati localmente.

---

## Configurazione

1. Salvare il **token API Hugging Face/OpenAI** in un file di testo (es. `HF_API_TOKEN.txt`).
2. Modificare il percorso del file token nel codice:

```python
HF_API_TOKEN = "C:/percorso/del/file/HF_API_TOKEN.txt"
