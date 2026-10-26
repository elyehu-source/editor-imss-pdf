# 🛡️ RedactaDoc Pro - Anonimización y Confidencialidad en PDFs

Una aplicación web interactiva desarrollada con **Streamlit** y **PyMuPDF (`fitz`)** para la protección de secretos, anonimización irreversible bajo normativas de privacidad (RGPD / LFPDPPP) y gestión documental segura.

---

## ✨ Características de Confidencialidad (Inspiradas en RedactaDoc Pro)

1. **⬛ Caja Negra (Blackout) — Anonimización Irreversible:**
   - Dibuja rectángulos negros sobre datos sensibles.
   - **Destrucción forense:** A diferencia de visores convencionales que solo dibujan una forma por encima, PyMuPDF elimina físicamente los caracteres, vectores y píxeles del flujo de datos del PDF. Nadie puede copiar, pegar ni recuperar el texto subyacente.
   - **Detección inteligente:** Búsqueda y tachado automático con un clic para:
     - 💳 Números de tarjetas de crédito.
     - 📧 Correos electrónicos.
     - 📞 Números telefónicos.
     - 🔤 Frases, nombres o palabras clave específicas.

2. **🛡️ Sello Confidencial:**
   - Estampa sellos con estilo notarial y marco doble oficial:
     - `CONFIDENCIAL`, `ESTRICTAMENTE SECRETO`, `NO DIVULGAR`, `COPIA NO CONTROLADA`, `RESERVADO - RGPD`, `DOCUMENTO PRIVADO` o texto personalizado.
   - Personalización de color, ángulo de rotación e inserción en esquinas o centro.

3. **🌫️ Pixelado (Censura Mosaico):**
   - Aplica un filtro de mosaico / pixelado visual sobre las áreas seleccionadas.
   - Purga paralelamente el texto subyacente para máxima seguridad.

4. **📐 Marca de Agua Diagonal:**
   - Aplica marcas de agua inclinadas a 45° a lo largo de las páginas con opacidad y color graduables.
   - Se puede aplicar a todo el documento o solo a la página actual.

5. **🔒 Descargar con Candado (Cifrado AES-256):**
   - Permite proteger el documento final con contraseña obligatoria para apertura en Adobe Acrobat o cualquier lector de PDF.

6. **⚡ Documento de Prueba Confidencial:**
   - Botón directo para cargar `documento_confidencial_prueba.pdf` con datos simulados (tarjetas, teléfonos, nombres) para probar las herramientas al instante.

7. **↩️ Deshacer (Undo):**
   - Historial de cambios para revertir la última acción si cometes un error.

---

## 🚀 Inicio Rápido

Haz doble clic en [`run.bat`](run.bat) o ejecuta en la terminal:
```bash
streamlit run app.py
```
Abre en tu navegador: **[http://localhost:8501](http://localhost:8501)**
