import io
import re
import streamlit as st
import pymupdf  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from streamlit_drawable_canvas import st_canvas

import os
import base64

st.set_page_config(
    page_title="EDITOR IMSS PDF - OOAD Sonora",
    page_icon="logo_imss_sonora_thumb.png" if os.path.exists("logo_imss_sonora_thumb.png") else "🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS avanzados
st.markdown("""
<style>
    .header-container {
        background: linear-gradient(135deg, #090e1a 0%, #172033 100%);
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 12px 20px;
        margin-bottom: 14px;
        color: #ffffff;
    }
    .badge-irreversible {
        background-color: rgba(225, 29, 72, 0.18);
        color: #f43f5e;
        border: 1px solid #f43f5e;
        border-radius: 5px;
        font-size: 0.72rem;
        font-weight: 700;
        padding: 2px 8px;
        letter-spacing: 0.05em;
        vertical-align: middle;
        margin-left: 8px;
        display: inline-block;
    }
    .header-title {
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        display: inline-block;
        color: #f8fafc;
    }
    .header-sub {
        color: #94a3b8;
        font-size: 0.82rem;
        margin-top: 2px;
    }
    .page-indicator-pill {
        background: #0f172a;
        color: #f8fafc;
        padding: 5px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.9rem;
        border: 1px solid #334155;
        text-align: center;
        display: inline-block;
    }
    .status-badge {
        background: #064e3b;
        color: #a7f3d0;
        border: 1px solid #059669;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 0.88rem;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 8px;
    }
    .pending-badge {
        background: #451a03;
        color: #fcd34d;
        border: 1px solid #f59e0b;
        padding: 6px 14px;
        border-radius: 6px;
        font-size: 0.88rem;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 8px;
    }
    /* Banner informativo solo visible en celulares */
    .mobile-tip-banner {
        display: none;
        background: linear-gradient(135deg, rgba(14, 165, 233, 0.15) 0%, rgba(30, 41, 59, 0.8) 100%);
        border: 1px solid #0284c7;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 12px;
        color: #f0f9ff;
        font-size: 0.82rem;
        line-height: 1.45;
    }
    @media (max-width: 768px) {
        .mobile-tip-banner {
            display: block !important;
        }
    }
</style>
""", unsafe_allow_html=True)


# --- FUNCIONES DE CACHÉ Y RENDERIZADO ---
@st.cache_data(show_spinner=False)
def render_page_image(pdf_bytes: bytes, page_num: int, dpi: int = 150) -> bytes:
    """Renderiza una página de PDF a imagen PNG utilizando PyMuPDF."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if 0 <= page_num < len(doc):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    return b""


@st.cache_data(show_spinner=False)
def get_pdf_metadata(pdf_bytes: bytes):
    """Extrae metadatos y número de páginas del documento."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    metadata = doc.metadata or {}
    return {
        "page_count": len(doc),
        "title": metadata.get("title", "") or "Sin título",
        "author": metadata.get("author", "") or "Desconocido"
    }


def push_history():
    """Guarda una instantánea del PDF para permitir Deshacer (Undo)."""
    if "history" not in st.session_state:
        st.session_state.history = []
    if st.session_state.pdf_bytes:
        st.session_state.history.append(st.session_state.pdf_bytes)
        if len(st.session_state.history) > 10:
            st.session_state.history.pop(0)


def pop_history():
    """Restaura la instantánea previa del documento."""
    if "history" in st.session_state and st.session_state.history:
        st.session_state.pdf_bytes = st.session_state.history.pop()
        st.session_state.canvas_epoch += 1
        st.toast("Cambio revertido", icon="↩️")
        st.rerun()


# --- CLASIFICACIÓN ROBUSTA DE OBJETOS DEL LIENZO ---
def is_blackout_object(obj: dict) -> bool:
    """Determina si un objeto del lienzo corresponde a Caja Negra o a Pixelado."""
    f = str(obj.get("fill", "")).replace(" ", "").lower()
    s = str(obj.get("stroke", "")).replace(" ", "").lower()
    return "0,0,0" in f or "#000" in f or f == "black" or "#000" in s or s == "black" or "rgba(0,0,0" in f


def apply_canvas_drawings_to_pdf(doc, page, bg_pil, canvas_objects):
    """Aplica de forma forense e indeleble las cajas negras y zonas pixeladas al documento PDF."""
    if not canvas_objects:
        return False

    scale_x = (page.rect.x1 - page.rect.x0) / bg_pil.width
    scale_y = (page.rect.y1 - page.rect.y0) / bg_pil.height
    modified = False

    blk_objects = [o for o in canvas_objects if is_blackout_object(o)]
    pix_objects = [o for o in canvas_objects if not is_blackout_object(o)]

    # 1. Zonas de pixelado
    if pix_objects:
        overlay = Image.new("RGBA", bg_pil.size, (0, 0, 0, 0))
        for obj in pix_objects:
            bx0 = max(0, int(obj["left"]))
            by0 = max(0, int(obj["top"]))
            bx1 = min(bg_pil.width, int(obj["left"] + obj["width"] * obj.get("scaleX", 1)))
            by1 = min(bg_pil.height, int(obj["top"] + obj["height"] * obj.get("scaleY", 1)))

            rx0 = page.rect.x0 + min(bx0, bx1) * scale_x
            rx1 = page.rect.x0 + max(bx0, bx1) * scale_x
            ry0 = page.rect.y0 + min(by0, by1) * scale_y
            ry1 = page.rect.y0 + max(by0, by1) * scale_y

            if rx1 > rx0 and ry1 > ry0:
                crop = bg_pil.crop((min(bx0, bx1), min(by0, by1), max(bx0, bx1), max(by0, by1)))
                small = crop.resize((max(1, (max(bx0, bx1) - min(bx0, bx1)) // 10), max(1, (max(by0, by1) - min(by0, by1)) // 10)), Image.NEAREST)
                pix_crop = small.resize((max(bx0, bx1) - min(bx0, bx1), max(by0, by1) - min(by0, by1)), Image.NEAREST)
                overlay.paste(pix_crop, (min(bx0, bx1), min(by0, by1)))

                pdf_r = pymupdf.Rect(rx0, ry0, rx1, ry1)
                page.add_redact_annot(pdf_r, fill=None)
                modified = True

        buf = io.BytesIO()
        overlay.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue(), overlay=True)

    # 2. Cajas negras (Blackout) con doble protección (redacción forense + dibujo indeleble)
    if blk_objects:
        blackout_rects = []
        for obj in blk_objects:
            scale_obj_x = float(obj.get("scaleX", 1) or 1)
            scale_obj_y = float(obj.get("scaleY", 1) or 1)
            w = float(obj.get("width", 0)) * scale_obj_x
            h = float(obj.get("height", 0)) * scale_obj_y
            origin_x = str(obj.get("originX", "left")).lower()
            origin_y = str(obj.get("originY", "top")).lower()
            ox_mult = 0.5 if origin_x == "center" else (1.0 if origin_x == "right" else 0.0)
            oy_mult = 0.5 if origin_y == "center" else (1.0 if origin_y == "bottom" else 0.0)
            left = float(obj.get("left", 0)) - ox_mult * w
            top = float(obj.get("top", 0)) - oy_mult * h

            bx0 = left
            by0 = top
            bx1 = left + w
            by1 = top + h

            rx0 = page.rect.x0 + min(bx0, bx1) * scale_x
            rx1 = page.rect.x0 + max(bx0, bx1) * scale_x
            ry0 = page.rect.y0 + min(by0, by1) * scale_y
            ry1 = page.rect.y0 + max(by0, by1) * scale_y

            if rx1 > rx0 and ry1 > ry0:
                pdf_rect = pymupdf.Rect(rx0, ry0, rx1, ry1)
                blackout_rects.append(pdf_rect)

                # Destruir texto en capa vectorial interna del PDF
                page.add_redact_annot(pdf_rect, fill=(0, 0, 0))
                modified = True

        # Primero aplicar todas las redacciones forenses
        page.apply_redactions()

        # Segundo, dibujar los rectángulos vectoriales negros indelebles en la capa superior
        for pdf_rect in blackout_rects:
            page.draw_rect(pdf_rect, color=(0, 0, 0), fill=(0, 0, 0), width=0, overlay=True)

    elif modified:
        page.apply_redactions()

    return modified


# --- GENERADOR DE SELLO NOTARIAL ---
def generate_rubber_stamp(text: str, color_hex: str = "#d32f2f", angle: int = -12):
    """Genera un sello con doble marco notarial y ángulo personalizable."""
    hex_clean = color_hex.lstrip("#")
    rgb = tuple(int(hex_clean[i:i+2], 16) for i in (0, 2, 4))
    stamp_color = (rgb[0], rgb[1], rgb[2], 230)

    try:
        font = ImageFont.truetype("arialbd.ttf", 34)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 34)
        except Exception:
            font = ImageFont.load_default()

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = dummy.textbbox((0, 0), text, font=font)
    txt_w = bbox[2] - bbox[0]
    txt_h = bbox[3] - bbox[1]

    pad_x, pad_y = 30, 16
    w = txt_w + pad_x * 2
    h = txt_h + pad_y * 2

    stamp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(stamp)
    d.rectangle([2, 2, w - 2, h - 2], outline=stamp_color, width=4)
    d.rectangle([8, 8, w - 8, h - 8], outline=stamp_color, width=2)
    d.text((pad_x, pad_y - 2), text, font=font, fill=stamp_color)

    if angle != 0:
        stamp = stamp.rotate(angle, expand=1, resample=Image.BICUBIC)

    return stamp


# --- MARCA DE AGUA DIAGONAL ---
def apply_watermark_to_doc(pdf_bytes: bytes, text: str, opacity_pct: int, color_hex: str, all_pages: bool, current_page: int) -> bytes:
    """Inserta una marca de agua a 45 grados en el PDF."""
    hex_clean = color_hex.lstrip("#")
    rgb = tuple(int(hex_clean[i:i+2], 16) for i in (0, 2, 4))
    alpha = int(255 * (opacity_pct / 100.0))
    watermark_color = (rgb[0], rgb[1], rgb[2], alpha)

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages_to_process = range(len(doc)) if all_pages else [current_page]

    try:
        font = ImageFont.truetype("arialbd.ttf", 75)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 75)
        except Exception:
            font = ImageFont.load_default()

    for p_idx in pages_to_process:
        page = doc[p_idx]
        w_px = int(page.rect.width * 2)
        h_px = int(page.rect.height * 2)

        canvas = Image.new("RGBA", (w_px, h_px), (0, 0, 0, 0))
        txt_img = Image.new("RGBA", (w_px, 350), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt_img)
        bbox = d.textbbox((0, 0), text, font=font)
        txt_w = bbox[2] - bbox[0]
        txt_h = bbox[3] - bbox[1]

        d.text(((w_px - txt_w) // 2, (350 - txt_h) // 2), text, fill=watermark_color, font=font)
        rotated = txt_img.rotate(45, expand=1, resample=Image.BICUBIC)
        r_w, r_h = rotated.size
        canvas.paste(rotated, ((w_px - r_w) // 2, (h_px - r_h) // 2), rotated)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue(), overlay=True)

    return doc.tobytes()


# --- CÁLCULO PRECISO DE ALTURA PARA LEYENDAS SIN DESBORDAMIENTO ---
def measure_text_box_height(text: str, width: float, fontsize: float) -> float:
    """Calcula con precisión milimétrica la altura requerida para que el texto de la leyenda no se corte."""
    try:
        dummy = pymupdf.open()
        p = dummy.new_page(width=max(width + 50.0, 400.0), height=2000.0)
        unused = p.insert_textbox(pymupdf.Rect(0, 0, width, 1800.0), text.strip(), fontsize=fontsize, fontname="helv")
        dummy.close()
        used = 1800.0 - unused
        return max(24.0, used + 8.0)
    except Exception:
        chars_per_line = max(1.0, width / (fontsize * 0.52))
        lines = max(1.0, math.ceil(len(text) / chars_per_line))
        return max(24.0, lines * fontsize * 1.35 + 8.0)


# --- INSERTADOR DE LEYENDAS OFICIALES Y NOTAS (LEYENDA 1 Y 2) ---
def insert_legend_to_doc(
    pdf_bytes: bytes,
    text: str,
    position: str,
    font_size: float = 7.5,
    text_color_hex: str = "#1e293b",
    bg_color_hex: str = "#f8fafc",
    has_box: bool = True,
    all_pages: bool = False,
    current_page: int = 0
) -> bytes:
    """Inserta una leyenda o nota oficial editable con marco o texto libre en el PDF con ajuste dinámico de tamaño."""
    if not text.strip():
        return pdf_bytes

    def hex_to_rgb_float(hex_str):
        h = hex_str.lstrip("#")
        return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages_to_process = range(len(doc)) if all_pages else [current_page]

    txt_rgb = hex_to_rgb_float(text_color_hex)
    bg_rgb = hex_to_rgb_float(bg_color_hex) if has_box else None
    border_rgb = (txt_rgb[0] * 0.7, txt_rgb[1] * 0.7, txt_rgb[2] * 0.7) if has_box else None

    for p_idx in pages_to_process:
        if 0 <= p_idx < len(doc):
            page = doc[p_idx]
            pw, ph = page.rect.width, page.rect.height

            # Determinar ancho según la posición
            if "Izquierda" in position:
                target_w = (pw * 0.58) - 35.0
                align = pymupdf.TEXT_ALIGN_LEFT
            elif "Derecha" in position:
                target_w = (pw - 35.0) - (pw * 0.42)
                align = pymupdf.TEXT_ALIGN_RIGHT
            elif "Margen" in position:
                target_w = pw - 90.0
                align = pymupdf.TEXT_ALIGN_CENTER
            else:  # Centrado
                target_w = pw - 70.0
                align = pymupdf.TEXT_ALIGN_CENTER

            box_h = measure_text_box_height(text, target_w - 10.0, font_size)

            if "Encabezado Superior (Centrado)" in position:
                rect = pymupdf.Rect(35, 12, pw - 35, 12 + box_h)
            elif "Encabezado Superior (Izquierda)" in position:
                rect = pymupdf.Rect(35, 12, pw * 0.58, 12 + box_h)
            elif "Encabezado Superior (Derecha)" in position:
                rect = pymupdf.Rect(pw * 0.42, 12, pw - 35, 12 + box_h)
            elif "Pie de Página (Centrado)" in position:
                rect = pymupdf.Rect(35, ph - 12 - box_h, pw - 35, ph - 12)
            elif "Pie de Página (Izquierda)" in position:
                rect = pymupdf.Rect(35, ph - 12 - box_h, pw * 0.58, ph - 12)
            elif "Pie de Página (Derecha)" in position:
                rect = pymupdf.Rect(pw * 0.42, ph - 12 - box_h, pw - 35, ph - 12)
            elif "Margen Superior (Sub-cabecera)" in position:
                rect = pymupdf.Rect(45, 45, pw - 45, 45 + box_h)
            else:  # Margen Inferior
                rect = pymupdf.Rect(45, ph - 45 - box_h, pw - 45, ph - 45)

            if has_box and bg_rgb:
                page.draw_rect(rect, color=border_rgb, fill=bg_rgb, width=0.75, overlay=True)

            pad_x = 5.0
            pad_y = 3.0
            inner_rect = rect + (pad_x, pad_y, -pad_x, -pad_y)

            # Insertar texto garantizando que nunca se desborde o corte
            cur_fs = font_size
            while cur_fs >= 5.0:
                rc = page.insert_textbox(
                    inner_rect,
                    text.strip(),
                    fontsize=cur_fs,
                    color=txt_rgb,
                    align=align,
                    fontname="helv"
                )
                if rc >= 0:
                    break
                cur_fs -= 0.5

    return doc.tobytes(garbage=3, deflate=True)


# --- INSERTADOR COMBINADO DE AMBAS LEYENDAS (GARANTIZA QUE SE VEAN LAS DOS) ---
def insert_both_legends_to_doc(
    pdf_bytes: bytes,
    text1: str,
    text2: str,
    mode: str = "📦 Juntas en el mismo recuadro (Recomendado - Se ven las dos)",
    position: str = "🔝 Encabezado Superior (Centrado)",
    font_size: float = 6.8,
    text_color_hex: str = "#0f172a",
    bg_color_hex: str = "#f8fafc",
    has_box: bool = True,
    all_pages: bool = False,
    current_page: int = 0
) -> bytes:
    """Garantiza que ambas leyendas se inserten juntas y ambas sean 100% visibles en el documento."""
    t1 = text1.strip()
    t2 = text2.strip()
    if not t1 and not t2:
        return pdf_bytes
    if not t1:
        return insert_legend_to_doc(pdf_bytes, t2, position, font_size, text_color_hex, bg_color_hex, has_box, all_pages, current_page)
    if not t2:
        return insert_legend_to_doc(pdf_bytes, t1, position, font_size, text_color_hex, bg_color_hex, has_box, all_pages, current_page)

    def hex_to_rgb(h_str):
        c = h_str.lstrip("#")
        return tuple(int(c[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    if "Separadas" in mode:
        b1 = insert_legend_to_doc(
            pdf_bytes, t1, "🔝 Encabezado Superior (Centrado)", font_size, text_color_hex, bg_color_hex, has_box, all_pages, current_page
        )
        return insert_legend_to_doc(
            b1, t2, "🔽 Pie de Página (Centrado)", font_size, text_color_hex, bg_color_hex, has_box, all_pages, current_page
        )

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages = range(len(doc)) if all_pages else [current_page]

    txt_rgb = hex_to_rgb(text_color_hex)
    bg_rgb = hex_to_rgb(bg_color_hex) if has_box else None
    bdr_rgb = (txt_rgb[0] * 0.7, txt_rgb[1] * 0.7, txt_rgb[2] * 0.7) if has_box else None

    for p_idx in pages:
        if 0 <= p_idx < len(doc):
            page = doc[p_idx]
            pw, ph = page.rect.width, page.rect.height
            target_w = pw - 70.0

            if "Apiladas" in mode:
                h1 = measure_text_box_height(f"1. {t1}", target_w - 10.0, font_size)
                h2 = measure_text_box_height(f"2. {t2}", target_w - 10.0, font_size)

                if "Pie de Página" in position:
                    total_h = h1 + h2 + 4.0
                    y_start = ph - 12.0 - total_h
                elif "Margen Superior" in position:
                    y_start = 45.0
                else:  # Encabezado
                    y_start = 12.0

                rect1 = pymupdf.Rect(35, y_start, pw - 35, y_start + h1)
                rect2 = pymupdf.Rect(35, y_start + h1 + 4.0, pw - 35, y_start + h1 + 4.0 + h2)

                if has_box and bg_rgb:
                    page.draw_rect(rect1, color=bdr_rgb, fill=bg_rgb, width=0.75, overlay=True)
                    page.draw_rect(rect2, color=bdr_rgb, fill=bg_rgb, width=0.75, overlay=True)

                page.insert_textbox(rect1 + (5, 3, -5, -3), f"1. {t1}", fontsize=font_size, color=txt_rgb, fontname="helv")
                page.insert_textbox(rect2 + (5, 3, -5, -3), f"2. {t2}", fontsize=font_size, color=txt_rgb, fontname="helv")

            else:  # "Juntas en el mismo recuadro" (Por defecto - Ambas 100% visibles juntas)
                combined = f"1. {t1}\n\n2. {t2}"
                box_h = measure_text_box_height(combined, target_w - 10.0, font_size)

                if "Pie de Página" in position:
                    rect = pymupdf.Rect(35, ph - 12.0 - box_h, pw - 35, ph - 12.0)
                elif "Margen Superior" in position:
                    rect = pymupdf.Rect(45, 45.0, pw - 45, 45.0 + box_h)
                else:  # Encabezado Superior
                    rect = pymupdf.Rect(35, 12.0, pw - 35, 12.0 + box_h)

                if has_box and bg_rgb:
                    page.draw_rect(rect, color=bdr_rgb, fill=bg_rgb, width=0.75, overlay=True)

                inner_rect = rect + (6, 4, -6, -4)
                cur_fs = font_size
                while cur_fs >= 5.0:
                    rc = page.insert_textbox(
                        inner_rect,
                        combined,
                        fontsize=cur_fs,
                        color=txt_rgb,
                        align=pymupdf.TEXT_ALIGN_LEFT,
                        fontname="helv"
                    )
                    if rc >= 0:
                        break
                    cur_fs -= 0.5

    return doc.tobytes(garbage=3, deflate=True)


# --- ESTAMPADOR DE FIRMA PROPIA / SELLO INSTITUCIONAL ---
def stamp_image_to_doc(
    pdf_bytes: bytes,
    image_path_or_bytes,
    position: str = "↙️ Esquina Inferior Izquierda",
    target_width: float = 70.0,
    all_pages: bool = False,
    current_page: int = 0
) -> bytes:
    """Estampa una imagen de firma o sello en la posición seleccionada del PDF."""
    if isinstance(image_path_or_bytes, str):
        im = Image.open(image_path_or_bytes)
    elif isinstance(image_path_or_bytes, bytes):
        im = Image.open(io.BytesIO(image_path_or_bytes))
    else:
        im = image_path_or_bytes

    aspect = im.height / im.width
    w_pt = float(target_width)
    h_pt = w_pt * aspect

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages = range(len(doc)) if all_pages else [current_page]

    margin_x = 35.0
    margin_y = 15.0

    for p_idx in pages:
        if 0 <= p_idx < len(doc):
            page = doc[p_idx]
            pw, ph = page.rect.width, page.rect.height

            if "Inferior Izquierda" in position:
                rect = pymupdf.Rect(margin_x, ph - margin_y - h_pt, margin_x + w_pt, ph - margin_y)
            elif "Inferior Derecha" in position:
                rect = pymupdf.Rect(pw - margin_x - w_pt, ph - margin_y - h_pt, pw - margin_x, ph - margin_y)
            elif "Superior Izquierda" in position:
                rect = pymupdf.Rect(margin_x, margin_y, margin_x + w_pt, margin_y + h_pt)
            elif "Superior Derecha" in position:
                rect = pymupdf.Rect(pw - margin_x - w_pt, margin_y, pw - margin_x, margin_y + h_pt)
            else:  # Centro Inferior
                rect = pymupdf.Rect((pw - w_pt) / 2.0, ph - margin_y - h_pt, (pw + w_pt) / 2.0, ph - margin_y)

            page.insert_image(rect, stream=img_bytes, overlay=True)

    return doc.tobytes(garbage=3, deflate=True)


# --- INICIALIZACIÓN DE ESTADO ---
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "file_name" not in st.session_state:
    st.session_state.file_name = "documento.pdf"
if "current_page" not in st.session_state:
    st.session_state.current_page = 0
if "zoom_dpi" not in st.session_state:
    st.session_state.zoom_dpi = 120
if "active_drawing_tool" not in st.session_state:
    st.session_state.active_drawing_tool = "⬛ Caja Negra (Blackout)"
if "prev_tool" not in st.session_state:
    st.session_state.prev_tool = "⬛ Caja Negra (Blackout)"
if "canvas_epoch" not in st.session_state:
    st.session_state.canvas_epoch = 0
if "history" not in st.session_state:
    st.session_state.history = []
if "show_password_modal" not in st.session_state:
    st.session_state.show_password_modal = False
if "just_applied" not in st.session_state:
    st.session_state.just_applied = False
if "pending_canvas_objects" not in st.session_state:
    st.session_state.pending_canvas_objects = []

# --- PLANTILLAS Y ESTADO DE LEYENDAS OFICIALES (LEYENDA 1 Y 2) ---
DEFAULT_LEYENDA_1 = (
    "SE ELIMINAN DATOS DE RFC POR CONSIDERARSE INFORMACIÓN CONFIDENCIAL DE LA PERSONA IDENTIFICABLE "
    "Y QUE POR SU DIFUSIÓN PUEDE AFECTAR LA ESFERA PRIVADA DE LA MISMA. LO ANTERIOR, CON FUNDAMENTO "
    "EN TERMINOS DE LOS ARTÍCULOS 115 PARRAFO I Y 120 DE LA LGTAIP."
)

DEFAULT_LEYENDA_2 = (
    "SE ELIMINAN DATOS DE CADENA ORIGINAL, NÚMERO DE SERIE, RFC Y CERTIFICADO POR CONSIDERARSE INFORMACIÓN CONFIDENCIAL "
    "DE LA PERSONA IDENTIFICABLE Y QUE POR SU DIFUSIÓN PUEDE AFECTAR LA ESFERA PRIVADA DE LA MISMA. LO ANTERIOR, "
    "CON FUNDAMENTO EN TERMINOS DE LOS ARTÍCULOS 115 PARRAFO I Y PARRAFO IV Y 120 DE LA LGTAIP."
)

PRESETS_L1 = {
    "⭐ Leyenda 1: Eliminación de RFC (Art. 115-I y 120 LGTAIP)": DEFAULT_LEYENDA_1,
    "📋 Versión Pública General (Art. 116 LGTAIP)": "VERSIÓN PÚBLICA: Eliminados datos personales con fundamento en el Art. 116 de la Ley General de Transparencia y Acceso a la Información Pública.",
    "📋 Documento Clasificado (Confidencial Estricto)": "DOCUMENTO CLASIFICADO - INFORMACIÓN CONFIDENCIAL ESTRICTA.",
    "📋 Información Testada (Lineamientos Generales)": "Información testada con base en los Lineamientos Generales de Clasificación y Desclasificación.",
    "✏️ Personalizada (escribe libremente)...": ""
}

PRESETS_L2 = {
    "⭐ Leyenda 2: Cadena Original, Serie, RFC y Certificado (Art. 115-I, IV y 120 LGTAIP)": DEFAULT_LEYENDA_2,
    "📋 Acta Comité de Transparencia": "Aprobado por el Comité de Transparencia en Sesión Extraordinaria N° 04/2026.",
    "📋 Periodo de Reserva": "Fecha de clasificación: Octubre 2026 | Periodo de reserva: Confidencial Permanente.",
    "📋 Copia Digital Restringida": "Copia digital no negociable | Validez restringida a uso legal y administrativo interno.",
    "✏️ Personalizada (escribe libremente)...": ""
}

if "input_legend_1" not in st.session_state:
    st.session_state.input_legend_1 = DEFAULT_LEYENDA_1
if "input_legend_2" not in st.session_state:
    st.session_state.input_legend_2 = DEFAULT_LEYENDA_2

def update_l1_from_preset():
    choice = st.session_state.get("select_preset_l1")
    if choice and choice in PRESETS_L1 and PRESETS_L1[choice]:
        st.session_state.input_legend_1 = PRESETS_L1[choice]

def update_l2_from_preset():
    choice = st.session_state.get("select_preset_l2")
    if choice and choice in PRESETS_L2 and PRESETS_L2[choice]:
        st.session_state.input_legend_2 = PRESETS_L2[choice]


def save_pending_canvas_if_any():
    """Guarda automáticamente cualquier censura dibujada pendiente antes de cambiar de página, herramienta o acción."""
    pending = st.session_state.get("pending_canvas_objects", [])
    if pending and st.session_state.pdf_bytes is not None:
        try:
            doc_tmp = pymupdf.open(stream=st.session_state.pdf_bytes, filetype="pdf")
            cur_p = st.session_state.current_page
            if 0 <= cur_p < len(doc_tmp):
                p_tmp = doc_tmp[cur_p]
                pix_tmp = p_tmp.get_pixmap(dpi=st.session_state.zoom_dpi)
                bg_tmp = Image.open(io.BytesIO(pix_tmp.tobytes("png")))
                applied = apply_canvas_drawings_to_pdf(doc_tmp, p_tmp, bg_tmp, pending)
                if applied:
                    st.session_state.pdf_bytes = doc_tmp.tobytes()
                    st.session_state.pending_canvas_objects = []
                    st.session_state.canvas_epoch += 1
        except Exception as e:
            print(f"Error auto-guardando censuras: {e}")


def get_downloadable_pdf_bytes() -> bytes:
    """Retorna los bytes del PDF con cualquier censura pendiente dibujada en el lienzo aplicada automáticamente."""
    base_bytes = st.session_state.pdf_bytes
    if base_bytes is None:
        return b""
    pending = st.session_state.get("pending_canvas_objects", [])
    if not pending:
        return base_bytes

    try:
        doc_tmp = pymupdf.open(stream=base_bytes, filetype="pdf")
        cur_p = st.session_state.current_page
        if 0 <= cur_p < len(doc_tmp):
            p_tmp = doc_tmp[cur_p]
            pix_tmp = p_tmp.get_pixmap(dpi=st.session_state.zoom_dpi)
            bg_tmp = Image.open(io.BytesIO(pix_tmp.tobytes("png")))
            applied = apply_canvas_drawings_to_pdf(doc_tmp, p_tmp, bg_tmp, pending)
            if applied:
                return doc_tmp.tobytes(garbage=3, deflate=True)
    except Exception as e:
        print(f"Error preparando bytes de descarga: {e}")
    return base_bytes


# --- BARRA LATERAL (Miniaturas y navegación) ---
with st.sidebar:
    st.markdown("### 🗂️ Documento y Miniaturas")

    uploaded_file = st.file_uploader(
        "Cargar archivo PDF propio",
        type=["pdf"],
        help="Arrastra o selecciona un archivo PDF"
    )

    if uploaded_file is not None:
        new_bytes = uploaded_file.getvalue()
        if st.session_state.pdf_bytes is None or uploaded_file.name != st.session_state.file_name:
            push_history()
            st.session_state.pdf_bytes = new_bytes
            st.session_state.file_name = uploaded_file.name
            st.session_state.current_page = 0
            st.session_state.pending_canvas_objects = []
            st.session_state.canvas_epoch += 1
            st.rerun()

    if st.session_state.pdf_bytes is not None:
        meta = get_pdf_metadata(st.session_state.pdf_bytes)
        total_pages = meta["page_count"]

        # Historial de cambios
        history_count = len(st.session_state.history)
        if history_count > 0:
            if st.button(f"↩️ Deshacer ({history_count})", use_container_width=True):
                st.session_state.pending_canvas_objects = []
                pop_history()

        st.divider()
        st.subheader("📑 Navegación")

        col_n1, col_n2 = st.columns([2, 1])
        with col_n1:
            target_p = st.number_input(
                f"Página (1 - {total_pages})",
                min_value=1,
                max_value=total_pages,
                value=st.session_state.current_page + 1,
                step=1
            )
            if target_p - 1 != st.session_state.current_page:
                save_pending_canvas_if_any()
                st.session_state.current_page = target_p - 1
                st.session_state.canvas_epoch += 1
                st.rerun()
        with col_n2:
            st.session_state.zoom_dpi = st.selectbox(
                "Zoom DPI",
                options=[90, 120, 150, 200],
                index=1
            )

        st.divider()
        st.subheader("🖼️ Miniaturas")
        # Optimización para documentos grandes: paginación de miniaturas para máxima fluidez
        if total_pages > 24:
            chunk_size = 20
            num_chunks = (total_pages + chunk_size - 1) // chunk_size
            curr_chunk = min(st.session_state.current_page // chunk_size, num_chunks - 1)
            selected_chunk = st.selectbox(
                "Bloque de miniaturas",
                options=list(range(num_chunks)),
                format_func=lambda c: f"Págs. {c * chunk_size + 1} a {min((c + 1) * chunk_size, total_pages)}",
                index=curr_chunk,
                key="thumb_chunk_select"
            )
            display_range = range(selected_chunk * chunk_size, min((selected_chunk + 1) * chunk_size, total_pages))
        else:
            display_range = range(total_pages)

        thumb_cols = st.columns(2)
        for idx in display_range:
            c_target = thumb_cols[idx % 2]
            with c_target:
                is_active = (idx == st.session_state.current_page)
                label = f"{'👉 ' if is_active else ''}Pág. {idx + 1}"
                if st.button(label, key=f"sidebar_thumb_{idx}", use_container_width=True, type="primary" if is_active else "secondary"):
                    save_pending_canvas_if_any()
                    st.session_state.current_page = idx
                    st.session_state.canvas_epoch += 1
                    st.rerun()
                thumb_bytes = render_page_image(st.session_state.pdf_bytes, idx, dpi=45)
                if thumb_bytes:
                    st.image(thumb_bytes, use_container_width=True)

    # --- LOGOTIPO PROPIO HASTA ABAJO EN LA BARRA LATERAL IZQUIERDA ---
    side_logo_path = "logotipo_sidebar_thumb.png" if os.path.exists("logotipo_sidebar_thumb.png") else ("logotipo_sidebar.png" if os.path.exists("logotipo_sidebar.png") else "")
    if side_logo_path:
        with open(side_logo_path, "rb") as f:
            side_logo_b64 = base64.b64encode(f.read()).decode("utf-8")
        st.markdown(f"""
        <div style="margin-top: 30px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.08); text-align: center;">
            <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;">
                <img src="data:image/png;base64,{side_logo_b64}" 
                     style="width: 52px; height: 52px; object-fit: contain; border-radius: 50%; box-shadow: 0 3px 10px rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); background: #ffffff;" />
                <span style="font-size: 0.65rem; color: #94a3b8; font-weight: 700; letter-spacing: 0.05em; margin-top: 3px;">EDITOR IMSS PDF</span>
            </div>
        </div>
        """, unsafe_allow_html=True)


# --- ENCABEZADO SUPERIOR EDITOR IMSS PDF ---
head_col1, head_col2 = st.columns([6.2, 3.8])

with head_col1:
    logo_imss_b64 = ""
    logo_path = "logo_imss_sonora_thumb.png" if os.path.exists("logo_imss_sonora_thumb.png") else ("logo_imss_sonora.png" if os.path.exists("logo_imss_sonora.png") else "")
    if logo_path:
        with open(logo_path, "rb") as f:
            logo_imss_b64 = base64.b64encode(f.read()).decode("utf-8")

    logo_img_tag = f'<img src="data:image/png;base64,{logo_imss_b64}" style="height: 88px; width: auto; object-fit: contain; border-radius: 10px; background: rgba(255,255,255,0.96); padding: 5px; box-shadow: 0 4px 16px rgba(0,0,0,0.45); vertical-align: middle; flex-shrink: 0;" />' if logo_imss_b64 else '<span style="font-size: 2.2rem;">🏥</span>'

    st.markdown(f"""
    <div class="header-container" style="display: flex; align-items: center; gap: 16px;">
        {logo_img_tag}
        <div>
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <span class="header-title" style="font-size: 1.65rem;">EDITOR IMSS PDF</span>
                <span class="badge-irreversible" style="font-size: 0.78rem;">OOAD SONORA · TESTADO</span>
            </div>
            <div class="header-sub" style="font-size: 0.95rem; margin-top: 4px; color: #cbd5e1;">
                Órgano de Operación Administrativa Desconcentrada Sonora
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with head_col2:
    st.markdown('<div style="height: 22px;"></div>', unsafe_allow_html=True)
    b_top1, b_top2, b_top3 = st.columns([1.5, 1.3, 1.4])
    with b_top1:
        if st.button("⚡ Cargar prueba confidencial", use_container_width=True, type="secondary"):
            try:
                with open("documento_confidencial_prueba.pdf", "rb") as f:
                    push_history()
                    st.session_state.pdf_bytes = f.read()
                    st.session_state.file_name = "documento_confidencial_prueba.pdf"
                    st.session_state.current_page = 0
                    st.session_state.pending_canvas_objects = []
                    st.session_state.canvas_epoch += 1
                    st.toast("Documento confidencial cargado", icon="⚡")
                    st.rerun()
            except Exception as e:
                st.error(f"Error al cargar: {e}")

    with b_top2:
        candado_label = "🔒 Candado" if not st.session_state.show_password_modal else "✖️ Cerrar"
        if st.button(candado_label, use_container_width=True, type="primary"):
            st.session_state.show_password_modal = not st.session_state.show_password_modal
            st.rerun()

    with b_top3:
        if st.session_state.pdf_bytes is not None:
            raw_fn = st.session_state.get("file_name", "documento.pdf")
            clean_fn = raw_fn if raw_fn.lower().endswith(".pdf") else f"{raw_fn}.pdf"
            clean_fn = re.sub(r'[\\/*?:"<>|]', "", clean_fn)
            dl_bytes_top = get_downloadable_pdf_bytes()
            st.download_button(
                label="💾 Descargar PDF",
                data=dl_bytes_top,
                file_name=f"redactado_{clean_fn}",
                mime="application/pdf",
                use_container_width=True,
                key="btn_download_header",
                on_click="ignore"
            )

# --- ADAPTACIÓN Y CONSEJO PARA MÓVILES (ZOOM TÁCTIL) ---
import streamlit.components.v1 as _st_components

_st_components.html("""
<script>
try {
    const parentDoc = window.parent.document;
    if (parentDoc) {
        let meta = parentDoc.querySelector('meta[name="viewport"]');
        if (!meta) {
            meta = parentDoc.createElement('meta');
            meta.name = 'viewport';
            parentDoc.head.appendChild(meta);
        }
        meta.setAttribute('content', 'width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes');
    }
} catch (e) {}
</script>
""", height=0)

st.markdown("""
<div class="mobile-tip-banner">
    📱 <b>Consejo para Celulares:</b> Para ver la pantalla idéntica a una computadora y hacer <b>zoom con 2 dedos</b> libremente:<br>
    <b>1.</b> Toca los tres puntos <b>⋮</b> (arriba a la derecha en Chrome) o el botón <b>aA</b> (en Safari).<br>
    <b>2.</b> Activa la opción <b>"Sitio para computadoras"</b> (o "Vista de escritorio").
</div>
""", unsafe_allow_html=True)


# --- MODAL DESPLEGABLE DE CIFRADO CON CONTRASEÑA ---
if st.session_state.show_password_modal:
    with st.container():
        st.markdown("""
        <div style="background-color: #064e3b; border: 1px solid #10b981; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; color: #ecfdf5;">
            <h4 style="margin: 0; color: #a7f3d0;">🔐 Descargar con Candado (Cifrado AES-256)</h4>
            <p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #d1fae5;">El archivo resultante requerirá esta contraseña obligatoria para poder ser abierto.</p>
        </div>
        """, unsafe_allow_html=True)

        if st.session_state.pdf_bytes is not None:
            c_pw1, c_pw2, c_pw3 = st.columns([2, 2, 2])
            with c_pw1:
                u_pass = st.text_input("Contraseña requerida:", type="password", key="user_pw_input")
            with c_pw2:
                u_pass_conf = st.text_input("Confirmar contraseña:", type="password", key="user_pw_confirm")
            with c_pw3:
                st.write("")
                st.write("")
                if u_pass:
                    if u_pass == u_pass_conf:
                        try:
                            enc_source_bytes = get_downloadable_pdf_bytes()
                            doc_enc = pymupdf.open(stream=enc_source_bytes, filetype="pdf")
                            enc_bytes = doc_enc.tobytes(
                                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                user_pw=u_pass,
                                owner_pw=u_pass + "_owner"
                            )
                            raw_fn = st.session_state.get("file_name", "documento.pdf")
                            clean_fn = raw_fn if raw_fn.lower().endswith(".pdf") else f"{raw_fn}.pdf"
                            clean_fn = re.sub(r'[\\/*?:"<>|]', "", clean_fn)
                            st.download_button(
                                label="⬇️ Descargar PDF Cifrado",
                                data=enc_bytes,
                                file_name=f"PROTEGIDO_{clean_fn}",
                                mime="application/pdf",
                                type="primary",
                                use_container_width=True,
                                key="btn_download_encrypted_modal",
                                on_click="ignore"
                            )
                        except Exception as e:
                            st.error(f"Error: {e}")
                    else:
                        st.warning("Las contraseñas no coinciden.")
                else:
                    st.caption("Ingresa una clave para habilitar la descarga.")
        st.divider()


# --- ESTADO SIN ARCHIVO ---
if st.session_state.pdf_bytes is None:
    st.info("👋 **Bienvenido a RedactaDoc Pro.** Haz clic en **⚡ Cargar prueba confidencial** arriba o sube un documento PDF desde la barra lateral izquierda.")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("#### ⬛ Caja Negra (Blackout)")
        st.caption("Dibuja cajas negras sobre los datos sensibles y pulsa 'Aplicar y Guardar' para destruirlos.")
    with c2:
        st.markdown("#### 🛡️ Sello Confidencial")
        st.caption("Estampa sellos notariales (CONFIDENCIAL, SECRETO, NO DIVULGAR) en cualquier posición.")
    with c3:
        st.markdown("#### 🌫️ Pixelado")
        st.caption("Aplica censura mediante mosaico pixelado y purga los datos subyacentes.")
    with c4:
        st.markdown("#### 📐 Marca de Agua")
        st.caption("Marca diagonal semi-transparente para evitar filtraciones y copias no autorizadas.")

else:
    meta = get_pdf_metadata(st.session_state.pdf_bytes)
    total_pages = meta["page_count"]
    current_page = st.session_state.current_page

    # --- BARRA DE NAVEGACIÓN DE PÁGINA (Pág. X de Y) ---
    col_nav1, col_nav2, col_nav3, col_nav4, col_nav5 = st.columns([1, 1, 3, 1, 1])
    with col_nav1:
        if st.button("⏮️ Primera", use_container_width=True, disabled=(current_page == 0)):
            save_pending_canvas_if_any()
            st.session_state.current_page = 0
            st.session_state.canvas_epoch += 1
            st.rerun()
    with col_nav2:
        if st.button("◀️ Anterior", use_container_width=True, disabled=(current_page == 0)):
            save_pending_canvas_if_any()
            st.session_state.current_page -= 1
            st.session_state.canvas_epoch += 1
            st.rerun()
    with col_nav3:
        st.markdown(
            f"<div style='text-align: center;'><span class='page-indicator-pill'>"
            f"Pág. <b>{current_page + 1}</b> de <b>{total_pages}</b> &nbsp;|&nbsp; {st.session_state.file_name}"
            f"</span></div>",
            unsafe_allow_html=True
        )
    with col_nav4:
        if st.button("Siguiente ▶️", use_container_width=True, disabled=(current_page >= total_pages - 1)):
            save_pending_canvas_if_any()
            st.session_state.current_page += 1
            st.session_state.canvas_epoch += 1
            st.rerun()
    with col_nav5:
        if st.button("Última ⏭️", use_container_width=True, disabled=(current_page >= total_pages - 1)):
            save_pending_canvas_if_any()
            st.session_state.current_page = total_pages - 1
            st.session_state.canvas_epoch += 1
            st.rerun()

    st.markdown("<hr style='margin: 6px 0 14px 0;'>", unsafe_allow_html=True)

    # --- ÁREA DE TRABAJO PRINCIPAL ---
    col_workspace, col_toolbox = st.columns([6.8, 3.2])

    doc = pymupdf.open(stream=st.session_state.pdf_bytes, filetype="pdf")
    page = doc[current_page]
    pix = page.get_pixmap(dpi=st.session_state.zoom_dpi)
    bg_pil = Image.open(io.BytesIO(pix.tobytes("png")))

    with col_workspace:
        c_mode1, c_mode2 = st.columns([3.5, 2.5])
        with c_mode1:
            chosen_tool = st.radio(
                "Herramienta activa para dibujar:",
                ["⬛ Caja Negra (Blackout)", "🌫️ Pixelado (Mosaico)", "👁️ Solo Visualizar"],
                horizontal=True,
                index=0 if "Caja Negra" in st.session_state.active_drawing_tool else (1 if "Pixelado" in st.session_state.active_drawing_tool else 2),
                label_visibility="collapsed"
            )
            if chosen_tool != st.session_state.prev_tool:
                save_pending_canvas_if_any()
                st.session_state.prev_tool = chosen_tool
                st.session_state.active_drawing_tool = chosen_tool
                st.session_state.canvas_epoch += 1
                st.rerun()

        with c_mode2:
            st.caption("1. Dibuja las cajas sobre el documento. 2. Pulsa '🚨 Aplicar y Guardar Censuras' o descarga directo.")

        if st.session_state.active_drawing_tool == "👁️ Solo Visualizar":
            st.image(bg_pil, use_container_width=True, caption=f"Página {current_page + 1}")
            canvas_obj = None
            drawn_rects = []
        else:
            if "Caja Negra" in st.session_state.active_drawing_tool:
                fill_color = "rgba(0, 0, 0, 0.95)"
                stroke_color = "#000000"
            else:
                fill_color = "rgba(59, 130, 246, 0.45)"
                stroke_color = "#2563eb"

            # Clave estable para el lienzo
            stable_canvas_key = f"studio_canvas_p{current_page}_{st.session_state.canvas_epoch}"

            canvas_obj = st_canvas(
                fill_color=fill_color,
                stroke_width=2,
                stroke_color=stroke_color,
                background_image=bg_pil,
                update_streamlit=True,
                height=bg_pil.height,
                width=bg_pil.width,
                drawing_mode="rect",
                key=stable_canvas_key
            )

            # Extraer y preservar rectángulos dibujados en el lienzo
            if canvas_obj and canvas_obj.json_data and "objects" in canvas_obj.json_data:
                current_raw_objects = [
                    o for o in canvas_obj.json_data["objects"]
                    if o.get("type", "").lower() in ("rect", "labeledrect") or (o.get("width", 0) > 0 and o.get("height", 0) > 0)
                ]
                if current_raw_objects:
                    st.session_state.pending_canvas_objects = current_raw_objects

        # PANEL DE CONTROL DE CENSURAS Y DESCARGA DIRECTA DEBAJO DEL LIENZO
        rects_to_burn = st.session_state.get("pending_canvas_objects", [])
        if not rects_to_burn and canvas_obj and canvas_obj.json_data and "objects" in canvas_obj.json_data:
            rects_to_burn = [
                o for o in canvas_obj.json_data["objects"]
                if o.get("type", "").lower() in ("rect", "labeledrect") or (o.get("width", 0) > 0 and o.get("height", 0) > 0)
            ]
        num_cajas = len(rects_to_burn)

        if num_cajas > 0:
            st.markdown(
                f"<div class='pending-badge'>✏️ <b>{num_cajas} caja(s) lista(s) para aplicar.</b> Pulsa '🚨 Aplicar y Guardar Censuras' para quemarlas, o descarga directamente el documento protegido.</div>",
                unsafe_allow_html=True
            )
        elif st.session_state.just_applied:
            st.markdown(
                "<div class='status-badge'>✅ ¡Censuras aplicadas y quemadas permanentemente en el documento! Listo para descargar.</div>",
                unsafe_allow_html=True
            )

        col_act1, col_act2, col_act3, col_act4 = st.columns([2.8, 2.8, 1.2, 1.2])

        # BOTÓN PRINCIPAL DE APLICACIÓN Y QUEMADO EN PDF (SIEMPRE HABILITADO)
        with col_act1:
            btn_text = f"🚨 Aplicar y Guardar Censuras ({num_cajas})" if num_cajas > 0 else "🚨 Aplicar y Guardar Censuras"
            if st.button(btn_text, key="btn_burn_censorship", type="primary", use_container_width=True):
                # Verificar cajas pendientes o en el lienzo actual
                target_rects = st.session_state.get("pending_canvas_objects", [])
                if not target_rects and canvas_obj and canvas_obj.json_data and "objects" in canvas_obj.json_data:
                    target_rects = [
                        o for o in canvas_obj.json_data["objects"]
                        if o.get("type", "").lower() in ("rect", "labeledrect") or (o.get("width", 0) > 0 and o.get("height", 0) > 0)
                    ]

                if target_rects:
                    push_history()
                    applied = apply_canvas_drawings_to_pdf(doc, page, bg_pil, target_rects)
                    if applied:
                        st.session_state.pdf_bytes = doc.tobytes()
                        st.session_state.pending_canvas_objects = []
                        st.session_state.canvas_epoch += 1
                        st.session_state.just_applied = True
                        st.toast(f"✅ ¡{len(target_rects)} censura(s) quemadas permanentemente en el PDF!", icon="🔒")
                        st.rerun()
                else:
                    st.info("💡 **Instrucción:** Haz clic y arrastra con el ratón sobre el texto que quieres censurar para dibujar una caja negra, y luego pulsa este botón.")

        # BOTÓN DE DESCARGA DIRECTA DEL PDF YA QUEMADO
        with col_act2:
            raw_fn = st.session_state.get("file_name", "documento.pdf")
            clean_fn = raw_fn if raw_fn.lower().endswith(".pdf") else f"{raw_fn}.pdf"
            clean_fn = re.sub(r'[\\/*?:"<>|]', "", clean_fn)
            dl_bytes_main = get_downloadable_pdf_bytes()
            st.download_button(
                label="💾 Descargar PDF Protegido Ahora",
                data=dl_bytes_main,
                file_name=f"redactado_{clean_fn}",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
                key="btn_download_below_canvas",
                on_click="ignore"
            )

        # BOTÓN DESCARTAR CAJAS DIBUJADAS SIN APLICAR
        with col_act3:
            if num_cajas > 0:
                if st.button("🗑️ Limpiar", use_container_width=True, key="btn_clear_canvas", help="Descartar cajas no guardadas"):
                    st.session_state.pending_canvas_objects = []
                    st.session_state.canvas_epoch += 1
                    st.rerun()

        # BOTÓN DESHACER
        with col_act4:
            if st.session_state.history:
                if st.button("↩️ Deshacer", use_container_width=True, key="btn_undo_below_canvas"):
                    st.session_state.just_applied = False
                    st.session_state.pending_canvas_objects = []
                    pop_history()

    # --- PANEL LATERAL DERECHO: LEYENDAS DE CONFIDENCIALIDAD ---
    with col_toolbox:
        st.markdown("### 📜 Leyendas de Confidencialidad")
        st.caption("Personaliza tus dos textos y pulsa el botón para ver ambos en el documento:")

        with st.expander("📝 Leyenda 1 (Eliminación de RFC)", expanded=True):
            preset_l1 = st.selectbox(
                "Plantilla rápida (Leyenda 1):",
                list(PRESETS_L1.keys()),
                key="select_preset_l1",
                on_change=update_l1_from_preset
            )
            text_l1 = st.text_area(
                "Texto Leyenda 1:",
                key="input_legend_1",
                height=85,
                help="Puedes modificar cualquier palabra o artículo directamente."
            )

        with st.expander("📝 Leyenda 2 (Cadena Original / Certificado)", expanded=True):
            preset_l2 = st.selectbox(
                "Plantilla rápida (Leyenda 2):",
                list(PRESETS_L2.keys()),
                key="select_preset_l2",
                on_change=update_l2_from_preset
            )
            text_l2 = st.text_area(
                "Texto Leyenda 2:",
                key="input_legend_2",
                height=95,
                help="Puedes modificar cualquier palabra o artículo directamente."
            )

        st.markdown("#### ⚙️ Opciones de Inserción")

        mode_both = st.selectbox(
            "¿Cómo mostrar ambas leyendas?:",
            [
                "📦 Juntas en el mismo recuadro (Recomendado - Se ven las dos)",
                "📑 Apiladas (Una caja sobre otra en el encabezado)",
                "↕️ Separadas (Leyenda 1 Arriba, Leyenda 2 Abajo)"
            ],
            index=0,
            key="select_mode_both"
        )

        pos_both = st.selectbox(
            "Ubicación en el documento:",
            [
                "🔝 Encabezado Superior (Centrado)",
                "🎯 Margen Superior (Sub-cabecera)",
                "🔽 Pie de Página (Centrado)"
            ],
            index=0,
            key="select_pos_both"
        )

        col_cfg1, col_cfg2 = st.columns(2)
        with col_cfg1:
            size_both = st.slider("Tamaño letra:", 6.0, 11.0, 6.8, 0.2, key="size_both_legends")
        with col_cfg2:
            box_both = st.checkbox("Recuadro y marco de fondo", value=True, key="box_flag_both")

        leg_all_pages = st.checkbox(
            "📋 Aplicar leyenda(s) a todas las páginas del PDF",
            value=False,
            key="legend_all_pages_sync",
            help="Si está marcado, las dos leyendas se insertarán en cada página del documento."
        )

        # BOTÓN PRINCIPAL DESTACADO: INSERTAR AMBAS
        if st.button(
            "⚡ INSERTAR AMBAS LEYENDAS (1 Y 2) EN EL DOCUMENTO",
            type="primary",
            use_container_width=True,
            key="btn_insert_both_legends"
        ):
            t1 = st.session_state.get("input_legend_1", "").strip()
            t2 = st.session_state.get("input_legend_2", "").strip()
            if t1 or t2:
                save_pending_canvas_if_any()
                push_history()
                new_pdf = insert_both_legends_to_doc(
                    st.session_state.pdf_bytes,
                    t1,
                    t2,
                    mode=mode_both,
                    position=pos_both,
                    font_size=size_both,
                    text_color_hex="#0f172a",
                    bg_color_hex="#f8fafc",
                    has_box=box_both,
                    all_pages=leg_all_pages,
                    current_page=current_page
                )
                st.session_state.pdf_bytes = new_pdf
                st.session_state.canvas_epoch += 1
                st.session_state.just_applied = True
                st.toast("¡Ambas leyendas insertadas y 100% visibles en el documento!", icon="⚡")
                st.rerun()
            else:
                st.warning("Escribe al menos una leyenda antes de insertar.")

        # BOTONES SECUNDARIOS PARA INSERTAR INDIVIDUALMENTE SI SE DESEA
        col_ind1, col_ind2 = st.columns(2)
        with col_ind1:
            if st.button("📜 Solo Leyenda 1", use_container_width=True, key="btn_insert_l1"):
                t1 = st.session_state.get("input_legend_1", "").strip()
                if t1:
                    save_pending_canvas_if_any()
                    push_history()
                    new_pdf = insert_legend_to_doc(
                        st.session_state.pdf_bytes,
                        t1,
                        pos_both,
                        size_both,
                        "#0f172a",
                        "#f8fafc",
                        box_both,
                        leg_all_pages,
                        current_page
                    )
                    st.session_state.pdf_bytes = new_pdf
                    st.session_state.canvas_epoch += 1
                    st.toast("¡Leyenda 1 insertada con éxito!", icon="📜")
                    st.rerun()
        with col_ind2:
            if st.button("📜 Solo Leyenda 2", use_container_width=True, key="btn_insert_l2"):
                t2 = st.session_state.get("input_legend_2", "").strip()
                if t2:
                    save_pending_canvas_if_any()
                    push_history()
                    new_pdf = insert_legend_to_doc(
                        st.session_state.pdf_bytes,
                        t2,
                        pos_both,
                        size_both,
                        "#0f172a",
                        "#f8fafc",
                        box_both,
                        leg_all_pages,
                        current_page
                    )
                    st.session_state.pdf_bytes = new_pdf
                    st.session_state.canvas_epoch += 1
                    st.toast("¡Leyenda 2 insertada con éxito!", icon="📜")
                    st.rerun()


