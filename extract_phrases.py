"""Извлечение словосочетаний из ruscorpora_content_*.csv"""

import os
import pandas as pd

FOLDER = "phrases"
csv_files = [file for file in os.listdir(FOLDER) if file.startswith("ruscorpora_content_") and file.endswith(".csv")]

cols = ["word_lex_0", "word_form_0", "word_gramm_0", "word_lex_1", "word_form_1", "word_gramm_1", "used"]
result = pd.DataFrame(columns=cols)

RESULT_FILE = os.path.join("phrases", "phrases.csv")
if os.path.exists(RESULT_FILE):
    result = pd.read_csv(RESULT_FILE)

for csv_file in csv_files:
    df = pd.read_csv(os.path.join(FOLDER, csv_file), sep=";")
    if "word_lex_2" in df.columns:
        df["word_lex_1"] = df["word_lex_2"]
        df["word_gramm_1"] = df["word_gramm_2"]
        df["word_form_1"] = df["word_form_1"] + " " + df["word_form_2"]
    df["used"] = False
    result = pd.concat([result, df[cols]])
result.drop_duplicates(subset=["word_lex_0", "word_lex_1"], inplace=True)

result = result[(result["word_form_0"].str.len() > 1) & (result["word_form_1"].str.split().str[-1].str.len() > 1)]
with open(os.path.join(FOLDER, "stopwords.txt"), encoding="utf8") as f:
    stopwords = [l.strip() for l in f.readlines()]
result = result[~(
    result["word_form_0"].str.lower().isin(stopwords)
    | result["word_form_1"].str.split().str[-1].str.lower().isin(stopwords)
)]

def toponify(s: str):
    l = s.split()
    l[-1] = l[-1].title()
    return " ".join(l)

def abbrify(s: str):
    l = s.split()
    l[-1] = l[-1].upper()
    return " ".join(l)

for num in range(2):
    topons = result[f"word_gramm_{num}"].str.contains("topon")
    result.loc[topons, f"word_form_{num}"] = result.loc[topons, f"word_form_{num}"].map(toponify)
    abbrs = result[f"word_gramm_{num}"].str.contains("abbr")
    result.loc[abbrs, f"word_form_{num}"] = result.loc[abbrs, f"word_form_{num}"].map(abbrify)

result.to_csv(RESULT_FILE, index=False)