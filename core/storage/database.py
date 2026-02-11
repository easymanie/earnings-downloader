"""SQLite database setup and management."""

import os
import sqlite3


class Database:
    """SQLite database wrapper."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS company_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    quarter TEXT NOT NULL,
                    year TEXT NOT NULL,
                    metrics_json TEXT NOT NULL DEFAULT '[]',
                    commentary_json TEXT NOT NULL DEFAULT '[]',
                    themes_json TEXT NOT NULL DEFAULT '[]',
                    highlights_json TEXT NOT NULL DEFAULT '[]',
                    risks_json TEXT NOT NULL DEFAULT '[]',
                    guidance TEXT,
                    doc_types_analyzed TEXT NOT NULL DEFAULT '[]',
                    llm_provider TEXT NOT NULL DEFAULT '',
                    llm_model TEXT NOT NULL DEFAULT '',
                    source_files_json TEXT NOT NULL DEFAULT '[]',
                    analyzed_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(company, quarter, year)
                );

                CREATE TABLE IF NOT EXISTS quarter_comparisons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    current_quarter TEXT NOT NULL,
                    current_year TEXT NOT NULL,
                    previous_quarter TEXT NOT NULL,
                    previous_year TEXT NOT NULL,
                    comparison_type TEXT NOT NULL,
                    changes_json TEXT NOT NULL DEFAULT '[]',
                    new_themes_json TEXT NOT NULL DEFAULT '[]',
                    dropped_themes_json TEXT NOT NULL DEFAULT '[]',
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(company, current_quarter, current_year, comparison_type)
                );

                CREATE TABLE IF NOT EXISTS industry_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    industry TEXT NOT NULL,
                    quarter TEXT NOT NULL,
                    year TEXT NOT NULL,
                    companies_json TEXT NOT NULL DEFAULT '[]',
                    themes_json TEXT NOT NULL DEFAULT '[]',
                    divergences_json TEXT NOT NULL DEFAULT '[]',
                    headline TEXT NOT NULL DEFAULT '',
                    narrative TEXT NOT NULL DEFAULT '',
                    revenue_growth_range TEXT,
                    margin_trend TEXT,
                    analyzed_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(industry, quarter, year)
                );

                CREATE TABLE IF NOT EXISTS industry_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    industry TEXT NOT NULL,
                    company TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(industry, company)
                );

                CREATE INDEX IF NOT EXISTS idx_analyses_company
                    ON company_analyses(company);
                CREATE INDEX IF NOT EXISTS idx_analyses_quarter
                    ON company_analyses(quarter, year);
                CREATE INDEX IF NOT EXISTS idx_industry_map
                    ON industry_mappings(industry);
            """)
            conn.commit()
        finally:
            conn.close()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._get_conn()
        try:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor
        finally:
            conn.close()

    def fetchone(self, query: str, params: tuple = ()) -> dict | None:
        conn = self._get_conn()
        try:
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def fetchall(self, query: str, params: tuple = ()) -> list[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
