"""
SLDM — Database layer
Handles all persistence using SQLite.
All modules read/write through this class.
"""

import sqlite3
import os
import json
import uuid
import csv
import re
from datetime import datetime
from typing import List, Dict, Optional, Any


def _uid() -> str:
    return str(uuid.uuid4())[:8]


class Database:
    """Central SQLite database for SLDM. One .sldm file = one SQLite database."""

    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-8000")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._create_schema()

    def _create_schema(self):
        c = self._conn
        c.executescript("""
        CREATE TABLE IF NOT EXISTS objects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            category    TEXT DEFAULT '',
            subcategory TEXT DEFAULT '',
            synonyms    TEXT DEFAULT '[]',
            notes       TEXT DEFAULT '',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS articles (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            authors     TEXT DEFAULT '',
            year        INTEGER,
            journal     TEXT DEFAULT '',
            volume      TEXT DEFAULT '',
            issue       TEXT DEFAULT '',
            pages       TEXT DEFAULT '',
            doi         TEXT DEFAULT '',
            abstract    TEXT DEFAULT '',
            keywords    TEXT DEFAULT '',
            file_path   TEXT DEFAULT '',
            raw_text    TEXT DEFAULT '',
            added_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS citations (
            id          TEXT PRIMARY KEY,
            object_id   TEXT NOT NULL,
            object_name TEXT NOT NULL,
            article_id  TEXT NOT NULL,
            article_title TEXT NOT NULL,
            year        INTEGER,
            FOREIGN KEY (object_id)  REFERENCES objects(id)  ON DELETE CASCADE,
            FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE,
            UNIQUE (object_id, article_id)
        );

        CREATE TABLE IF NOT EXISTS review_data (
            id          TEXT PRIMARY KEY,
            object_name TEXT NOT NULL,
            parameter   TEXT NOT NULL,
            value       TEXT DEFAULT '',
            value_num   REAL,
            unit        TEXT DEFAULT '',
            species     TEXT DEFAULT '',
            article_id  TEXT DEFAULT '',
            article_ref TEXT DEFAULT '',
            notes       TEXT DEFAULT '',
            added_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS param_mappings (
            original    TEXT PRIMARY KEY,
            standard    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS extracted_tables (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            source_file TEXT DEFAULT '',
            page_num    INTEGER DEFAULT 0,
            headers     TEXT DEFAULT '[]',
            rows        TEXT DEFAULT '[]',
            added_at    TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS project_meta (
            key         TEXT PRIMARY KEY,
            value       TEXT
        );

        -- Performance indexes
        CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
        CREATE INDEX IF NOT EXISTS idx_articles_year ON articles(year);
        CREATE INDEX IF NOT EXISTS idx_citations_object ON citations(object_id);
        CREATE INDEX IF NOT EXISTS idx_citations_article ON citations(article_id);
        CREATE INDEX IF NOT EXISTS idx_citations_object_name ON citations(object_name);
        CREATE INDEX IF NOT EXISTS idx_review_object ON review_data(object_name);
        CREATE INDEX IF NOT EXISTS idx_review_param ON review_data(parameter);
        """)
        # Migrate: add categories column if not present
        cols = [r[1] for r in c.execute("PRAGMA table_info(objects)").fetchall()]
        if "categories" not in cols:
            c.execute("ALTER TABLE objects ADD COLUMN categories TEXT DEFAULT '[]'")
            # Back-fill from existing category/subcategory fields
            rows = c.execute("SELECT id, category, subcategory FROM objects").fetchall()
            for row in rows:
                cats = []
                if row[1]: cats.append(row[1])
                if row[2]: cats.append(row[2])
                c.execute("UPDATE objects SET categories=? WHERE id=?",
                          (json.dumps(cats), row[0]))
        c.commit()
        if not self.get_meta("project_name"):
            self.set_meta("project_name", "New Project")

    def close(self):
        self._conn.close()

    # ── META ──────────────────────────────────────────────────────────────────
    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM project_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        self._conn.execute("INSERT OR REPLACE INTO project_meta(key,value) VALUES(?,?)", (key, value))
        self._conn.commit()

    # ── OBJECTS ───────────────────────────────────────────────────────────────
    def get_objects(self) -> List[Dict]:
        rows = self._conn.execute("SELECT * FROM objects ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Parse categories array; back-fill from legacy fields if empty
            cats = []
            try: cats = json.loads(d.get("categories", "[]") or "[]")
            except: pass
            if not cats:
                if d.get("category"):    cats.append(d["category"])
                if d.get("subcategory"): cats.append(d["subcategory"])
            d["categories"] = cats
            # Keep legacy keys as aliases for backward compat
            d["category"]    = cats[0] if len(cats) > 0 else ""
            d["subcategory"] = cats[1] if len(cats) > 1 else ""
            result.append(d)
        return result

    def get_object_by_name(self, name: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT * FROM objects WHERE name=? LIMIT 1", (name,)
        ).fetchone()
        if not row: return None
        d = dict(row)
        cats = []
        try: cats = json.loads(d.get("categories", "[]") or "[]")
        except: pass
        if not cats:
            if d.get("category"):    cats.append(d["category"])
            if d.get("subcategory"): cats.append(d["subcategory"])
        d["categories"] = cats
        d["category"]    = cats[0] if len(cats) > 0 else ""
        d["subcategory"] = cats[1] if len(cats) > 1 else ""
        return d

    def add_object(self, name: str, category="", subcategory="",
                   synonyms: List[str]=None, notes="",
                   categories: List[str]=None) -> str:
        oid = _uid()
        # Build categories list: prefer explicit list, else build from legacy fields
        if categories is None:
            categories = []
            if category:    categories.append(category)
            if subcategory: categories.append(subcategory)
        cat1 = categories[0] if len(categories) > 0 else category
        cat2 = categories[1] if len(categories) > 1 else subcategory
        self._conn.execute(
            "INSERT INTO objects(id,name,category,subcategory,synonyms,notes,categories) "
            "VALUES(?,?,?,?,?,?,?)",
            (oid, name.strip(), cat1, cat2,
             json.dumps(synonyms or []), notes, json.dumps(categories))
        )
        self._conn.commit()
        return oid

    def update_object(self, oid: str, **kwargs):
        if "synonyms" in kwargs and isinstance(kwargs["synonyms"], list):
            kwargs["synonyms"] = json.dumps(kwargs["synonyms"])
        # If categories list provided, sync legacy fields too
        if "categories" in kwargs:
            cats = kwargs["categories"]
            if isinstance(cats, list):
                kwargs["category"]    = cats[0] if len(cats) > 0 else ""
                kwargs["subcategory"] = cats[1] if len(cats) > 1 else ""
                kwargs["categories"]  = json.dumps(cats)
        # If legacy fields updated, sync categories
        elif "category" in kwargs or "subcategory" in kwargs:
            existing = self.get_object_by_name_id(oid)
            cats = list(existing.get("categories", []))
            if "category" in kwargs:
                if cats: cats[0] = kwargs["category"]
                else: cats = [kwargs["category"]]
            if "subcategory" in kwargs:
                if len(cats) > 1: cats[1] = kwargs["subcategory"]
                elif len(cats) == 1: cats.append(kwargs["subcategory"])
                else: cats = ["", kwargs["subcategory"]]
            kwargs["categories"] = json.dumps(cats)
        sets = ", ".join(f"{k}=?" for k in kwargs)
        self._conn.execute(f"UPDATE objects SET {sets} WHERE id=?", (*kwargs.values(), oid))
        self._conn.commit()

    def get_object_by_name_id(self, oid: str) -> dict:
        row = self._conn.execute("SELECT * FROM objects WHERE id=?", (oid,)).fetchone()
        if not row: return {}
        d = dict(row)
        try: d["categories"] = json.loads(d.get("categories","[]") or "[]")
        except: d["categories"] = []
        return d

    def delete_object(self, oid: str):
        self._conn.execute("DELETE FROM objects WHERE id=?", (oid,))
        self._conn.commit()

    @staticmethod
    def _detect_delimiter(filepath: str) -> str:
        """
        Detect whether the CSV uses semicolon or comma as column delimiter.
        Tries semicolon first (preferred for scientific data that may contain
        commas inside compound names).  Falls back to comma if the file has
        more comma-separated columns than semicolon-separated.
        """
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            sample = f.read(4096)
        # Count columns detected by each delimiter on the first line
        first_line = sample.split('\n')[0]
        n_semi  = len(first_line.split(';'))
        n_comma = len(first_line.split(','))
        return ';' if n_semi >= n_comma else ','

    def get_csv_columns(self, filepath: str):
        """Return (columns, preview_rows) from a CSV file."""
        delim = self._detect_delimiter(filepath)
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=delim)
            columns = reader.fieldnames or []
            preview = []
            for i, row in enumerate(reader):
                if i >= 5: break
                preview.append(dict(row))
        return columns, preview

    def import_objects_csv(self, filepath: str, mapping: dict = None) -> int:
        """
        Import objects from CSV with flexible column mapping.
        mapping = {
            'name_col':       'Common Name',
            'category_cols':  ['Body Plan', 'Habitat', 'Trophic Level'],  # ordered list, N categories
            'synonym_col':    'Alternative Names',
            'notes_col':      '',
        }
        Legacy keys 'category_col' and 'subcategory_col' are still accepted.
        """
        delim = self._detect_delimiter(filepath)

        if mapping is None:
            columns, _ = self.get_csv_columns(filepath)
            col_lower = {c.lower(): c for c in columns}
            mapping = {
                'name_col':     (col_lower.get('object') or col_lower.get('name') or
                                 col_lower.get('compound name') or col_lower.get('compound') or
                                 (columns[0] if columns else '')),
                'category_cols': [],
                'synonym_col':  col_lower.get('synonym') or col_lower.get('synonyms') or '',
                'notes_col':    col_lower.get('notes') or '',
            }
            # Auto-detect category columns
            for c in columns:
                cl = c.lower()
                if cl in ('category','class','group','type','family',
                          'category 1','class 1'):
                    mapping['category_cols'].insert(0, c)
                elif cl in ('subcategory','subclass','subgroup','subtype',
                            'subfamily','sub','category 2','class 2'):
                    if len(mapping['category_cols']) < 2:
                        mapping['category_cols'].append(c)

        name_col   = mapping.get('name_col', '')
        # Accept both new 'category_cols' list and legacy 'category_col'/'subcategory_col'
        cat_cols = mapping.get('category_cols', [])
        if not cat_cols:
            c1 = mapping.get('category_col', '')
            c2 = mapping.get('subcategory_col', '')
            if c1: cat_cols.append(c1)
            if c2: cat_cols.append(c2)
        syn_col   = mapping.get('synonym_col', '')
        notes_col = mapping.get('notes_col', '')

        grouped = {}
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=delim)
            for row in reader:
                name = row.get(name_col, "").strip()
                if not name:
                    continue
                if name not in grouped:
                    cats = [row.get(c, "").strip() for c in cat_cols]
                    grouped[name] = {
                        'categories': cats,
                        'synonyms':   [],
                        'notes':      row.get(notes_col, "").strip() if notes_col else "",
                    }
                if syn_col:
                    raw_syn = row.get(syn_col, "").strip()
                    for syn in raw_syn.split(';'):
                        syn = syn.strip()
                        if syn and syn != name and syn not in grouped[name]['synonyms']:
                            grouped[name]['synonyms'].append(syn)

        count = 0
        for name, data in grouped.items():
            cats = data['categories']
            try:
                self.add_object(
                    name=name,
                    categories=cats,
                    synonyms=data['synonyms'],
                    notes=data['notes'],
                )
                count += 1
            except sqlite3.IntegrityError:
                pass
        return count

    # ── ARTICLES ──────────────────────────────────────────────────────────────
    def get_articles(self) -> List[Dict]:
        rows = self._conn.execute("SELECT * FROM articles ORDER BY year DESC, title").fetchall()
        return [dict(r) for r in rows]

    def get_article(self, aid: str) -> Optional[Dict]:
        row = self._conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        return dict(row) if row else None

    def add_article(self, title: str, authors="", year=None, journal="", volume="",
                    issue="", pages="", doi="", abstract="", keywords="",
                    file_path="", raw_text="") -> str:
        aid = _uid()
        self._conn.execute(
            """INSERT INTO articles(id,title,authors,year,journal,volume,issue,pages,
               doi,abstract,keywords,file_path,raw_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, title, authors, year, journal, volume, issue, pages,
             doi, abstract, keywords, file_path, raw_text)
        )
        self._conn.commit()
        return aid

    def update_article(self, aid: str, **kwargs):
        sets = ", ".join(f"{k}=?" for k in kwargs)
        self._conn.execute(f"UPDATE articles SET {sets} WHERE id=?", (*kwargs.values(), aid))
        self._conn.commit()

    def delete_article(self, aid: str):
        self._conn.execute("DELETE FROM articles WHERE id=?", (aid,))
        self._conn.commit()

    # ── CITATIONS ─────────────────────────────────────────────────────────────
    def get_citations(self) -> List[Dict]:
        rows = self._conn.execute("""
            SELECT c.*, a.journal, a.authors
            FROM citations c
            JOIN articles a ON a.id = c.article_id
            ORDER BY c.object_name, c.year
        """).fetchall()
        return [dict(r) for r in rows]

    def add_citation(self, object_id: str, object_name: str,
                     article_id: str, article_title: str, year=None):
        cid = _uid()
        try:
            self._conn.execute(
                "INSERT INTO citations(id,object_id,object_name,article_id,article_title,year) VALUES(?,?,?,?,?,?)",
                (cid, object_id, object_name, article_id, article_title, year)
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            pass  # already exists

    def delete_citations_for_article(self, article_id: str):
        self._conn.execute("DELETE FROM citations WHERE article_id=?", (article_id,))
        self._conn.commit()

    def get_citation_counts(self) -> Dict[str, int]:
        """Returns {object_name: article_count}"""
        rows = self._conn.execute(
            "SELECT object_name, COUNT(DISTINCT article_id) as cnt FROM citations GROUP BY object_name"
        ).fetchall()
        return {r["object_name"]: r["cnt"] for r in rows}

    def get_citations_by_year(self) -> List[Dict]:
        rows = self._conn.execute("""
            SELECT object_name, year, COUNT(DISTINCT article_id) as cnt
            FROM citations WHERE year IS NOT NULL
            GROUP BY object_name, year ORDER BY year
        """).fetchall()
        return [dict(r) for r in rows]

    def get_articles_per_year(self) -> List[Dict]:
        rows = self._conn.execute("""
            SELECT year, COUNT(*) as cnt FROM articles
            WHERE year IS NOT NULL GROUP BY year ORDER BY year
        """).fetchall()
        return [dict(r) for r in rows]

    def get_citations_by_journal(self) -> List[Dict]:
        rows = self._conn.execute("""
            SELECT a.journal, COUNT(DISTINCT c.article_id) as cnt
            FROM citations c JOIN articles a ON a.id=c.article_id
            WHERE a.journal != '' GROUP BY a.journal ORDER BY cnt DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_objects_per_article(self) -> List[Dict]:
        """For each article, count how many objects appear."""
        rows = self._conn.execute("""
            SELECT article_title, COUNT(DISTINCT object_id) as obj_count, year
            FROM citations GROUP BY article_id ORDER BY obj_count DESC
        """).fetchall()
        return [dict(r) for r in rows]

    # ── REVIEW DATA ───────────────────────────────────────────────────────────
    def get_review_data(self) -> List[Dict]:
        rows = self._conn.execute("SELECT * FROM review_data ORDER BY object_name, parameter").fetchall()
        return [dict(r) for r in rows]

    def add_review_row(self, object_name: str, parameter: str, value="",
                       unit="", species="", article_id="", article_ref="", notes="") -> str:
        rid = _uid()
        value_num = None
        try: value_num = float(value)
        except: pass
        self._conn.execute(
            """INSERT INTO review_data(id,object_name,parameter,value,value_num,unit,
               species,article_id,article_ref,notes) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (rid, object_name, parameter, value, value_num, unit, species, article_id, article_ref, notes)
        )
        self._conn.commit()
        return rid

    def update_review_row(self, rid: str, **kwargs):
        if "value" in kwargs:
            try: kwargs["value_num"] = float(kwargs["value"])
            except: kwargs["value_num"] = None
        sets = ", ".join(f"{k}=?" for k in kwargs)
        self._conn.execute(f"UPDATE review_data SET {sets} WHERE id=?", (*kwargs.values(), rid))
        self._conn.commit()

    def delete_review_row(self, rid: str):
        self._conn.execute("DELETE FROM review_data WHERE id=?", (rid,))
        self._conn.commit()

    def import_review_csv(self, filepath: str) -> int:
        count = 0
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                obj = row.get("object","") or row.get("compound","")
                param = row.get("parameter","") or row.get("param","")
                if not obj or not param:
                    continue
                self.add_review_row(
                    object_name=obj.strip(),
                    parameter=param.strip(),
                    value=row.get("value",""),
                    unit=row.get("unit",""),
                    species=row.get("species",""),
                    article_ref=row.get("article","") or row.get("source",""),
                    notes=row.get("notes",""),
                )
                count += 1
        return count

    def get_review_parameters(self) -> List[str]:
        rows = self._conn.execute("SELECT DISTINCT parameter FROM review_data ORDER BY parameter").fetchall()
        return [r["parameter"] for r in rows]

    def get_review_species(self) -> List[str]:
        rows = self._conn.execute("SELECT DISTINCT species FROM review_data WHERE species!='' ORDER BY species").fetchall()
        return [r["species"] for r in rows]

    # ── EXTRACTED TABLES ──────────────────────────────────────────────────────
    def save_extracted_table(self, name: str, headers: list, rows: list,
                              source_file: str = "", page_num: int = 0) -> str:
        tid = _uid()
        self._conn.execute(
            "INSERT INTO extracted_tables(id,name,source_file,page_num,headers,rows) VALUES(?,?,?,?,?,?)",
            (tid, name, source_file, page_num, json.dumps(headers), json.dumps(rows))
        )
        self._conn.commit()
        return tid

    def get_extracted_tables(self) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM extracted_tables ORDER BY added_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["headers"] = json.loads(d["headers"])
            d["rows"]    = json.loads(d["rows"])
            result.append(d)
        return result

    def get_extracted_table(self, tid: str) -> Optional[Dict]:
        row = self._conn.execute(
            "SELECT * FROM extracted_tables WHERE id=?", (tid,)
        ).fetchone()
        if not row: return None
        d = dict(row)
        d["headers"] = json.loads(d["headers"])
        d["rows"]    = json.loads(d["rows"])
        return d

    def update_extracted_table(self, tid: str, name: str = None,
                                headers: list = None, rows: list = None):
        updates, vals = [], []
        if name    is not None: updates.append("name=?");    vals.append(name)
        if headers is not None: updates.append("headers=?"); vals.append(json.dumps(headers))
        if rows    is not None: updates.append("rows=?");    vals.append(json.dumps(rows))
        if not updates: return
        vals.append(tid)
        self._conn.execute(f"UPDATE extracted_tables SET {', '.join(updates)} WHERE id=?", vals)
        self._conn.commit()

    def delete_extracted_table(self, tid: str):
        self._conn.execute("DELETE FROM extracted_tables WHERE id=?", (tid,))
        self._conn.commit()

    # ── PARAM MAPPINGS ────────────────────────────────────────────────────────
    def get_param_mappings(self) -> Dict[str, str]:
        rows = self._conn.execute("SELECT * FROM param_mappings").fetchall()
        return {r["original"]: r["standard"] for r in rows}

    def set_param_mapping(self, original: str, standard: str):
        self._conn.execute("INSERT OR REPLACE INTO param_mappings(original,standard) VALUES(?,?)", (original, standard))
        self._conn.commit()

    def delete_param_mapping(self, original: str):
        self._conn.execute("DELETE FROM param_mappings WHERE original=?", (original,))
        self._conn.commit()

    def standardize(self, param: str) -> str:
        mappings = self.get_param_mappings()
        return mappings.get(param, param)

    # ── COMPILER VIEW ─────────────────────────────────────────────────────────
    def get_compiled(self, object_names: List[str]=None,
                     parameters: List[str]=None,
                     species_filter: str=None) -> List[Dict]:
        """Build the compiled summary table."""
        import pandas as pd
        import numpy as np

        cite_counts = self.get_citation_counts()
        review = self.get_review_data()
        mappings = self.get_param_mappings()

        all_objects = object_names or list({r["object_name"] for r in review} | set(cite_counts.keys()))
        all_params = parameters or list({mappings.get(r["parameter"], r["parameter"]) for r in review})

        results = []
        for obj in sorted(all_objects):
            row = {"object": obj, "articles_cited": cite_counts.get(obj, 0)}
            for par in sorted(all_params):
                vals = [
                    float(r["value"]) for r in review
                    if r["object_name"] == obj
                    and mappings.get(r["parameter"], r["parameter"]) == par
                    and (not species_filter or r["species"] == species_filter)
                    and r["value_num"] is not None
                ]
                if vals:
                    avg = sum(vals) / len(vals)
                    col = f"{par}" + (f"_{species_filter}" if species_filter else "")
                    row[col] = round(avg, 4) if len(vals) > 1 else vals[0]
                    row[f"{col}_n"] = len(vals)
            results.append(row)
        return results

    # ── EXPORT ────────────────────────────────────────────────────────────────
    def export_citations_csv(self, filepath: str):
        rows = self.get_citations()
        if not rows: return
        keys = ["object_name","article_title","year","journal","authors"]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    def export_review_csv(self, filepath: str):
        rows = self.get_review_data()
        if not rows: return
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    def export_compiled_csv(self, filepath: str, **kwargs):
        rows = self.get_compiled(**kwargs)
        if not rows: return
        cols = list(rows[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
