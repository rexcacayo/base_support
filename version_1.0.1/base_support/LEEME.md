# Base Support 1.0.1

Complemento para Blender 4.2 a 5.x. **Analiza cómo apoya la figura** en la cama y le da un apoyo firme.

## Qué cambia en 1.0.1

- **Varias piezas seleccionadas = un conjunto** (3MF por colores): la base plana corta solo las piezas
  que llegan al corte y **todas bajan lo mismo**; la peana se une a la pieza que apoya y el resto
  queda en su sitio; el mejor apoyo gira todo el conjunto a la vez. Antes solo se tocaba una pieza
  y el resto quedaba descolocado.

## Uso (pestaña Base Support)

1. **Analizar apoyo**: superficie de contacto con la cama, número de zonas de apoyo (pies), huella, si el centro de gravedad cae dentro del apoyo (estable o se cae) y cuánto conviene recortar para tener base plana.
2. **Base plana**: corta a ras por abajo (la altura recomendada sale sola) y tapa el corte; opcionalmente la baja a Z = 0.
3. **Crear peana**: redonda, ovalada, cuadrada o hexagonal, con alto, borde y chaflán; unida a la figura (un solo sólido) o como pieza aparte.
4. **Mejor apoyo**: gira la figura para que apoye sobre su cara plana más grande en la que no vuelca.

Todo crea una copia; el original queda oculto. Colores conservados (salvo en la peana unida, que toma el color base).
