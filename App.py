import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import os, re, sys
import shutil
import PyPDF2, threading
from pdf2image import convert_from_path
import pytesseract
import requests
from openai import OpenAI

HF_API_TOKEN = "C:/your/personal/route//HF_API_TOKEN.txt" # SAVE IT IN THE SYSTEM THEN ACCESS WITH 'OS'
# Leggi il token dal file
try:
    with open(HF_API_TOKEN , "r") as f:
        HF_API_TOKEN = f.read().strip()  # strip() rimuove eventuali spazi o ritorni a capo
except FileNotFoundError:
    raise FileNotFoundError(f"File token non trovato: {HF_API_TOKEN}")

# Verifica
if not HF_API_TOKEN:
    raise ValueError("Il token è vuoto nel file!")
HF_MODEL = "meta-llama/Llama-3.2-3B-Instruct" # meta-llama/Llama-3.1-8B-Instruct - meta-llama/Llama-3.3-70B-Instruct - meta-llama/Llama-3.2-3B-Instruct

# Inizializza il client OpenAI per Hugging Face Router
client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_API_TOKEN,
)

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

POPPLER_PATH = os.path.join(base_path, "poppler-25.07.0", "Library/bin")
TESSERACT_CMD = os.path.join(base_path, "Tesseract-OCR", "tesseract.exe")
TESSDATA_PATH = os.path.join(base_path, "Tesseract-OCR", "tessdata")

BASE_DIR = "clienti"
os.makedirs(BASE_DIR, exist_ok=True)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
os.environ['TESSDATA_PREFIX'] = TESSDATA_PATH

def ocr_pdf_page(pdf_path, page_num, lang):
    """Esegue l'OCR su una singola pagina del PDF."""
    try:
        pagina_immagine = convert_from_path(
            pdf_path,
            poppler_path=POPPLER_PATH,
            dpi=150,
            first_page=page_num + 1,
            last_page=page_num + 1
        )
        if pagina_immagine:
            return pytesseract.image_to_string(pagina_immagine[0], lang=lang)
    except Exception as e:
        print(f"Errore OCR su pagina {page_num + 1}: {e}")
    return ""

# ---------------- THREADS ----------------

class FindPagesThread(threading.Thread):
    def __init__(self, root, cliente_selezionato, file_name, keywords, lang, callback):
        super().__init__()
        self.root = root
        self.cliente_selezionato = cliente_selezionato
        self.file_name = file_name
        self.keywords = [k.lower().strip() for k in keywords]
        self.lang = lang
        self.callback = callback
        self.progress_var = tk.DoubleVar()
        self.status_var = tk.StringVar()
        self.risultato = None

    def update_progress(self, current, total, text=""):
        percent = (current / total) * 100
        self.root.after(0, self.progress_var.set, percent)
        self.root.after(0, self.status_var.set, f"Analisi pagina {current} di {total} {text}")

    def page_text_extract(self, pdf_path, page_num):
        return ocr_pdf_page(pdf_path, page_num, self.lang)

    def run(self):
        file_path = os.path.join(BASE_DIR, self.cliente_selezionato, self.file_name)
        pagine_trovate_idx = []

        try:
            writer = PyPDF2.PdfWriter()
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                num_pages = len(reader.pages)

                for i in range(num_pages):
                    self.update_progress(i + 1, num_pages)
                    testo_pagina = reader.pages[i].extract_text()

                    if not testo_pagina or testo_pagina.strip() == "":
                        self.update_progress(i + 1, num_pages, "(OCR in corso...)")
                        testo_pagina = self.page_text_extract(file_path, i)

                    if testo_pagina:
                        testo_pagina_lower = testo_pagina.lower()
                        if all(keyword in testo_pagina_lower for keyword in self.keywords):
                            pagine_trovate_idx.append(i)

                if pagine_trovate_idx:
                    for page_idx in pagine_trovate_idx:
                        writer.add_page(reader.pages[page_idx])

            if pagine_trovate_idx:
                keywords_filename_part = "_".join(self.keywords)
                nome_base, estensione = os.path.splitext(file_path)
                output_path = f"{nome_base}_FILTRATO_{keywords_filename_part}{estensione}"

                with open(output_path, "wb") as out_f:
                    writer.write(out_f)

                self.risultato = (output_path, pagine_trovate_idx)
            else:
                self.risultato = (None, [])

        except Exception as e:
            self.risultato = (f"Errore durante l'elaborazione: {e}", None)

        self.root.after(0, self.callback, self.risultato)

class AIExtractThread(threading.Thread):
    def __init__(self, root, file_path, lang, callback, block_max_tokens=2000):
        super().__init__()
        self.root = root
        self.file_path = file_path
        self.lang = lang
        self.callback = callback
        self.block_max_tokens = block_max_tokens  # Numero massimo di token per blocco

    def run(self):
        try:
            # Estrai tutto il testo dal PDF (OCR se necessario)
            pagine_testo = []
            reader = PyPDF2.PdfReader(self.file_path)
            for i, page in enumerate(reader.pages):
                testo_pagina = page.extract_text()
                if not testo_pagina or testo_pagina.strip() == "":
                    testo_pagina = ocr_pdf_page(self.file_path, i, self.lang)
                pagine_testo.append(testo_pagina)

            testo_completo = " ".join(pagine_testo)
            if not testo_completo.strip():
                self.root.after(0, self.callback, None, "Nessun testo rilevato nel PDF.")
                return

            # Suddividi in blocchi gestibili
            blocchi = self.suddividi_blocchi(testo_completo, self.block_max_tokens)

            # Analizza ogni blocco con AI e raccogli i risultati
            risultati_blocchi = []
            for idx, blocco in enumerate(blocchi):
                self.root.after(0, lambda idx=idx: self.root.title(f"Analisi AI blocco {idx+1}/{len(blocchi)}"))
                summary_blocco = self.genera_riassunto_ai(blocco)
                risultati_blocchi.append(summary_blocco)

            # 4Combina i riassunti finali
            riassunto_finale = "\n\n".join(risultati_blocchi)
            self.root.after(0, self.callback, riassunto_finale, None)

        except Exception as e:
            self.root.after(0, self.callback, None, f"Errore durante l'elaborazione AI: {e}")

    @staticmethod
    def suddividi_blocchi(testo, max_len=2000):
        """Divide il testo in blocchi di lunghezza massima senza spezzare parole."""
        parole = testo.split()
        blocchi = []
        blocco_corrente = []
        lunghezza_corrente = 0

        for parola in parole:
            lunghezza_corrente += len(parola) + 1
            blocco_corrente.append(parola)
            if lunghezza_corrente >= max_len:
                blocchi.append(" ".join(blocco_corrente))
                blocco_corrente = []
                lunghezza_corrente = 0

        if blocco_corrente:
            blocchi.append(" ".join(blocco_corrente))

        return blocchi

    @staticmethod
    def genera_riassunto_ai(testo, max_tokens=500):
        messages = [
            {"role": "user", "content": f"""
            Sei un assistente esperto in assicurazioni, tasse e documenti finanziari. 
            Leggi attentamente il testo e fornisci:
            1. Riassunto chiaro dei dati principali del cliente.
            2. Informazioni specifiche come reddito, tipo di documento, dati fiscali, assicurazioni, ecc.
            3. Linguaggio tecnico ma chiaro e conciso.
            4. Se le informazioni non sono certe, scrivi "non disponibile o poco chiaro".

            {testo}
            """}
        ]
        try:
            completion = client.chat.completions.create(
                model=HF_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.6,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise Exception(f"Errore API HuggingFace/OpenAI: {e}")



class FileUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Gestione Clienti - File Uploader")
        self.root.geometry("1200x800")

        self.font_label = ("Arial", 22)
        self.font_entry = ("Arial", 12)
        self.font_listbox = ("Arial", 11)
        self.font_button = ("Arial", 12, "bold")

        self.progress_var = tk.DoubleVar()
        self.status_var = tk.StringVar(value="Seleziona un PDF e avvia la ricerca per parole chiave.")
        self.lang_var = tk.StringVar(value="ita")
        self.file_list_completa = []

        style = ttk.Style()
        style.configure("My.TButton", font=("Arial", 12, "bold"))
        style.configure("TProgressbar", thickness=20)

        # ===== SEZIONE CENTRALE: DATI CLIENTE =====
        frame_centrale = tk.Frame(root)
        frame_centrale.pack(pady=20)

        tk.Label(frame_centrale, text="Nome:", font=self.font_label).grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.entry_nome = tk.Entry(frame_centrale, width=25, font=self.font_entry)
        self.entry_nome.grid(row=0, column=1, padx=5, pady=2)

        tk.Label(frame_centrale, text="Cognome:", font=self.font_label).grid(row=1, column=0, sticky="e", padx=5,
                                                                             pady=2)
        self.entry_cognome = tk.Entry(frame_centrale, width=25, font=self.font_entry)
        self.entry_cognome.grid(row=1, column=1, padx=5, pady=2)

        tk.Label(frame_centrale, text="Codice Fiscale:", font=self.font_label).grid(row=2, column=0, sticky="e", padx=5,
                                                                                    pady=2)
        self.entry_cf = tk.Entry(frame_centrale, width=25, font=self.font_entry)
        self.entry_cf.grid(row=2, column=1, padx=5, pady=2)

        self.btn_carica = ttk.Button(frame_centrale, text="Carica File", command=self.carica_file)
        self.btn_carica.grid(row=3, column=0, columnspan=2, pady=10)
        self.btn_carica.config(style="My.TButton")

        # ===== SEZIONE INFERIORE: CLIENTI E FILE =====
        frame_inferiore = tk.Frame(root)
        frame_inferiore.pack(fill="both", expand=True, padx=10, pady=10)

        frame_inferiore.columnconfigure(0, weight=1)
        frame_inferiore.columnconfigure(1, weight=3)
        frame_inferiore.rowconfigure(0, weight=1)

        # Frame Clienti + ricerca
        frame_clienti = tk.Frame(frame_inferiore)
        frame_clienti.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame_clienti.rowconfigure(2, weight=1)
        frame_clienti.columnconfigure(0, weight=1)

        tk.Label(frame_clienti, text="Clienti", font=self.font_label).grid(row=0, column=0, sticky="w", padx=(5, 5))

        frame_ricerca = tk.Frame(frame_clienti)
        frame_ricerca.grid(row=1, column=0, sticky="w", pady=(5, 5))

        self.entry_cerca_cf = tk.Entry(frame_ricerca, font=self.font_entry, fg="grey")
        self.entry_cerca_cf.insert(0, "CF, cognome o nome")
        self.entry_cerca_cf.bind("<FocusIn>", self._clear_placeholder)
        self.entry_cerca_cf.bind("<FocusOut>", self._add_placeholder)
        self.entry_cerca_cf.grid(row=0, column=0, padx=(0, 5))

        self.btn_cerca = ttk.Button(frame_ricerca, text="Cerca", command=self.cerca_cliente)
        self.btn_cerca.grid(row=0, column=1, padx=(0, 5))

        self.btn_mostra_tutti = ttk.Button(frame_ricerca, text="Mostra tutti", command=self.carica_clienti_esistenti)
        self.btn_mostra_tutti.grid(row=0, column=2)

        self.listbox_clienti = tk.Listbox(frame_clienti, font=self.font_listbox)
        self.listbox_clienti.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        self.listbox_clienti.bind("<<ListboxSelect>>", self.aggiorna_cliente_selezionato)

        # Frame File del cliente
        frame_file = tk.Frame(frame_inferiore)
        frame_file.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        frame_file.rowconfigure(2, weight=1)
        frame_file.columnconfigure(0, weight=1)

        tk.Label(frame_file, text="File del cliente", font=self.font_label).grid(row=0, column=0, sticky="w",
                                                                                 padx=(5, 5))

        # --- BARRA DI RICERCA FILE ---
        frame_cerca_file = tk.Frame(frame_file)
        frame_cerca_file.grid(row=1, column=0, sticky="ew", pady=(5, 5))
        frame_cerca_file.columnconfigure(0, weight=1)

        self.search_file_var = tk.StringVar()
        self.search_file_entry = ttk.Entry(frame_cerca_file, textvariable=self.search_file_var, font=self.font_entry)
        self.search_file_entry.grid(row=0, column=0, sticky="ew", padx=(5, 5))
        self.search_file_entry.bind("<KeyRelease>", self.filtra_file_cliente)

        self.btn_reset_search = ttk.Button(frame_cerca_file, text="Reset", command=self.reset_ricerca_file)
        self.btn_reset_search.grid(row=0, column=1, padx=(0, 5))
        # --- FINE BARRA DI RICERCA FILE ---

        # Frame per Listbox + Scrollbar
        frame_listbox_file = tk.Frame(frame_file)
        frame_listbox_file.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        frame_listbox_file.rowconfigure(0, weight=1)
        frame_listbox_file.columnconfigure(0, weight=1)

        self.listbox_file = tk.Listbox(frame_listbox_file, font=self.font_listbox, selectmode="browse")
        self.listbox_file.grid(row=0, column=0, sticky="nsew")

        scrollbar_file = tk.Scrollbar(frame_listbox_file, orient="vertical", command=self.listbox_file.yview)
        scrollbar_file.grid(row=0, column=1, sticky="ns")
        self.listbox_file.config(yscrollcommand=scrollbar_file.set)

        self.listbox_file.bind("<Double-1>", self.apri_file_selezionato)

        self.btn_aggiungi = ttk.Button(frame_file, text="Aggiungi file", command=self.aggiungi_file_cliente)
        self.btn_aggiungi.grid(row=3, column=0, pady=5, sticky="ew")

        self.btn_elimina = ttk.Button(frame_file, text="Elimina Cliente", command=self.elimina_cliente)
        self.btn_elimina.grid(row=4, column=0, pady=(2, 5), sticky="ew")

        self.btn_elimina_file = ttk.Button(frame_file, text="Elimina File Selezionato",
                                           command=self.elimina_file_selezionato)
        self.btn_elimina_file.grid(row=5, column=0, pady=(2, 5), sticky="ew")

        frame_ocr_lang = tk.Frame(frame_file)
        frame_ocr_lang.grid(row=6, column=0, sticky="ew", pady=(2, 5))
        tk.Label(frame_ocr_lang, text="Lingua OCR:", font=("Arial", 10)).pack(side="left")
        self.lang_dropdown = ttk.Combobox(frame_ocr_lang, textvariable=self.lang_var, values=["ita", "eng"],
                                          state="readonly")
        self.lang_dropdown.pack(side="left", padx=5)

        self.btn_cerca_pagine = ttk.Button(frame_file, text="Cerca Pagine per Parole Chiave",
                                           command=self.run_pages_research)
        self.btn_cerca_pagine.grid(row=7, column=0, pady=(2, 5), sticky="ew")

        self.progressbar = ttk.Progressbar(frame_file, variable=self.progress_var, maximum=100)
        self.progressbar.grid(row=8, column=0, pady=(2, 2), sticky="ew")
        self.status_label = tk.Label(frame_file, textvariable=self.status_var, font=("Arial", 10, "italic"))
        self.status_label.grid(row=9, column=0, sticky="ew")

        self.btn_ai_extract = ttk.Button(frame_file, text="Estrai info PDF con AI", command=self.run_ai_extraction)
        self.btn_ai_extract.grid(row=10, column=0, pady=(2, 5), sticky="ew")

        self.cliente_selezionato = None
        self.carica_clienti_esistenti()

    def run_ai_extraction(self):
        if not self.cliente_selezionato:
            messagebox.showerror("Errore", "Seleziona prima un cliente.")
            return

        selected_file_idx = self.listbox_file.curselection()
        if not selected_file_idx:
            messagebox.showerror("Errore", "Seleziona un file PDF da analizzare.")
            return

        file_name = self.listbox_file.get(selected_file_idx[0])
        if not file_name.lower().endswith(".pdf"):
            messagebox.showerror("Errore", "Questa funzione è disponibile solo per file PDF.")
            return

        file_path = os.path.join(BASE_DIR, self.cliente_selezionato, file_name)
        self.progress_var.set(0)
        self.status_var.set("Avvio estrazione informazioni AI...")

        thread = AIExtractThread(
            self.root,
            file_path,
            self.lang_var.get(),
            self.on_ai_extraction_completed
        )
        thread.start()

    def on_ai_extraction_completed(self, summary, errore):
        self.progress_var.set(100)
        if errore:
            self.status_var.set("Errore estrazione AI.")
            messagebox.showerror("Errore", errore)
        else:
            self.status_var.set("Estrazione AI completata.")
            summary_window = tk.Toplevel(self.root)
            summary_window.title("Riassunto AI")
            text_widget = tk.Text(summary_window, wrap="word", font=("Arial", 12))
            text_widget.pack(fill="both", expand=True)
            text_widget.insert("1.0", summary)
            text_widget.config(state="disabled")

    def aggiorna_cliente_selezionato(self, event=None):
        selected = self.listbox_clienti.curselection()
        if selected:
            self.cliente_selezionato = self.listbox_clienti.get(selected[0])
            self.mostra_file_cliente()
            self.progress_var.set(0)
            self.status_var.set("Seleziona un file e avvia la ricerca per parole chiave.")

    def mostra_file_cliente(self, event=None):
        if not self.cliente_selezionato:
            return

        cliente_id = self.cliente_selezionato
        self.listbox_file.delete(0, tk.END)
        cliente_dir = os.path.join(BASE_DIR, cliente_id)

        if os.path.exists(cliente_dir):
            self.file_list_completa = sorted(os.listdir(cliente_dir))
            for file_name in self.file_list_completa:
                self.listbox_file.insert(tk.END, file_name)

        self.search_file_var.set("")

    def filtra_file_cliente(self, event=None):
        ricerca = self.search_file_var.get().lower().strip()

        self.listbox_file.delete(0, tk.END)

        if not ricerca:
            for file_name in self.file_list_completa:
                self.listbox_file.insert(tk.END, file_name)
        else:
            for file_name in self.file_list_completa:
                if ricerca in file_name.lower():
                    self.listbox_file.insert(tk.END, file_name)

    def reset_ricerca_file(self):
        self.search_file_var.set("")
        self.filtra_file_cliente()

    def elimina_file_selezionato(self):
        if not self.cliente_selezionato:
            messagebox.showerror("Errore", "Seleziona prima un cliente.")
            return
        cliente_id = self.cliente_selezionato

        selected_file = self.listbox_file.curselection()
        if not selected_file:
            messagebox.showerror("Errore", "Seleziona prima un file da eliminare.")
            return
        file_name = self.listbox_file.get(selected_file[0])

        file_path = os.path.join(BASE_DIR, cliente_id, file_name)

        conferma = messagebox.askyesno("Conferma eliminazione", f"Sei sicuro di voler eliminare il file '{file_name}'?")
        if not conferma:
            return

        try:
            os.remove(file_path)
            self.mostra_file_cliente()
            messagebox.showinfo("Successo", f"File '{file_name}' eliminato con successo.")
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile eliminare il file: {e}")

    def apri_file_selezionato(self, event):
        if not self.cliente_selezionato:
            return

        selected_file = self.listbox_file.curselection()
        if not selected_file:
            return

        file_name = self.listbox_file.get(selected_file[0])
        file_path = os.path.join(BASE_DIR, self.cliente_selezionato, file_name)

        if not os.path.exists(file_path):
            messagebox.showerror("Errore", f"Il file {file_name} non esiste!")
            return

        try:
            os.startfile(file_path)
        except Exception as e:
            messagebox.showerror("Errore", f"Impossibile aprire il file:\n{e}")

    def genera_codice_nome_cognome(self, cognome, nome):
        def estrai_lettere(s):
            consonanti = "".join([c for c in s if c.upper() in "BCDFGHJKLMNPQRSTVWXYZ"])
            vocali = "".join([c for c in s if c.upper() in "AEIOU"])
            return (consonanti + vocali + "XXX").upper()[:3]

        return estrai_lettere(cognome) + estrai_lettere(nome)

    def elimina_cliente(self):
        selected = self.listbox_clienti.curselection()
        if not selected:
            messagebox.showerror("Errore", "Seleziona un cliente da eliminare!")
            return

        cliente_id = self.listbox_clienti.get(selected[0])
        cliente_dir = os.path.join(BASE_DIR, cliente_id)

        conferma = messagebox.askyesno("Conferma eliminazione",
                                       f"Sei sicuro di voler eliminare il cliente '{cliente_id}' e tutti i suoi file?")
        if conferma:
            try:
                shutil.rmtree(cliente_dir)
                self.carica_clienti_esistenti()
                self.listbox_file.delete(0, tk.END)
                messagebox.showinfo("Successo", f"Cliente '{cliente_id}' eliminato con tutti i file.")
            except Exception as e:
                messagebox.showerror("Errore", f"Impossibile eliminare il cliente: {e}")

    def aggiungi_file_cliente(self):
        selected = self.listbox_clienti.curselection()
        if not selected:
            messagebox.showerror("Errore", "Seleziona un cliente prima di aggiungere file!")
            return

        cliente_id = self.listbox_clienti.get(selected[0])
        cliente_dir = os.path.join(BASE_DIR, cliente_id)
        os.makedirs(cliente_dir, exist_ok=True)

        file_paths = filedialog.askopenfilenames(title="Seleziona file da aggiungere")
        if not file_paths:
            return

        for f in file_paths:
            file_name = os.path.basename(f)
            dest_path = os.path.join(cliente_dir, file_name)
            shutil.copy(f, dest_path)

        self.mostra_file_cliente()
        messagebox.showinfo("Successo", f"Aggiunti {len(file_paths)} file a {cliente_id}.")

    def _clear_placeholder(self, event):
        if self.entry_cerca_cf.get() == "CF, cognome o nome":
            self.entry_cerca_cf.delete(0, tk.END)
            self.entry_cerca_cf.config(fg="black")

    def _add_placeholder(self, event):
        if not self.entry_cerca_cf.get():
            self.entry_cerca_cf.insert(0, "CF, cognome o nome")
            self.entry_cerca_cf.config(fg="grey")

    def carica_clienti_esistenti(self):
        self.listbox_clienti.delete(0, tk.END)
        for cliente_id in os.listdir(BASE_DIR):
            if os.path.isdir(os.path.join(BASE_DIR, cliente_id)):
                self.listbox_clienti.insert(tk.END, cliente_id)

    def carica_file(self):
        nome = self.entry_nome.get().strip()
        cognome = self.entry_cognome.get().strip()
        cf = self.entry_cf.get().strip().upper()

        if not nome or not cognome or len(cf) != 16:
            messagebox.showerror("Errore", "Compila correttamente tutti i campi (CF = 16 caratteri)!")
            return

        pattern = r'^[A-Z]{6}[0-9]{2}[A-EHLMPRST]{1}[0-9]{2}[A-Z][0-9]{3}[A-Z]$'
        if not re.match(pattern, cf):
            messagebox.showerror("Errore", "Il codice fiscale non è nel formato corretto!")
            return

        cf_nome_cognome = self.genera_codice_nome_cognome(cognome, nome)
        if not cf.startswith(cf_nome_cognome):
            conferma = messagebox.askyesno(
                "Avviso di incongruenza",
                f"Il codice fiscale inserito ({cf}) non sembra corrispondere al nome/cognome ({cf_nome_cognome}).\n"
                "Vuoi continuare comunque?"
            )
            if not conferma:
                return

        file_paths = filedialog.askopenfilenames(title="Seleziona file")
        if not file_paths:
            return

        cliente_id = f"{cognome}_{nome}_{cf}"
        cliente_dir = os.path.join(BASE_DIR, cliente_id)

        for existing_cliente in os.listdir(BASE_DIR):
            if os.path.isdir(os.path.join(BASE_DIR, existing_cliente)):
                try:
                    _, _, cf_existing = existing_cliente.split("_")
                except ValueError:
                    continue
                if cf_existing.upper() == cf.upper():
                    messagebox.showerror("Errore", f"Cliente con codice fiscale {cf} già esistente!")
                    return

        os.makedirs(cliente_dir, exist_ok=True)

        for f in file_paths:
            file_name = os.path.basename(f)
            dest_path = os.path.join(cliente_dir, file_name)
            shutil.copy(f, dest_path)

        self.carica_clienti_esistenti()
        messagebox.showinfo("Successo", f"Caricati {len(file_paths)} file per {nome} {cognome}.")

    def cerca_cliente(self):
        ricerca = self.entry_cerca_cf.get().strip().upper()
        if not ricerca or ricerca == "CF, cognome o nome":
            messagebox.showerror("Errore", "Inserisci un nome, cognome o codice fiscale da cercare!")
            return

        self.listbox_clienti.delete(0, tk.END)
        for cliente_id in os.listdir(BASE_DIR):
            if os.path.isdir(os.path.join(BASE_DIR, cliente_id)):
                try:
                    cognome, nome, cf_cliente = cliente_id.split("_")
                except ValueError:
                    continue

                if (ricerca in cognome.upper() or
                        ricerca in nome.upper() or
                        ricerca in cf_cliente.upper()):
                    self.listbox_clienti.insert(tk.END, cliente_id)

    # Questo è il metodo mancante che devi aggiungere
    def run_pages_research(self):
        """ Avvia la ricerca per parole chiave. """
        if not self.cliente_selezionato:
            messagebox.showerror("Errore", "Seleziona prima un cliente.")
            return

        selected_file_idx = self.listbox_file.curselection()
        if not selected_file_idx:
            messagebox.showerror("Errore", "Seleziona un file PDF su cui cercare.")
            return

        file_name = self.listbox_file.get(selected_file_idx[0])
        if not file_name.lower().endswith(".pdf"):
            messagebox.showerror("Errore", "Questa funzione è disponibile solo per i file PDF.")
            return

        keywords_str = simpledialog.askstring(
            "Parole Chiave",
            "Inserisci le parole chiave da cercare, separate da una virgola (,):",
            parent=self.root
        )

        if not keywords_str or not keywords_str.strip():
            messagebox.showinfo("Info", "Nessuna parola chiave inserita. Operazione annullata.")
            return

        keywords = keywords_str.split(',')

        self.progress_var.set(0)
        self.status_var.set("Avvio ricerca pagine...")

        thread = FindPagesThread(
            self.root,
            self.cliente_selezionato,
            file_name,
            keywords,
            self.lang_var.get(),
            self.on_research_pages_completed
        )
        thread.progress_var = self.progress_var
        thread.status_var = self.status_var
        thread.start()

    # Questo è il metodo di callback che devi aggiungere
    def on_research_pages_completed(self, risultato):
        """ Gestisce il risultato della ricerca. """
        self.progress_var.set(100)
        output_path, pagine_trovate_idx = risultato

        if output_path and "Errore" in output_path:
            self.status_var.set("Ricerca fallita.")
            messagebox.showerror("Errore", output_path)
            return

        if not pagine_trovate_idx:
            self.status_var.set("Ricerca completata. Nessuna pagina trovata.")
            messagebox.showinfo("Risultato", "Nessuna pagina trovata con tutte le parole chiave specificate.")
        else:
            num_pagine = len(pagine_trovate_idx)
            file_generato = os.path.basename(output_path)
            self.status_var.set(f"Trovate {num_pagine} pagine. File '{file_generato}' creato.")
            self.mostra_file_cliente()
            aprire = messagebox.askyesno(
                "Successo",
                f"Trovate {num_pagine} pagine contenenti le parole chiave.\n\n"
                f"È stato creato il file:\n{file_generato}\n\nVuoi aprirlo ora?"
            )
            if aprire:
                try:
                    os.startfile(output_path)
                except Exception as e:
                    messagebox.showerror("Errore Apertura", f"Impossibile aprire il file: {e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = FileUploaderApp(root)

    root.mainloop()
