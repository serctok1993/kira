# Tuning-Werkbank — unser eigenes Qwen finetunen

Ziel (des Nutzers „Unschlagbar-Kombi"): ein **Harness nur für dich** (Kira) + ein
**Lokalmodell nur für dich** (getuntes Qwen). Kira bleibt dabei voll flexibel —
sie trainiert **nichts** selbst und hängt an **keinem** Modell. Dieses Modul
sammelt nur Trainingsmaterial und exportiert es; das Training läuft **außerhalb**,
auf deinem PC, und ist komplett optional.

## Was Kira dir liefert

- **Rekorder:** jede echte Unterhaltung wird still als eine Zeile nach
  `data/tuning/episodes.jsonl` geschrieben (Test-/Benchmark-/Wallpaper-Chats nie).
- **Synth-Generator:** erzeugt live aus Kiras Werkzeug-Registry Beispiele für das
  ACT-Protokoll, Arbeitsdisziplin (sofort handeln statt ankündigen) und Kira-Ton.
- **Grundstock (Seed):** handgeschriebene Mehrschritt-Beispiele, die Kiras Struktur
  lehren — Coding (suchen → chirurgisch editieren → **verifizieren**), Tool-Ketten,
  Planen-dann-ausführen, Freigabe-Reflex für Außen-Aktionen, Ton/Kreativität, plus
  des Nutzers stabile Identität & Werte (Systemdenker, positive Wirkung, Unabhängigkeit).
  Wichtig: **stabile** Dinge (Stil, Werte, Struktur) gehören in die Gewichte —
  **veränderliche** Fakten (Termine, Zahlen, Projektdetails) bleiben im Gedächtnis.
- **Export:** Prüfstand → „Datensatz exportieren" schreibt ein ChatML-JSONL nach
  `data/tuning/kira-sft-<zeit>.jsonl` (Standardformat, das jedes Trainingswerkzeug frisst).

## Der Zwei-Phasen-Plan

1. **Struktur-Tune (sofort möglich):** nur mit den synthetischen Beispielen — bringt
   dem Modell Kiras Protokoll, Disziplin und Ton bei. Sinnvoll, sobald das finale
   Lokalmodell feststeht.
2. **Nachschärfen (nach ~2 Wochen):** erneut exportieren, jetzt mit den echten
   Episoden dabei. Gleicher Befehl, besserer Datensatz.

## Training (außerhalb von Kira, auf deinem PC)

**Empfohlen: [Unsloth](https://github.com/unslothai/unsloth)** — schnell, sparsam,
QLoRA (nur kleine Zusatz-Gewichte werden trainiert, das Basismodell bleibt heil).

VRAM-Faustregel (QLoRA, 4-bit):
- **8 GB** → Qwen 3–4B
- **12–16 GB** → Qwen 7–9B
- **24 GB** → Qwen 14B

Skizze (Python, einmalig `pip install unsloth`):

```python
from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig

model, tok = FastLanguageModel.from_pretrained(
    "unsloth/Qwen2.5-7B-Instruct", load_in_4bit=True, max_seq_length=4096)
model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=16)

ds = load_dataset("json", data_files="data/tuning/kira-sft-XXXX.jsonl", split="train")
ds = ds.map(lambda e: {"text": tok.apply_chat_template(e["messages"], tokenize=False)})

SFTTrainer(model=model, tokenizer=tok, train_dataset=ds,
           args=SFTConfig(per_device_train_batch_size=2, gradient_accumulation_steps=4,
                          warmup_steps=5, num_train_epochs=2, learning_rate=2e-4,
                          logging_steps=5, output_dir="out")).train()

model.save_pretrained_gguf("kira-qwen", tok, quantization_method="q4_k_m")
```

## Zurück in Kira (ganz ohne Codeänderung)

```
ollama create kira-qwen -f Modelfile      # Modelfile zeigt auf die kira-qwen.gguf
```

Danach steht `kira-qwen` **sofort** im Modell-Dropdown (die lokale Liste ist
ungecacht). Im Steuerpult einer Rolle zuweisen — z.B. dem **Arbeiter** (Masse) —
und im Prüfstand gegen den Ist-Zustand benchen. Jede Route, wo das getunte Qwen
gleichzieht, kannst du auf lokal umlegen; die Cloud bleibt als Eskalation. Nichts
davon ist Einbahnstraße: du schaltest jederzeit zurück.
