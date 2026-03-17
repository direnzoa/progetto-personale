# Appunti veloci su CSS Grid

CSS Grid è il sistema di layout bidimensionale di CSS.

## Proprietà principali

- `grid-template-columns` — definisce le colonne
- `grid-template-rows` — definisce le righe
- `gap` — spazio tra le celle
- `grid-column` — posizione su più colonne

## Esempio base

```css
.container {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}
```

Questo crea una griglia a **3 colonne** di larghezza uguale.
