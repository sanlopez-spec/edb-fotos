Fotos de productos de EDB (Estación de Bebidas) para la tienda online.

- `lote1/`: fotos de Baliquors, ya cargadas en Tiendanube.
- `pedidos/*.csv`: listas de fotos a descargar (columnas `codigo,url,lote`). Al subir un CSV, la automatización
  "Procesar fotos" descarga cada imagen, la deja con fondo blanco en 1280x1280, centrada, y la guarda en `<lote>/<codigo>.jpg`,
  junto con `_informe.csv` y `_vista_previa.jpg`.
