from __future__ import annotations

from typing import Annotated
from pathlib import Path
from typing import Any, Dict

import copy
import math
import json

import uvicorn
from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import AuthService, role_allows
from .config import REPORTS_DIR, load_settings
from .models import ADMETBatchRequest, ADMETBatchTaskRequest, Pipeline58Request
from .service import Pipeline58Service, smiles_descriptors


SETTINGS = load_settings()
SERVICE = Pipeline58Service(SETTINGS)
AUTH = AuthService()
app = FastAPI(title="Pipeline58 Local MVP", version=SETTINGS.service_version)
KETCHER_STATIC_DIR = Path(__file__).resolve().parent / "static" / "ketcher"
if KETCHER_STATIC_DIR.exists():
    app.mount("/ketcher", StaticFiles(directory=str(KETCHER_STATIC_DIR), html=True), name="ketcher")


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pipeline58 Dashboard</title>
  <style>
    :root {
      --bg: #f2efe8;
      --panel: rgba(255,255,255,0.8);
      --ink: #1e2a2f;
      --muted: #62747a;
      --line: rgba(30,42,47,0.12);
      --good: #1e7f5c;
      --warn: #c7851a;
      --bad: #b13b2e;
      --accent: #204d63;
      --shadow: 0 18px 50px rgba(27, 43, 51, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Aptos", "Segoe UI Variable", "Noto Sans SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(32,77,99,0.18), transparent 28%),
        radial-gradient(circle at bottom right, rgba(177,59,46,0.10), transparent 24%),
        linear-gradient(180deg, #f7f3ec 0%, var(--bg) 100%);
      min-height: 100vh;
    }
    body.auth-locked {
      overflow: hidden;
    }
    .shell {
      max-width: 1380px;
      margin: 0 auto;
      padding: 28px 20px 44px;
    }
    .auth-screen {
      position: fixed;
      inset: 0;
      z-index: 80;
      background: rgba(25, 33, 40, 0.58);
      backdrop-filter: blur(14px);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .auth-screen.open {
      display: flex;
    }
    .auth-card {
      width: min(480px, 100%);
      padding: 30px;
      border-radius: 28px;
      background: rgba(255,255,255,0.9);
      border: 1px solid rgba(255,255,255,0.55);
      box-shadow: 0 24px 60px rgba(24, 39, 48, 0.2);
    }
    .auth-card h2 {
      margin: 0 0 10px;
      font-size: 34px;
      line-height: 1.05;
      letter-spacing: -0.03em;
    }
    .auth-copy {
      color: var(--muted);
      line-height: 1.65;
      margin-bottom: 18px;
    }
    .auth-error {
      min-height: 20px;
      color: var(--bad);
      font-size: 13px;
      margin-top: 8px;
    }
    .user-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
      display: grid;
      gap: 4px;
    }
    .user-name {
      font-size: 18px;
      font-weight: 700;
    }
    .user-meta {
      color: var(--muted);
      font-size: 13px;
    }
    .hero {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 18px;
      margin-bottom: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }
    .hero-main {
      padding: 28px;
      min-height: 180px;
      position: relative;
      overflow: hidden;
    }
    .hero-main::after {
      content: "";
      position: absolute;
      width: 220px;
      height: 220px;
      right: -50px;
      top: -60px;
      border-radius: 50%;
      background: linear-gradient(135deg, rgba(32,77,99,0.18), rgba(177,59,46,0.12));
    }
    h1 {
      margin: 0 0 8px;
      font-size: clamp(30px, 4vw, 48px);
      line-height: 1;
      letter-spacing: -0.03em;
    }
    .sub {
      font-size: 16px;
      line-height: 1.6;
      color: var(--muted);
      max-width: 720px;
      margin-bottom: 18px;
    }
    .hero-meta {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }
    .hero-runtime {
      position: relative;
      z-index: 1;
      margin-top: 18px;
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 12px;
    }
    .hero-runtime-card {
      border: 1px solid var(--line);
      border-radius: 22px;
      background: rgba(255,255,255,0.74);
      padding: 16px;
      min-height: 136px;
    }
    .hero-runtime-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-top: 10px;
    }
    .runtime-chip {
      border: 1px solid rgba(32,77,99,0.12);
      border-radius: 18px;
      background: rgba(247,251,252,0.96);
      padding: 12px 14px;
      display: grid;
      gap: 4px;
    }
    .runtime-chip strong {
      font-size: 15px;
    }
    .runtime-meta {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
      font-size: 13px;
    }
    .hero-side {
      padding: 24px;
      display: grid;
      gap: 12px;
    }
    .hero-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 4px;
    }
    .custom-baseline-tools {
      display: grid;
      gap: 10px;
      width: 100%;
      margin-top: 2px;
    }
    .baseline-create-panel {
      display: none;
      grid-template-columns: minmax(220px, 420px) auto auto;
      gap: 10px;
      align-items: center;
      width: 100%;
    }
    .baseline-create-panel.open {
      display: grid;
    }
    .baseline-create-panel input {
      height: 48px;
      padding: 0 14px;
    }
    .baseline-new-btn {
      border-color: rgba(30,127,92,0.28);
      color: var(--good);
      background: rgba(236,248,241,0.82);
    }
    .baseline-cancel-btn {
      color: var(--muted);
    }
    .custom-baseline-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      width: 100%;
    }
    .custom-baseline-row:empty {
      display: none;
    }
    .custom-baseline-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid rgba(32,77,99,0.16);
      border-radius: 14px;
      background: rgba(255,255,255,0.72);
      padding: 0 8px 0 0;
      overflow: hidden;
    }
    .custom-baseline-pill.active {
      border-color: rgba(30,127,92,0.46);
      background: rgba(236,248,241,0.88);
      box-shadow: inset 0 0 0 1px rgba(30,127,92,0.18);
    }
    .custom-baseline-pill.pending {
      border-style: dashed;
    }
    .custom-baseline-pill .ghost-btn {
      border: 0;
      background: transparent;
      border-radius: 0;
    }
    .baseline-delete-btn {
      border: 0;
      width: 28px;
      height: 28px;
      border-radius: 999px;
      padding: 0;
      background: rgba(177,59,46,0.10);
      color: var(--bad);
      font-weight: 800;
      line-height: 1;
    }
    @media (max-width: 680px) {
      .baseline-create-panel {
        grid-template-columns: 1fr;
      }
    }
    .ghost-btn {
      border: 1px solid rgba(32,77,99,0.16);
      background: rgba(255,255,255,0.72);
      color: var(--accent);
      padding: 12px 14px;
      border-radius: 14px;
      font-weight: 700;
      cursor: pointer;
    }
    .engine-ready {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
    }
    .engine-ready::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #24a06b;
      box-shadow: 0 0 0 4px rgba(36,160,107,0.12);
    }
    .stat-label {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .stat-value {
      font-size: 28px;
      font-weight: 700;
    }
    .layout {
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
    }
    .card {
      padding: 22px;
    }
    .card h2 {
      margin: 0 0 14px;
      font-size: 18px;
      letter-spacing: -0.02em;
    }
    form {
      display: grid;
      gap: 12px;
    }
    .row-2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .row-3 {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    label {
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    .field {
      display: grid;
      gap: 8px;
    }
    .field-title {
      display: grid;
      gap: 1px;
      line-height: 1.15;
    }
    .field-zh {
      font-size: 14px;
      font-weight: 700;
      color: var(--ink);
    }
    .field-en {
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    input, select, textarea, button {
      font: inherit;
    }
    input:not([type="checkbox"]), select, textarea {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.82);
      padding: 12px 14px;
      color: var(--ink);
    }
    textarea {
      min-height: 88px;
      resize: vertical;
    }
    button {
      border: 0;
      border-radius: 16px;
      padding: 14px 18px;
      background: linear-gradient(135deg, #204d63, #2d6d7f);
      color: white;
      cursor: pointer;
      font-weight: 700;
    }
    button:disabled {
      opacity: 0.6;
      cursor: wait;
    }
    .grid-cards {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
      margin-bottom: 12px;
    }
    .mini {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
    }
    .mini strong {
      display: block;
      font-size: 22px;
      margin-top: 6px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 84px;
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 13px;
      font-weight: 700;
      color: white;
    }
    .risk-green { background: var(--good); }
    .risk-yellow { background: var(--warn); }
    .risk-red { background: var(--bad); }
    .result-block {
      border-top: 1px solid var(--line);
      padding-top: 14px;
      margin-top: 14px;
    }
    .result-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-top: 12px;
    }
    .mono {
      font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
    }
    .checkbox-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    .toggle-card {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 12px;
      align-items: start;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
      cursor: pointer;
      transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
      position: relative;
    }
    .toggle-card:hover {
      transform: translateY(-1px);
      box-shadow: 0 8px 18px rgba(32,77,99,0.08);
    }
    .toggle-card.active {
      border-color: rgba(32,77,99,0.38);
      background: linear-gradient(180deg, rgba(32,77,99,0.12), rgba(255,255,255,0.94));
      box-shadow: 0 12px 26px rgba(32,77,99,0.12);
    }
    .toggle-card.active::after {
      content: "已启用";
      position: absolute;
      top: 12px;
      right: 12px;
      padding: 4px 8px;
      border-radius: 999px;
      background: rgba(32,77,99,0.16);
      color: var(--accent);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .toggle-card input[type="checkbox"] {
      margin: 2px 0 0;
      width: 18px;
      height: 18px;
      accent-color: #204d63;
    }
    .toggle-card.active input[type="checkbox"] {
      transform: scale(1.05);
    }
    .toggle-copy {
      display: grid;
      gap: 2px;
      line-height: 1.15;
    }
    .toggle-copy .field-zh {
      font-size: 15px;
    }
    .toggle-note {
      font-size: 11px;
      color: var(--muted);
    }
    .toggle-card.active .toggle-note {
      color: #355764;
    }
    .runs {
      display: grid;
      gap: 10px;
      max-height: 560px;
      overflow: auto;
      padding-right: 4px;
    }
    .run-item {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.72);
      cursor: pointer;
      transition: transform 0.16s ease, box-shadow 0.16s ease;
    }
    .run-item:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 20px rgba(32,77,99,0.08);
    }
    .run-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      margin-bottom: 8px;
    }
    @media (max-width: 980px) {
      .layout, .hero {
        grid-template-columns: 1fr;
      }
      .row-3, .checkbox-grid, .result-grid, .metric-strip, .chart-grid, .batch-grid {
        grid-template-columns: 1fr;
      }
      .engine-run-row {
        grid-template-columns: 1fr;
      }
      .grid-cards {
        grid-template-columns: 1fr;
      }
      .section-headline {
        display: grid;
      }
    }
    .detail-pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: rgba(19,32,38,0.94);
      color: #d9edf2;
      border-radius: 18px;
      padding: 16px;
      min-height: 220px;
      max-height: 460px;
      overflow: auto;
    }
    .chart-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-top: 12px;
    }
    .analysis-board {
      display: grid;
      gap: 14px;
    }
    .analysis-section {
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.84), rgba(245,250,250,0.72));
      box-shadow: 0 14px 36px rgba(27, 43, 51, 0.06);
    }
    .section-headline {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      margin-bottom: 14px;
    }
    .section-headline h3 {
      margin: 2px 0 4px;
      font-size: 22px;
      letter-spacing: -0.03em;
    }
    .section-headline p {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
      font-size: 13px;
      max-width: 680px;
    }
    .section-kicker {
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.14em;
    }
    .engine-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid rgba(32,77,99,0.18);
      background: rgba(32,77,99,0.08);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }
    .metric-strip {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 14px;
    }
    .metric-pill {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.82);
    }
    .metric-name {
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .metric-value {
      margin-top: 6px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: -0.03em;
      color: var(--ink);
    }
    .metric-note {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    .form-status {
      margin-top: 8px;
      min-height: 20px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .form-status.error {
      color: var(--bad);
      font-weight: 700;
    }
    .form-status.ok {
      color: var(--good);
      font-weight: 700;
    }
    .engine-run-row {
      display: grid;
      grid-template-columns: minmax(0, 2fr) minmax(220px, 0.8fr);
      gap: 12px;
      align-items: stretch;
    }
    .secondary-run-btn {
      background: rgba(255,255,255,0.9);
      border: 1px solid rgba(32,77,99,0.18);
      color: var(--accent);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.55);
    }
    .secondary-run-btn:hover, .action-chip.engine-run:hover {
      border-color: rgba(32,77,99,0.34);
      background: rgba(240,247,247,0.95);
    }
    .pksim-vm-card {
      margin-top: 12px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(239,247,244,0.9));
    }
    .pksim-vm-card .metric-strip {
      margin-bottom: 0;
    }
    .pksim-workbench {
      margin-top: 18px;
      display: grid;
      gap: 18px;
    }
    .pksim-workbench .section-headline {
      margin-bottom: 0;
    }
    .chart-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,0.86);
      position: relative;
    }
    .chart-stage {
      background:
        radial-gradient(circle at top right, rgba(32,77,99,0.08), transparent 22%),
        linear-gradient(180deg, rgba(255,255,255,0.92), rgba(240,247,247,0.9));
    }
    .chart-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .chart-title-main {
      font-size: 16px;
      font-weight: 700;
      color: var(--ink);
    }
    .chart-title-sub {
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .chart-tooltip {
      position: fixed;
      z-index: 90;
      min-width: 180px;
      max-width: 260px;
      border-radius: 14px;
      background: rgba(18, 29, 36, 0.94);
      color: #e9f4f7;
      box-shadow: 0 16px 40px rgba(17, 28, 34, 0.28);
      border: 1px solid rgba(255,255,255,0.08);
      padding: 10px 12px;
      pointer-events: none;
      opacity: 0;
      transform: translateY(6px);
      transition: opacity 0.12s ease, transform 0.12s ease;
    }
    .chart-tooltip.open {
      opacity: 1;
      transform: translateY(0);
    }
    .tooltip-title {
      font-size: 12px;
      color: #9dc0cb;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .tooltip-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 4px;
      font-size: 13px;
      line-height: 1.4;
    }
    .tooltip-swatch {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      flex: 0 0 9px;
    }
    .chart-svg {
      width: 100%;
      height: 220px;
      display: block;
      border-radius: 14px;
      background: linear-gradient(180deg, rgba(248,252,252,0.95), rgba(233,242,243,0.85));
      border: 1px solid rgba(32,77,99,0.08);
    }
    .chart-lg {
      height: 300px;
    }
    .chart-notes {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    .note-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,0.8);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .chart-title {
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 10px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .lit-list {
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }
    .lit-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
      background: rgba(255,255,255,0.72);
    }
    .lit-item a {
      color: var(--accent);
      text-decoration: none;
    }
    .bullet-list {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }
    .bullet-item {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px 14px;
      background: rgba(255,255,255,0.82);
      line-height: 1.6;
      color: var(--ink);
    }
    .legend-list {
      display: grid;
      gap: 10px;
    }
    .legend-row {
      display: grid;
      grid-template-columns: auto 1fr auto auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
      background: rgba(255,255,255,0.82);
    }
    .legend-swatch {
      width: 12px;
      height: 12px;
      border-radius: 999px;
      display: inline-block;
    }
    .legend-main {
      font-size: 13px;
      color: var(--ink);
      font-weight: 600;
    }
    .legend-meta {
      font-size: 12px;
      color: var(--muted);
    }
    .action-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
      margin-bottom: 6px;
    }
    .action-chip {
      border: 1px solid rgba(32,77,99,0.16);
      background: rgba(255,255,255,0.86);
      color: var(--accent);
      padding: 10px 12px;
      border-radius: 12px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
    }
    .action-chip[aria-disabled="true"] {
      opacity: 0.45;
      pointer-events: none;
    }
    button.action-chip:disabled {
      opacity: 0.45;
      pointer-events: none;
    }
    .action-chip.engine-run {
      background: rgba(36,160,107,0.1);
      border-color: rgba(36,160,107,0.28);
      color: #16734f;
    }
    .workbench-grid {
      display: grid;
      grid-template-columns: 0.92fr 1.08fr;
      gap: 18px;
      align-items: start;
    }
    .form-section {
      border-top: 1px solid var(--line);
      padding-top: 14px;
      margin-top: 4px;
    }
    .section-label {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-bottom: 12px;
    }
    .section-title {
      margin: 0 0 6px;
      font-size: 20px;
      letter-spacing: -0.03em;
    }
    .section-copy {
      margin: 0 0 12px;
      color: var(--muted);
      line-height: 1.6;
      font-size: 13px;
    }
    .textarea-lg {
      min-height: 120px;
    }
    .fit-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-top: 12px;
    }
    .drawer-overlay {
      position: fixed;
      inset: 0;
      background: rgba(16, 25, 30, 0.28);
      backdrop-filter: blur(4px);
      display: none;
      z-index: 20;
    }
    .drawer-overlay.open {
      display: block;
    }
    .history-drawer {
      position: fixed;
      top: 0;
      right: 0;
      width: min(640px, 100vw);
      height: 100vh;
      background: rgba(248, 248, 245, 0.96);
      border-left: 1px solid rgba(30,42,47,0.12);
      box-shadow: -16px 0 48px rgba(20, 34, 40, 0.18);
      padding: 24px 20px;
      transform: translateX(102%);
      transition: transform 0.22s ease;
      overflow: auto;
      z-index: 21;
    }
    .history-drawer.open {
      transform: translateX(0);
    }
    .drawer-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
      margin-bottom: 14px;
    }
    .drawer-close {
      border: 0;
      border-radius: 999px;
      width: 36px;
      height: 36px;
      background: rgba(32,77,99,0.1);
      color: var(--accent);
      font-weight: 700;
      cursor: pointer;
    }
    .drawer-list {
      display: grid;
      gap: 10px;
    }
    .drawer-item {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      background: rgba(255,255,255,0.82);
    }
    .drawer-item-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      margin-bottom: 8px;
    }
    .drawer-item-title {
      font-size: 16px;
      font-weight: 700;
      color: var(--ink);
    }
    .drawer-item-meta {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
    }
    .batch-shell {
      margin-top: 18px;
      display: none; /* moved to /admet */
      gap: 18px;
    }
    .batch-grid {
      display: grid;
      grid-template-columns: 0.95fr 1.05fr;
      gap: 18px;
    }
    .batch-textarea {
      min-height: 220px;
      font-family: "Consolas", "SFMono-Regular", monospace;
      font-size: 13px;
      line-height: 1.6;
      resize: vertical;
    }
    .batch-status {
      min-height: 20px;
      font-size: 13px;
      color: var(--muted);
      margin-top: 10px;
    }
    .batch-status.error { color: var(--bad); }
    .batch-status.ok { color: var(--good); }
    .task-list {
      display: grid;
      gap: 12px;
      max-height: 420px;
      overflow: auto;
      padding-right: 4px;
    }
    .task-item {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.72);
      padding: 14px;
      cursor: pointer;
      transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
    }
    .task-item:hover,
    .task-item.active {
      transform: translateY(-1px);
      border-color: rgba(32,77,99,0.22);
      box-shadow: 0 12px 24px rgba(17,28,34,0.08);
    }
    .task-item-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
    }
    .task-progress {
      height: 8px;
      border-radius: 999px;
      background: rgba(30,42,47,0.08);
      overflow: hidden;
      margin-top: 10px;
    }
    .task-progress span {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, #204d63, #2a7c90);
    }
    .batch-table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: rgba(255,255,255,0.7);
    }
    .batch-table {
      width: 100%;
      border-collapse: collapse;
      min-width: 920px;
      font-size: 13px;
    }
    .batch-table th,
    .batch-table td {
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid rgba(30,42,47,0.08);
      vertical-align: top;
    }
    .batch-table th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
      background: rgba(246,249,250,0.96);
      position: sticky;
      top: 0;
      z-index: 1;
    }
    .inline-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }
    body.loading {
      overflow: hidden;
    }
    .run-overlay {
      position: fixed;
      inset: 0;
      background: rgba(16, 24, 30, 0.48);
      backdrop-filter: blur(10px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 40;
    }
    .run-overlay.open {
      display: flex;
    }
    .run-dialog {
      width: min(520px, calc(100vw - 32px));
      border-radius: 28px;
      border: 1px solid rgba(255,255,255,0.18);
      background: linear-gradient(180deg, rgba(248,250,250,0.95), rgba(236,243,244,0.92));
      box-shadow: 0 28px 80px rgba(8, 16, 20, 0.28);
      padding: 28px 26px;
    }
    .run-kicker {
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      margin-bottom: 10px;
    }
    .run-title {
      font-size: 28px;
      line-height: 1.1;
      letter-spacing: -0.04em;
      margin: 0 0 8px;
      color: var(--ink);
    }
    .run-copy {
      margin: 0;
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }
    .run-status {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 18px;
      align-items: center;
      margin: 20px 0 18px;
    }
    .run-spinner {
      width: 68px;
      height: 68px;
      border-radius: 50%;
      border: 5px solid rgba(32,77,99,0.14);
      border-top-color: #204d63;
      border-right-color: #2d6d7f;
      animation: runSpin 0.9s linear infinite;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.5);
    }
    .run-stage-title {
      font-size: 18px;
      font-weight: 700;
      color: var(--ink);
      margin-bottom: 4px;
    }
    .run-stage-copy {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    .run-steps {
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }
    .run-step {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border-radius: 16px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(30,42,47,0.08);
      color: var(--muted);
    }
    .run-step-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: rgba(30,42,47,0.18);
    }
    .run-step.active {
      border-color: rgba(32,77,99,0.22);
      color: var(--ink);
      background: rgba(255,255,255,0.92);
    }
    .run-step.active .run-step-dot {
      background: #204d63;
      box-shadow: 0 0 0 6px rgba(32,77,99,0.10);
    }
    .run-step.done .run-step-dot {
      background: #1e7f5c;
    }
    @keyframes runSpin {
      to { transform: rotate(360deg); }
    }
    @media (max-width: 980px) {
      .hero, .layout, .row-2, .row-3, .grid-cards, .result-grid, .chart-grid, .workbench-grid, .fit-grid, .hero-runtime, .hero-runtime-grid {
        grid-template-columns: 1fr;
      }
      .shell {
        padding: 16px 14px 28px;
      }
      .hero-main, .hero-side, .card {
        padding: 18px;
      }
    }

.ketcher-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}.ketcher-modal{position:fixed;inset:0;z-index:999;background:rgba(20,28,34,.62);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;padding:24px}.ketcher-modal.show{display:flex}.ketcher-panel{width:min(1120px,96vw);height:min(760px,92vh);background:#fff;border-radius:22px;box-shadow:0 24px 80px rgba(0,0,0,.28);display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}.ketcher-head,.ketcher-foot{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line,rgba(30,42,47,.13))}.ketcher-foot{border-top:1px solid var(--line,rgba(30,42,47,.13));border-bottom:0}.ketcher-head h3{margin:0;font-size:18px}.ketcher-frame{width:100%;height:100%;border:0}.ketcher-close{background:rgba(255,255,255,.86)!important;color:var(--accent,#204d63)!important;border:1px solid var(--line,rgba(30,42,47,.13))!important}.ketcher-apply{min-width:180px}.ketcher-status{color:var(--muted,#62747a);font-size:12px;line-height:1.4}@media(max-width:700px){.ketcher-panel{height:94vh}.ketcher-foot{display:grid}.ketcher-apply{width:100%}}

</style>
</head>
<body>
  <div class="auth-screen open" id="auth-screen">
    <div class="auth-card">
      <div class="stat-label">Pipeline58 Secure Access</div>
      <h2>登录工作台</h2>
      <div class="auth-copy">系统已经切到登录保护模式。先完成账号认证，再进入 ADMET、PBPK、PK/PD 与 DDI 工作台。</div>
      <form id="login-form" novalidate method="post" action="/auth/web-login">
        <label>
          <span class="field-title"><span class="field-zh">用户名</span><span class="field-en">Username</span></span>
          <input type="text" name="username" autocomplete="username" required>
        </label>
        <label>
          <span class="field-title"><span class="field-zh">密码</span><span class="field-en">Password</span></span>
          <input type="password" name="password" autocomplete="current-password" required>
        </label>
        <button id="login-btn" type="submit">登录系统</button>
        <div class="auth-error" id="auth-error"></div>
      </form>
    </div>
  </div>
  <div class="shell">
    <section class="hero">
      <div class="panel hero-main">
        <div class="stat-label">Pipeline58 Local</div>
        <h1>hanmi人体内外预测DEMO版</h1>
        <div class="sub">这页是给人直接用的。输入化合物和基本给药条件，系统会顺序跑 STEP 5 到 STEP 8，并把 ADMET、PBPK、PK/PD 和 DDI 风险汇总出来。</div>
        <div class="hero-meta">
          <div class="pill">ADMET: <strong id="hero-admet">-</strong></div>
          <div class="pill">PBPK: <strong id="hero-pbpk">-</strong></div>
          <div class="pill">PK/PD: <strong id="hero-pkpd">-</strong></div>
        </div>
        <div class="hero-runtime">
          <div class="hero-runtime-card">
            <div class="section-label">Runtime</div>
            <div class="chart-title-main">算力与运行后端</div>
            <div class="runtime-meta">这里显示 ADMET 当前实际设备、批量筛选并行策略，以及 GPU0 / GPU1 的在线状态。</div>
            <div class="hero-runtime-grid" id="runtime-gpu-grid">
              <div class="runtime-chip">
                <div class="stat-label">ADMET Device</div>
                <strong id="runtime-admet-device">加载中</strong>
                <div class="runtime-meta" id="runtime-admet-batch">正在获取批量筛选状态</div>
              </div>
              <div class="runtime-chip">
                <div class="stat-label">Batch Screening</div>
                <strong id="runtime-batch-mode">-</strong>
                <div class="runtime-meta" id="runtime-batch-detail">等待运行态信息</div>
              </div>
            </div>
          </div>
          <div class="hero-runtime-card">
            <div class="section-label">GPUs</div>
            <div class="chart-title-main">Tesla T4 状态</div>
            <div class="runtime-meta">显卡就绪后，批量 ADMET 会按 GPU0 / GPU1 并行拆分任务。</div>
            <div class="hero-runtime-grid" id="runtime-gpu-cards">
              <div class="runtime-chip">
                <div class="stat-label">GPU</div>
                <strong>检测中</strong>
                <div class="runtime-meta">正在获取显卡运行态</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="panel hero-side">
        <div>
        <div class="stat-label">服务状态</div>
          <div class="stat-value" id="svc-status">加载中</div>
        </div>
        <div>
          <div class="stat-label">已保存分析次数</div>
          <div class="stat-value" id="svc-runs">0</div>
        </div>
        <div>
          <div class="stat-label">接口入口</div>
          <div class="mono">/docs | /api/v1/pipeline58</div>
        </div>
        <div class="user-card">
          <div class="stat-label">当前账号</div>
          <div class="user-name" id="auth-user-name">未登录</div>
          <div class="user-meta" id="auth-user-meta">请先登录后再运行分析。</div>
        </div>
        <div class="hero-actions">
          <button class="ghost-btn" id="open-history-btn" type="button">查看历史记录</button>
          <button class="ghost-btn" id="open-projects-btn" type="button">查看项目</button>
          <button class="ghost-btn" id="open-audit-btn" type="button">查看审计</button>
          <span class="ghost-btn engine-ready" title="mrgsolve whole-body PBPK is built into STEP 6">全身 PBPK Engine</span>
          <a class="ghost-btn" href="/admet" target="_blank" rel="noreferrer">ADMET Deep-Dive</a>
          <a class="ghost-btn" href="/admin/users" target="_blank" rel="noreferrer">User Admin</a>
          <a class="ghost-btn" id="logout-btn" href="/logout">退出登录</a>
        </div>
      </div>
    </section>

    <section class="layout">
      <div class="panel card">
        <h2>发起分析</h2>
        <p class="section-copy">主页只保留分析工作台。项目治理、观测数据、虚拟人群分级和联用药场景都在这里完成。</p>
        <form id="analyze-form" novalidate onsubmit="return false;">
          <div class="hero-actions" style="margin-bottom:6px;">
            <button class="ghost-btn" id="load-midazolam-baseline-btn" type="button">Midazolam 基线</button>
            <button class="ghost-btn" id="load-warfarin-baseline-btn" type="button">Warfarin 基线</button>
            <button class="ghost-btn" id="load-caffeine-baseline-btn" type="button">Caffeine 基线</button>
            <button class="ghost-btn baseline-new-btn" id="new-baseline-btn" type="button">+ 新建基线</button>
            <div class="custom-baseline-tools">
              <div class="baseline-create-panel" id="baseline-create-panel">
                <input id="new-baseline-name" type="text" placeholder="输入基线名称，例如 1号测试基线">
                <button class="ghost-btn baseline-new-btn" id="confirm-baseline-btn" type="button">确认新建</button>
                <button class="ghost-btn baseline-cancel-btn" id="cancel-baseline-btn" type="button">取消</button>
              </div>
              <div class="custom-baseline-row" id="custom-baseline-row"></div>
            </div>
          </div>
          <div class="form-section">
            <div class="section-label">Project</div>
            <div class="row-2">
              <label class="field"><span class="field-title"><span class="field-zh">项目名称</span><span class="field-en">Project name</span></span>
                <input name="project_name" value="Pipeline58 最小闭环">
              </label>
              <label class="field"><span class="field-title"><span class="field-zh">项目编号</span><span class="field-en">Project code</span></span>
                <input name="project_code" value="P58-MVP">
              </label>
            </div>
            <div class="row-3">
              <label class="field"><span class="field-title"><span class="field-zh">负责人</span><span class="field-en">Owner</span></span>
                <input name="owner" value="analyst">
              </label>
              <label class="field"><span class="field-title"><span class="field-zh">访问级别</span><span class="field-en">Access level</span></span>
                <select name="access_level">
                  <option value="internal" selected>内部</option>
                  <option value="restricted">受限</option>
                </select>
              </label>
              <label class="field"><span class="field-title"><span class="field-zh">标签</span><span class="field-en">Tags</span></span>
                <input name="project_tags" value="admet,pbpk,pkpd">
              </label>
            </div>
          </div>

          <div class="form-section">
            <div class="section-label">Program</div>
          <div class="row-2">
            <label class="field"><span class="field-title"><span class="field-zh">化合物名称</span><span class="field-en">Compound name</span></span>
              <input name="compound_name" value="Midazolam-like candidate" required>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">靶点</span><span class="field-en">Target</span></span>
              <input name="target_name" value="CYP3A4">
            </label>
          </div>
          <label class="field"><span class="field-title"><span class="field-zh">SMILES</span><span class="field-en">Structure string</span></span>
            <textarea name="smiles" required>CN1C=NC2=C1N=CN2C</textarea>
          </label>
          <div class="ketcher-tools"><button class="ghost-btn" type="button" data-ketcher-field="smiles">Ketcher 结构绘制</button><span class="helper-text">画完后将结构回填到 SMILES输入框。</span></div>
          <div class="row-3">
            <label class="field"><span class="field-title"><span class="field-zh">适应症</span><span class="field-en">Indication</span></span>
              <input name="indication" value="镇静">
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">作用机制</span><span class="field-en">Mechanism</span></span>
              <select name="mechanism">
                <option value="inhibition" selected>抑制</option>
                <option value="activation">激活</option>
              </select>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">给药途径</span><span class="field-en">Route</span></span>
              <select name="route">
                <option value="po" selected>口服</option>
                <option value="iv">静脉</option>
              </select>
            </label>
          </div>
          <div class="row-3">
            <label class="field"><span class="field-title"><span class="field-zh">剂量</span><span class="field-en">Dose (mg)</span></span>
              <input type="number" name="dose_mg" step="0.1" value="7.5">
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">给药间隔</span><span class="field-en">Interval (h)</span></span>
              <input type="number" name="interval_hours" step="1" value="24">
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">重复天数</span><span class="field-en">Repeat days</span></span>
              <input type="number" name="repeat_days" step="1" value="3">
            </label>
          </div>
          <div class="row-3">
            <label class="field"><span class="field-title"><span class="field-zh">体重</span><span class="field-en">Weight (kg)</span></span>
              <input type="number" name="weight_kg" step="0.1" value="70">
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">年龄</span><span class="field-en">Age</span></span>
              <input type="number" name="age_years" step="1" value="40">
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">效力</span><span class="field-en">Potency (uM)</span></span>
              <input type="number" name="potency_uM" step="0.01" value="0.8">
            </label>
          </div>
          <div class="row-3">
            <label class="field"><span class="field-title"><span class="field-zh">人群预设</span><span class="field-en">Population preset</span></span>
              <select name="preset">
                <option value="adult" selected>成人</option>
                <option value="infant">婴儿</option>
                <option value="child">儿童</option>
                <option value="adolescent">青少年</option>
                <option value="elderly">老年</option>
                <option value="east_asian_adult">东亚成人</option>
                <option value="european_adult">欧洲成人</option>
                <option value="pregnant_adult">妊娠成人</option>
                <option value="renal_ckd">慢性肾病</option>
                <option value="hepatic_cirrhosis">肝硬化</option>
              </select>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">人群来源</span><span class="field-en">Ethnicity</span></span>
              <select name="ethnicity">
                <option value="general" selected>通用</option>
                <option value="east_asian">东亚</option>
                <option value="european">欧洲</option>
                <option value="african_ancestry">非洲祖源</option>
                <option value="latino">拉美</option>
              </select>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">性别</span><span class="field-en">Sex</span></span>
              <select name="sex">
                <option value="unknown" selected>未知</option>
                <option value="male">男</option>
                <option value="female">女</option>
              </select>
            </label>
          </div>
          <div class="checkbox-grid">
            <label class="toggle-card">
              <input type="checkbox" name="renal_impairment">
              <span class="toggle-copy">
                <span class="field-zh">肾损伤</span>
                <span class="field-en">Renal impairment</span>
                <span class="toggle-note">用于降低肾功能相关清除能力。</span>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" name="hepatic_impairment">
              <span class="toggle-copy">
                <span class="field-zh">肝损伤</span>
                <span class="field-en">Hepatic impairment</span>
                <span class="toggle-note">用于降低肝代谢相关清除能力。</span>
              </span>
            </label>
            <label class="toggle-card">
              <input type="checkbox" name="pregnant">
              <span class="toggle-copy">
                <span class="field-zh">妊娠</span>
                <span class="field-en">Pregnant</span>
                <span class="toggle-note">用于调整分布容积和妊娠状态参数。</span>
              </span>
            </label>
          </div>
          <div class="row-3">
            <label class="field"><span class="field-title"><span class="field-zh">肾损伤分级</span><span class="field-en">Renal stage</span></span>
              <select name="renal_stage">
                <option value="normal" selected>正常</option>
                <option value="mild">轻度</option>
                <option value="moderate">中度</option>
                <option value="severe">重度</option>
              </select>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">肝损伤分级</span><span class="field-en">Hepatic stage</span></span>
              <select name="hepatic_stage">
                <option value="normal" selected>正常</option>
                <option value="child_pugh_a">Child-Pugh A</option>
                <option value="child_pugh_b">Child-Pugh B</option>
                <option value="child_pugh_c">Child-Pugh C</option>
              </select>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">妊娠分期</span><span class="field-en">Trimester</span></span>
              <select name="pregnancy_trimester">
                <option value="none" selected>无</option>
                <option value="t1">孕早期</option>
                <option value="t2">孕中期</option>
                <option value="t3">孕晚期</option>
              </select>
            </label>
          </div>
          </div>

          <div class="form-section">
            <div class="section-label">Validation</div>
            <div class="row-3">
              <label class="toggle-card">
                <input type="checkbox" name="enable_pk_fit">
                <span class="toggle-copy">
                  <span class="field-zh">启用 PK 拟合</span>
                  <span class="field-en">PK fit</span>
                  <span class="toggle-note">根据观测浓度自动搜索 CL / V / Ka。</span>
                </span>
              </label>
              <label class="toggle-card">
                <input type="checkbox" name="enable_pd_fit">
                <span class="toggle-copy">
                  <span class="field-zh">启用 PD 拟合</span>
                  <span class="field-en">PD fit</span>
                  <span class="toggle-note">根据观测效应自动搜索 EC50 / Hill。</span>
                </span>
              </label>
              <label class="field"><span class="field-title"><span class="field-zh">拟合精度</span><span class="field-en">Fit profile</span></span>
                <select name="fit_profile">
                  <option value="quick" selected>快速</option>
                  <option value="standard">标准</option>
                  <option value="deep">深度</option>
                </select>
              </label>
            </div>
            <label class="field"><span class="field-title"><span class="field-zh">观测数据 CSV</span><span class="field-en">Observed data</span></span>
              <textarea class="textarea-lg" name="observations_text" placeholder="time_h,conc_ng_ml,effect_pct&#10;1,39.1,22.6&#10;2,37.3,21.7&#10;4,18.5,10.1"></textarea>
            </label>
          </div>

          <div class="form-section">
            <div class="section-label">DDI</div>
            <label class="field"><span class="field-title"><span class="field-zh">联用药场景 CSV</span><span class="field-en">Concomitant drugs</span></span>
              <textarea class="textarea-lg" name="concomitant_text" placeholder="name,role,mechanism,enzyme,strength,dose_note&#10;ketoconazole,perpetrator,inhibitor,CYP3A4,strong,400 mg qd&#10;rifampicin,co-medication,inducer,CYP3A4,strong,600 mg qd"></textarea>
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">补充备注</span><span class="field-en">DDI notes</span></span>
              <textarea name="ddi_notes_text" placeholder="每行一条备注，例如：避免与强 CYP3A4 抑制剂联用。"></textarea>
            </label>
          </div>
          <button id="submit-btn" type="button">&#36816;&#34892; STEP 5-8</button>
          <div class="form-status" id="form-status">等待运行。</div>
        </form>

        <div class="result-block analysis-board">
          <div class="grid-cards">
            <div class="mini">
              <div class="stat-label">综合风险</div>
              <strong id="risk-badge-wrap"><span class="badge risk-yellow">待运行</span></strong>
            </div>
            <div class="mini">
              <div class="stat-label">推荐给药</div>
              <strong id="result-regimen">-</strong>
            </div>
            <div class="mini">
              <div class="stat-label">ADMET 分数</div>
              <strong id="result-admet-score">-</strong>
            </div>
            <div class="mini">
              <div class="stat-label">最新分析 ID</div>
              <strong class="mono" id="result-run-id">-</strong>
            </div>
            <div class="mini">
              <div class="stat-label">人群 Population</div>
              <strong id="result-population">-</strong>
            </div>
          </div>
          <div class="result-grid">
            <div class="mini"><div class="stat-label">Cmax</div><strong id="result-cmax">-</strong></div>
            <div class="mini"><div class="stat-label">AUC</div><strong id="result-auc">-</strong></div>
            <div class="mini"><div class="stat-label">目标达成率 Target attainment</div><strong id="result-attain">-</strong></div>
          </div>
          <div class="action-row">
            <a class="action-chip" id="html-report-link" href="#" target="_blank" rel="noreferrer" aria-disabled="true">打开专业 HTML 报告</a>
            <a class="action-chip" id="report-link" href="#" target="_blank" rel="noreferrer" aria-disabled="true">导出 Markdown 报告</a>
            <a class="action-chip" id="json-link" href="#" target="_blank" rel="noreferrer" aria-disabled="true">查看 JSON 结果</a>
          </div>
          <div class="fit-grid">
            <div class="chart-card">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">PK 拟合质量</div>
                  <div class="chart-title-sub">Observed vs simulated concentration</div>
                </div>
              </div>
              <div class="metric-strip" id="pk-fit-metrics"></div>
            </div>
            <div class="chart-card">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">PD 拟合质量</div>
                  <div class="chart-title-sub">Observed vs simulated effect</div>
                </div>
              </div>
              <div class="metric-strip" id="pd-fit-metrics"></div>
            </div>
          </div>

          <section class="analysis-section">
            <div class="section-headline">
              <div>
                <div class="section-kicker">PBPK</div>
                <h3>全身 PBPK 暴露分析</h3>
                <p>基于输入化合物 ADMET/SMILES 参数，运行 gut-liver-kidney-lung-blood-tissue 全身 PBPK 模型。</p>
              </div>
              <div class="engine-chip" id="pbpk-engine">-</div>
            </div>
            <div class="metric-strip" id="pbpk-metrics"></div>
            <div class="chart-card chart-stage">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">浓度-时间曲线</div>
                  <div class="chart-title-sub">Concentration-time profile</div>
                </div>
              </div>
              <svg class="chart-svg chart-lg" id="pbpk-chart" viewBox="0 0 720 320" preserveAspectRatio="none"></svg>
              <div class="chart-notes" id="pbpk-notes"></div>
            </div>
            <div class="chart-grid" style="margin-top:12px;">
              <div class="chart-card chart-stage">
                <div class="chart-head">
                  <div>
                    <div class="chart-title-main">多人群暴露对比</div>
                    <div class="chart-title-sub">Population exposure overlay</div>
                  </div>
                </div>
                <svg class="chart-svg chart-lg" id="compare-chart" viewBox="0 0 720 320" preserveAspectRatio="none"></svg>
                <div class="chart-notes" id="compare-notes"></div>
              </div>
              <div class="chart-card">
                <div class="chart-head">
                  <div>
                    <div class="chart-title-main">对比图例与暴露摘要</div>
                    <div class="chart-title-sub">Comparison legend</div>
                  </div>
                </div>
                <div class="legend-list" id="compare-legend"></div>
              </div>
            </div>
            <div class="chart-card chart-stage" style="margin-top:12px;">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">虚拟人群暴露分布</div>
                  <div class="chart-title-sub">Virtual population percentile band</div>
                </div>
              </div>
              <svg class="chart-svg chart-lg" id="distribution-chart" viewBox="0 0 720 320" preserveAspectRatio="none"></svg>
              <div class="chart-notes" id="distribution-notes"></div>
            </div>
          </section>

          <section class="analysis-section">
            <div class="section-headline">
              <div>
                <div class="section-kicker">PK/PD</div>
                <h3>药效响应分析</h3>
                <p>展示真实 PK/PD 时间曲线、EC50 对应效应和推荐起始剂量。</p>
              </div>
              <div class="engine-chip" id="pkpd-engine">-</div>
            </div>
            <div class="metric-strip" id="pkpd-metrics"></div>
            <div class="chart-card chart-stage">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">效应-时间曲线</div>
                  <div class="chart-title-sub">Effect-time profile</div>
                </div>
              </div>
              <svg class="chart-svg chart-lg" id="pkpd-chart" viewBox="0 0 720 320" preserveAspectRatio="none"></svg>
              <div class="chart-notes" id="pkpd-notes"></div>
            </div>
          </section>

          <section class="analysis-section">
            <div class="section-headline">
              <div>
                <div class="section-kicker">STEP 8</div>
                <h3>DDI 与安全性</h3>
                <p>汇总 DDI 风险等级、器官安全指标、监测建议和外部文献证据。</p>
              </div>
              <div class="engine-chip">规则引擎 + PubMed</div>
            </div>
            <div class="metric-strip" id="ddi-metrics"></div>
            <div class="chart-card" style="margin-bottom:12px;">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">机制化 DDI 情景矩阵</div>
                  <div class="chart-title-sub">Mechanistic co-medication scenarios</div>
                </div>
              </div>
              <div class="legend-list" id="ddi-matrix"></div>
            </div>
            <div class="chart-grid">
              <div class="chart-card">
                <div class="chart-head">
                  <div>
                    <div class="chart-title-main">监测建议</div>
                    <div class="chart-title-sub">Monitoring plan</div>
                  </div>
                </div>
                <div class="bullet-list" id="monitoring-list"></div>
              </div>
              <div class="chart-card">
                <div class="chart-head">
                  <div>
                    <div class="chart-title-main">外部资源</div>
                    <div class="chart-title-sub">External references</div>
                  </div>
                </div>
                <div class="lit-list" id="resource-links"></div>
              </div>
            </div>
            <div class="chart-card" style="margin-top:12px;">
              <div class="chart-head">
                <div>
                  <div class="chart-title-main">文献快照</div>
                  <div class="chart-title-sub">Literature snapshot</div>
                </div>
              </div>
              <div class="lit-list" id="literature-list"></div>
            </div>
          </section>
        </div>
      </div>

    </section>



    <section class="panel card batch-shell">
      <div class="section-headline">
        <div>
          <div class="section-label">Single screening</div>
          <h2 class="section-title">ADMET Single Screening Workbench</h2>
          <p class="section-copy">Single-item mode. Submit only one compound each time to avoid queue delays and keep the main flow stable.</p>
        </div>
      </div>
      <div class="batch-grid">
        <div class="chart-card">
          <div class="chart-head">
            <div>
              <div class="chart-title-main">Submit Single Screening</div>
              <div class="chart-title-sub">CSV or line-based input</div>
            </div>
          </div>
          <div class="row-2">
            <label class="field"><span class="field-title"><span class="field-zh">任务名称</span><span class="field-en">Project name</span></span>
              <input id="batch-project-name" value="ADMET Single Screening">
            </label>
            <label class="field"><span class="field-title"><span class="field-zh">任务编号</span><span class="field-en">Project code</span></span>
              <input id="batch-project-code" value="P58-BATCH">
            </label>
          </div>
          <label class="field"><span class="field-title"><span class="field-zh">化合物列表</span><span class="field-en">Compound list</span></span>
            <textarea class="batch-textarea" id="batch-items-text">compound_name,smiles
Midazolam,CC1=NC=C2N1C3=C(C=C(C=C3)Cl)C(c1ccccc1F)=NC2</textarea>
          </label>
          <label class="field"><span class="field-title"><span class="field-zh">任务备注</span><span class="field-en">Notes</span></span>
            <textarea id="batch-notes" placeholder="可填写项目来源、筛选目的、化学系列等。"></textarea>
          </label>
          <div class="inline-actions">
            <button class="ghost-btn" id="load-batch-sample-btn" type="button">Load single sample</button>
            <button class="ghost-btn" id="refresh-tasks-btn" type="button">刷新任务队列</button>
            <button class="primary-btn" id="submit-batch-btn" type="button">Submit single screening task</button>
          </div>
          <div class="batch-status" id="batch-status">Single-item mode: only 1 `compound_name,smiles` record is allowed.</div>
        </div>
        <div class="chart-card">
          <div class="chart-head">
            <div>
              <div class="chart-title-main">任务队列</div>
              <div class="chart-title-sub">Asynchronous queue</div>
            </div>
          </div>
          <div class="task-list" id="task-list"></div>
          <div class="inline-actions">
            <a class="action-chip" id="task-html-link" href="#" target="_blank" rel="noreferrer" aria-disabled="true">Open task HTML report</a>
            <a class="action-chip" id="task-csv-link" href="#" target="_blank" rel="noreferrer" aria-disabled="true">Export task CSV</a>
          </div>
        </div>
      </div>
      <div class="chart-card">
        <div class="chart-head">
          <div>
            <div class="chart-title-main">Screening Result</div>
            <div class="chart-title-sub">Ranked ADMET summary</div>
          </div>
        </div>
        <div class="batch-table-wrap">
          <table class="batch-table">
            <thead>
              <tr>
                <th>Compound</th>
                <th>GPU</th>
                <th>ADMET score</th>
                <th>Oral F</th>
                <th>HIA</th>
                <th>hERG</th>
                <th>DILI</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody id="batch-results-body">
              <tr><td colspan="8">还没有批量结果。</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
  <div class="chart-tooltip" id="chart-tooltip"></div>
  <div class="drawer-overlay" id="history-overlay"></div>
  <aside class="history-drawer" id="history-drawer">
    <div class="drawer-head">
      <div>
        <div class="section-label">History</div>
        <h2 class="section-title">历史分析记录</h2>
        <p class="section-copy">历史记录移到独立抽屉，不再占主页宽度。点击任意记录可回看结果。</p>
      </div>
      <button class="drawer-close" id="close-history-btn" type="button">×</button>
    </div>
    <div class="runs" id="runs-list"></div>
    <div class="result-block">
      <h2>详细结果</h2>
      <div class="detail-pre mono" id="run-detail">选择一条分析记录，或者先运行一次新分析。</div>
    </div>
  </aside>
  <aside class="history-drawer" id="projects-drawer">
    <div class="drawer-head">
      <div>
        <div class="section-label">Projects</div>
        <h2 class="section-title">项目概览</h2>
        <p class="section-copy">按项目查看最近运行、风险等级和访问级别。</p>
      </div>
      <button class="drawer-close" id="close-projects-btn" type="button">×</button>
    </div>
    <div class="drawer-list" id="projects-list"></div>
  </aside>
  <aside class="history-drawer" id="audit-drawer">
    <div class="drawer-head">
      <div>
        <div class="section-label">Audit</div>
        <h2 class="section-title">审计事件</h2>
        <p class="section-copy">记录最近分析的项目、负责人、访问级别和拟合状态。</p>
      </div>
      <button class="drawer-close" id="close-audit-btn" type="button">×</button>
    </div>
    <div class="drawer-list" id="audit-list"></div>
  </aside>
  <div class="run-overlay" id="run-overlay" aria-hidden="true">
    <div class="run-dialog" role="status" aria-live="polite" aria-busy="true">
      <div class="run-kicker">Pipeline58 Running</div>
      <h2 class="run-title">系统正在运算</h2>
      <p class="run-copy">页面已暂时锁定，避免在主分析和对比计算期间出现状态错位。结果生成后会自动恢复。</p>
      <div class="run-status">
        <div class="run-spinner" aria-hidden="true"></div>
        <div>
          <div class="run-stage-title" id="run-stage-title">正在提交分析任务</div>
          <div class="run-stage-copy" id="run-stage-copy">主分析开始前，正在整理输入参数与工作流上下文。</div>
        </div>
      </div>
      <div class="run-steps" id="run-steps">
        <div class="run-step active" data-step="analyze"><span class="run-step-dot"></span><span>主分析: ADMET / PBPK / PK/PD / DDI</span></div>
        <div class="run-step" data-step="render"><span class="run-step-dot"></span><span>结果整理: 指标卡、曲线和拟合面板</span></div>
        <div class="run-step" data-step="compare"><span class="run-step-dot"></span><span>扩展计算: 多人群真实对比</span></div>
      </div>
    </div>
  </div>

  <script>
    const form = document.getElementById("analyze-form");
    const submitBtn = document.getElementById("submit-btn");
    const runsList = document.getElementById("runs-list");
    const detail = document.getElementById("run-detail");
    const compareCache = new Map();
    let currentRunId = "";
    const historyDrawer = document.getElementById("history-drawer");
    const projectsDrawer = document.getElementById("projects-drawer");
    const auditDrawer = document.getElementById("audit-drawer");
    const historyOverlay = document.getElementById("history-overlay");
    const openHistoryBtn = document.getElementById("open-history-btn");
    const openProjectsBtn = document.getElementById("open-projects-btn");
    const openAuditBtn = document.getElementById("open-audit-btn");
    const closeHistoryBtn = document.getElementById("close-history-btn");
    const closeProjectsBtn = document.getElementById("close-projects-btn");
    const closeAuditBtn = document.getElementById("close-audit-btn");
    const runOverlay = document.getElementById("run-overlay");
    const runStageTitle = document.getElementById("run-stage-title");
    const runStageCopy = document.getElementById("run-stage-copy");
    const loadMidazolamBaselineBtn = document.getElementById("load-midazolam-baseline-btn");
    const loadWarfarinBaselineBtn = document.getElementById("load-warfarin-baseline-btn");
    const loadCaffeineBaselineBtn = document.getElementById("load-caffeine-baseline-btn");
    const newBaselineBtn = document.getElementById("new-baseline-btn");
    const baselineCreatePanel = document.getElementById("baseline-create-panel");
    const newBaselineName = document.getElementById("new-baseline-name");
    const confirmBaselineBtn = document.getElementById("confirm-baseline-btn");
    const cancelBaselineBtn = document.getElementById("cancel-baseline-btn");
    const customBaselineRow = document.getElementById("custom-baseline-row");
    const projectsList = document.getElementById("projects-list");
    const auditList = document.getElementById("audit-list");
    const reportLink = document.getElementById("report-link");
    const htmlReportLink = document.getElementById("html-report-link");
    const jsonLink = document.getElementById("json-link");
    const pksimLink = document.getElementById("pksim-link");
    const ospsuiteRunBtn = document.getElementById("ospsuite-run-btn");
    const openPkSimVmWorkbenchBtn = document.getElementById("open-pksim-vm-workbench-btn");
    const pksimVmWorkbench = document.getElementById("pksim-vm-workbench");
    const pksimVmForm = document.getElementById("pksim-vm-form");
    const pksimVmSubmitBtn = document.getElementById("pksim-vm-submit-btn");
    const pksimVmStatus = document.getElementById("pksim-vm-status");
    const pksimVmResultStatus = document.getElementById("pksim-vm-result-status");
    const pksimVmFormStatus = document.getElementById("pksim-vm-form-status");
    const authScreen = document.getElementById("auth-screen");
    const loginForm = document.getElementById("login-form");
    const loginBtn = document.getElementById("login-btn");
    const authError = document.getElementById("auth-error");
    const logoutBtn = document.getElementById("logout-btn");
    const authUserName = document.getElementById("auth-user-name");
    const authUserMeta = document.getElementById("auth-user-meta");
    const runtimeGpuCards = document.getElementById("runtime-gpu-cards");
    const runtimeAdmetDevice = document.getElementById("runtime-admet-device");
    const runtimeAdmetBatch = document.getElementById("runtime-admet-batch");
    const runtimeBatchMode = document.getElementById("runtime-batch-mode");
    const runtimeBatchDetail = document.getElementById("runtime-batch-detail");
    const chartTooltip = document.getElementById("chart-tooltip");
    const formStatus = document.getElementById("form-status");
    const batchProjectName = document.getElementById("batch-project-name");
    const batchProjectCode = document.getElementById("batch-project-code");
    const batchItemsText = document.getElementById("batch-items-text");
    const batchNotes = document.getElementById("batch-notes");
    const batchStatus = document.getElementById("batch-status");
    const submitBatchBtn = document.getElementById("submit-batch-btn");
    const loadBatchSampleBtn = document.getElementById("load-batch-sample-btn");
    const refreshTasksBtn = document.getElementById("refresh-tasks-btn");
    const taskList = document.getElementById("task-list");
    const batchResultsBody = document.getElementById("batch-results-body");
    const taskHtmlLink = document.getElementById("task-html-link");
    const taskCsvLink = document.getElementById("task-csv-link");
    let authToken = localStorage.getItem("pipeline58-token") || "";
    let currentUser = null;
    let currentRuntimeInfo = null;
    let currentTaskId = "";
    let activeCustomBaselineId = localStorage.getItem("pipeline58-active-custom-baseline") || "";
    let taskPollTimer = null;
    let runOverlayOpenedAt = 0;
    const DEFAULT_SAMPLE = {
      project_name: "Pipeline58 测试项目",
      project_code: "P58-DEMO",
      owner: "demo",
      access_level: "internal",
      project_tags: "demo,midazolam,pbpk",
      compound_name: "Midazolam",
      smiles: "CC1=NC=C2N1C3=C(C=C(C=C3)Cl)C(c1ccccc1F)=NC2",
      target_name: "CYP3A4",
      indication: "镇静",
      mechanism: "inhibition",
      route: "po",
      dose_mg: "7.5",
      interval_hours: "24",
      repeat_days: "3",
      weight_kg: "70",
      age_years: "40",
      potency_uM: "0.8",
      preset: "adult",
      ethnicity: "general",
      sex: "female",
      renal_stage: "normal",
      hepatic_stage: "normal",
      pregnancy_trimester: "none",
      observations_text: "time_h,conc_ng_ml,effect_pct\\n1,39.1,22.6\\n2,37.3,21.7\\n4,18.5,10.1",
      concomitant_text: "name,role,mechanism,enzyme,strength,dose_note\\nketoconazole,perpetrator,inhibitor,CYP3A4,strong,400 mg qd\\nrifampicin,co-medication,inducer,CYP3A4,strong,600 mg qd",
      ddi_notes_text: "避免与强 CYP3A4 抑制剂联用。"
    };

    const BASELINE_SAMPLES = {
      midazolam: {
        compound_name: "Midazolam",
        smiles: "CC1=NC=C2N1C3=C(C=C(C=C3)Cl)C(c1ccccc1F)=NC2",
        target_name: "CYP3A4",
        indication: "镇静",
        mechanism: "inhibition",
        route: "po",
        dose_mg: "7.5",
        interval_hours: "24",
        repeat_days: "3",
        preset: "adult",
        ethnicity: "general",
        sex: "female"
      },
      warfarin: {
        compound_name: "Warfarin",
        smiles: "CC(C)(C1=CC=C(C=C1)C(=O)CC(c1ccccc1)O)C",
        target_name: "VKORC1",
        indication: "抗凝",
        mechanism: "inhibition",
        route: "po",
        dose_mg: "5",
        interval_hours: "24",
        repeat_days: "5",
        preset: "adult",
        ethnicity: "general",
        sex: "male"
      },
      caffeine: {
        compound_name: "Caffeine",
        smiles: "CN1C=NC2=C1N(C(=O)N(C)C2=O)C",
        target_name: "A2A",
        indication: "中枢兴奋",
        mechanism: "inhibition",
        route: "po",
        dose_mg: "100",
        interval_hours: "24",
        repeat_days: "2",
        preset: "adult",
        ethnicity: "general",
        sex: "unknown"
      }
    };

    const CUSTOM_BASELINES_KEY = "pipeline58-custom-baselines-v1";

    function authHeaders(extra = {}) {
      const headers = { ...extra };
      if (authToken) {
        headers["X-Pipeline58-Token"] = authToken;
      }
      return headers;
    }

    async function apiFetch(url, options = {}) {
      const config = { ...options, headers: authHeaders(options.headers || {}) };
      const res = await fetch(url, config);
      if (res.status === 401) {
        clearAuthState();
        throw new Error("请先登录后再操作。");
      }
      if (res.status === 403) {
        throw new Error("当前账号没有执行这个操作的权限。");
      }
      return res;
    }

    function setCurrentUser(user) {
      currentUser = user || null;
      if (!authUserName || !authUserMeta) return;
      if (!currentUser) {
        authUserName.textContent = "未登录";
        authUserMeta.textContent = "请先登录后再运行分析。";
        return;
      }
      authUserName.textContent = `${currentUser.display_name} / ${currentUser.username}`;
      authUserMeta.textContent = `角色 ${currentUser.role}${currentUser.password_change_required ? " | 建议尽快修改初始密码" : ""}`;
    }

    function openAuthScreen(message = "") {
      document.body.classList.add("auth-locked");
      authScreen.classList.add("open");
      if (authError) authError.textContent = message;
    }

    function closeAuthScreen() {
      authScreen.classList.remove("open");
      document.body.classList.remove("auth-locked");
      if (authError) authError.textContent = "";
    }

    function clearAuthState() {
      authToken = "";
      localStorage.removeItem("pipeline58-token");
      if (taskPollTimer) {
        clearTimeout(taskPollTimer);
        taskPollTimer = null;
      }
      setCurrentUser(null);
      setResultLinks("");
      setTaskLinks("");
      openAuthScreen("登录状态已失效，请重新登录。");
    }

    function syncToggleCards() {
      if (!form) return;
      document.querySelectorAll(".toggle-card").forEach(card => {
        const box = card.querySelector('input[type="checkbox"]');
        if (!box) return;
        card.classList.toggle("active", !!box.checked);
      });
      const sexField = form.querySelector('[name="sex"]');
      const pregnantField = form.querySelector('[name="pregnant"]');
      const trimesterField = form.querySelector('[name="pregnancy_trimester"]');
      if (pregnantField && pregnantField.checked) {
        if (sexField && sexField.value === "male") {
          sexField.value = "female";
        }
        if (trimesterField && trimesterField.value === "none") {
          trimesterField.value = "t2";
        }
      } else if (trimesterField && trimesterField.value !== "none") {
        trimesterField.value = "none";
      }
      if (trimesterField) {
        trimesterField.disabled = !(pregnantField && pregnantField.checked);
      }
    }

    function formatNumber(value, digits = 1) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "-";
      return num.toFixed(digits);
    }

    function formatPercent(value, digits = 0) {
      const num = Number(value);
      if (!Number.isFinite(num)) return "-";
      if (num <= 1) return `${(num * 100).toFixed(digits)}%`;
      return `${num.toFixed(digits)}%`;
    }

    function setFormStatus(message, tone = "") {
      if (!formStatus) return;
      formStatus.textContent = message || "";
      formStatus.className = `form-status${tone ? ` ${tone}` : ""}`;
    }

    function safeSetText(id, value) {
      const node = document.getElementById(id);
      if (!node) return;
      node.textContent = value == null || value === "" ? "-" : String(value);
    }

    function safeSetHtml(id, html) {
      const node = document.getElementById(id);
      if (!node) return;
      node.innerHTML = html || "";
    }

    function safeSetDetail(message) {
      if (!detail) return;
      detail.textContent = message || "";
    }

    function applySummaryFallback(detailData) {
      const summary = (detailData && detailData.summary) || {};
      safeSetHtml("risk-badge-wrap", riskBadge(summary.overall_risk || "yellow"));
      safeSetText("result-regimen", summary.recommended_regimen || "-");
      safeSetText("result-admet-score", summary.admet_score == null ? "-" : summary.admet_score);
      safeSetText("result-run-id", summary.run_id || "-");
      safeSetText("result-population", "Result available (fallback mode)");
      safeSetText("result-cmax", "-");
      safeSetText("result-auc", "-");
      safeSetText("result-attain", "-");
      setResultLinks(summary.run_id || "");
    }

    function showChartTooltip(clientX, clientY, title, rows) {
      if (!chartTooltip) return;
      chartTooltip.innerHTML = `
        <div class="tooltip-title">${title}</div>
        ${(rows || []).map(row => `
          <div class="tooltip-row">
            <span class="tooltip-swatch" style="background:${row.color || '#9dc0cb'}"></span>
            <span>${row.label}</span>
          </div>
        `).join("")}
      `;
      chartTooltip.classList.add("open");
      const width = chartTooltip.offsetWidth || 220;
      const height = chartTooltip.offsetHeight || 80;
      const left = Math.min(window.innerWidth - width - 12, clientX + 16);
      const top = Math.min(window.innerHeight - height - 12, clientY + 16);
      chartTooltip.style.left = `${Math.max(12, left)}px`;
      chartTooltip.style.top = `${Math.max(12, top)}px`;
    }

    function hideChartTooltip() {
      if (!chartTooltip) return;
      chartTooltip.classList.remove("open");
    }

    function bindSeriesHover(svg, seriesGroups, projectX, projectY, xLabel, yFormatter) {
      if (!svg || !seriesGroups || !seriesGroups.length) return;
      const hoverLayer = document.createElementNS("http://www.w3.org/2000/svg", "g");
      svg.appendChild(hoverLayer);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("stroke", "rgba(32,77,99,0.18)");
      line.setAttribute("stroke-width", "1.2");
      line.setAttribute("stroke-dasharray", "5 5");
      hoverLayer.appendChild(line);
      const circles = [];
      seriesGroups.forEach(group => {
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("r", "4.5");
        circle.setAttribute("fill", group.color || "#204d63");
        circle.setAttribute("stroke", "#ffffff");
        circle.setAttribute("stroke-width", "2");
        hoverLayer.appendChild(circle);
        circles.push(circle);
      });
      const clear = () => {
        line.setAttribute("visibility", "hidden");
        circles.forEach(circle => circle.setAttribute("visibility", "hidden"));
        hideChartTooltip();
      };
      clear();
      svg.addEventListener("mouseleave", clear);
      svg.addEventListener("mousemove", event => {
        const rect = svg.getBoundingClientRect();
        const scaleX = 720 / rect.width;
        const localX = (event.clientX - rect.left) * scaleX;
        let best = null;
        seriesGroups.forEach((group, index) => {
          (group.points || []).forEach(point => {
            const px = projectX(point.x);
            const py = projectY(point.y);
            const dx = Math.abs(localX - px);
            if (!best || dx < best.dx) {
              best = { groupIndex: index, point, px, py, dx };
            }
          });
        });
        if (!best) {
          clear();
          return;
        }
        const rows = [];
        line.setAttribute("visibility", "visible");
        line.setAttribute("x1", String(best.px));
        line.setAttribute("x2", String(best.px));
        line.setAttribute("y1", "18");
        line.setAttribute("y2", "276");
        seriesGroups.forEach((group, index) => {
          const nearest = (group.points || []).reduce((prev, point) => {
            if (!prev) return point;
            return Math.abs(projectX(point.x) - best.px) < Math.abs(projectX(prev.x) - best.px) ? point : prev;
          }, null);
          const circle = circles[index];
          if (!nearest) {
            circle.setAttribute("visibility", "hidden");
            return;
          }
          circle.setAttribute("visibility", "visible");
          circle.setAttribute("cx", String(projectX(nearest.x)));
          circle.setAttribute("cy", String(projectY(nearest.y)));
          rows.push({
            color: group.color,
            label: `${group.label}: ${yFormatter(nearest.y)}`
          });
        });
        showChartTooltip(event.clientX, event.clientY, `${xLabel} ${formatNumber(best.point.x, 1)} h`, rows);
      });
    }

    function renderMetricStrip(holderId, items) {
      const holder = document.getElementById(holderId);
      if (!holder) return;
      holder.innerHTML = (items || []).map(item => `
        <div class="metric-pill">
          <div class="metric-name">${item.label || "-"}</div>
          <div class="metric-value">${item.value || "-"}</div>
          <div class="metric-note">${item.note || ""}</div>
        </div>
      `).join("");
    }

    function setResultLinks(runId) {
      currentRunId = runId || "";
      if (!currentRunId) {
        htmlReportLink.setAttribute("aria-disabled", "true");
        reportLink.setAttribute("aria-disabled", "true");
        jsonLink.setAttribute("aria-disabled", "true");
        if (pksimLink) pksimLink.setAttribute("aria-disabled", "true");
        if (ospsuiteRunBtn) {
          ospsuiteRunBtn.disabled = true;
          ospsuiteRunBtn.setAttribute("aria-disabled", "true");
        }
        htmlReportLink.href = "#";
        reportLink.href = "#";
        jsonLink.href = "#";
        if (pksimLink) pksimLink.href = "#";
        return;
      }
      htmlReportLink.removeAttribute("aria-disabled");
      reportLink.removeAttribute("aria-disabled");
      jsonLink.removeAttribute("aria-disabled");
      if (pksimLink) pksimLink.removeAttribute("aria-disabled");
      if (ospsuiteRunBtn) {
        ospsuiteRunBtn.disabled = false;
        ospsuiteRunBtn.removeAttribute("aria-disabled");
      }
      const tokenQuery = authToken ? `?token=${encodeURIComponent(authToken)}` : "";
      htmlReportLink.href = `/api/v1/pipeline58/runs/${currentRunId}/report/html${tokenQuery}`;
      reportLink.href = `/api/v1/pipeline58/runs/${currentRunId}/report${tokenQuery}`;
      jsonLink.href = `/api/v1/pipeline58/runs/${currentRunId}${tokenQuery}`;
      refreshPkSimLink();
    }

    function setBatchStatus(message, tone = "") {
      if (!batchStatus) return;
      batchStatus.textContent = message || "";
      batchStatus.className = `batch-status${tone ? ` ${tone}` : ""}`;
    }

    function setTaskLinks(taskId) {
      currentTaskId = taskId || "";
      if (!currentTaskId) {
        taskHtmlLink.setAttribute("aria-disabled", "true");
        taskCsvLink.setAttribute("aria-disabled", "true");
        taskHtmlLink.href = "#";
        taskCsvLink.href = "#";
        return;
      }
      const tokenQuery = authToken ? `?token=${encodeURIComponent(authToken)}` : "";
      taskHtmlLink.removeAttribute("aria-disabled");
      taskCsvLink.removeAttribute("aria-disabled");
      taskHtmlLink.href = `/api/v1/pipeline58/tasks/${currentTaskId}/report/html${tokenQuery}`;
      taskCsvLink.href = `/api/v1/pipeline58/tasks/${currentTaskId}/results.csv${tokenQuery}`;
    }

    function parseBatchItems(text) {
      const source = String(text || "").trim();
      if (!source) return [];
      const lines = source.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      if (!lines.length) return [];
      const looksLikeCsv = lines[0].toLowerCase().includes("smiles");
      const bodyLines = looksLikeCsv ? lines.slice(1) : lines;
      return bodyLines.map((line, index) => {
        if (line.includes(",")) {
          const parts = line.split(",");
          const compoundName = String(parts[0] || "").trim();
          const smiles = String(parts.slice(1).join(",") || "").trim();
          return { compound_name: compoundName || `Compound ${index + 1}`, smiles };
        }
        const pieces = line.split(/\s+/).filter(Boolean);
        if (pieces.length < 2) {
          return { compound_name: `Compound ${index + 1}`, smiles: pieces[0] || "" };
        }
        return { compound_name: pieces.slice(1).join(" "), smiles: pieces[0] };
      }).filter(item => String(item.smiles || "").trim());
    }

    function renderTaskResults(items) {
      if (!batchResultsBody) return;
      if (!items || !items.length) {
        batchResultsBody.innerHTML = '<tr><td colspan="8">当前任务还没有完成结果。</td></tr>';
        return;
      }
      batchResultsBody.innerHTML = items.map(item => `
        <tr>
          <td><strong>${item.compound_name || "-"}</strong><div class="mono">${item.smiles || "-"}</div></td>
          <td>GPU${item.gpu_index != null ? item.gpu_index : "-"}</td>
          <td>${item.overall_admet_score != null ? item.overall_admet_score : "-"}</td>
          <td>${item.oral_f != null ? item.oral_f : "-"}</td>
          <td>${item.hia != null ? item.hia : "-"}</td>
          <td>${item.herg_risk || "-"}</td>
          <td>${item.dili_risk || "-"}</td>
          <td>${(item.development_flags || []).join(" | ") || "-"}</td>
        </tr>
      `).join("");
    }

    function renderTaskList(items) {
      if (!taskList) return;
      if (!items || !items.length) {
        taskList.innerHTML = '<div class="task-item">当前还没有批量任务。</div>';
        renderTaskResults([]);
        setTaskLinks("");
        return;
      }
      taskList.innerHTML = items.map(item => `
        <div class="task-item ${item.task_id === currentTaskId ? "active" : ""}" data-task-id="${item.task_id}">
          <div class="task-item-head">
            <strong>${item.project_name || item.task_id}</strong>
            ${taskStatusBadge(item.status)}
          </div>
          <div class="drawer-item-meta">${item.project_code || "-"} | ${item.created_at || "-"}</div>
          <div class="drawer-item-meta">状态: ${item.status || "-"} | 进度: ${formatNumber(item.progress_pct || 0, 0)}% | ${item.completed || 0}/${item.submitted || 0}</div>
          <div class="drawer-item-meta">GPU: ${(item.gpu_workers || []).map(value => `GPU${value}`).join(", ") || "-"}</div>
          <div class="task-progress"><span style="width:${Math.max(4, Number(item.progress_pct || 0))}%"></span></div>
        </div>
      `).join("");
      taskList.querySelectorAll(".task-item[data-task-id]").forEach(node => {
        node.addEventListener("click", () => loadTaskDetail(node.dataset.taskId));
      });
    }

    async function loadTasks(focusTaskId = "") {
      const res = await apiFetch("/api/v1/pipeline58/tasks");
      const payload = await res.json();
      const items = payload.data || [];
      renderTaskList(items);
      const targetId = focusTaskId || currentTaskId || (items[0] && items[0].task_id) || "";
      if (targetId) {
        await loadTaskDetail(targetId, false);
      }
      const hasActive = items.some(item => ["queued", "running"].includes(String(item.status || "")));
      if (taskPollTimer) {
        clearTimeout(taskPollTimer);
        taskPollTimer = null;
      }
      if (hasActive) {
        taskPollTimer = setTimeout(() => loadTasks(currentTaskId).catch(error => setBatchStatus(String(error), "error")), 3500);
      }
    }

    async function loadTaskDetail(taskId, refreshList = true) {
      if (!taskId) return;
      const res = await apiFetch(`/api/v1/pipeline58/tasks/${taskId}`);
      const payload = await res.json();
      const task = payload.data || {};
      currentTaskId = taskId;
      setTaskLinks(taskId);
      renderTaskResults(task.items || []);
      setBatchStatus(`任务 ${taskId} | 状态 ${task.status || "-"} | ${task.completed || 0}/${task.submitted || 0}`, task.status === "failed" ? "error" : task.status === "completed" ? "ok" : "");
      if (refreshList) {
        await loadTasks(taskId);
      }
    }

    function renderProjects(items) {
      if (!projectsList) return;
      if (!items || !items.length) {
        projectsList.innerHTML = '<div class="drawer-item">当前还没有项目记录。</div>';
        return;
      }
      projectsList.innerHTML = items.map(item => `
        <div class="drawer-item">
          <div class="drawer-item-head">
            <div class="drawer-item-title">${item.project_name}</div>
            ${riskBadge(item.last_overall_risk || "yellow")}
          </div>
          <div class="drawer-item-meta">项目编号: ${item.project_code}</div>
          <div class="drawer-item-meta">负责人: ${item.owner} | 访问级别: ${item.access_level}</div>
          <div class="drawer-item-meta">运行次数: ${item.run_count} | 最近运行: ${item.last_run_at || "-"}</div>
          <div class="drawer-item-meta">标签: ${(item.tags || []).join(", ") || "-"}</div>
        </div>
      `).join("");
    }

    function renderAudit(items) {
      if (!auditList) return;
      if (!items || !items.length) {
        auditList.innerHTML = '<div class="drawer-item">当前还没有审计事件。</div>';
        return;
      }
      auditList.innerHTML = items.map(item => `
        <div class="drawer-item">
          <div class="drawer-item-head">
            <div class="drawer-item-title">${item.compound_name}</div>
            ${riskBadge(item.overall_risk || "yellow")}
          </div>
          <div class="drawer-item-meta">Run ID: ${item.run_id}</div>
          <div class="drawer-item-meta">项目: ${item.project_name} (${item.project_code})</div>
          <div class="drawer-item-meta">负责人: ${item.owner} | 访问级别: ${item.access_level}</div>
          <div class="drawer-item-meta">时间: ${item.created_at || "-"} | 拟合启用: ${item.fit_enabled ? "是" : "否"}</div>
        </div>
      `).join("");
    }

    function renderFitMetrics(holderId, fit, typeLabel) {
      if (!fit) {
        renderMetricStrip(holderId, [
          { label: `${typeLabel} 观测点`, value: "0", note: "当前没有导入观测数据" },
          { label: "RMSE", value: "-", note: "等待观测数据" },
          { label: "MAPE", value: "-", note: "等待观测数据" },
          { label: "R2", value: "-", note: "等待观测数据" }
        ]);
        return;
      }
      renderMetricStrip(holderId, [
        { label: `${typeLabel} 观测点`, value: String(fit.n || 0), note: "与模拟曲线对位的样本数" },
        { label: "RMSE", value: fit.RMSE ? `${formatNumber(fit.RMSE.value, 2)} ${fit.RMSE.unit}` : "-", note: "均方根误差" },
        { label: "MAPE", value: fit.MAPE_pct == null ? "-" : `${formatNumber(fit.MAPE_pct, 1)}%`, note: "平均绝对百分比误差" },
        { label: "R2", value: fit.R2 == null ? "-" : formatNumber(fit.R2, 3), note: "拟合决定系数" }
      ]);
    }

    function parseCsvRows(text) {
      return String(text || "")
        .split(/\\r?\\n/)
        .map(line => line.trim())
        .filter(Boolean)
        .filter(line => !line.startsWith("#"));
    }

    function parseObservations(text) {
      const rows = parseCsvRows(text);
      if (!rows.length) return [];
      const bodyRows = /time_h/i.test(rows[0]) ? rows.slice(1) : rows;
      return bodyRows.map(line => {
        const [time_h, conc_ng_ml, effect_pct] = line.split(",").map(item => item.trim());
        const result = { time_h: Number(time_h) };
        if (conc_ng_ml !== undefined && conc_ng_ml !== "") result.conc_ng_ml = Number(conc_ng_ml);
        if (effect_pct !== undefined && effect_pct !== "") result.effect_pct = Number(effect_pct);
        return result;
      }).filter(item => Number.isFinite(item.time_h));
    }

    function parseConcomitant(text) {
      const rows = parseCsvRows(text);
      if (!rows.length) return [];
      const bodyRows = /name/i.test(rows[0]) ? rows.slice(1) : rows;
      return bodyRows.map(line => {
        const [name, role, mechanism, enzyme, strength, dose_note] = line.split(",").map(item => (item || "").trim());
        return {
          name,
          role: role || "co-medication",
          mechanism: mechanism || "mixed",
          enzyme: enzyme || "CYP3A4",
          strength: strength || "moderate",
          dose_note: dose_note || ""
        };
      }).filter(item => item.name);
    }

    function parseLines(text) {
      return String(text || "")
        .split(/\\r?\\n/)
        .map(line => line.trim())
        .filter(Boolean);
    }

    function applySampleCase() {
      Object.entries(DEFAULT_SAMPLE).forEach(([name, value]) => {
        const field = form.querySelector(`[name="${name}"]`);
        if (!field) return;
        field.value = value;
      });
      ["renal_impairment", "hepatic_impairment", "pregnant", "enable_pk_fit", "enable_pd_fit"].forEach(name => {
        const field = form.querySelector(`[name="${name}"]`);
        if (field) field.checked = false;
      });
      syncToggleCards();
      detail.textContent = "已加载测试样例，可直接点击“运行 STEP 5-8”。";
    }

    function defaultBaselineValues() {
      return {
        ...DEFAULT_SAMPLE,
        renal_impairment: false,
        hepatic_impairment: false,
        pregnant: false,
        enable_pk_fit: false,
        enable_pd_fit: false
      };
    }

    function applyFormValues(values) {
      if (!form) return;
      Object.entries(values || {}).forEach(([name, value]) => {
        const field = form.querySelector(`[name="${name}"]`);
        if (!field) return;
        if (field.type === "checkbox") {
          field.checked = !!value;
        } else {
          field.value = value == null ? "" : value;
        }
      });
      syncToggleCards();
      refreshPkSimLink();
    }

    function setActiveCustomBaseline(id) {
      activeCustomBaselineId = id || "";
      if (activeCustomBaselineId) {
        localStorage.setItem("pipeline58-active-custom-baseline", activeCustomBaselineId);
      } else {
        localStorage.removeItem("pipeline58-active-custom-baseline");
      }
      renderCustomBaselines();
    }

    function applyBaselineCase(sampleKey, label) {
      const baseline = BASELINE_SAMPLES[sampleKey];
      if (!baseline) return;
      setActiveCustomBaseline("");
      applyFormValues({ ...defaultBaselineValues(), ...baseline });
      detail.textContent = `已加载 ${label} 基线，可直接点击“运行 STEP 5-8”。`;
      setFormStatus(`已加载 ${label} 基线。`, "ok");
    }

    function readCustomBaselines() {
      try {
        const parsed = JSON.parse(localStorage.getItem(CUSTOM_BASELINES_KEY) || "[]");
        return Array.isArray(parsed) ? parsed.filter(item => item && item.id && item.label) : [];
      } catch (error) {
        return [];
      }
    }

    function writeCustomBaselines(items) {
      localStorage.setItem(CUSTOM_BASELINES_KEY, JSON.stringify((items || []).slice(0, 48)));
    }

    function normalizeBaselineLabel(label) {
      return String(label || "").trim().replace(/\s+/g, " ");
    }

    function collectCurrentBaselineValues() {
      const values = {};
      form.querySelectorAll("input[name], select[name], textarea[name]").forEach(field => {
        values[field.name] = field.type === "checkbox" ? !!field.checked : field.value;
      });
      return values;
    }

    function createCustomBaseline() {
      const label = normalizeBaselineLabel(newBaselineName ? newBaselineName.value : "");
      if (!label) {
        setFormStatus("请先输入基线名称。", "error");
        if (newBaselineName) newBaselineName.focus();
        return;
      }
      const items = readCustomBaselines();
      const existing = items.find(item => String(item.label || "").toLowerCase() === label.toLowerCase());
      const next = existing || { id: `custom_${Date.now()}`, label, values: null, updated_at: "" };
      next.label = label;
      next.pending = !next.values;
      const kept = items.filter(item => item.id !== next.id);
      writeCustomBaselines([next, ...kept]);
      if (newBaselineName) newBaselineName.value = "";
      if (baselineCreatePanel) baselineCreatePanel.classList.remove("open");
      setActiveCustomBaseline(next.id);
      setFormStatus(`已新建 ${label}，运行成功后会自动保存当前输入。`, "ok");
    }

    function saveActiveBaselineAfterRun() {
      if (!activeCustomBaselineId) return null;
      const items = readCustomBaselines();
      const target = items.find(item => item.id === activeCustomBaselineId);
      if (!target) {
        setActiveCustomBaseline("");
        return null;
      }
      target.values = collectCurrentBaselineValues();
      target.pending = false;
      target.updated_at = new Date().toISOString();
      writeCustomBaselines([target, ...items.filter(item => item.id !== target.id)]);
      renderCustomBaselines();
      return target;
    }

    function renderCustomBaselines() {
      if (!customBaselineRow) return;
      const items = readCustomBaselines();
      if (activeCustomBaselineId && !items.some(item => item.id === activeCustomBaselineId)) {
        activeCustomBaselineId = "";
        localStorage.removeItem("pipeline58-active-custom-baseline");
      }
      customBaselineRow.innerHTML = "";
      items.forEach(item => {
        const wrap = document.createElement("span");
        wrap.className = `custom-baseline-pill${item.id === activeCustomBaselineId ? " active" : ""}${item.values ? "" : " pending"}`;
        const loadBtn = document.createElement("button");
        loadBtn.type = "button";
        loadBtn.className = "ghost-btn";
        loadBtn.textContent = item.values ? item.label : `${item.label} (待保存)`;
        loadBtn.addEventListener("click", () => {
          setActiveCustomBaseline(item.id);
          if (item.values) {
            applyFormValues(item.values || {});
            detail.textContent = `已加载 ${item.label}，可直接点击“运行 STEP 5-8”。`;
            setFormStatus(`已选择 ${item.label}。运行成功后会覆盖保存这个基线。`, "ok");
          } else {
            setFormStatus(`已选择 ${item.label}。请填写参数并运行，成功后自动保存。`, "ok");
          }
        });
        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        deleteBtn.className = "baseline-delete-btn";
        deleteBtn.title = "删除这个自定义基线";
        deleteBtn.textContent = "x";
        deleteBtn.addEventListener("click", () => {
          if (!confirm(`删除 ${item.label} 吗？`)) return;
          writeCustomBaselines(readCustomBaselines().filter(saved => saved.id !== item.id));
          if (activeCustomBaselineId === item.id) setActiveCustomBaseline("");
          renderCustomBaselines();
          setFormStatus(`已删除 ${item.label}。`, "ok");
        });
        wrap.appendChild(loadBtn);
        wrap.appendChild(deleteBtn);
        customBaselineRow.appendChild(wrap);
      });
    }

    function ensureDefaultSmiles(body) {
      if (String(body.smiles || "").trim()) return body;
      const fallback = { ...body };
      fallback.compound_name = fallback.compound_name || DEFAULT_SAMPLE.compound_name;
      fallback.smiles = DEFAULT_SAMPLE.smiles;
      fallback.target_name = fallback.target_name || DEFAULT_SAMPLE.target_name;
      fallback.indication = fallback.indication || DEFAULT_SAMPLE.indication;
      const smilesField = form.querySelector('[name="smiles"]');
      if (smilesField) smilesField.value = DEFAULT_SAMPLE.smiles;
      detail.textContent = "SMILES 为空，系统已自动回填测试样例 Midazolam。";
      return fallback;
    }

    function validateRequestBody(body) {
      if (!String(body.compound_name || "").trim()) return "请填写化合物名称。";
      if (!String(body.smiles || "").trim()) return "请填写 SMILES，或点击“加载测试样例”。";
      if (!String(body.target_name || "").trim()) return "请填写靶点。";
      return null;
    }

    function setRunOverlayState(stage, title, copy) {
      if (runStageTitle) runStageTitle.textContent = title;
      if (runStageCopy) runStageCopy.textContent = copy;
      document.querySelectorAll("#run-steps .run-step").forEach(node => {
        const step = node.dataset.step;
        node.classList.remove("active", "done");
        if (step === stage) {
          node.classList.add("active");
        } else if (
          (stage === "render" && step === "analyze") ||
          (stage === "compare" && (step === "analyze" || step === "render"))
        ) {
          node.classList.add("done");
        }
      });
    }

    function openRunOverlay() {
      runOverlayOpenedAt = Date.now();
      document.body.classList.add("loading");
      runOverlay.classList.add("open");
      runOverlay.setAttribute("aria-hidden", "false");
      setRunOverlayState(
        "analyze",
        "正在执行主分析",
        "系统正在运行 ADMET、PBPK、PK/PD 与 DDI 主链路。"
      );
    }

    async function closeRunOverlay() {
      const elapsed = Date.now() - runOverlayOpenedAt;
      if (elapsed < 700) {
        await new Promise(resolve => setTimeout(resolve, 700 - elapsed));
      }
      document.body.classList.remove("loading");
      runOverlay.classList.remove("open");
      runOverlay.setAttribute("aria-hidden", "true");
      setRunOverlayState(
        "analyze",
        "正在提交分析任务",
        "主分析开始前，正在整理输入参数与工作流上下文。"
      );
    }

    async function waitForPaint() {
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }

    function renderNoteChips(holderId, notes) {
      const holder = document.getElementById(holderId);
      if (!holder) return;
      holder.innerHTML = (notes || []).map(note => `<div class="note-chip">${note}</div>`).join("");
    }

    function translateMonitoring(item) {
      const table = {
        "Check QT interval if hERG probability is not green.": "如果 hERG 风险不是绿色，需监测 QT 间期。",
        "Monitor ALT and AST during dose escalation.": "剂量爬坡期间监测 ALT / AST。",
        "Review ketoconazole and clarithromycin co-administration scenarios.": "复核与酮康唑、克拉霉素联用场景。"
      };
      return table[item] || item;
    }

    function renderMonitoring(items) {
      const holder = document.getElementById("monitoring-list");
      if (!holder) return;
      if (!items || !items.length) {
        holder.innerHTML = '<div class="bullet-item">当前没有额外监测建议。</div>';
        return;
      }
      holder.innerHTML = items.map(item => `<div class="bullet-item">${translateMonitoring(item)}</div>`).join("");
    }

    function renderResources(items) {
      const holder = document.getElementById("resource-links");
      if (!holder) return;
      if (!items || !items.length) {
        holder.innerHTML = '<div class="lit-item">当前没有额外外部资源。</div>';
        return;
      }
      holder.innerHTML = items.map(item => `
        <div class="lit-item">
          <div class="stat-label">${item.label || "外部资源"}</div>
          <div><a href="${item.url}" target="_blank" rel="noreferrer">${item.url}</a></div>
        </div>
      `).join("");
    }

    function refreshPkSimLink() {
      if (!pksimLink || !form) return;
      if (!currentRunId) {
        pksimLink.setAttribute("aria-disabled", "true");
        pksimLink.href = "#";
        return;
      }
      const fd = new FormData(form);
      const params = new URLSearchParams();
      const map = {
        compound_name: "compound_name",
        route: "route",
        dose_mg: "dose_mg",
        interval_hours: "interval_hours",
        repeat_days: "repeat_days"
      };
      Object.entries(map).forEach(([k, field]) => {
        const v = String(fd.get(field) || "").trim();
        if (v) params.set(k, v);
      });
      params.set("from", "step5-8");
      // keep PK-Sim default 24h unless repeat_days implies longer
      const repeatDays = Number(fd.get("repeat_days") || 1);
      const suggestedHours = Number.isFinite(repeatDays) && repeatDays > 0 ? Math.max(24, repeatDays * 24) : 24;
      params.set("total_hours", String(suggestedHours));
      pksimLink.removeAttribute("aria-disabled");
      pksimLink.href = `/pksim?${params.toString()}`;
    }

    function makeRequestBody(fd) {
      return {
        compound_name: fd.get("compound_name"),
        smiles: fd.get("smiles"),
        target_name: fd.get("target_name"),
        indication: fd.get("indication"),
        project: {
          project_name: fd.get("project_name"),
          project_code: fd.get("project_code"),
          owner: fd.get("owner"),
          access_level: fd.get("access_level"),
          tags: parseLines(fd.get("project_tags")).flatMap(item => item.split(",").map(tag => tag.trim()).filter(Boolean))
        },
        potency_uM: Number(fd.get("potency_uM")),
        mechanism: fd.get("mechanism"),
        dosing: {
          route: fd.get("route"),
          dose_mg: Number(fd.get("dose_mg")),
          interval_hours: Number(fd.get("interval_hours")),
          repeat_days: Number(fd.get("repeat_days"))
        },
        population: {
          species: "human",
          preset: fd.get("preset"),
          ethnicity: fd.get("ethnicity"),
          sex: fd.get("sex"),
          weight_kg: Number(fd.get("weight_kg")),
          age_years: Number(fd.get("age_years")),
          renal_impairment: !!((form.querySelector('[name="renal_impairment"]') || {}).checked),
          hepatic_impairment: !!((form.querySelector('[name="hepatic_impairment"]') || {}).checked),
          pregnant: !!((form.querySelector('[name="pregnant"]') || {}).checked),
          renal_stage: (function(){ const field = form.querySelector('[name="renal_stage"]'); return field ? field.value : "normal"; })(),
          hepatic_stage: (function(){ const field = form.querySelector('[name="hepatic_stage"]'); return field ? field.value : "normal"; })(),
          pregnancy_trimester: (function(){ const field = form.querySelector('[name="pregnancy_trimester"]'); return field ? field.value : "none"; })()
        },
        observations: parseObservations(fd.get("observations_text")),
        concomitant_drugs: parseConcomitant(fd.get("concomitant_text")),
        ddi_notes: parseLines(fd.get("ddi_notes_text")),
        fit: {
          enable_pk_fit: !!((form.querySelector('[name="enable_pk_fit"]') || {}).checked),
          enable_pd_fit: !!((form.querySelector('[name="enable_pd_fit"]') || {}).checked),
          profile: fd.get("fit_profile")
        }
      };
    }

    function buildComparisonRequests(requestPayload) {
      const base = JSON.parse(JSON.stringify(requestPayload));
      base.observations = [];
      base.concomitant_drugs = [];
      base.ddi_notes = [];
      base.fit = { enable_pk_fit: false, enable_pd_fit: false, profile: "quick" };
      const currentPopulation = base.population || {};
      const scenarios = [
        { label: "当前情景", color: "#0f6c78", payload: base },
        {
          label: "成人基线",
          color: "#406882",
          payload: {
            ...base,
            population: {
              ...currentPopulation,
              preset: "adult",
              ethnicity: "general",
              sex: "unknown",
              weight_kg: 70,
              age_years: 40,
              renal_impairment: false,
              hepatic_impairment: false,
              pregnant: false
            }
          }
        },
        {
          label: "老年",
          color: "#8d6a9f",
          payload: {
            ...base,
            population: {
              ...currentPopulation,
              preset: "elderly",
              ethnicity: "general",
              weight_kg: 65,
              age_years: 72,
              renal_impairment: false,
              hepatic_impairment: false,
              pregnant: false
            }
          }
        },
        {
          label: "肾损伤",
          color: "#c7851a",
          payload: {
            ...base,
            population: {
              ...currentPopulation,
              preset: "adult",
              ethnicity: "general",
              weight_kg: 70,
              age_years: 40,
              renal_impairment: true,
              hepatic_impairment: false,
              pregnant: false
            }
          }
        },
        {
          label: "肝损伤",
          color: "#b13b2e",
          payload: {
            ...base,
            population: {
              ...currentPopulation,
              preset: "adult",
              ethnicity: "general",
              weight_kg: 70,
              age_years: 40,
              renal_impairment: false,
              hepatic_impairment: true,
              pregnant: false
            }
          }
        }
      ];
      if ((currentPopulation.sex || "unknown") !== "male") {
        scenarios.push({
          label: "妊娠",
          color: "#d35f8d",
          payload: {
            ...base,
            population: {
              ...currentPopulation,
              preset: "adult",
              ethnicity: "general",
              sex: "female",
              weight_kg: 68,
              age_years: 30,
              renal_impairment: false,
              hepatic_impairment: false,
              pregnant: true
            }
          }
        });
      }
      return scenarios;
    }

    async function analyzePayload(payload, persist = true, timeoutMs = null) {
      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      const parsedTimeout = Number(timeoutMs);
      const effectiveTimeout = Number.isFinite(parsedTimeout) && parsedTimeout > 0 ? parsedTimeout : (persist ? 180000 : 45000);
      const timer = controller ? setTimeout(() => controller.abort(new Error("request timeout")), effectiveTimeout) : null;
      let res;
      try {
        res = await apiFetch(persist ? "/api/v1/pipeline58/analyze" : "/api/v1/pipeline58/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller ? controller.signal : undefined
        });
      } catch (error) {
        if (timer) clearTimeout(timer);
        const msg = String(error || "");
        if (msg.toLowerCase().includes("abort") || msg.toLowerCase().includes("timeout")) {
          throw new Error(`Request timed out (${Math.round(effectiveTimeout/1000)}s)`);
        }
        throw error;
      }
      if (timer) clearTimeout(timer);
      if (!res.ok) {
        const rawText = await res.text();
        try {
          const parsed = JSON.parse(rawText);
          throw new Error(parsed.detail || parsed.error || rawText);
        } catch (error) {
          throw new Error(rawText);
        }
      }
      const body = await res.json();
      return body.data;
    }

    function setPkSimVmStatus(message, tone = "") {
      if (!pksimVmFormStatus) return;
      pksimVmFormStatus.textContent = message || "";
      pksimVmFormStatus.className = `form-status${tone ? ` ${tone}` : ""}`;
    }

    function renderPkSimVmResult(data) {
      const artifact = data || {};
      const result = artifact.result || {};
      const pk = result.pk || {};
      const backend = result.backend || {};
      const curve = result.concentration_time_curve || [];
      if (pksimVmStatus) pksimVmStatus.textContent = "Simulation completed";
      if (pksimVmResultStatus) pksimVmResultStatus.textContent = "Simulation completed";
      renderMetricStrip("pksim-vm-metrics", [
        { label: "Cmax", value: pk.Cmax ? `${pk.Cmax.value} ${pk.Cmax.unit || ""}` : "-", note: "PK-Sim/OSPSuite output" },
        { label: "Tmax", value: pk.Tmax ? `${pk.Tmax.value} ${pk.Tmax.unit || "h"}` : "-", note: "Time of Cmax" },
        { label: "AUC0-t", value: pk.AUC0_t ? `${pk.AUC0_t.value} ${pk.AUC0_t.unit || ""}` : "-", note: `${curve.length || 0} curve points` },
        { label: "Engine", value: backend.model || "PK-Sim", note: backend.pkml || artifact.artifact_path || "-" }
      ]);
      const warnings = (((result.pkml_mapping || {}).warnings) || []).slice(0, 3);
      const notes = [
        "Actual simulation completed: PKML loaded, simulation executed, concentration-time curve and PK metrics exported.",
        artifact.artifact_path ? `Server artifact: ${artifact.artifact_path}` : "",
        ...warnings
      ].filter(Boolean);
      renderNoteChips("pksim-vm-notes", notes);
    }

    function makePkSimVmRequestBody(fd) {
      const repeatDays = Number(fd.get("pksim_repeat_days") || 1);
      const intervalHours = Number(fd.get("pksim_interval_hours") || 24);
      const templatePath = String(fd.get("pksim_template_path") || "").trim();
      return {
        compound_name: String(fd.get("pksim_compound_name") || "").trim(),
        route: String(fd.get("pksim_route") || "po"),
        dose_mg: Number(fd.get("pksim_dose_mg") || 0),
        interval_hours: intervalHours,
        repeat_days: repeatDays,
        total_hours: Math.max(24, repeatDays * intervalHours),
        path_filter: "PeripheralVenousBlood|Plasma",
        pkml_path: templatePath,
        compound_parameters: {
          molecular_weight: null,
          logP: null,
          log_solubility: null
        },
        notes: String(fd.get("pksim_notes") || "").trim(),
        project: {
          project_name: String(fd.get("pksim_project_name") || "PK-Sim Simulation Project").trim(),
          project_code: String(fd.get("pksim_project_code") || "PKSIM-SIM").trim()
        },
        population: {
          preset: String(fd.get("pksim_preset") || "adult"),
          sex: String(fd.get("pksim_sex") || "unknown"),
          weight_kg: Number(fd.get("pksim_weight_kg") || 70),
          age_years: Number(fd.get("pksim_age_years") || 40)
        }
      };
    }

    async function runPkSimVmFromWorkbench() {
      if (!pksimVmForm || !pksimVmSubmitBtn) return;
      pksimVmSubmitBtn.disabled = true;
      pksimVmSubmitBtn.dataset.oldText = pksimVmSubmitBtn.textContent || "";
      pksimVmSubmitBtn.textContent = "PK-Sim simulation running...";
      if (pksimVmStatus) pksimVmStatus.textContent = "Running";
      if (pksimVmResultStatus) pksimVmResultStatus.textContent = "Running";
      setPkSimVmStatus("Running actual PK-Sim/OSPSuite simulation.");
      try {
        const fd = new FormData(pksimVmForm);
        const body = makePkSimVmRequestBody(fd);
        if (!body.compound_name || !body.dose_mg) {
          setPkSimVmStatus("Compound name and dose are required.", "error");
          return;
        }
        const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(new Error("request timeout")), 180000) : null;
        let res;
        try {
          res = await apiFetch("/api/v1/pksim/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: controller ? controller.signal : undefined
          });
        } catch (error) {
          if (String(error || "").toLowerCase().includes("abort") || String(error || "").toLowerCase().includes("timeout")) {
            throw new Error("PK-Sim simulation timed out (180s)");
          }
          throw error;
        } finally {
          if (timer) clearTimeout(timer);
        }
        if (!res.ok) {
          const rawText = await res.text();
          try {
            const parsed = JSON.parse(rawText);
            throw new Error(parsed.detail || parsed.error || rawText);
          } catch (parseError) {
            throw new Error(rawText);
          }
        }
        const payload = await res.json();
        const data = payload.data || payload;
        renderPkSimVmResult(data);
        safeSetDetail(JSON.stringify(data, null, 2));
        setPkSimVmStatus(`PK-Sim simulation completed: ${data.run_id || "completed"}`, "ok");
      } catch (error) {
        if (pksimVmStatus) pksimVmStatus.textContent = "Failed";
        if (pksimVmResultStatus) pksimVmResultStatus.textContent = "Failed";
        renderNoteChips("pksim-vm-notes", [`PK-Sim simulation failed: ${String(error)}`]);
        safeSetDetail(`PK-Sim simulation failed

${String(error)}

${(error && error.stack) ? error.stack : ""}`);
        setPkSimVmStatus(`PK-Sim simulation failed: ${String(error)}`, "error");
      } finally {
        pksimVmSubmitBtn.disabled = false;
        pksimVmSubmitBtn.textContent = pksimVmSubmitBtn.dataset.oldText || "Run PK-Sim Simulation";
      }
    }

    function renderOverlayChart(seriesList) {
      const svg = document.getElementById("compare-chart");
      if (!svg) return;
      if (!seriesList || !seriesList.length) {
        svg.innerHTML = "";
        return;
      }
      const width = 720;
      const height = 320;
      const margin = { top: 18, right: 24, bottom: 44, left: 58 };
      const allPoints = seriesList.flatMap(item => item.series || []);
      const xs = allPoints.map(point => Number(point.time_h || 0));
      const ys = allPoints.map(point => Number(point.conc_ng_ml || 0));
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const maxY = Math.max(...ys, 1) * 1.12;
      const xSpan = Math.max(maxX - minX, 1);
      const ySpan = Math.max(maxY, 1);
      const projectX = value => margin.left + ((Number(value) - minX) / xSpan) * (width - margin.left - margin.right);
      const projectY = value => height - margin.bottom - (Number(value) / ySpan) * (height - margin.top - margin.bottom);
      const xTicks = Array.from({ length: 6 }, (_, index) => minX + (xSpan / 5) * index);
      const yTicks = Array.from({ length: 5 }, (_, index) => (ySpan / 4) * index);
      const grid = [
        ...xTicks.map(value => {
          const x = projectX(value);
          return `
            <line x1="${x}" y1="${margin.top}" x2="${x}" y2="${height - margin.bottom}" stroke="rgba(30,42,47,0.08)" stroke-width="1"/>
            <text x="${x}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#62747a">${formatNumber(value, 0)}</text>
          `;
        }),
        ...yTicks.map(value => {
          const y = projectY(value);
          return `
            <line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" stroke="rgba(30,42,47,0.08)" stroke-width="1"/>
            <text x="${margin.left - 10}" y="${y + 4}" text-anchor="end" font-size="11" fill="#62747a">${formatNumber(value, 1)}</text>
          `;
        })
      ].join("");
      const lines = seriesList.map(item => {
        const points = (item.series || []).map(point => `${projectX(point.time_h).toFixed(1)},${projectY(point.conc_ng_ml).toFixed(1)}`).join(" ");
        return `<polyline fill="none" stroke="${item.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${points}"></polyline>`;
      }).join("");
      svg.innerHTML = `
        <rect x="${margin.left}" y="${margin.top}" width="${width - margin.left - margin.right}" height="${height - margin.top - margin.bottom}" rx="12" fill="rgba(255,255,255,0.62)"/>
        ${grid}
        ${lines}
        <text x="${width / 2}" y="${height - 8}" text-anchor="middle" font-size="12" fill="#62747a">时间 Time (h)</text>
        <text x="18" y="${height / 2}" transform="rotate(-90 18 ${height / 2})" text-anchor="middle" font-size="12" fill="#62747a">浓度 Concentration (ng/mL)</text>
      `;
      bindSeriesHover(
        svg,
        seriesList.map(item => ({
          label: item.label,
          color: item.color,
          points: (item.series || []).map(point => ({ x: Number(point.time_h || 0), y: Number(point.conc_ng_ml || 0) }))
        })),
        projectX,
        projectY,
        "时间",
        value => `${formatNumber(value, 2)} ng/mL`
      );
    }

    function renderComparisonLegend(items) {
      const holder = document.getElementById("compare-legend");
      if (!holder) return;
      if (!items || !items.length) {
        holder.innerHTML = '<div class="lit-item">当前没有对比结果。</div>';
        return;
      }
      holder.innerHTML = items.map(item => `
        <div class="legend-row">
          <span class="legend-swatch" style="background:${item.color}"></span>
          <div>
            <div class="legend-main">${item.label}</div>
            <div class="legend-meta">${item.population}</div>
          </div>
          <div class="legend-meta">Cmax ${formatNumber(item.cmax, 1)}</div>
          <div class="legend-meta">AUC ${formatNumber(item.auc, 1)}</div>
        </div>
      `).join("");
    }

    function renderDistributionBand(distribution) {
      const svg = document.getElementById("distribution-chart");
      if (!svg) return;
      if (!distribution || !distribution.available || !distribution.percentile_curve || !distribution.percentile_curve.length) {
        svg.innerHTML = "";
        renderNoteChips("distribution-notes", ["当前没有可用的人群分布结果"]);
        return;
      }
      const series = distribution.percentile_curve;
      const width = 720;
      const height = 320;
      const margin = { top: 18, right: 24, bottom: 44, left: 58 };
      const xs = series.map(point => Number(point.time_h || 0));
      const maxY = Math.max(...series.map(point => Number(point.p90_conc_ng_ml || 0)), 1) * 1.12;
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const xSpan = Math.max(maxX - minX, 1);
      const projectX = value => margin.left + ((Number(value) - minX) / xSpan) * (width - margin.left - margin.right);
      const projectY = value => height - margin.bottom - (Number(value) / maxY) * (height - margin.top - margin.bottom);
      const xTicks = Array.from({ length: 6 }, (_, index) => minX + (xSpan / 5) * index);
      const yTicks = Array.from({ length: 5 }, (_, index) => (maxY / 4) * index);
      const bandUpper = series.map(point => `${projectX(point.time_h).toFixed(1)},${projectY(point.p90_conc_ng_ml).toFixed(1)}`).join(" ");
      const bandLower = [...series].reverse().map(point => `${projectX(point.time_h).toFixed(1)},${projectY(point.p10_conc_ng_ml).toFixed(1)}`).join(" ");
      const medianLine = series.map(point => `${projectX(point.time_h).toFixed(1)},${projectY(point.p50_conc_ng_ml).toFixed(1)}`).join(" ");
      const grid = [
        ...xTicks.map(value => {
          const x = projectX(value);
          return `<line x1="${x}" y1="${margin.top}" x2="${x}" y2="${height - margin.bottom}" stroke="rgba(30,42,47,0.08)" stroke-width="1"/><text x="${x}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#62747a">${formatNumber(value, 0)}</text>`;
        }),
        ...yTicks.map(value => {
          const y = projectY(value);
          return `<line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" stroke="rgba(30,42,47,0.08)" stroke-width="1"/><text x="${margin.left - 10}" y="${y + 4}" text-anchor="end" font-size="11" fill="#62747a">${formatNumber(value, 1)}</text>`;
        })
      ].join("");
      svg.innerHTML = `
        <rect x="${margin.left}" y="${margin.top}" width="${width - margin.left - margin.right}" height="${height - margin.top - margin.bottom}" rx="12" fill="rgba(255,255,255,0.62)"/>
        ${grid}
        <polygon points="${bandUpper} ${bandLower}" fill="rgba(32,77,99,0.16)"></polygon>
        <polyline fill="none" stroke="#204d63" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${medianLine}"></polyline>
        <text x="${width / 2}" y="${height - 8}" text-anchor="middle" font-size="12" fill="#62747a">时间 Time (h)</text>
        <text x="18" y="${height / 2}" transform="rotate(-90 18 ${height / 2})" text-anchor="middle" font-size="12" fill="#62747a">浓度 Concentration (ng/mL)</text>
      `;
      bindSeriesHover(
        svg,
        [
          { label: "P10", color: "#8db1bc", points: series.map(point => ({ x: Number(point.time_h || 0), y: Number(point.p10_conc_ng_ml || 0) })) },
          { label: "P50", color: "#204d63", points: series.map(point => ({ x: Number(point.time_h || 0), y: Number(point.p50_conc_ng_ml || 0) })) },
          { label: "P90", color: "#5b8a96", points: series.map(point => ({ x: Number(point.time_h || 0), y: Number(point.p90_conc_ng_ml || 0) })) },
        ],
        projectX,
        projectY,
        "时间",
        value => `${formatNumber(value, 2)} ng/mL`
      );
      renderNoteChips("distribution-notes", [
        `虚拟人群 n=${distribution.population_n}`,
        `Cmax P50 ${formatNumber(distribution.summary.Cmax_p50, 2)} ng/mL`,
        `AUC P50 ${formatNumber(distribution.summary.AUC_p50, 2)} ng*h/mL`,
        `后端 ${distribution.model_backend.backend}`
      ]);
    }

    function renderDDIMatrix(items) {
      const holder = document.getElementById("ddi-matrix");
      if (!holder) return;
      if (!items || !items.length) {
        holder.innerHTML = '<div class="lit-item">当前没有联用药情景。可在表单中导入联用药 CSV。</div>';
        return;
      }
      holder.innerHTML = items.map(item => `
        <div class="legend-row">
          <span class="legend-swatch" style="background:${item.classification === 'high' ? '#b13b2e' : item.classification === 'moderate' ? '#c7851a' : '#1e7f5c'}"></span>
          <div>
            <div class="legend-main">${item.drug}</div>
            <div class="legend-meta">${item.mechanism} / ${item.enzyme} / ${item.strength}</div>
          </div>
          <div class="legend-meta">AUC ${formatNumber(item.predicted_delta_auc, 2)}x</div>
          <div class="legend-meta">${String(item.classification || '-').toUpperCase()}</div>
        </div>
      `).join("");
    }

    async function updateComparisonBoard(requestPayload) {
      const compareNotes = document.getElementById("compare-notes");
      const compareLegend = document.getElementById("compare-legend");
      if (compareNotes) compareNotes.innerHTML = '<div class="note-chip">正在生成多情景真实对比...</div>';
      if (compareLegend) compareLegend.innerHTML = '<div class="lit-item">正在调用真实后端生成对比。</div>';
      setRunOverlayState(
        "compare",
        "正在生成多人群对比",
        "系统正在调用真实 PBPK 后端，叠加成人、老年、肾损伤、肝损伤与妊娠情景。"
      );
      try {
        const cacheKey = JSON.stringify(requestPayload);
        let results = compareCache.get(cacheKey);
        if (!results) {
          const scenarios = buildComparisonRequests(requestPayload);
          const collected = [];
          for (const scenario of scenarios) {
            try {
              const detailData = await analyzePayload(scenario.payload, false, 45000);
              const step6 = detailData.result.step6_pbpk;
              collected.push({
                label: scenario.label,
                color: scenario.color,
                population: populationSummary(step6.scenario.population),
                cmax: step6.pk_parameters.Cmax.value,
                auc: step6.pk_parameters.AUC0_t.value,
                series: step6.concentration_time_curve
              });
            } catch (error) {
              // skip timed-out scenario to keep UI responsive
            }
          }
          results = collected;
          compareCache.set(cacheKey, results);
        }
        renderOverlayChart(results);
        renderComparisonLegend(results);
        renderNoteChips("compare-notes", [
          "同化合物同剂量",
          "各情景重新调用真实 PBPK 后端",
          "用于快速比较敏感人群暴露变化"
        ]);
      } catch (error) {
        if (compareNotes) compareNotes.innerHTML = `<div class="note-chip">对比生成失败: ${String(error)}</div>`;
        if (compareLegend) compareLegend.innerHTML = '<div class="lit-item">对比图暂时不可用。</div>';
      }
    }

    function renderClinicalChart(options) {
      const {
        svgId,
        series,
        xKey,
        yKey,
        color,
        fillColor,
        xLabel,
        yLabel,
        referenceLines = [],
        marker,
        observationPoints = [],
        observationYKey = null,
        axisDigits = 1
      } = options;
      const svg = document.getElementById(svgId);
      if (!svg) return [];
      if (!series || !series.length) {
        svg.innerHTML = "";
        return [];
      }
      const width = 720;
      const height = 320;
      const margin = { top: 18, right: 24, bottom: 44, left: 58 };
      const xs = series.map(point => Number(point[xKey] || 0));
      const ys = series.map(point => Number(point[yKey] || 0));
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const rawSeriesMax = Math.max(...ys, 0);
      const candidateRefs = referenceLines
        .filter(line => Number.isFinite(Number(line.value)))
        .map(line => Number(line.value));
      const scaleRefs = candidateRefs.filter(value => value <= Math.max(rawSeriesMax * 3, 1));
      const maxY = Math.max(rawSeriesMax, ...scaleRefs, 1) * 1.12;
      const minY = 0;
      const xSpan = Math.max(maxX - minX, 1);
      const ySpan = Math.max(maxY - minY, 1);
      const projectX = value => margin.left + ((Number(value) - minX) / xSpan) * (width - margin.left - margin.right);
      const projectY = value => height - margin.bottom - ((Number(value) - minY) / ySpan) * (height - margin.top - margin.bottom);
      const polyline = series.map(point => `${projectX(point[xKey]).toFixed(1)},${projectY(point[yKey]).toFixed(1)}`).join(" ");
      const areaPath = `${polyline} ${projectX(series[series.length - 1][xKey]).toFixed(1)},${height - margin.bottom} ${projectX(series[0][xKey]).toFixed(1)},${height - margin.bottom}`;
      const xTicks = Array.from({ length: 6 }, (_, index) => minX + (xSpan / 5) * index);
      const yTicks = Array.from({ length: 5 }, (_, index) => minY + (ySpan / 4) * index);
      const visibleRefs = referenceLines.filter(line => Number.isFinite(Number(line.value)) && Number(line.value) <= maxY);
      const hiddenRefs = referenceLines.filter(line => Number.isFinite(Number(line.value)) && Number(line.value) > maxY);

      const grid = [
        ...xTicks.map(value => {
          const x = projectX(value);
          return `
            <line x1="${x}" y1="${margin.top}" x2="${x}" y2="${height - margin.bottom}" stroke="rgba(30,42,47,0.08)" stroke-width="1"/>
            <text x="${x}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#62747a">${formatNumber(value, 0)}</text>
          `;
        }),
        ...yTicks.map(value => {
          const y = projectY(value);
          return `
            <line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" stroke="rgba(30,42,47,0.08)" stroke-width="1"/>
            <text x="${margin.left - 10}" y="${y + 4}" text-anchor="end" font-size="11" fill="#62747a">${formatNumber(value, axisDigits)}</text>
          `;
        })
      ].join("");

      const referenceMarkup = visibleRefs.map(line => {
        const y = projectY(line.value);
        return `
          <line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" stroke="${line.color || '#b13b2e'}" stroke-width="1.5" stroke-dasharray="6 5"/>
          <text x="${width - margin.right - 6}" y="${y - 6}" text-anchor="end" font-size="11" fill="${line.color || '#b13b2e'}">${line.label}</text>
        `;
      }).join("");

      const markerMarkup = marker && Number.isFinite(Number(marker.value)) ? `
        <circle cx="${projectX(marker.x)}" cy="${projectY(marker.value)}" r="5" fill="${marker.color || color}" stroke="white" stroke-width="2"/>
        <text x="${Math.min(projectX(marker.x) + 10, width - margin.right - 40)}" y="${Math.max(projectY(marker.value) - 10, margin.top + 12)}" font-size="11" fill="${marker.color || color}">${marker.label}</text>
      ` : "";
      const observationMarkup = observationYKey ? observationPoints
        .filter(item => Number.isFinite(Number(item.time_h)) && Number.isFinite(Number(item[observationYKey])))
        .map(item => `
          <circle cx="${projectX(item.time_h)}" cy="${projectY(item[observationYKey])}" r="4.5" fill="#ffffff" stroke="${color}" stroke-width="2"/>
        `).join("") : "";

      svg.innerHTML = `
        <rect x="${margin.left}" y="${margin.top}" width="${width - margin.left - margin.right}" height="${height - margin.top - margin.bottom}" rx="12" fill="rgba(255,255,255,0.62)"/>
        ${grid}
        ${referenceMarkup}
        <polyline fill="${fillColor || 'rgba(32,77,99,0.12)'}" stroke="none" points="${areaPath}"></polyline>
        <polyline fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="${polyline}"></polyline>
        ${observationMarkup}
        ${markerMarkup}
        <text x="${width / 2}" y="${height - 8}" text-anchor="middle" font-size="12" fill="#62747a">${xLabel}</text>
        <text x="18" y="${height / 2}" transform="rotate(-90 18 ${height / 2})" text-anchor="middle" font-size="12" fill="#62747a">${yLabel}</text>
      `;
      const hoverGroups = [{
        label: color === "#a83d32" ? "效应曲线" : "主曲线",
        color,
        points: series.map(point => ({ x: Number(point[xKey] || 0), y: Number(point[yKey] || 0) })),
      }];
      if (observationYKey) {
        const obsPoints = observationPoints
          .filter(item => Number.isFinite(Number(item.time_h)) && Number.isFinite(Number(item[observationYKey])))
          .map(item => ({ x: Number(item.time_h || 0), y: Number(item[observationYKey] || 0) }));
        if (obsPoints.length) {
          hoverGroups.push({ label: "观测点", color: "#d68b32", points: obsPoints });
        }
      }
      bindSeriesHover(svg, hoverGroups, projectX, projectY, "时间", value => `${formatNumber(value, axisDigits)} ${yLabel.includes('%') ? '%' : yLabel.includes('Concentration') ? 'ng/mL' : ''}`.trim());
      return hiddenRefs.map(item => `${item.label} 超出当前图窗`);
    }

    function riskBadge(risk) {
      const safe = (risk || "unknown").toLowerCase();
      const cls = safe === "green" ? "risk-green" : safe === "red" ? "risk-red" : "risk-yellow";
      const label = safe === "green"
        ? "低风险 Low"
        : safe === "red"
          ? "高风险 High"
          : safe === "yellow"
            ? "中风险 Medium"
            : "未知 Unknown";
      return `<span class="badge ${cls}">${label}</span>`;
    }

    function taskStatusBadge(status) {
      const safe = String(status || "queued").toLowerCase();
      const cls = safe === "completed" ? "risk-green" : safe === "failed" || safe === "interrupted" ? "risk-red" : "risk-yellow";
      const label = safe === "completed"
        ? "已完成 Completed"
        : safe === "failed"
          ? "失败 Failed"
          : safe === "running"
            ? "运行中 Running"
            : safe === "queued"
              ? "排队中 Queued"
              : "中断 Interrupted";
      return `<span class="badge ${cls}">${label}</span>`;
    }

    function populationSummary(population) {
      if (!population) return "-";
      const bits = [population.label || population.preset || "-"];
      if (population.sex_label) bits.push(`性别 ${population.sex_label}`);
      if (population.ethnicity_label) bits.push(`人群来源 ${population.ethnicity_label}`);
      if (population.renal_impairment) bits.push("肾损伤");
      if (population.hepatic_impairment) bits.push("肝损伤");
      if (population.pregnant) bits.push("妊娠");
      return bits.join(" | ");
    }

    function renderLiterature(snapshot) {
      const holder = document.getElementById("literature-list");
      if (!holder) return;
      const articles = [
        ...((snapshot && snapshot.ddi_articles) || []).map(item => ({ ...item, group: "DDI 文献" })),
        ...((snapshot && snapshot.safety_articles) || []).map(item => ({ ...item, group: "安全性文献" }))
      ];
      if (!articles.length) {
        holder.innerHTML = '<div class="lit-item">当前分析没有抓到可用的 PubMed 文献快照。</div>';
        return;
      }
      holder.innerHTML = articles.map(item => `
        <div class="lit-item">
          <div class="stat-label">${item.group}</div>
          <div><a href="${item.url}" target="_blank" rel="noreferrer">${item.title || item.url}</a></div>
          <div class="mono">${item.source || "-"} | ${item.pubdate || "-"}</div>
        </div>
      `).join("");
    }

    function renderRuntimePanel(runtime) {
      if (!runtime) return;
      currentRuntimeInfo = {
        ...(currentRuntimeInfo || {}),
        ...runtime,
        admet: { ...((currentRuntimeInfo || {}).admet || {}), ...(runtime.admet || {}) },
        pbpk: { ...((currentRuntimeInfo || {}).pbpk || {}), ...(runtime.pbpk || {}) },
        pkpd: { ...((currentRuntimeInfo || {}).pkpd || {}), ...(runtime.pkpd || {}) },
        gpus: runtime.gpus && runtime.gpus.length ? runtime.gpus : ((currentRuntimeInfo || {}).gpus || []),
      };
      runtime = currentRuntimeInfo;
      const admet = runtime.admet || {};
      const gpus = runtime.gpus || [];
      if (runtimeAdmetDevice) {
        runtimeAdmetDevice.textContent = `${String(admet.backend || "-").toUpperCase()} / ${String(admet.device || "cpu").toUpperCase()}`;
      }
      if (runtimeAdmetBatch) {
        runtimeAdmetBatch.textContent = `Workers ${admet.num_workers || 0} | 并行 GPU ${((admet.batch_parallel_gpus || []).join(" / ")) || "-"}`;
      }
      if (runtimeBatchMode) {
        runtimeBatchMode.textContent = (admet.batch_parallel_gpus || []).length > 1 ? "GPU0 + GPU1 并行" : "单设备模式";
      }
      if (runtimeBatchDetail) {
        runtimeBatchDetail.textContent = (admet.batch_parallel_gpus || []).length > 1
          ? "批量 ADMET 会按两张 T4 分片并行筛选"
          : "当前只启用单 GPU 或 CPU 回退";
      }
      if (!runtimeGpuCards) return;
      if (!gpus.length) {
        runtimeGpuCards.innerHTML = `
          <div class="runtime-chip">
            <div class="stat-label">GPU</div>
            <strong>未检测到</strong>
            <div class="runtime-meta">当前没有可用显卡</div>
          </div>
        `;
        return;
      }
      runtimeGpuCards.innerHTML = gpus.map(gpu => `
        <div class="runtime-chip">
          <div class="stat-label">GPU ${gpu.index}</div>
          <strong>${gpu.name}</strong>
          <div class="runtime-meta">驱动 ${gpu.driver_version || '-'} | 显存 ${gpu.memory_used_mib}/${gpu.memory_total_mib} MiB | 利用率 ${gpu.utilization_pct}%</div>
        </div>
      `).join("");
    }

    async function setSummary(detailData) {
      const summary = detailData.summary;
      const result = detailData.result;
      const step6 = result.step6_pbpk;
      const step7 = result.step7_pkpd;
      const step8 = result.step8_ddi;
      const fitSummary = result.fit_summary || {};
      const observationFit = result.observation_fit || {};
      const virtualPopulation = result.virtual_population || {};
      const pbpkParams = step6.pk_parameters;
      const pbpkBackend = step6.model_backend || {};
      const tissueExposure = step6.tissue_exposure_summary || {};
      const giSegments = step6.gi_segment_summary || {};
      const compoundPbpk = step6.compound_specific_parameters || {};
      const pbpkCompartments = pbpkBackend.compartments || [];
      const pkpdDose = step7.dose_optimization;
      const pkpdModel = step7.model || {};
      const peakConc = step6.concentration_time_curve.reduce((best, item) => Number(item.conc_ng_ml || 0) > Number(best.conc_ng_ml || 0) ? item : best, step6.concentration_time_curve[0] || { time_h: 0, conc_ng_ml: 0 });
      const peakEffect = step7.effect_time_curve.reduce((best, item) => Number(item.effect_pct || 0) > Number(best.effect_pct || 0) ? item : best, step7.effect_time_curve[0] || { time_h: 0, effect_pct: 0 });

      document.getElementById("risk-badge-wrap").innerHTML = riskBadge(summary.overall_risk);
      document.getElementById("result-regimen").textContent = summary.recommended_regimen;
      document.getElementById("result-admet-score").textContent = String(summary.admet_score);
      document.getElementById("result-run-id").textContent = summary.run_id;
      setResultLinks(summary.run_id);
      document.getElementById("result-population").textContent = populationSummary(step6.scenario.population);
      document.getElementById("result-cmax").textContent = `${pbpkParams.Cmax.value} ng/mL`;
      document.getElementById("result-auc").textContent = `${pbpkParams.AUC0_t.value} ng*h/mL`;
      document.getElementById("result-attain").textContent = formatPercent(pkpdDose.target_attainment, 0);
      document.getElementById("hero-admet").textContent = `${result.step5_admet.model_backend.backend} / ${String(result.step5_admet.model_backend.device || "cpu").toUpperCase()}`;
      document.getElementById("hero-pbpk").textContent = pbpkBackend.model_type || pbpkBackend.backend;
      document.getElementById("hero-pkpd").textContent = step7.model_backend.backend;
      document.getElementById("pbpk-engine").textContent = `${pbpkBackend.backend || "-"} ${pbpkBackend.engine || ""} ? ${pbpkBackend.model_type || "whole-body PBPK"}`.trim();
      document.getElementById("pkpd-engine").textContent = `${step7.model_backend.backend} ${step7.model_backend.engine || ""}`.trim();
      setRunOverlayState(
        "render",
        "正在刷新结果面板",
        "主分析已完成，系统正在整理指标卡、曲线、拟合结果和 DDI 矩阵。"
      );

      renderMetricStrip("pbpk-metrics", [
        { label: "模型", value: pbpkBackend.model_type || "whole-body PBPK", note: pbpkBackend.parameterization || "compound-specific" },
        { label: "器官/组织", value: `${pbpkCompartments.length || "-"}`, note: (pbpkCompartments.slice(0, 4).join(" / ") || "gut / liver / kidney / tissue") },
        { label: "口服生物利用度 F", value: formatPercent(pbpkParams.F, 0), note: "来自 STEP 5 + STEP 6 联合推断" },
        { label: "Tmax", value: `${formatNumber(pbpkParams.Tmax.value, 1)} h`, note: "峰浓度出现时间" },
        { label: "半衰期", value: `${formatNumber(pbpkParams.t_half.value, 2)} h`, note: "终末消除半衰期" },
        { label: "累积比 Rac", value: formatNumber(pbpkParams.Rac.value, 2), note: "重复给药稳态倾向" },
        { label: "肝脏峰浓度", value: `${formatNumber(tissueExposure.max_liver_ng_ml, 2)} ng/mL`, note: "whole-body tissue exposure" },
        { label: "肾脏峰浓度", value: `${formatNumber(tissueExposure.max_kidney_ng_ml, 2)} ng/mL`, note: "renal tissue exposure" },
        { label: "脂肪峰浓度", value: `${formatNumber(tissueExposure.max_fat_ng_ml, 2)} ng/mL`, note: "fat distribution exposure" },
        { label: "\u80c3\u5185\u6700\u9ad8\u91cf", value: `${formatNumber(giSegments.max_stomach_mg, 3)} mg`, note: "stomach luminal amount" },
        { label: "\u5c0f\u80a0\u6700\u9ad8\u91cf", value: `${formatNumber(Math.max(Number(giSegments.max_duodenum_mg || 0), Number(giSegments.max_jejunum_mg || 0), Number(giSegments.max_ileum_mg || 0)), 3)} mg`, note: "duodenum / jejunum / ileum" },
        { label: "\u5927\u80a0\u6700\u9ad8\u91cf", value: `${formatNumber(giSegments.max_colon_mg, 3)} mg`, note: "colon luminal amount" },
        { label: "\u6700\u5927\u5438\u6536\u901f\u7387", value: `${formatNumber(giSegments.max_absorption_rate_mg_h, 3)} mg/h`, note: "GI absorption into portal liver" },
        { label: "参数来源", value: compoundPbpk.compound_name || summary.compound_name, note: compoundPbpk.parameter_source || "ADMET/descriptor-derived" }
      ]);
      renderMetricStrip("pkpd-metrics", [
        { label: "EC50", value: `${formatNumber(pkpdModel.EC50 && pkpdModel.EC50.value, 2)} ng/mL`, note: "50% Emax 对应浓度" },
        { label: "治疗指数 TI", value: formatNumber(pkpdDose.therapeutic_index, 2), note: "MTC / MEC" },
        { label: "起始剂量", value: `${formatNumber(pkpdDose.recommended_starting_dose_mg, 1)} mg`, note: "模型建议起始剂量" },
        { label: "最大效应 Emax", value: `${formatNumber(pkpdModel.Emax && pkpdModel.Emax.value, 0)}%`, note: "模型最大药效响应" }
      ]);
      renderMetricStrip("ddi-metrics", [
        { label: "DDI 等级", value: String(step8.perpetrator_risk.classification || "-").toUpperCase(), note: "基于 R 值和 AUC 变化" },
        { label: "R 值", value: formatNumber(step8.perpetrator_risk.R_value, 2), note: "酶抑制触发风险指标" },
        { label: "AUC 倍数", value: `${formatNumber(step8.perpetrator_risk.delta_auc, 2)}x`, note: "预测暴露变化倍数" },
        { label: "hERG 安全窗", value: formatNumber(step8.organ_safety.hERG_safety_margin, 2), note: `DILI ${String(step8.organ_safety.DILI_risk || "-").toUpperCase()}` }
      ]);
      renderFitMetrics("pk-fit-metrics", observationFit.pk_fit, "PK");
      renderFitMetrics("pd-fit-metrics", observationFit.pd_fit, "PD");

      const pbpkHiddenNotes = renderClinicalChart({
        svgId: "pbpk-chart",
        series: step6.concentration_time_curve,
        xKey: "time_h",
        yKey: "conc_ng_ml",
        color: "#0f6c78",
        fillColor: "rgba(15,108,120,0.14)",
        xLabel: "时间 Time (h)",
        yLabel: "浓度 Concentration (ng/mL)",
        referenceLines: [
          { label: `MEC ${formatNumber(pkpdDose.MEC.value, 1)}`, value: Number(pkpdDose.MEC.value), color: "#c7851a" },
          { label: `MTC ${formatNumber(pkpdDose.MTC.value, 1)}`, value: Number(pkpdDose.MTC.value), color: "#b13b2e" }
        ],
        marker: {
          x: peakConc.time_h,
          value: peakConc.conc_ng_ml,
          label: `Cmax ${formatNumber(peakConc.conc_ng_ml, 1)} @ ${formatNumber(peakConc.time_h, 1)}h`,
          color: "#0f6c78"
        },
        observationPoints: observationFit.overlay_points || [],
        observationYKey: "obs_conc_ng_ml",
        axisDigits: 1
      });
      renderNoteChips("pbpk-notes", [
        `后端 ${pbpkBackend.backend || "-"} ${pbpkBackend.engine || ""}`.trim(),
        `模型 ${pbpkBackend.model_type || "whole-body PBPK"}`,
        `AUC ${formatNumber(pbpkParams.AUC0_t.value, 2)} ng*h/mL`,
        `CL ${formatNumber(pbpkParams.CL.value, 2)} L/h`,
        compoundPbpk.parameter_source ? `参数 ${compoundPbpk.parameter_source}` : "compound-specific parameters",
        giSegments.transit_absorption ? "GI \u8def\u5f84: \u80c3 / \u5c0f\u80a0\u5206\u6bb5 / \u7ed3\u80a0 / \u809d / \u4f53\u5faa\u73af" : "GI \u5206\u6bb5\u5f85\u8ba1\u7b97",
        fitSummary.pk_fit_applied ? `PK 拟合 ${JSON.stringify(fitSummary.pk_overrides || {})}` : "未启用 PK 拟合",
        observationFit.pk_fit ? `PK RMSE ${formatNumber(observationFit.pk_fit.RMSE && observationFit.pk_fit.RMSE.value, 2)}` : "未导入 PK 观测点",
        ...pbpkHiddenNotes
      ]);

      const halfEmax = Number((pkpdModel.Emax && pkpdModel.Emax.value) || 100) / 2;
      const pkpdHiddenNotes = renderClinicalChart({
        svgId: "pkpd-chart",
        series: step7.effect_time_curve,
        xKey: "time_h",
        yKey: "effect_pct",
        color: "#a83d32",
        fillColor: "rgba(168,61,50,0.12)",
        xLabel: "时间 Time (h)",
        yLabel: "效应 Effect (%)",
        referenceLines: [
          { label: `EC50 对应效应 ${formatNumber(halfEmax, 0)}%`, value: halfEmax, color: "#c7851a" }
        ],
        marker: {
          x: peakEffect.time_h,
          value: peakEffect.effect_pct,
          label: `Emax ${formatNumber(peakEffect.effect_pct, 1)}%`,
          color: "#a83d32"
        },
        observationPoints: observationFit.overlay_points || [],
        observationYKey: "obs_effect_pct",
        axisDigits: 0
      });
      renderNoteChips("pkpd-notes", [
        `真实后端 ${step7.model_backend.backend}`,
        `目标达成率 ${formatPercent(pkpdDose.target_attainment, 0)}`,
        `推荐方案 ${pkpdDose.recommended_regimen}`,
        fitSummary.pd_fit_applied ? `PD 拟合 ${JSON.stringify(fitSummary.pd_overrides || {})}` : "未启用 PD 拟合",
        observationFit.pd_fit ? `PD RMSE ${formatNumber(observationFit.pd_fit.RMSE && observationFit.pd_fit.RMSE.value, 2)}` : "未导入 PD 观测点",
        ...pkpdHiddenNotes
      ]);
      renderRuntimePanel({
        admet: result.step5_admet.model_backend,
        pbpk: step6.model_backend,
        pkpd: step7.model_backend,
        gpus: []
      });

      renderMonitoring(step8.recommended_monitoring);
      renderResources(step8.external_literature);
      renderDDIMatrix((step8.mechanistic_matrix && step8.mechanistic_matrix.scenarios) || []);
      renderLiterature(step8.literature_snapshot);
      renderDistributionBand(virtualPopulation);
      detail.textContent = JSON.stringify(detailData, null, 2);
      if (detailData && detailData.request) {
        updateComparisonBoard(detailData.request).catch(error => {
          const compareNotes = document.getElementById("compare-notes");
          if (compareNotes) compareNotes.innerHTML = `<div class="note-chip">Comparison failed: ${String(error)}</div>`;
        });
      }
    }

    async function loadStatus() {
      const res = await apiFetch("/health");
      const data = await res.json();
      document.getElementById("svc-status").textContent = data.ok ? "在线" : "离线";
      document.getElementById("svc-runs").textContent = String(data.runs || 0);
    }

    async function loadRuntime() {
      const res = await apiFetch("/api/v1/pipeline58/runtime");
      const payload = await res.json();
      renderRuntimePanel(payload.data || {});
    }

    async function loadProjects() {
      const res = await apiFetch("/api/v1/pipeline58/projects");
      const payload = await res.json();
      renderProjects(payload.data || []);
    }

    async function loadAudit() {
      const res = await apiFetch("/api/v1/pipeline58/audit");
      const payload = await res.json();
      renderAudit(payload.data || []);
    }

    async function loadRuns() {
      const res = await apiFetch("/api/v1/pipeline58/runs");
      const payload = await res.json();
      const items = payload.data || [];
      runsList.innerHTML = "";
      if (!items.length) {
        runsList.innerHTML = '<div class="run-item">还没有保存的分析记录。</div>';
        return;
      }
      for (const item of items) {
        const div = document.createElement("div");
        div.className = "run-item";
        div.innerHTML = `
          <div class="run-head">
            <strong>${item.compound_name}</strong>
            ${riskBadge(item.overall_risk)}
          </div>
          <div>${item.target_name}</div>
          <div class="stat-label">${item.created_at}</div>
          <div class="mono">${item.run_id}</div>
        `;
        div.addEventListener("click", () => loadRun(item.run_id));
        runsList.appendChild(div);
      }
    }

    async function loadRun(runId) {
      const res = await apiFetch(`/api/v1/pipeline58/runs/${runId}`);
      const payload = await res.json();
      await setSummary(payload.data);
      closeHistoryDrawer();
    }

    function closeAllDrawers() {
      historyDrawer.classList.remove("open");
      projectsDrawer.classList.remove("open");
      auditDrawer.classList.remove("open");
      historyOverlay.classList.remove("open");
    }

    function openHistoryDrawer() {
      closeAllDrawers();
      historyDrawer.classList.add("open");
      historyOverlay.classList.add("open");
    }

    async function openProjectsDrawer() {
      closeAllDrawers();
      projectsDrawer.classList.add("open");
      historyOverlay.classList.add("open");
      await loadProjects();
    }

    async function openAuditDrawer() {
      closeAllDrawers();
      auditDrawer.classList.add("open");
      historyOverlay.classList.add("open");
      await loadAudit();
    }

    function closeHistoryDrawer() {
      closeAllDrawers();
    }

    async function ensureAuthenticated() {
      try {
        const res = await apiFetch("/api/v1/auth/me");
        const payload = await res.json();
        setCurrentUser(payload.data || null);
        closeAuthScreen();
        return true;
      } catch (error) {
        setCurrentUser(null);
        openAuthScreen("请使用系统账号登录。");
        return false;
      }
    }

    async function bootDashboard() {
      const ok = await ensureAuthenticated();
      setResultLinks("");
      setTaskLinks("");
      if (!ok) return;
      const settled = await Promise.allSettled([loadStatus(), loadRuns(), loadRuntime(), loadTasks()]);
      const failed = settled.find(item => item.status === "rejected");
      if (failed && failed.reason) {
        setFormStatus(`部分面板加载失败：${String(failed.reason)}`, "error");
      }
    }

    if (form && submitBtn) {
      form.addEventListener("input", refreshPkSimLink);
      form.addEventListener("change", refreshPkSimLink);
      refreshPkSimLink();
      submitBtn.dataset.bound = "1";
      submitBtn.addEventListener("click", () => {
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        submitBtn.disabled = true;
        submitBtn.textContent = "分析中...";
        setFormStatus("已提交请求，正在启动主分析。");
        try {
          const fd = new FormData(form);
          let body = makeRequestBody(fd);
          body = ensureDefaultSmiles(body);
          const validationError = validateRequestBody(body);
          if (validationError) {
            safeSetDetail(validationError);
            setFormStatus(validationError, "error");
            return;
          }
          openRunOverlay();
          await waitForPaint();
          const data = await analyzePayload(body, true);
          safeSetDetail(JSON.stringify(data, null, 2));
          try {
            await setSummary(data);
          } catch (renderError) {
            console.error("setSummary failed", renderError);
            applySummaryFallback(data);
            setFormStatus(`Run completed but render failed: ${String(renderError)}`, "error");
            await loadStatus();
            await loadRuns();
            return;
          }
          const savedBaseline = saveActiveBaselineAfterRun();
          await loadStatus();
          await loadRuns();
          setFormStatus(savedBaseline ? `Run completed: ${data.summary.run_id} | 已保存到 ${savedBaseline.label}` : `Run completed: ${data.summary.run_id}`, "ok");
        } catch (error) {
          safeSetDetail(`Analyze failed\n\n${String(error)}\n\n${(error && error.stack) ? error.stack : ""}`);
          setFormStatus(`运行失败：${String(error)}`, "error");
        } finally {
          await closeRunOverlay();
          submitBtn.disabled = false;
          submitBtn.textContent = "运行 STEP 5-8";
        }
      });
    }

    if (openPkSimVmWorkbenchBtn && pksimVmWorkbench) {
      openPkSimVmWorkbenchBtn.addEventListener("click", () => {
        pksimVmWorkbench.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    if (pksimVmForm && pksimVmSubmitBtn) {
      pksimVmForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        await runPkSimVmFromWorkbench();
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        window.location.href = "/logout";
      });
    }

    if (loadMidazolamBaselineBtn) {
      loadMidazolamBaselineBtn.addEventListener("click", () => applyBaselineCase("midazolam", "Midazolam"));
    }
    if (loadWarfarinBaselineBtn) {
      loadWarfarinBaselineBtn.addEventListener("click", () => applyBaselineCase("warfarin", "Warfarin"));
    }
    if (loadCaffeineBaselineBtn) {
      loadCaffeineBaselineBtn.addEventListener("click", () => applyBaselineCase("caffeine", "Caffeine"));
    }
    if (newBaselineBtn) {
      newBaselineBtn.addEventListener("click", () => {
        if (baselineCreatePanel) baselineCreatePanel.classList.add("open");
        if (newBaselineName) newBaselineName.focus();
      });
    }
    if (confirmBaselineBtn) {
      confirmBaselineBtn.addEventListener("click", createCustomBaseline);
    }
    if (cancelBaselineBtn) {
      cancelBaselineBtn.addEventListener("click", () => {
        if (newBaselineName) newBaselineName.value = "";
        if (baselineCreatePanel) baselineCreatePanel.classList.remove("open");
      });
    }
    if (newBaselineName) {
      newBaselineName.addEventListener("keydown", event => {
        if (event.key === "Enter") {
          event.preventDefault();
          createCustomBaseline();
        }
        if (event.key === "Escape") {
          event.preventDefault();
          if (baselineCreatePanel) baselineCreatePanel.classList.remove("open");
        }
      });
    }
    renderCustomBaselines();
    if (loadBatchSampleBtn) {
      loadBatchSampleBtn.addEventListener("click", () => {
        if (batchItemsText) {
          batchItemsText.value = `compound_name,smiles
Midazolam,CC1=NC=C2N1C3=C(C=C(C=C3)Cl)C(c1ccccc1F)=NC2`;
        }
        setBatchStatus("已载入批量筛选样例，可直接提交。");
      });
    }
    if (refreshTasksBtn) {
      refreshTasksBtn.addEventListener("click", () => {
        loadTasks(currentTaskId).catch(error => setBatchStatus(String(error), "error"));
      });
    }
    if (submitBatchBtn) {
      submitBatchBtn.addEventListener("click", async () => {
        submitBatchBtn.disabled = true;
        submitBatchBtn.textContent = "提交中...";
        try {
          const items = parseBatchItems(batchItemsText ? batchItemsText.value : "");
          if (!items.length) {
            throw new Error("Please provide one compound record first.");
          }
          if (items.length > 1) {
            throw new Error(`Single-item mode: keep only 1 record (current ${items.length}).`);
          }
          const res = await apiFetch("/api/v1/pipeline58/tasks/admet-batch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_name: String(batchProjectName && batchProjectName.value || "").trim() || "ADMET Single Screening",
              project_code: String(batchProjectCode && batchProjectCode.value || "").trim() || "P58-BATCH",
              notes: String(batchNotes && batchNotes.value || "").trim(),
              items
            })
          });
          const payload = await res.json();
          if (!res.ok || !payload.ok) {
            throw new Error(payload.detail || payload.error || "Task submission failed");
          }
          setBatchStatus(`任务已提交：${payload.data.task_id}，正在进入队列。`, "ok");
          await loadTasks(payload.data.task_id);
        } catch (error) {
          setBatchStatus(`提交失败：${String(error)}`, "error");
        } finally {
          submitBatchBtn.disabled = false;
          submitBatchBtn.textContent = "Submit single screening task";
        }
      });
    }
    if (openHistoryBtn) openHistoryBtn.addEventListener("click", openHistoryDrawer);
    if (openProjectsBtn) openProjectsBtn.addEventListener("click", openProjectsDrawer);
    if (openAuditBtn) openAuditBtn.addEventListener("click", openAuditDrawer);
    if (closeHistoryBtn) closeHistoryBtn.addEventListener("click", closeHistoryDrawer);
    if (closeProjectsBtn) closeProjectsBtn.addEventListener("click", closeHistoryDrawer);
    if (closeAuditBtn) closeAuditBtn.addEventListener("click", closeHistoryDrawer);
    if (historyOverlay) historyOverlay.addEventListener("click", closeHistoryDrawer);

    if (form) {
      form.querySelectorAll('.toggle-card input[type="checkbox"]').forEach(box => {
        box.addEventListener("change", syncToggleCards);
      });
      const sexField = form.querySelector('[name="sex"]');
      const trimesterField = form.querySelector('[name="pregnancy_trimester"]');
      if (sexField) sexField.addEventListener("change", syncToggleCards);
      if (trimesterField) trimesterField.addEventListener("change", syncToggleCards);

      const smilesField = form.querySelector('[name="smiles"]');
      if (smilesField && !String(smilesField.value || "").trim()) {
        applySampleCase();
      }
      syncToggleCards();
    }
    window.__p58MainBindingsReady = true;
    bootDashboard();

let activeKetcherField=null;
function getSmilesInput(name){return document.querySelector(`[name="${name}"]`);}
function setKetcherStatus(msg){const el=document.getElementById('ketcher-status'); if(el) el.textContent=msg;}
async function waitForKetcherApi(frame, tries=30){
  for(let i=0;i<tries;i++){
    const api=frame.contentWindow&&frame.contentWindow.ketcher;
    if(api&&typeof api.getSmiles==='function') return api;
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  throw new Error('Ketcher editor is not ready yet.');
}
async function preloadKetcherMolecule(field){
  const frame=document.getElementById('ketcher-frame');
  const smiles=String(field?.value||'').trim();
  if(!smiles) return;
  try{
    const api=await waitForKetcherApi(frame,20);
    if(typeof api.setMolecule==='function') await api.setMolecule(smiles);
    setKetcherStatus('Current SMILES loaded into Ketcher. Edit structure and apply when ready.');
  }catch(err){setKetcherStatus('Ketcher opened. Existing SMILES could not be preloaded; draw or paste structure manually.');}
}
function openKetcherFor(name){
  const field=getSmilesInput(name);
  if(!field){setKetcherStatus('SMILES input field not found.');return;}
  activeKetcherField=field;
  const modal=document.getElementById('ketcher-modal'), frame=document.getElementById('ketcher-frame');
  if(frame&&!frame.getAttribute('src')) frame.setAttribute('src',frame.dataset.src||'/ketcher/');
  modal?.classList.add('show');
  modal?.setAttribute('aria-hidden','false');
  setKetcherStatus('Loading Ketcher molecule editor...');
  setTimeout(()=>preloadKetcherMolecule(field),500);
}
function closeKetcher(){const modal=document.getElementById('ketcher-modal'); modal?.classList.remove('show'); modal?.setAttribute('aria-hidden','true');}
async function applyKetcherSmiles(){
  const frame=document.getElementById('ketcher-frame');
  if(!activeKetcherField||!frame){setKetcherStatus('No active SMILES field selected.');return;}
  try{
    setKetcherStatus('Reading SMILES from Ketcher...');
    const api=await waitForKetcherApi(frame,30);
    const smiles=String(await api.getSmiles()).trim();
    if(!smiles){setKetcherStatus('No molecule found in Ketcher.');return;}
    activeKetcherField.value=smiles;
    activeKetcherField.dispatchEvent(new Event('input',{bubbles:true}));
    activeKetcherField.dispatchEvent(new Event('change',{bubbles:true}));
    closeKetcher();
  }catch(err){setKetcherStatus(`Ketcher failed: ${String(err.message||err)}`);}
}
document.addEventListener('click',e=>{const btn=e.target.closest('[data-ketcher-field]'); if(btn) openKetcherFor(btn.dataset.ketcherField);});
document.getElementById('ketcher-close')?.addEventListener('click',closeKetcher);
document.getElementById('ketcher-apply')?.addEventListener('click',applyKetcherSmiles);
document.getElementById('ketcher-modal')?.addEventListener('click',e=>{if(e.target.id==='ketcher-modal') closeKetcher();});

  </script>
</body>
</html>
"""


PORTAL_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pipeline58 Portal</title>
  <style>
    :root { --bg:#f2efe8; --ink:#1e2a2f; --muted:#62747a; --line:rgba(30,42,47,.12); --accent:#204d63; --good:#1e7f5c; --shadow:0 18px 50px rgba(27,43,51,.12); }
    *{box-sizing:border-box} body{margin:0;min-height:100vh;font-family:"Aptos","Segoe UI Variable","Noto Sans SC",sans-serif;color:var(--ink);background:radial-gradient(circle at top left,rgba(32,77,99,.18),transparent 28%),radial-gradient(circle at bottom right,rgba(177,59,46,.10),transparent 24%),linear-gradient(180deg,#f7f3ec 0%,var(--bg) 100%)}
    .shell{max-width:1180px;margin:0 auto;padding:34px 20px 48px}.hero{border:1px solid rgba(255,255,255,.62);background:rgba(255,255,255,.78);border-radius:30px;padding:34px;box-shadow:var(--shadow);backdrop-filter:blur(18px)}
    .kicker{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#60777f;font-weight:800}.hero h1{font-size:58px;line-height:.98;margin:10px 0 12px;letter-spacing:-.05em}.sub{max-width:860px;color:var(--muted);font-size:18px;line-height:1.65}.user{margin-top:20px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:22px}.entry{display:grid;gap:14px;padding:24px;border:1px solid var(--line);background:rgba(255,255,255,.82);border-radius:24px;text-decoration:none;color:var(--ink);min-height:220px;transition:.16s ease}.entry:hover{transform:translateY(-3px);box-shadow:0 14px 30px rgba(32,77,99,.12);border-color:rgba(32,77,99,.28)}
    .entry strong{font-size:26px;letter-spacing:-.03em}.entry p{margin:0;color:var(--muted);line-height:1.55}.tag{align-self:end;display:inline-flex;width:max-content;border-radius:999px;padding:8px 12px;background:rgba(32,77,99,.09);color:var(--accent);font-weight:800;font-size:12px}.tag.good{background:rgba(30,127,92,.11);color:var(--good)}
    .actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}.btn{border:1px solid var(--line);background:rgba(255,255,255,.85);padding:12px 16px;border-radius:15px;color:var(--accent);font-weight:800;text-decoration:none}.logout{color:#8a3a31}
    @media(max-width:900px){.grid{grid-template-columns:1fr}.hero h1{font-size:40px}.hero{padding:24px}}

.ketcher-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}.ketcher-modal{position:fixed;inset:0;z-index:999;background:rgba(20,28,34,.62);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;padding:24px}.ketcher-modal.show{display:flex}.ketcher-panel{width:min(1120px,96vw);height:min(760px,92vh);background:#fff;border-radius:22px;box-shadow:0 24px 80px rgba(0,0,0,.28);display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}.ketcher-head,.ketcher-foot{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line,rgba(30,42,47,.13))}.ketcher-foot{border-top:1px solid var(--line,rgba(30,42,47,.13));border-bottom:0}.ketcher-head h3{margin:0;font-size:18px}.ketcher-frame{width:100%;height:100%;border:0}.ketcher-close{background:rgba(255,255,255,.86)!important;color:var(--accent,#204d63)!important;border:1px solid var(--line,rgba(30,42,47,.13))!important}.ketcher-apply{min-width:180px}.ketcher-status{color:var(--muted,#62747a);font-size:12px;line-height:1.4}@media(max-width:700px){.ketcher-panel{height:94vh}.ketcher-foot{display:grid}.ketcher-apply{width:100%}}

</style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="kicker">Pipeline58 Local Portal</div>
      <h1>hanmi PBPK / ADMET DEMO</h1>
      <div class="sub">Choose one workbench first. STEP 5-8, PBPK/PBBM, and ADMET are separated so inputs and results do not mix.</div>
      <div class="user">Current account: <strong>__USER_LABEL__</strong></div>
      <div class="grid">
        <a class="entry" href="/step58" target="_blank" rel="noreferrer">
          <strong>STEP 5-8 Workbench</strong>
          <p>ADMET + PBPK + PK/PD + DDI closed loop. Uses the existing baseline, run history, project, and result cards.</p>
          <span class="tag good">Open STEP 5-8</span>
        </a>
        <a class="entry" href="/pbpk" target="_blank" rel="noreferrer">
          <strong>PBPK / PBBM</strong>
          <p>Dedicated whole-body PBPK and GI/PBBM entrance. Shows stomach, intestine, liver, kidney, tissue, and plasma curves.</p>
          <span class="tag good">Open PBPK</span>
        </a>
        <a class="entry" href="/admet" target="_blank" rel="noreferrer">
          <strong>ADMET Deep-Dive</strong>
          <p>Single-compound ADMET review and model output inspection. Kept independent from STEP 5-8 and the PBPK workbench.</p>
          <span class="tag">Open ADMET</span>
        </a>
      </div>
      <div class="actions">
        <a class="btn" href="/docs" target="_blank" rel="noreferrer">API Docs</a>
        <a class="btn" href="/admin/users" target="_blank" rel="noreferrer">User Admin</a>
        <a class="btn logout" href="/logout">Logout</a>
      </div>
    </section>
  </main>
</body>
</html>
"""


LOGIN_HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pipeline58 登录</title>
  <style>
    :root {
      --bg: #f2efe8;
      --ink: #1e2a2f;
      --muted: #62747a;
      --accent: #204d63;
      --line: rgba(30,42,47,0.12);
      --bad: #b13b2e;
      --shadow: 0 18px 50px rgba(27, 43, 51, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Aptos", "Segoe UI Variable", "Noto Sans SC", sans-serif;
      color: var(--ink);
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at top left, rgba(32,77,99,0.18), transparent 28%),
        radial-gradient(circle at bottom right, rgba(177,59,46,0.10), transparent 24%),
        linear-gradient(180deg, #f7f3ec 0%, var(--bg) 100%);
      padding: 24px;
      overflow: hidden;
      position: relative;
    }
    body::before,
    body::after {
      content: "";
      position: fixed;
      inset: auto;
      border-radius: 50%;
      filter: blur(16px);
      opacity: 0.9;
      pointer-events: none;
    }
    body::before {
      width: 360px;
      height: 360px;
      left: -80px;
      top: -90px;
      background: radial-gradient(circle, rgba(32,77,99,0.22), rgba(32,77,99,0));
    }
    body::after {
      width: 320px;
      height: 320px;
      right: -60px;
      bottom: -70px;
      background: radial-gradient(circle, rgba(177,59,46,0.16), rgba(177,59,46,0));
    }
    .card {
      width: min(480px, 100%);
      padding: 32px;
      border-radius: 28px;
      background: rgba(255,255,255,0.76);
      border: 1px solid rgba(255,255,255,0.58);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
      position: relative;
      z-index: 1;
    }
    .kicker {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #59727d;
      margin-bottom: 10px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 40px;
      line-height: 1;
      letter-spacing: -0.04em;
    }
    .copy {
      color: var(--muted);
      line-height: 1.7;
      margin-bottom: 18px;
    }
    form {
      display: grid;
      gap: 14px;
    }
    label {
      display: grid;
      gap: 8px;
    }
    .label-zh {
      font-size: 15px;
      font-weight: 700;
    }
    .label-en {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #6f848b;
    }
    input {
      width: 100%;
      border-radius: 18px;
      border: 1px solid #d3dde1;
      padding: 16px 18px;
      font-size: 18px;
      background: #eef4ff;
      outline: none;
    }
    button {
      border: 0;
      border-radius: 20px;
      background: var(--accent);
      color: #fff;
      font-size: 18px;
      font-weight: 700;
      padding: 16px 18px;
      cursor: pointer;
    }
    .error {
      min-height: 22px;
      color: var(--bad);
      font-size: 14px;
    }

.ketcher-tools{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:8px}.ketcher-modal{position:fixed;inset:0;z-index:999;background:rgba(20,28,34,.62);backdrop-filter:blur(8px);display:none;align-items:center;justify-content:center;padding:24px}.ketcher-modal.show{display:flex}.ketcher-panel{width:min(1120px,96vw);height:min(760px,92vh);background:#fff;border-radius:22px;box-shadow:0 24px 80px rgba(0,0,0,.28);display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}.ketcher-head,.ketcher-foot{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line,rgba(30,42,47,.13))}.ketcher-foot{border-top:1px solid var(--line,rgba(30,42,47,.13));border-bottom:0}.ketcher-head h3{margin:0;font-size:18px}.ketcher-frame{width:100%;height:100%;border:0}.ketcher-close{background:rgba(255,255,255,.86)!important;color:var(--accent,#204d63)!important;border:1px solid var(--line,rgba(30,42,47,.13))!important}.ketcher-apply{min-width:180px}.ketcher-status{color:var(--muted,#62747a);font-size:12px;line-height:1.4}@media(max-width:700px){.ketcher-panel{height:94vh}.ketcher-foot{display:grid}.ketcher-apply{width:100%}}

</style>
</head>
<body>
  <section class="card">
    <div class="kicker">Pipeline58 secure access</div>
    <h1>登录工作台</h1>
    <div class="copy">系统已经切到登录保护模式。
完成账号认证，再进
 ADMET、PBPK、PK/PD 与 DDI 工作台。</div>
    <form method="post" action="/auth/web-login">
      <label>
        <span class="label-zh">用户名</span>
        <span class="label-en">Username</span>
        <input type="text" name="username" autocomplete="username" required>
      </label>
      <label>
        <span class="label-zh">密码</span>
        <span class="label-en">Password</span>
        <input type="password" name="password" autocomplete="current-password" required>
      </label>
      <button type="submit">登录系统</button>
      <div class="error">__LOGIN_ERROR__</div>
    </form>
  </section>
</body>
</html>
"""


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
        return request.client.host
    return ""


def _current_user_from_header(
    x_pipeline58_token: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
    pipeline58_token: Annotated[str | None, Cookie()] = None,
) -> Dict[str, Any]:
    user = AUTH.get_current_user(x_pipeline58_token or token or pipeline58_token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def _require_role(required_role: str):
    def dependency(user: Dict[str, Any] = Depends(_current_user_from_header)) -> Dict[str, Any]:
        if not role_allows(str(user.get("role", "viewer")), required_role):
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return dependency


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": SETTINGS.service_name,
        "version": SETTINGS.service_version,
        "runs": len(SERVICE.list_runs()),
    }


def _apply_user_to_dashboard(html: str, user: Dict[str, Any] | None) -> str:
    if user:
        html = html.replace('class="auth-screen open" id="auth-screen"', 'class="auth-screen" id="auth-screen"', 1)
        html = html.replace('id="auth-user-name">Not signed in', f'id="auth-user-name">{user.get("display_name", user.get("username", "User"))} / {user.get("username", "")}', 1)
        html = html.replace('id="auth-user-meta">Please sign in before running analysis.', f'id="auth-user-meta">Role {user.get("role", "viewer")}', 1)
    return html


def _render_step58_html(user: Dict[str, Any] | None) -> str:
    html = DASHBOARD_HTML
    section_start = html.find('<section class="panel card pksim-workbench" id="pksim-vm-workbench">')
    section_end = html.find('<section class="panel card batch-shell">', section_start)
    if section_start >= 0 and section_end > section_start:
        html = html[:section_start] + html[section_end:]
    html = html.replace('<button class="ghost-btn" id="open-pksim-vm-workbench-btn" type="button" title="Open independent PK-Sim simulation workbench">PK-Sim Simulation Workbench</button>', '<a class="ghost-btn" href="/pksim-simulation" target="_blank" rel="noreferrer">PK-Sim Simulation</a>', 1)
    html = html.replace('''    const openPkSimVmWorkbenchBtn = document.getElementById("open-pksim-vm-workbench-btn");
    const pksimVmWorkbench = document.getElementById("pksim-vm-workbench");
    const pksimVmForm = document.getElementById("pksim-vm-form");
    const pksimVmSubmitBtn = document.getElementById("pksim-vm-submit-btn");
    const pksimVmStatus = document.getElementById("pksim-vm-status");
    const pksimVmResultStatus = document.getElementById("pksim-vm-result-status");
    const pksimVmFormStatus = document.getElementById("pksim-vm-form-status");
''', '')
    func_start = html.find('    function setPkSimVmStatus(message, tone = "") {')
    func_end = html.find('    function renderOverlayChart(seriesList) {', func_start)
    if func_start >= 0 and func_end > func_start:
        html = html[:func_start] + html[func_end:]
    bind = '''    if (openPkSimVmWorkbenchBtn && pksimVmWorkbench) {
      openPkSimVmWorkbenchBtn.addEventListener("click", () => {
        pksimVmWorkbench.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
    if (pksimVmForm && pksimVmSubmitBtn) {
      pksimVmForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        await runPkSimVmFromWorkbench();
      });
    }

'''
    html = html.replace(bind, '')
    return _apply_user_to_dashboard(html, user)


def _portal_html(user: Dict[str, Any]) -> str:
    label = f'{user.get("display_name", user.get("username", "User"))} / {user.get("username", "")}'
    return PORTAL_HTML.replace('__USER_LABEL__', label)


def _pbpk_workbench_response() -> HTMLResponse:
    page_path = Path(__file__).resolve().parent / "pbpk_workbench.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="PBPK workbench page not found")
    html = page_path.read_text(encoding="utf-8")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/", response_class=HTMLResponse)
def dashboard_home(
    request: Request,
    pipeline58_token: Annotated[str | None, Cookie()] = None,
):
    token = pipeline58_token or request.query_params.get("token") or request.headers.get("x-pipeline58-token")
    user = AUTH.get_current_user(token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return _pbpk_workbench_response()


@app.get("/step58", response_class=HTMLResponse)
def step58_page(
    request: Request,
    pipeline58_token: Annotated[str | None, Cookie()] = None,
):
    if any(
        key in request.query_params
        for key in ("compound_name", "smiles", "target_name", "dose_mg", "interval_hours", "project_name")
    ):
        return RedirectResponse("/step58", status_code=303)
    token = pipeline58_token or request.query_params.get("token") or request.headers.get("x-pipeline58-token")
    user = AUTH.get_current_user(token)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(
        _render_step58_html(user),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Clear-Site-Data": '"cache"',
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    error: Annotated[str | None, Query()] = None,
    pipeline58_token: Annotated[str | None, Cookie()] = None,
):
    token = pipeline58_token or request.query_params.get("token") or request.headers.get("x-pipeline58-token")
    if AUTH.get_current_user(token):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(
        LOGIN_HTML.replace("__LOGIN_ERROR__", error or ""),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/logout")
def web_logout(
    request: Request,
    pipeline58_token: Annotated[str | None, Cookie()] = None,
):
    if pipeline58_token:
        AUTH.logout(pipeline58_token, client_ip=_client_ip(request))
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("pipeline58_token", path="/")
    return response


@app.get("/api/v1/pipeline58/config")
def pipeline58_config(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    return {"ok": True, "data": SETTINGS.__dict__, "error": None}


@app.get("/api/v1/pipeline58/runtime")
def pipeline58_runtime(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    return {"ok": True, "data": SERVICE.runtime_status(), "error": None}


@app.get("/pbpk", response_class=HTMLResponse)
def pbpk_workbench_page(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> HTMLResponse:
    return _pbpk_workbench_response()


@app.get("/pksim", response_class=HTMLResponse)
def pksim_page() -> RedirectResponse:
    return RedirectResponse("/pksim-simulation", status_code=303)


@app.get("/pksim-simulation", response_class=HTMLResponse)
def pksim_simulation_page(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> HTMLResponse:
    page_path = Path(__file__).resolve().parent / "pksim_simulation.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="PK-Sim simulation page not found")
    html = page_path.read_text(encoding="utf-8")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/admet", response_class=HTMLResponse)
def admet_page() -> HTMLResponse:
    page_path = Path(__file__).resolve().parent / "admet_page.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="ADMET page not found")
    html = page_path.read_text(encoding="utf-8")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.post("/api/v1/admet/analyze")
def admet_analyze(
    request: Pipeline58Request,
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        if request.project.owner == "analyst":
            request.project.owner = str(user.get("username", "analyst"))
        desc = smiles_descriptors(request.smiles)
        admet = SERVICE._admet(request, desc)
        payload = {
            "compound_name": request.compound_name,
            "smiles": request.smiles,
            "target_name": request.target_name,
            "mechanism": request.mechanism,
            "route": request.dosing.route,
            "overall_admet_score": admet.get("overall_admet_score"),
            "model_backend": admet.get("model_backend", {}),
            "risk_flags": admet.get("risk_flags", []),
            "descriptors": admet.get("descriptors", {}),
            "absorption": admet.get("absorption", {}),
            "distribution": admet.get("distribution", {}),
            "metabolism": admet.get("metabolism", {}),
            "excretion": admet.get("excretion", {}),
            "toxicity": admet.get("toxicity", {}),
            "raw_model_output": admet.get("raw_model_output", {}),
        }
        return {"ok": True, "data": payload, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/pksim-vm/payloads/{payload_id}")
def pksim_vm_payload(payload_id: str, secret: Annotated[str | None, Query()] = None) -> FileResponse:
    safe_id = payload_id.strip()
    if not safe_id or any(ch in safe_id for ch in "/\\.."):
        raise HTTPException(status_code=404, detail="payload not found")
    payload_dir = REPORTS_DIR / "pksim_vm_payloads"
    payload_path = payload_dir / f"{safe_id}.json"
    secret_path = payload_dir / f"{safe_id}.secret"
    if not payload_path.exists() or not secret_path.exists():
        raise HTTPException(status_code=404, detail="payload not found")
    expected = secret_path.read_text(encoding="utf-8").strip()
    if not secret or secret != expected:
        raise HTTPException(status_code=403, detail="invalid payload secret")
    return FileResponse(payload_path, media_type="application/json", filename=f"{safe_id}.json")


@app.post("/api/v1/pksim-vm/run")
def pksim_vm_run(
    request: Pipeline58Request,
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        if getattr(request.project, "owner", "") == "analyst":
            request.project.owner = str(user.get("username") or "analyst")
        result = SERVICE.run_pksim_vm_case(request, user["username"], user["role"])
        return {"ok": True, "data": result, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/pksim/run")
def pksim_run(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        result = SERVICE.run_pksim_case(payload, user["username"], user["role"])
        return {"ok": True, "data": result, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(user: Dict[str, Any] = Depends(_require_role("admin"))) -> HTMLResponse:
    page_path = Path(__file__).resolve().parent / "users_admin.html"
    if not page_path.exists():
        raise HTTPException(status_code=404, detail="admin users page not found")
    html = page_path.read_text(encoding="utf-8")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.post("/api/v1/auth/login")
def auth_login(payload: Dict[str, str], request: Request) -> Dict[str, Any]:
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    try:
        session = AUTH.authenticate(username, password, client_ip=_client_ip(request))
        response = JSONResponse({"ok": True, "data": session, "error": None})
        response.set_cookie(
            key="pipeline58_token",
            value=str(session["token"]),
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))



@app.post("/auth/web-login")
def auth_web_login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    try:
        session = AUTH.authenticate(str(username).strip(), str(password), client_ip=_client_ip(request))
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            key="pipeline58_token",
            value=str(session["token"]),
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response
    except ValueError as exc:
        return RedirectResponse(f"/login?error={quote_plus(str(exc))}", status_code=303)


@app.get("/api/v1/auth/me")
def auth_me(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    return {"ok": True, "data": user, "error": None}


@app.post("/api/v1/auth/logout")
def auth_logout(
    request: Request,
    x_pipeline58_token: Annotated[str | None, Header()] = None,
    pipeline58_token: Annotated[str | None, Cookie()] = None,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> JSONResponse:
    active_token = x_pipeline58_token or pipeline58_token
    if active_token:
        AUTH.logout(active_token, client_ip=_client_ip(request))
    response = JSONResponse({"ok": True, "data": {"logged_out": True, "username": user["username"]}, "error": None})
    response.delete_cookie("pipeline58_token", path="/")
    return response


@app.post("/api/v1/auth/password")
def auth_change_password(
    payload: Dict[str, str],
    request: Request,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> Dict[str, Any]:
    current_password = str(payload.get("current_password", ""))
    new_password = str(payload.get("new_password", ""))
    try:
        AUTH.change_password(user["username"], current_password, new_password, client_ip=_client_ip(request))
        return {"ok": True, "data": {"password_changed": True}, "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/auth/users")
def auth_users(user: Dict[str, Any] = Depends(_require_role("admin"))) -> Dict[str, Any]:
    return {"ok": True, "data": AUTH.list_users(), "error": None}


@app.post("/api/v1/auth/users")
def auth_create_user(
    payload: Dict[str, Any],
    request: Request,
    user: Dict[str, Any] = Depends(_require_role("admin")),
) -> Dict[str, Any]:
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "viewer")).strip().lower() or "viewer"
    display_name = str(payload.get("display_name", "")).strip()
    active = bool(payload.get("active", True))
    try:
        created = AUTH.create_user(
            username=username,
            password=password,
            role=role,
            display_name=display_name,
            active=active,
            actor=str(user.get("username", "admin")),
            client_ip=_client_ip(request),
        )
        return {"ok": True, "data": created, "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))




@app.post("/api/v1/auth/users/{username}/password-reset")
def auth_reset_user_password(
    username: str,
    payload: Dict[str, Any],
    request: Request,
    user: Dict[str, Any] = Depends(_require_role("admin")),
) -> Dict[str, Any]:
    new_password = str(payload.get("new_password", ""))
    try:
        updated = AUTH.admin_reset_password(
            username=username,
            new_password=new_password,
            actor=str(user.get("username", "admin")),
            client_ip=_client_ip(request),
        )
        return {"ok": True, "data": updated, "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/auth/users/{username}/active")
def auth_set_user_active(
    username: str,
    payload: Dict[str, Any],
    request: Request,
    user: Dict[str, Any] = Depends(_require_role("admin")),
) -> Dict[str, Any]:
    try:
        updated = AUTH.admin_set_user_active(
            username=username,
            active=bool(payload.get("active", True)),
            actor=str(user.get("username", "admin")),
            client_ip=_client_ip(request),
        )
        return {"ok": True, "data": updated, "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/v1/auth/users/{username}")
def auth_delete_user(
    username: str,
    request: Request,
    user: Dict[str, Any] = Depends(_require_role("admin")),
) -> Dict[str, Any]:
    try:
        result = AUTH.admin_delete_user(
            username=username,
            actor=str(user.get("username", "admin")),
            client_ip=_client_ip(request),
        )
        return {"ok": True, "data": result, "error": None}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/be/compare")
def be_compare_run(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    """Reference-vs-test generic BE/PBBM comparison for formulation risk review."""
    try:
        from datetime import datetime, timezone
        import uuid

        def val(source: Dict[str, Any], key: str, default: Any = None) -> Any:
            value = source.get(key, default)
            return default if value in (None, "") else value

        def as_float(source: Dict[str, Any], key: str, default: float | None = None) -> float | None:
            value = source.get(key)
            if value in (None, "", "auto", "Auto", "AUTO"):
                return default
            try:
                return float(value)
            except Exception:
                return default

        def as_int(source: Dict[str, Any], key: str, default: int) -> int:
            try:
                return int(float(source.get(key, default)))
            except Exception:
                return default

        common = payload.get("common") if isinstance(payload.get("common"), dict) else {}
        ref = payload.get("reference") if isinstance(payload.get("reference"), dict) else {}
        test = payload.get("test") if isinstance(payload.get("test"), dict) else {}
        if not ref or not test:
            raise ValueError("reference and test product inputs are required")

        dose_mg = as_float(common, "dose_mg", as_float(test, "dose_mg", as_float(ref, "dose_mg", 100.0))) or 100.0
        route = str(val(common, "route", "po") or "po")
        interval_hours = as_int(common, "interval_hours", 24)
        repeat_days = as_int(common, "repeat_days", 1)
        population_payload = {
            "preset": str(val(common, "population", "adult") or "adult"),
            "sex": str(val(common, "sex", "unknown") or "unknown"),
            "weight_kg": as_float(common, "weight_kg", 70.0) or 70.0,
            "age_years": as_int(common, "age_years", 40),
            "ethnicity": "general",
        }

        def build_request(product: Dict[str, Any], label: str) -> Pipeline58Request:
            return Pipeline58Request(
                compound_name=str(val(product, "compound_name", label) or label),
                smiles=str(val(product, "smiles", "CN1C=NC2=C1N(C(=O)N(C)C2=O)C") or "CN1C=NC2=C1N(C(=O)N(C)C2=O)C"),
                target_name=str(val(common, "target_name", val(product, "target_name", "BE")) or "BE"),
                indication=str(val(common, "indication", val(product, "indication", "Generic BE")) or "Generic BE"),
                project={
                    "project_name": str(val(common, "project_name", "Generic BE Risk Project") or "Generic BE Risk Project"),
                    "project_code": str(val(common, "project_code", "BE-PBBM") or "BE-PBBM"),
                    "owner": str(user.get("username", "analyst")),
                    "access_level": "internal",
                    "tags": ["be", "pbbm", "generic"],
                },
                dosing={
                    "route": route if route in {"po", "iv"} else "po",
                    "dose_mg": dose_mg,
                    "interval_hours": interval_hours,
                    "repeat_days": repeat_days,
                },
                population=population_payload,
                potency_uM=as_float(common, "potency_uM", None),
                mechanism=str(val(common, "mechanism", "inhibition") or "inhibition"),
            )

        def parse_profile(text: Any) -> list[dict[str, float]]:
            rows: list[dict[str, float]] = []
            if not text:
                return rows
            for raw in str(text).replace(";", "\n").splitlines():
                line = raw.strip()
                if not line or line.lower().startswith("time"):
                    continue
                parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip()]
                if len(parts) < 2:
                    parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    rows.append({"time_min": float(parts[0]), "released_pct": max(0.0, min(100.0, float(parts[1])))})
                except Exception:
                    continue
            return sorted(rows, key=lambda row: row["time_min"])

        def interpolation(rows: list[dict[str, float]], target: float) -> float | None:
            if not rows:
                return None
            if target <= rows[0]["time_min"]:
                return rows[0]["released_pct"]
            for left, right in zip(rows, rows[1:]):
                if left["time_min"] <= target <= right["time_min"]:
                    span = max(right["time_min"] - left["time_min"], 1e-9)
                    frac = (target - left["time_min"]) / span
                    return left["released_pct"] + frac * (right["released_pct"] - left["released_pct"])
            return rows[-1]["released_pct"]

        def time_to_pct(rows: list[dict[str, float]], pct: float) -> float | None:
            if not rows:
                return None
            last = rows[0]
            if last["released_pct"] >= pct:
                return last["time_min"]
            for row in rows[1:]:
                if row["released_pct"] >= pct:
                    span = max(row["released_pct"] - last["released_pct"], 1e-9)
                    frac = (pct - last["released_pct"]) / span
                    return last["time_min"] + frac * (row["time_min"] - last["time_min"])
                last = row
            return None

        def f2_similarity(test_rows: list[dict[str, float]], ref_rows: list[dict[str, float]]) -> Dict[str, Any]:
            if len(test_rows) < 3 or len(ref_rows) < 3:
                return {"available": False, "f2": None, "pass": None, "pairs": []}
            ref_times = {round(row["time_min"], 4): row["released_pct"] for row in ref_rows}
            pairs = []
            for row in test_rows:
                key = round(row["time_min"], 4)
                if key in ref_times:
                    pairs.append({"time_min": row["time_min"], "reference_pct": ref_times[key], "test_pct": row["released_pct"], "delta_pct": round(row["released_pct"] - ref_times[key], 3)})
            if len(pairs) < 3:
                return {"available": False, "f2": None, "pass": None, "pairs": pairs}
            mse = sum((pair["test_pct"] - pair["reference_pct"]) ** 2 for pair in pairs) / len(pairs)
            f2 = 50.0 * math.log10((1.0 + mse) ** -0.5 * 100.0)
            return {"available": True, "f2": round(f2, 2), "pass": f2 >= 50.0, "pairs": pairs}

        def parse_excipients(product: Dict[str, Any]) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            raw_items = product.get("excipients")
            if isinstance(raw_items, list):
                items = raw_items
            else:
                items = str(raw_items or "").replace(";", "\n").splitlines()
            for item in items:
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    role = str(item.get("role", "other")).strip()
                    amount = as_float(item, "amount_pct", 0.0) or 0.0
                else:
                    parts = [part.strip() for part in str(item).split(",")]
                    if not parts or not parts[0]:
                        continue
                    name = parts[0]
                    role = parts[1] if len(parts) > 1 and parts[1] else "other"
                    try:
                        amount = float(parts[2]) if len(parts) > 2 and parts[2] else 0.0
                    except Exception:
                        amount = 0.0
                rows.append({"name": name, "role": role, "amount_pct": amount})
            return rows

        def excipient_effect(rows: list[dict[str, Any]]) -> Dict[str, Any]:
            dissolution_factor = 1.0
            solubility_factor = 1.0
            warnings: list[str] = []
            for row in rows:
                role = str(row.get("role", "")).lower()
                amount = float(row.get("amount_pct") or 0.0)
                if "崩" in role or "disintegrant" in role:
                    dissolution_factor *= 1.0 + min(amount, 8.0) * 0.035
                elif "黏" in role or "binder" in role:
                    dissolution_factor *= max(0.72, 1.0 - min(amount, 10.0) * 0.022)
                elif "润滑" in role or "lubricant" in role:
                    dissolution_factor *= max(0.65, 1.0 - min(amount, 5.0) * 0.045)
                    if amount >= 1.0:
                        warnings.append(f"{row.get('name')} lubricant level may slow wetting/dissolution")
                elif "助溶" in role or "surfactant" in role or "solubilizer" in role:
                    solubility_factor *= 1.0 + min(amount, 10.0) * 0.06
                    dissolution_factor *= 1.0 + min(amount, 10.0) * 0.02
            return {
                "dissolution_factor": round(dissolution_factor, 4),
                "solubility_factor": round(solubility_factor, 4),
                "warnings": warnings,
            }

        def apply_product_to_admet(product: Dict[str, Any], request_model: Pipeline58Request) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
            desc = smiles_descriptors(request_model.smiles)
            admet = SERVICE._admet(request_model, desc)
            applied: Dict[str, Any] = {}
            descriptor_keys = {"mw": "mw", "logp": "logp", "tpsa": "tpsa", "logs": "logs"}
            for key, target in descriptor_keys.items():
                product_val = as_float(product, key, None)
                if product_val is not None:
                    admet.setdefault("descriptors", {})[target] = product_val
                    applied[key] = product_val
            for key in ("pka_acid", "pka_base"):
                product_val = as_float(product, key, None)
                if product_val is not None:
                    admet.setdefault("descriptors", {})[key] = product_val
                    applied[key] = product_val
            sol = as_float(product, "solubility_mg_ml", None)
            excipients = parse_excipients(product)
            exc_eff = excipient_effect(excipients)
            if sol is not None and sol > 0:
                adjusted_sol = sol * float(exc_eff["solubility_factor"])
                mw_for_sol = float(admet.get("descriptors", {}).get("mw") or desc.get("mw") or 400.0)
                logs = round(math.log10(max(adjusted_sol / max(mw_for_sol, 1e-6), 1e-12)), 4)
                admet.setdefault("descriptors", {})["logs"] = logs
                admet.setdefault("absorption", {}).setdefault("Solubility", {})["value"] = logs
                admet["absorption"]["Solubility"]["source"] = "be_user_solubility"
                applied["solubility_mg_ml"] = sol
                applied["solubility_after_excipient_mg_ml"] = round(adjusted_sol, 4)
                applied["logs_from_solubility_mg_ml"] = logs
            metric_map = {
                "caco2": ("absorption", "Caco2_Papp"),
                "oral_f": ("absorption", "Oral_F"),
                "ppb": ("distribution", "PPB"),
                "vdss": ("distribution", "VDss"),
                "cl_total": ("excretion", "CLtotal"),
                "cl_renal": ("excretion", "CLrenal"),
                "cyp3a4_sub": ("metabolism", "CYP3A4_substrate"),
                "cyp3a4_inh": ("metabolism", "CYP3A4_inhibitor"),
            }
            for key, (section, metric) in metric_map.items():
                product_val = as_float(product, key, None)
                if product_val is not None:
                    admet.setdefault(section, {}).setdefault(metric, {})["value"] = product_val
                    admet[section][metric]["source"] = "be_user_override"
                    applied[key] = product_val
            overrides: Dict[str, Any] = {}
            numeric_overrides = (
                "solubility_mg_ml", "pka_acid", "pka_base", "particle_size_um",
                "dissolution_t50_min", "dissolution_30min_pct", "ka_multiplier",
                "cl_multiplier", "v_multiplier", "dissolution_h", "gastric_emptying_h",
                "abs_duodenum_h", "abs_jejunum_h", "abs_ileum_h", "abs_colon_h",
            )
            for key in numeric_overrides:
                product_val = as_float(product, key, None)
                if product_val is not None:
                    overrides[key] = product_val
            if "dissolution_30min_pct" in overrides:
                overrides["dissolution_30min_pct"] = max(1.0, min(100.0, float(overrides["dissolution_30min_pct"]) * float(exc_eff["dissolution_factor"])))
            else:
                profile = parse_profile(product.get("dissolution_profile"))
                pct30 = interpolation(profile, 30.0)
                if pct30 is not None:
                    overrides["dissolution_30min_pct"] = max(1.0, min(100.0, pct30 * float(exc_eff["dissolution_factor"])))
            if "dissolution_t50_min" not in overrides:
                t50 = time_to_pct(parse_profile(product.get("dissolution_profile")), 50.0)
                if t50 is not None:
                    overrides["dissolution_t50_min"] = max(1.0, t50 / max(float(exc_eff["dissolution_factor"]), 0.1))
            for key in ("release_type", "food_state", "formulation_notes"):
                if product.get(key) not in (None, ""):
                    overrides[key] = str(product.get(key))
            process = str(product.get("process_type", "") or "").lower()
            compression = as_float(product, "compression_force_kn", None)
            if compression is not None and compression > 18:
                overrides["dissolution_30min_pct"] = max(1.0, float(overrides.get("dissolution_30min_pct", 70.0)) * 0.9)
                applied["compression_force_effect"] = "high compression may delay disintegration"
            if "wet" in process:
                overrides["dissolution_30min_pct"] = max(1.0, min(100.0, float(overrides.get("dissolution_30min_pct", 70.0)) * 1.03))
            applied["excipients"] = excipients
            applied["excipient_effect"] = exc_eff
            return admet, overrides, applied

        def pk_metric(model: Dict[str, Any], key: str) -> float:
            value = (model.get("pk_parameters", {}).get(key, {}) or {}).get("value", 0.0)
            try:
                return float(value or 0.0)
            except Exception:
                return 0.0

        def ci90(ratio: float | None, cv_pct: float, n: int) -> Dict[str, Any]:
            if ratio is None or ratio <= 0:
                return {"low": None, "high": None}
            cv = max(float(cv_pct or 30.0) / 100.0, 0.01)
            subjects = max(int(n or 24), 4)
            se = math.sqrt(2.0 * math.log(1.0 + cv * cv) / subjects)
            return {
                "low": round(math.exp(math.log(ratio) - 1.645 * se), 3),
                "high": round(math.exp(math.log(ratio) + 1.645 * se), 3),
            }

        def run_product(product: Dict[str, Any], label: str) -> Dict[str, Any]:
            request_model = build_request(product, label)
            admet, overrides, applied = apply_product_to_admet(product, request_model)
            pbpk = SERVICE._pbpk(request_model, admet, overrides=overrides)
            pbbm = SERVICE._pbbm_profile(request_model, pbpk, admet)
            pkpd = SERVICE._pkpd(request_model, pbpk, admet, overrides={})
            profile = parse_profile(product.get("dissolution_profile"))
            return {
                "label": label,
                "request": request_model.model_dump(),
                "input": product,
                "applied": applied,
                "admet": admet,
                "pbpk": pbpk,
                "pbbm": pbbm,
                "pkpd": pkpd,
                "dissolution_profile": profile,
                "dissolution_summary": {
                    "pct_15": interpolation(profile, 15.0),
                    "pct_30": interpolation(profile, 30.0),
                    "pct_60": interpolation(profile, 60.0),
                    "t50_min": time_to_pct(profile, 50.0),
                    "t85_min": time_to_pct(profile, 85.0),
                },
                "pk": {
                    "Cmax": round(pk_metric(pbpk, "Cmax"), 4),
                    "Tmax": round(pk_metric(pbpk, "Tmax"), 4),
                    "AUC0_t": round(pk_metric(pbpk, "AUC0_t"), 4),
                    "F": round(float((pbpk.get("pk_parameters", {}) or {}).get("F") or (pbbm.get("summary", {}) or {}).get("F_estimated") or 0.0), 4),
                },
            }

        ref_result = run_product(ref, "Reference")
        test_result = run_product(test, "Test")
        ref_pk = ref_result["pk"]
        test_pk = test_result["pk"]
        auc_ratio = round(test_pk["AUC0_t"] / ref_pk["AUC0_t"], 4) if ref_pk["AUC0_t"] else None
        cmax_ratio = round(test_pk["Cmax"] / ref_pk["Cmax"], 4) if ref_pk["Cmax"] else None
        tmax_delta = round(test_pk["Tmax"] - ref_pk["Tmax"], 4)
        cv_pct = as_float(common, "be_cv_pct", 30.0) or 30.0
        subject_n = as_int(common, "be_subject_n", 24)
        auc_ci = ci90(auc_ratio, cv_pct, subject_n)
        cmax_ci = ci90(cmax_ratio, cv_pct, subject_n)
        be_pk_pass = bool(
            auc_ci["low"] is not None and auc_ci["low"] >= 0.8 and auc_ci["high"] <= 1.25
            and cmax_ci["low"] is not None and cmax_ci["low"] >= 0.8 and cmax_ci["high"] <= 1.25
        )
        f2 = f2_similarity(test_result["dissolution_profile"], ref_result["dissolution_profile"])

        api_findings: list[str] = []
        formulation_findings: list[str] = []
        action_items: list[str] = []
        api_score = 0
        formulation_score = 0
        pk_score = 0

        for key, label, threshold in [
            ("salt_form", "salt form", None),
            ("polymorph", "polymorph/crystal form", None),
            ("api_supplier", "API supplier", None),
        ]:
            if str(ref.get(key, "")).strip().lower() != str(test.get(key, "")).strip().lower():
                api_score += 12
                api_findings.append(f"{label} differs between reference and test product")
        for key, label, limit_pct in [
            ("particle_size_um", "D50 particle size", 30.0),
            ("solubility_mg_ml", "solubility", 25.0),
            ("pka_acid", "acidic pKa", 0.4),
            ("pka_base", "basic pKa", 0.4),
        ]:
            rv = as_float(ref, key, None)
            tv = as_float(test, key, None)
            if rv is None or tv is None:
                continue
            if key.startswith("pka"):
                if abs(tv - rv) >= float(limit_pct):
                    api_score += 10
                    api_findings.append(f"{label} differs by {abs(tv-rv):.2f}")
            else:
                denom = max(abs(rv), 1e-9)
                diff_pct = abs(tv - rv) / denom * 100.0
                if diff_pct >= float(limit_pct):
                    api_score += min(25, 8 + diff_pct / 5.0)
                    api_findings.append(f"{label} differs by {diff_pct:.1f}%")

        if f2.get("available"):
            if not f2.get("pass"):
                formulation_score += 35
                formulation_findings.append(f"dissolution f2={f2.get('f2')} is below 50")
                action_items.append("Adjust formulation or process so the multi-media dissolution profile reaches f2 >= 50.")
            else:
                formulation_findings.append(f"dissolution f2={f2.get('f2')} meets the usual similarity threshold")
        else:
            formulation_score += 10
            formulation_findings.append("matched dissolution time points are insufficient for f2")
            action_items.append("Complete matched reference/test dissolution points from 5 to 120 min under pH 1.2, 4.5 and 6.8 media.")

        for key, label in [("dosage_form", "dosage form"), ("process_type", "manufacturing process"), ("coating", "coating")]:
            if str(ref.get(key, "")).strip().lower() != str(test.get(key, "")).strip().lower():
                formulation_score += 10
                formulation_findings.append(f"{label} differs")

        ref_exc = {str(row.get("role", "")).lower(): float(row.get("amount_pct") or 0.0) for row in ref_result["applied"].get("excipients", [])}
        test_exc = {str(row.get("role", "")).lower(): float(row.get("amount_pct") or 0.0) for row in test_result["applied"].get("excipients", [])}
        for role in sorted(set(ref_exc) | set(test_exc)):
            if abs(test_exc.get(role, 0.0) - ref_exc.get(role, 0.0)) >= 1.0:
                formulation_score += 6
                formulation_findings.append(f"excipient role '{role}' differs by {abs(test_exc.get(role, 0.0)-ref_exc.get(role, 0.0)):.1f}%")

        if auc_ratio is None or cmax_ratio is None:
            pk_score += 25
        else:
            if not (0.8 <= auc_ratio <= 1.25):
                pk_score += 30
                action_items.append("Investigate AUC deviation first: solubility, permeability, clearance and total released fraction.")
            if not (0.8 <= cmax_ratio <= 1.25):
                pk_score += 30
                action_items.append("Investigate Cmax deviation first: early dissolution, particle size, disintegrant level, compression force and gastric-emptying sensitivity.")
            if abs(tmax_delta) >= 1.0:
                pk_score += 10
                action_items.append("When Tmax is delayed, focus on 15-60 min dissolution and disintegration behavior.")

        for warning in test_result["applied"].get("excipient_effect", {}).get("warnings", []):
            formulation_score += 8
            formulation_findings.append(warning)

        root_scores = {
            "API": round(api_score, 2),
            "Formulation / Process": round(formulation_score, 2),
            "PK exposure": round(pk_score, 2),
        }
        primary_cause = max(root_scores, key=root_scores.get)
        total_score = min(100.0, api_score * 0.35 + formulation_score * 0.4 + pk_score * 0.55)
        if be_pk_pass and (not f2.get("available") or f2.get("pass")) and total_score < 25:
            risk = "Low"
            decision = "Low risk: proceed to the next formulation confirmation step."
        elif total_score >= 55 or not be_pk_pass:
            risk = "High"
            decision = "High risk: optimize formulation/process before considering a BE study."
        else:
            risk = "Medium"
            decision = "Medium risk: add dissolution and key API measurements, then re-run the review."

        if not action_items:
            action_items = [
                "Keep the current formulation direction while adding multi-media dissolution curves and measured particle-size distribution.",
                "Use reference-product batch data to re-check Cmax/AUC ratio stability.",
            ]

        run_id = f"be_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        result = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "risk": risk,
                "decision": decision,
                "primary_cause": primary_cause,
                "be_pk_pass": be_pk_pass,
                "auc_ratio": auc_ratio,
                "cmax_ratio": cmax_ratio,
                "tmax_delta_h": tmax_delta,
                "auc_90ci": auc_ci,
                "cmax_90ci": cmax_ci,
                "f2": f2.get("f2"),
                "f2_pass": f2.get("pass"),
                "root_scores": root_scores,
                "total_score": round(total_score, 2),
            },
            "reference": ref_result,
            "test": test_result,
            "dissolution": f2,
            "findings": {
                "api": api_findings or ["API key inputs are broadly aligned or not supplied"],
                "formulation": formulation_findings or ["formulation/process inputs are broadly aligned or not supplied"],
                "actions": action_items,
            },
            "method": {
                "engine": "mrgsolve/PBBM internal comparison",
                "be_criteria": "T/R 90% CI for Cmax and AUC within 80-125%; dissolution f2 >= 50 as formulation similarity screen",
                "note": "Decision-support model for formulation screening; external scientific validation is required before regulatory use.",
            },
        }
        return {"ok": True, "data": result, "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/be/optimize")
def be_optimize_run(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    """Generate test-product formulation candidates against a fixed reference product."""
    try:
        from copy import deepcopy
        from datetime import datetime, timezone
        import uuid

        def as_float(source: Dict[str, Any], key: str, default: float | None = None) -> float | None:
            value = source.get(key)
            if value in (None, "", "auto", "Auto", "AUTO"):
                return default
            try:
                return float(value)
            except Exception:
                return default

        def parse_profile(text: Any) -> list[dict[str, float]]:
            rows: list[dict[str, float]] = []
            if not text:
                return rows
            for raw in str(text).replace(";", "\n").splitlines():
                line = raw.strip()
                if not line or line.lower().startswith("time"):
                    continue
                parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip()]
                if len(parts) < 2:
                    parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    rows.append({"time_min": float(parts[0]), "released_pct": max(0.0, min(100.0, float(parts[1])))} )
                except Exception:
                    continue
            return sorted(rows, key=lambda row: row["time_min"])

        def serialize_profile(rows: list[dict[str, float]]) -> str:
            return "\n".join(f"{row['time_min']:.0f},{row['released_pct']:.1f}" for row in rows)

        def interpolate(rows: list[dict[str, float]], target: float) -> float | None:
            if not rows:
                return None
            if target <= rows[0]["time_min"]:
                return rows[0]["released_pct"]
            for left, right in zip(rows, rows[1:]):
                if left["time_min"] <= target <= right["time_min"]:
                    span = max(right["time_min"] - left["time_min"], 1e-9)
                    frac = (target - left["time_min"]) / span
                    return left["released_pct"] + frac * (right["released_pct"] - left["released_pct"])
            return rows[-1]["released_pct"]

        def blended_profile(test_text: Any, ref_text: Any, blend: float) -> str:
            ref_rows = parse_profile(ref_text)
            test_rows = parse_profile(test_text)
            if not ref_rows:
                return str(test_text or "")
            times = sorted({row["time_min"] for row in ref_rows} | {row["time_min"] for row in test_rows})
            if not times:
                times = [5, 10, 15, 30, 45, 60, 90, 120]
            rows = []
            for time_min in times:
                ref_pct = interpolate(ref_rows, time_min)
                test_pct = interpolate(test_rows, time_min)
                if ref_pct is None:
                    ref_pct = test_pct if test_pct is not None else 0.0
                if test_pct is None:
                    test_pct = ref_pct
                rows.append({"time_min": time_min, "released_pct": max(0.0, min(100.0, test_pct + (ref_pct - test_pct) * blend))})
            return serialize_profile(rows)

        def get_excipients(product: Dict[str, Any]) -> list[dict[str, Any]]:
            rows = product.get("excipients")
            if not isinstance(rows, list):
                return []
            return [dict(row) for row in rows if isinstance(row, dict)]

        def set_excipient(rows: list[dict[str, Any]], role: str, amount: float, name: str) -> list[dict[str, Any]]:
            role_l = role.lower()
            updated = False
            out = []
            for row in rows:
                item = dict(row)
                if role_l in str(item.get("role", "")).lower():
                    item["amount_pct"] = round(amount, 3)
                    updated = True
                out.append(item)
            if not updated:
                out.append({"name": name, "role": role, "amount_pct": round(amount, 3)})
            return out

        def reduce_excipient(rows: list[dict[str, Any]], role: str, max_amount: float) -> list[dict[str, Any]]:
            role_l = role.lower()
            out = []
            for row in rows:
                item = dict(row)
                if role_l in str(item.get("role", "")).lower():
                    try:
                        item["amount_pct"] = min(float(item.get("amount_pct") or 0.0), max_amount)
                    except Exception:
                        item["amount_pct"] = max_amount
                out.append(item)
            return out

        def candidate_payload(name: str, changes: list[str], mutate) -> Dict[str, Any]:
            candidate = deepcopy(payload)
            candidate.setdefault("reference", deepcopy(payload.get("reference") or {}))
            candidate.setdefault("test", deepcopy(payload.get("test") or {}))
            mutate(candidate["test"], candidate.get("reference") or {})
            return {"name": name, "changes": changes, "payload": candidate}

        def score_result(result: Dict[str, Any]) -> float:
            summary = result.get("summary", {})
            score = 100.0
            for key, weight in (("auc_ratio", 95.0), ("cmax_ratio", 115.0)):
                ratio = summary.get(key)
                if ratio in (None, 0):
                    score -= 35.0
                else:
                    score -= abs(float(ratio) - 1.0) * weight
            f2 = summary.get("f2")
            if f2 is None:
                score -= 10.0
            elif f2 < 50:
                score -= (50.0 - float(f2)) * 1.1
            else:
                score += min(12.0, (float(f2) - 50.0) * 0.25)
            if not summary.get("be_pk_pass"):
                score -= 20.0
            risk = str(summary.get("risk", "")).lower()
            if risk == "high":
                score -= 18.0
            elif risk == "medium":
                score -= 7.0
            return round(score, 3)

        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        ref = payload.get("reference") if isinstance(payload.get("reference"), dict) else {}
        test = payload.get("test") if isinstance(payload.get("test"), dict) else {}
        if not ref or not test:
            raise ValueError("reference and test product inputs are required")

        base = be_compare_run(payload, user).get("data")
        ref_pct30 = as_float(ref, "dissolution_30min_pct", None)
        test_pct30 = as_float(test, "dissolution_30min_pct", None)
        ref_sol = as_float(ref, "solubility_mg_ml", None)
        test_sol = as_float(test, "solubility_mg_ml", None)
        ref_d50 = as_float(ref, "particle_size_um", None)
        test_d50 = as_float(test, "particle_size_um", None)
        test_compression = as_float(test, "compression_force_kn", None)

        candidates: list[dict[str, Any]] = []
        candidates.append(candidate_payload(
            "Dissolution-match adjustment",
            ["Move the test dissolution profile closer to the reference profile", "Set 30 min dissolution near reference target"],
            lambda t, r: (
                t.__setitem__("dissolution_profile", blended_profile(t.get("dissolution_profile"), r.get("dissolution_profile"), 0.70)),
                t.__setitem__("dissolution_30min_pct", round(min(98.0, max(float(test_pct30 or 60.0), float(ref_pct30 or 80.0) - 3.0)), 2)),
            ),
        ))
        candidates.append(candidate_payload(
            "Particle-size reduction",
            ["Reduce D50 to improve wetting and early dissolution", "Keep API identity fixed while changing manufacturable particle target"],
            lambda t, r: t.__setitem__("particle_size_um", round(max(5.0, min(float(test_d50 or 60.0) * 0.60, float(ref_d50 or test_d50 or 60.0) * 1.15)), 2)),
        ))
        candidates.append(candidate_payload(
            "Excipient balance",
            ["Increase disintegrant support", "Reduce lubricant drag if present", "Keep reference product unchanged"],
            lambda t, r: t.__setitem__("excipients", reduce_excipient(set_excipient(get_excipients(t), "disintegrant", 4.5, "disintegrant candidate"), "lubricant", 0.6)),
        ))
        candidates.append(candidate_payload(
            "Compression/process relief",
            ["Reduce compression force to support disintegration", "Partially recover early dissolution profile"],
            lambda t, r: (
                t.__setitem__("compression_force_kn", round(min(float(test_compression or 18.0), 14.0), 2)),
                t.__setitem__("dissolution_profile", blended_profile(t.get("dissolution_profile"), r.get("dissolution_profile"), 0.40)),
            ),
        ))
        candidates.append(candidate_payload(
            "Solubility assistance",
            ["Add solubilizer/surfactant candidate", "Increase apparent solubility input for sensitivity review"],
            lambda t, r: (
                t.__setitem__("solubility_mg_ml", round(max(float(test_sol or 0.1) * 1.35, min(float(ref_sol or test_sol or 0.1) * 0.90, float(test_sol or 0.1) * 1.65)), 4)),
                t.__setitem__("excipients", set_excipient(get_excipients(t), "solubilizer", 2.0, "solubilizer candidate")),
            ),
        ))
        candidates.append(candidate_payload(
            "Combined conservative proposal",
            ["Blend dissolution 55% toward reference", "Set D50 closer to reference", "Balance disintegrant/lubricant"],
            lambda t, r: (
                t.__setitem__("dissolution_profile", blended_profile(t.get("dissolution_profile"), r.get("dissolution_profile"), 0.55)),
                t.__setitem__("dissolution_30min_pct", round(min(95.0, max(float(test_pct30 or 60.0) + 10.0, float(ref_pct30 or 80.0) - 8.0)), 2)),
                t.__setitem__("particle_size_um", round(max(5.0, min(float(test_d50 or 60.0) * 0.70, float(ref_d50 or test_d50 or 60.0) * 1.25)), 2)),
                t.__setitem__("excipients", reduce_excipient(set_excipient(get_excipients(t), "disintegrant", 4.0, "disintegrant candidate"), "lubricant", 0.7)),
            ),
        ))
        candidates.append(candidate_payload(
            "Combined aggressive proposal",
            ["Blend dissolution 80% toward reference", "Reduce D50 strongly", "Add solubilizer and lower lubricant"],
            lambda t, r: (
                t.__setitem__("dissolution_profile", blended_profile(t.get("dissolution_profile"), r.get("dissolution_profile"), 0.80)),
                t.__setitem__("dissolution_30min_pct", round(min(98.0, max(float(test_pct30 or 60.0) + 18.0, float(ref_pct30 or 80.0) - 2.0)), 2)),
                t.__setitem__("particle_size_um", round(max(3.0, min(float(test_d50 or 60.0) * 0.50, float(ref_d50 or test_d50 or 60.0) * 1.05)), 2)),
                t.__setitem__("excipients", set_excipient(reduce_excipient(set_excipient(get_excipients(t), "disintegrant", 5.0, "disintegrant candidate"), "lubricant", 0.45), "solubilizer", 1.5, "solubilizer candidate")),
            ),
        ))

        evaluated = []
        seen = set()
        for candidate in candidates:
            key = json.dumps(candidate["payload"].get("test", {}), sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            try:
                result = be_compare_run(candidate["payload"], user).get("data")
                evaluated.append({
                    "name": candidate["name"],
                    "score": score_result(result),
                    "changes": candidate["changes"],
                    "summary": result.get("summary", {}),
                    "test_input": candidate["payload"].get("test", {}),
                    "result": {
                        "reference": {"pk": result.get("reference", {}).get("pk", {})},
                        "test": {"pk": result.get("test", {}).get("pk", {}), "dissolution_summary": result.get("test", {}).get("dissolution_summary", {})},
                        "dissolution": result.get("dissolution", {}),
                    },
                })
            except Exception as candidate_exc:
                evaluated.append({"name": candidate["name"], "score": -999, "changes": candidate["changes"], "error": str(candidate_exc)})
        evaluated = sorted(evaluated, key=lambda row: row.get("score", -999), reverse=True)[:3]
        run_id = f"beopt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return {
            "ok": True,
            "data": {
                "run_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "base": base,
                "recommendations": evaluated,
                "method": {
                    "engine": "rule-guided local PBBM search",
                    "fixed_side": "Reference product is not modified",
                    "optimized_side": "Test product only",
                    "objective": "bring AUC/Cmax T/R toward 1.0 and f2 toward >=50 while reducing root-cause risk",
                },
            },
            "error": None,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/pbpk/run")
def pbpk_run(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    """Run the dedicated PBPK/PBBM model with optional expert parameter overrides."""
    try:
        from datetime import datetime, timezone
        import uuid

        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else payload
        advanced = payload.get("advanced") or payload.get("pbpk_overrides") or {}
        reference_payload = payload.get("reference") if isinstance(payload.get("reference"), dict) else {}
        request_model = Pipeline58Request(**request_payload)
        if request_model.project.owner == "analyst":
            request_model.project.owner = str(user.get("username", "analyst"))

        def clean_float(key: str):
            value = advanced.get(key)
            if value in (None, "", "auto", "Auto", "AUTO"):
                return None
            try:
                return float(value)
            except Exception:
                return None

        desc = smiles_descriptors(request_model.smiles)
        admet = SERVICE._admet(request_model, desc)
        applied: Dict[str, Any] = {}

        descriptor_map = {
            "mw": "mw",
            "logp": "logp",
            "tpsa": "tpsa",
            "logs": "logs",
        }
        for key, target in descriptor_map.items():
            val = clean_float(key)
            if val is not None:
                admet.setdefault("descriptors", {})[target] = val
                applied[key] = val

        for key in ("pka_acid", "pka_base"):
            val = clean_float(key)
            if val is not None:
                admet.setdefault("descriptors", {})[key] = val
                applied[key] = val

        sol_mg_ml = clean_float("solubility_mg_ml")
        if sol_mg_ml is not None and sol_mg_ml > 0:
            try:
                mw_for_sol = float(admet.get("descriptors", {}).get("mw") or desc.get("mw") or 400.0)
            except Exception:
                mw_for_sol = 400.0
            # mg/mL equals g/L; mol/L = (g/L) / molecular weight.
            log_molar_solubility = round(math.log10(max(sol_mg_ml / max(mw_for_sol, 1e-6), 1e-12)), 4)
            admet.setdefault("descriptors", {})["logs"] = log_molar_solubility
            admet.setdefault("absorption", {}).setdefault("Solubility", {})["value"] = log_molar_solubility
            admet["absorption"]["Solubility"]["source"] = "user_solubility_mg_ml"
            applied["solubility_mg_ml"] = sol_mg_ml
            applied["logs_from_solubility_mg_ml"] = log_molar_solubility

        metric_map = {
            "caco2": ("absorption", "Caco2_Papp"),
            "oral_f": ("absorption", "Oral_F"),
            "ppb": ("distribution", "PPB"),
            "vdss": ("distribution", "VDss"),
            "cl_total": ("excretion", "CLtotal"),
            "cl_renal": ("excretion", "CLrenal"),
            "cyp3a4_sub": ("metabolism", "CYP3A4_substrate"),
            "cyp3a4_inh": ("metabolism", "CYP3A4_inhibitor"),
        }
        for key, (section, metric) in metric_map.items():
            val = clean_float(key)
            if val is not None:
                admet.setdefault(section, {}).setdefault(metric, {})["value"] = val
                admet[section][metric]["source"] = "user_override"
                applied[key] = val

        pbpk_overrides: Dict[str, Any] = {}
        for key in (
            "ka_multiplier", "cl_multiplier", "v_multiplier",
            "dissolution_h", "gastric_emptying_h", "duodenum_to_jejunum_h",
            "jejunum_to_ileum_h", "ileum_to_colon_h", "colon_transit_h",
            "abs_duodenum_h", "abs_jejunum_h", "abs_ileum_h", "abs_colon_h",
            "solubility_mg_ml", "pka_acid", "pka_base", "particle_size_um",
            "dissolution_t50_min", "dissolution_30min_pct",
        ):
            val = clean_float(key)
            if val is not None:
                pbpk_overrides[key] = val
                applied[key] = val
        for key in ("release_type", "food_state", "formulation_notes", "api_data_source", "formulation_data_source", "dissolution_data_source", "test_dissolution_profile"):
            val = advanced.get(key)
            if val not in (None, ""):
                pbpk_overrides[key] = str(val)
                applied[key] = str(val)

        pkpd_overrides: Dict[str, float] = {}
        for key in ("ec50_multiplier", "hill", "emax"):
            val = clean_float(key)
            if val is not None:
                pkpd_overrides[key] = val
                applied[key] = val

        def collect_reference_overrides(source: Dict[str, Any]) -> Dict[str, Any]:
            ref: Dict[str, Any] = {}
            numeric_keys = (
                "solubility_mg_ml", "pka_acid", "pka_base", "particle_size_um",
                "dissolution_t50_min", "dissolution_30min_pct", "ka_multiplier",
                "dissolution_h", "gastric_emptying_h", "abs_duodenum_h",
                "abs_jejunum_h", "abs_ileum_h", "abs_colon_h",
            )
            for key in numeric_keys:
                value = source.get(key)
                if value in (None, "", "auto", "Auto", "AUTO"):
                    continue
                try:
                    ref[key] = float(value)
                except Exception:
                    continue
            for key in ("release_type", "food_state", "formulation_notes", "api_data_source", "formulation_data_source", "dissolution_data_source", "reference_dissolution_profile"):
                value = source.get(key)
                if value not in (None, ""):
                    ref[key] = str(value)
            return ref

        def parse_profile(text: Any) -> list[dict[str, float]]:
            rows: list[dict[str, float]] = []
            if not text:
                return rows
            for raw in str(text).replace(";", "\n").splitlines():
                line = raw.strip()
                if not line or line.lower().startswith("time"):
                    continue
                parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip()]
                if len(parts) < 2:
                    parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    rows.append({"time_min": float(parts[0]), "released_pct": max(0.0, min(100.0, float(parts[1])))})
                except Exception:
                    continue
            return sorted(rows, key=lambda x: x["time_min"])

        def similarity_f2(test_rows: list[dict[str, float]], ref_rows: list[dict[str, float]]) -> Dict[str, Any]:
            if len(test_rows) < 3 or len(ref_rows) < 3:
                return {"available": False, "f2": None, "pass": None, "n": 0, "rows": []}
            ref_by_time = {round(r["time_min"], 4): r["released_pct"] for r in ref_rows}
            pairs = []
            for row in test_rows:
                key = round(row["time_min"], 4)
                if key in ref_by_time:
                    pairs.append({"time_min": row["time_min"], "test": row["released_pct"], "ref": ref_by_time[key]})
            if len(pairs) < 3:
                return {"available": False, "f2": None, "pass": None, "n": len(pairs), "rows": pairs}
            mse = sum((p["test"] - p["ref"]) ** 2 for p in pairs) / len(pairs)
            f2 = 50.0 * math.log10((1.0 + mse) ** -0.5 * 100.0)
            return {"available": True, "f2": round(f2, 2), "pass": f2 >= 50.0, "n": len(pairs), "rows": pairs}

        def pk_metric(model: Dict[str, Any], key: str) -> float:
            value = (model.get("pk_parameters", {}).get(key, {}) or {}).get("value", 0.0)
            try:
                return float(value or 0.0)
            except Exception:
                return 0.0

        def ci90(ratio: float | None, cv_pct: float, n: int) -> Dict[str, Any]:
            if ratio is None or ratio <= 0:
                return {"low": None, "high": None}
            cv = max(float(cv_pct or 30.0) / 100.0, 0.01)
            subjects = max(int(n or 24), 4)
            se = math.sqrt(2.0 * math.log(1.0 + cv * cv) / subjects)
            low = math.exp(math.log(ratio) - 1.645 * se)
            high = math.exp(math.log(ratio) + 1.645 * se)
            return {"low": round(low, 3), "high": round(high, 3)}

        pbpk = SERVICE._pbpk(request_model, admet, overrides=pbpk_overrides)
        pbbm = SERVICE._pbbm_profile(request_model, pbpk, admet)
        pkpd = SERVICE._pkpd(request_model, pbpk, admet, overrides=pkpd_overrides)

        be_comparison: Dict[str, Any] = {"available": False}
        if str(reference_payload.get("enabled", "false")).lower() in {"1", "true", "yes", "on"}:
            ref_advanced = reference_payload.get("advanced") if isinstance(reference_payload.get("advanced"), dict) else {}
            ref_overrides = collect_reference_overrides(ref_advanced)
            ref_request = request_model.model_copy(deep=True)
            if reference_payload.get("name"):
                ref_request.project.project_name = str(reference_payload.get("name"))
            ref_pbpk = SERVICE._pbpk(ref_request, copy.deepcopy(admet), overrides=ref_overrides)
            ref_pbbm = SERVICE._pbbm_profile(ref_request, ref_pbpk, copy.deepcopy(admet))
            test_auc = pk_metric(pbpk, "AUC0_t")
            ref_auc = pk_metric(ref_pbpk, "AUC0_t")
            test_cmax = pk_metric(pbpk, "Cmax")
            ref_cmax = pk_metric(ref_pbpk, "Cmax")
            test_tmax = pk_metric(pbpk, "Tmax")
            ref_tmax = pk_metric(ref_pbpk, "Tmax")
            auc_ratio = round(test_auc / ref_auc, 4) if ref_auc > 0 else None
            cmax_ratio = round(test_cmax / ref_cmax, 4) if ref_cmax > 0 else None
            cv_pct = float(ref_advanced.get("be_cv_pct") or advanced.get("be_cv_pct") or 30.0)
            subject_n = int(float(ref_advanced.get("be_subject_n") or advanced.get("be_subject_n") or 24))
            auc_ci = ci90(auc_ratio, cv_pct, subject_n)
            cmax_ci = ci90(cmax_ratio, cv_pct, subject_n)
            be_pass = bool(
                auc_ci["low"] is not None and auc_ci["low"] >= 0.8 and auc_ci["high"] <= 1.25
                and cmax_ci["low"] is not None and cmax_ci["low"] >= 0.8 and cmax_ci["high"] <= 1.25
            )
            test_profile = parse_profile(advanced.get("test_dissolution_profile"))
            ref_profile = parse_profile(ref_advanced.get("reference_dissolution_profile"))
            f2 = similarity_f2(test_profile, ref_profile)
            be_comparison = {
                "available": True,
                "reference_name": str(reference_payload.get("name") or "Reference product"),
                "method": "virtual T/R comparison with PowerTOST-style 90% CI",
                "cv_pct": cv_pct,
                "subject_n": subject_n,
                "test_pk": {"Cmax": round(test_cmax, 4), "Tmax": round(test_tmax, 4), "AUC0_t": round(test_auc, 4)},
                "reference_pk": {"Cmax": round(ref_cmax, 4), "Tmax": round(ref_tmax, 4), "AUC0_t": round(ref_auc, 4)},
                "be": {
                    "auc_ratio": auc_ratio, "cmax_ratio": cmax_ratio,
                    "auc_90ci": auc_ci, "cmax_90ci": cmax_ci,
                    "pass": be_pass,
                    "risk": "Low" if be_pass else "Review",
                    "criteria": "90% CI for AUC and Cmax within 80-125%",
                },
                "dissolution": f2,
                "reference_overrides": ref_overrides,
                "reference_pbbm_summary": ref_pbbm.get("summary", {}),
            }

        base_cmax = pk_metric(pbpk, "Cmax")
        base_auc = pk_metric(pbpk, "AUC0_t")
        base_tmax = pk_metric(pbpk, "Tmax")

        def safe_float(value: Any, default: float) -> float:
            try:
                if value in (None, "", "auto", "Auto", "AUTO"):
                    return default
                return float(value)
            except Exception:
                return default

        def model_summary(label: str, overrides: Dict[str, Any], note: str = "") -> Dict[str, Any]:
            try:
                model = SERVICE._pbpk(request_model, copy.deepcopy(admet), overrides=overrides)
                summary = SERVICE._pbbm_profile(request_model, model, copy.deepcopy(admet)).get("summary", {})
                cmax = pk_metric(model, "Cmax")
                auc = pk_metric(model, "AUC0_t")
                tmax = pk_metric(model, "Tmax")
                return {
                    "label": label,
                    "status": "ok",
                    "note": note,
                    "Cmax": round(cmax, 4),
                    "Tmax": round(tmax, 4),
                    "AUC0_t": round(auc, 4),
                    "F": round(float((model.get("pk_parameters", {}) or {}).get("F") or summary.get("F_estimated") or 0.0), 4),
                    "Cmax_ratio": round(cmax / base_cmax, 4) if base_cmax > 0 else None,
                    "AUC_ratio": round(auc / base_auc, 4) if base_auc > 0 else None,
                    "overrides": overrides,
                }
            except Exception as scenario_exc:
                return {
                    "label": label,
                    "status": "failed",
                    "note": str(scenario_exc),
                    "Cmax": None,
                    "Tmax": None,
                    "AUC0_t": None,
                    "F": None,
                    "Cmax_ratio": None,
                    "AUC_ratio": None,
                    "overrides": overrides,
                }

        base_dissolution = safe_float(advanced.get("dissolution_30min_pct"), 70.0)
        base_particle = safe_float(advanced.get("particle_size_um"), 50.0)
        base_solubility = safe_float(advanced.get("solubility_mg_ml"), 1.0)
        scenario_rows = [
            model_summary("Current input", dict(pbpk_overrides), "Current form values"),
            model_summary(
                "Fed state",
                {**pbpk_overrides, "food_state": "fed"},
                "Food-effect check with the same formulation",
            ),
            model_summary(
                "Slower dissolution",
                {
                    **pbpk_overrides,
                    "dissolution_30min_pct": max(5.0, base_dissolution * 0.6),
                    "particle_size_um": max(1.0, base_particle * 1.5),
                },
                "Low-release / larger-particle stress case",
            ),
            model_summary(
                "Faster dissolution",
                {
                    **pbpk_overrides,
                    "dissolution_30min_pct": min(100.0, max(base_dissolution * 1.25, base_dissolution + 10.0)),
                    "particle_size_um": max(1.0, base_particle * 0.6),
                },
                "High-release / smaller-particle improvement case",
            ),
        ]
        scenario_comparison = {
            "available": True,
            "method": "same-compound virtual scenario comparison using the current PBPK/PBBM engine",
            "baseline": {"Cmax": round(base_cmax, 4), "Tmax": round(base_tmax, 4), "AUC0_t": round(base_auc, 4)},
            "scenarios": scenario_rows,
        }

        sensitivity_specs = [
            ("Solubility", "solubility_mg_ml", max(base_solubility * 2.0, base_solubility + 0.25), "Increase solubility input"),
            ("Dissolution 30 min", "dissolution_30min_pct", min(100.0, max(base_dissolution + 20.0, base_dissolution * 1.25)), "Improve early release"),
            ("Particle size D50", "particle_size_um", max(1.0, base_particle * 0.5), "Reduce particle size"),
            ("Absorption rate", "ka_multiplier", safe_float(advanced.get("ka_multiplier"), 1.0) * 1.25, "Increase Ka multiplier"),
            ("Clearance", "cl_multiplier", safe_float(advanced.get("cl_multiplier"), 1.0) * 1.25, "Increase total clearance"),
        ]
        sensitivity_rows = []
        for label, key, value, change_note in sensitivity_specs:
            variant = model_summary(label, {**pbpk_overrides, key: value}, change_note)
            if variant["status"] == "ok":
                cmax_delta = ((float(variant["Cmax"]) / base_cmax) - 1.0) * 100.0 if base_cmax > 0 else 0.0
                auc_delta = ((float(variant["AUC0_t"]) / base_auc) - 1.0) * 100.0 if base_auc > 0 else 0.0
                impact = abs(cmax_delta) + 0.6 * abs(auc_delta)
                direction = "increase" if cmax_delta >= 0 else "decrease"
                variant.update({
                    "parameter": key,
                    "new_value": round(float(value), 4),
                    "Cmax_delta_pct": round(cmax_delta, 2),
                    "AUC_delta_pct": round(auc_delta, 2),
                    "impact_score": round(impact, 2),
                    "interpretation": f"{label} {direction}s Cmax by {abs(cmax_delta):.1f}% under this perturbation.",
                })
            sensitivity_rows.append(variant)
        sensitivity_rows = sorted(sensitivity_rows, key=lambda x: float(x.get("impact_score") or -1.0), reverse=True)
        sensitivity_analysis = {
            "available": True,
            "method": "one-factor-at-a-time PBPK perturbation; each row re-runs the same PBPK/PBBM engine with one changed parameter",
            "factors": sensitivity_rows,
        }

        top_factor = next((row for row in sensitivity_rows if row.get("status") == "ok"), {})
        high_exposure = base_cmax >= 1000 or base_auc >= 10000
        be_state = "not requested"
        if be_comparison.get("available"):
            be_state = "pass" if (be_comparison.get("be", {}) or {}).get("pass") else "review"
        decision_level = "Formulation review" if high_exposure or be_state == "review" else "Proceed with current scenario"
        decision_summary = {
            "available": True,
            "decision_level": decision_level,
            "headline": f"{request_model.compound_name} PBPK/PBBM run completed; main driver is {top_factor.get('label', 'exposure parameter')}." ,
            "items": [
                {
                    "area": "Exposure",
                    "finding": f"Cmax {round(base_cmax, 3)} ng/mL, AUC0-t {round(base_auc, 3)} ng*h/mL, Tmax {round(base_tmax, 3)} h.",
                    "action": "Use as baseline for formulation and dosing discussion.",
                },
                {
                    "area": "Sensitivity",
                    "finding": f"Top factor: {top_factor.get('label', '-')}; Cmax delta {top_factor.get('Cmax_delta_pct', '-')}%, AUC delta {top_factor.get('AUC_delta_pct', '-')}%.",
                    "action": "Prioritize this parameter for measured input or formulation control.",
                },
                {
                    "area": "Reference/Test",
                    "finding": f"Virtual BE comparison: {be_state}.",
                    "action": "If required, add measured reference dissolution and observed PK for stronger review.",
                },
                {
                    "area": "Next experiment",
                    "finding": "Model confidence improves most when solubility, dissolution profile, PPB, clearance, and observed PK are supplied.",
                    "action": "Request measured API/formulation values before external scientific verification.",
                },
            ],
        }

        run_id = f"pbpk_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        result = {
            "step5_admet": admet,
            "step6_pbpk": pbpk,
            "pbbm": pbbm,
            "step7_pkpd": pkpd,
            "be_comparison": be_comparison,
            "scenario_comparison": scenario_comparison,
            "sensitivity_analysis": sensitivity_analysis,
            "decision_summary": decision_summary,
            "advanced_overrides": applied,
        }
        return {
            "ok": True,
            "data": {
                "summary": {
                    "run_id": run_id,
                    "compound_name": request_model.compound_name,
                    "target_name": request_model.target_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "engine": pbpk.get("model_backend", {}).get("backend", "mrgsolve"),
                    "advanced_override_count": len(applied),
                    "target_attainment": pkpd.get("dose_optimization", {}).get("target_attainment"),
                    "recommended_regimen": pkpd.get("dose_optimization", {}).get("recommended_regimen"),
                    "be_pass": (be_comparison.get("be", {}) or {}).get("pass"),
                    "be_risk": (be_comparison.get("be", {}) or {}).get("risk"),
                },
                "request": request_model.model_dump(),
                "result": result,
            },
            "error": None,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/pipeline58/analyze")
def pipeline58_analyze(
    request: Pipeline58Request,
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        if request.project.owner == "analyst":
            request.project.owner = str(user.get("username", "analyst"))
        detail = SERVICE.run_pipeline(request)
        return {"ok": True, "data": detail.model_dump(), "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/pipeline58/preview")
def pipeline58_preview(
    request: Pipeline58Request,
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        if request.project.owner == "analyst":
            request.project.owner = str(user.get("username", "analyst"))
        detail = SERVICE.preview_pipeline(request)
        return {"ok": True, "data": detail.model_dump(), "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/pipeline58/admet/batch")
def pipeline58_admet_batch(
    request: ADMETBatchRequest,
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": SERVICE.batch_admet_screen(request), "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/v1/pipeline58/tasks/admet-batch")
def pipeline58_admet_batch_task(
    request: ADMETBatchTaskRequest,
    user: Dict[str, Any] = Depends(_require_role("analyst")),
) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": SERVICE.submit_admet_batch_task(request, user["username"]), "error": None}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/pipeline58/tasks")
def pipeline58_tasks(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    return {"ok": True, "data": SERVICE.list_tasks(user["username"], user["role"]), "error": None}


@app.get("/api/v1/pipeline58/tasks/{task_id}")
def pipeline58_task_detail(
    task_id: str,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> Dict[str, Any]:
    try:
        return {"ok": True, "data": SERVICE.get_task(task_id, user["username"], user["role"]), "error": None}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")


@app.get("/api/v1/pipeline58/tasks/{task_id}/results.csv", response_class=PlainTextResponse)
def pipeline58_task_csv(
    task_id: str,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> PlainTextResponse:
    try:
        task = SERVICE.get_task(task_id, user["username"], user["role"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")
    csv_path = Path(str(task.get("csv_path", "")))
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="csv not found")
    return PlainTextResponse(csv_path.read_text(encoding="utf-8-sig"), media_type="text/csv; charset=utf-8")


@app.get("/api/v1/pipeline58/tasks/{task_id}/report/html", response_class=HTMLResponse)
def pipeline58_task_report_html(
    task_id: str,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> HTMLResponse:
    try:
        task = SERVICE.get_task(task_id, user["username"], user["role"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")
    html_path = Path(str(task.get("html_report_path", "")))
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="html report not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/v1/pipeline58/runs")
def pipeline58_runs(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    return {"ok": True, "data": [item.model_dump() for item in SERVICE.list_runs(user["username"], user["role"])], "error": None}


@app.get("/api/v1/pipeline58/projects")
def pipeline58_projects(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    return {"ok": True, "data": SERVICE.list_projects(user["username"], user["role"]), "error": None}


@app.get("/api/v1/pipeline58/audit")
def pipeline58_audit(user: Dict[str, Any] = Depends(_require_role("viewer"))) -> Dict[str, Any]:
    events = SERVICE.list_audit_events(user["username"], user["role"])
    if role_allows(str(user.get("role", "")), "admin"):
        events = AUTH.list_auth_audit() + events
    return {"ok": True, "data": events, "error": None}


@app.get("/api/v1/pipeline58/runs/{run_id}")
def pipeline58_run_detail(
    run_id: str,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> Dict[str, Any]:
    try:
        detail = SERVICE.get_run(run_id, user["username"], user["role"])
        return {"ok": True, "data": detail.model_dump(), "error": None}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")


@app.get("/api/v1/pipeline58/runs/{run_id}/report", response_class=PlainTextResponse)
def pipeline58_run_report(
    run_id: str,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> str:
    try:
        detail = SERVICE.get_run(run_id, user["username"], user["role"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")
    report_path = Path(detail.summary.report_path)
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    return report_path.read_text(encoding="utf-8")


@app.get("/api/v1/pipeline58/runs/{run_id}/report/html", response_class=HTMLResponse)
def pipeline58_run_report_html(
    run_id: str,
    user: Dict[str, Any] = Depends(_require_role("viewer")),
) -> HTMLResponse:
    try:
        detail = SERVICE.get_run(run_id, user["username"], user["role"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="权限不足")
    return HTMLResponse(SERVICE.render_run_report_html(detail))


if __name__ == "__main__":
    uvicorn.run(app, host=SETTINGS.host, port=SETTINGS.port)
