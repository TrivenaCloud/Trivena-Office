"""Brief → one-slide PPTX for TrivOffice (replaces Genspark tool_cli /slide_generate)."""

from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Any

import httpx
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

_HEX = re.compile(r"#([0-9a-fA-F]{6})")


def _rgb(hex_color: str, default: str = "1A1A2E") -> RGBColor:
    m = _HEX.search(hex_color or "")
    h = m.group(1) if m else default
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _pick_colors(style_skill: str) -> dict[str, str]:
    found = _HEX.findall(style_skill or "")
    # Prefer later explicit "Main background" / "Primary accent" style lines when present
    bg, text, accent = "FFFFFF", "1A1A2E", "2563EB"
    skill = style_skill or ""
    for label, key in (
        ("Main background", "bg"),
        ("Main text", "text"),
        ("Primary accent", "accent"),
    ):
        m = re.search(rf"{label}[^#\n]*?(#[0-9a-fA-F]{{6}})", skill, re.I)
        if m:
            if key == "bg":
                bg = m.group(1)
            elif key == "text":
                text = m.group(1)
            else:
                accent = m.group(1)
    if found and bg == "FFFFFF":
        # Fall back to first hexes in the skill if labels missing
        if len(found) >= 1:
            bg = "#" + found[0]
        if len(found) >= 2:
            text = "#" + found[1]
        if len(found) >= 3:
            accent = "#" + found[2]
    return {"bg": bg if bg.startswith("#") else f"#{bg}", "text": text if text.startswith("#") else f"#{text}", "accent": accent if accent.startswith("#") else f"#{accent}"}


async def _gemini_structure(
    *,
    brief: str,
    title: str,
    style_skill: str,
    deck_context: dict[str, Any] | None,
) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    model = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
    if not api_key:
        # Offline-ish fallback: crude split of the brief
        lines = [ln.strip(" -•\t") for ln in brief.splitlines() if ln.strip()]
        return {
            "title": title or (lines[0][:80] if lines else "Slide"),
            "bullets": lines[1:7] if len(lines) > 1 else lines[:5],
            "subtitle": "",
        }

    ctx = json.dumps(deck_context or {}, ensure_ascii=False)[:1500]
    prompt = (
        "You design one presentation slide. Reply with ONLY valid JSON (no markdown):\n"
        '{"title":"...","subtitle":"...","bullets":["...","..."],"notes":"..."}\n'
        "Rules: 3-6 short bullets; concrete facts from the brief; no invented numbers; "
        "title max 60 chars; bullets max 14 words each.\n\n"
        f"TITLE HINT: {title}\n"
        f"STYLE: {style_skill[:1200]}\n"
        f"DECK CONTEXT: {ctx}\n"
        f"BRIEF:\n{brief[:6000]}"
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 1200,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Gemini slide plan failed HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    content = (
        ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned non-JSON slide plan: {content[:200]}") from e
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini slide plan was not an object")
    return parsed


async def _fetch_image(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "TrivOffice-SlideGen/1.0"})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
    except Exception:
        return None
    return None


def _build_pptx(
    structure: dict[str, Any],
    *,
    colors: dict[str, str],
    image_bytes: bytes | None,
    width_px: int,
    height_px: int,
) -> bytes:
    # Map CSS-ish pixels (1280×720) onto inches at 96dpi
    w_in = max(8.0, min(20.0, (width_px or 1280) / 96.0))
    h_in = max(5.0, min(12.0, (height_px or 720) / 96.0))
    prs = Presentation()
    prs.slide_width = Inches(w_in)
    prs.slide_height = Inches(h_in)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    # Background fill via a full-bleed rectangle (more reliable than slide background theme)
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(0), Emu(0), prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = _rgb(colors["bg"], "FFFFFF")
    bg.line.fill.background()

    # Accent bar on the left
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.18), prs.slide_height
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = _rgb(colors["accent"], "2563EB")
    bar.line.fill.background()

    title = str(structure.get("title") or "Slide").strip()[:120]
    subtitle = str(structure.get("subtitle") or "").strip()[:160]
    bullets = structure.get("bullets") or []
    if not isinstance(bullets, list):
        bullets = [str(bullets)]
    bullets = [str(b).strip() for b in bullets if str(b).strip()][:8]

    has_image = bool(image_bytes)
    text_right = Inches(w_in - 0.6) if not has_image else Inches(w_in * 0.55)

    title_box = slide.shapes.add_textbox(Inches(0.55), Inches(0.35), text_right - Inches(0.55), Inches(1.1))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(32)
    p.font.bold = True
    p.font.color.rgb = _rgb(colors["text"], "1A1A2E")
    p.alignment = PP_ALIGN.LEFT

    y = Inches(1.4)
    if subtitle:
        sub_box = slide.shapes.add_textbox(Inches(0.55), y, text_right - Inches(0.55), Inches(0.5))
        st = sub_box.text_frame.paragraphs[0]
        st.text = subtitle
        st.font.size = Pt(16)
        st.font.color.rgb = _rgb(colors["accent"], "2563EB")
        y = Inches(1.95)

    body_box = slide.shapes.add_textbox(
        Inches(0.55), y, text_right - Inches(0.55), Inches(h_in) - y - Inches(0.4)
    )
    btf = body_box.text_frame
    btf.word_wrap = True
    for i, bullet in enumerate(bullets or [title]):
        para = btf.paragraphs[0] if i == 0 else btf.add_paragraph()
        para.text = bullet
        para.level = 0
        para.font.size = Pt(18)
        para.font.color.rgb = _rgb(colors["text"], "1A1A2E")
        para.space_after = Pt(10)

    if has_image and image_bytes:
        img_left = Inches(w_in * 0.58)
        img_top = Inches(1.3)
        img_w = Inches(w_in * 0.36)
        img_h = Inches(h_in - 2.0)
        try:
            slide.shapes.add_picture(io.BytesIO(image_bytes), img_left, img_top, width=img_w, height=img_h)
        except Exception:
            pass

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


async def generate_slide_pptx(payload: dict[str, Any]) -> dict[str, Any]:
    brief = str(payload.get("brief") or "").strip()
    if not brief:
        raise ValueError("brief is required")
    title = str(payload.get("title") or "").strip()
    style_skill = str(payload.get("style_skill") or payload.get("styleSkill") or "")
    deck_context = payload.get("deck_context") or payload.get("deckContext")
    if deck_context is not None and not isinstance(deck_context, dict):
        deck_context = None
    images = payload.get("images") or []
    width = int(payload.get("width") or 1280)
    height = int(payload.get("height") or 720)

    structure = await _gemini_structure(
        brief=brief, title=title, style_skill=style_skill, deck_context=deck_context
    )
    if title and not structure.get("title"):
        structure["title"] = title

    image_bytes = None
    if isinstance(images, list):
        for item in images[:3]:
            url = item.get("url") if isinstance(item, dict) else item
            if isinstance(url, str) and url.startswith("http"):
                image_bytes = await _fetch_image(url)
                if image_bytes:
                    break

    colors = _pick_colors(style_skill)
    pptx_bytes = _build_pptx(
        structure, colors=colors, image_bytes=image_bytes, width_px=width, height_px=height
    )
    model = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
    return {
        "pptx_base64": base64.b64encode(pptx_bytes).decode("ascii"),
        "model": f"trivena-local/{model}",
        "title": structure.get("title"),
    }
