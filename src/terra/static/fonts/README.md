# Bundled fonts

These files are **self-hosted** so TERRA works on **air-gapped** networks without `fonts.googleapis.com` or `fonts.gstatic.com`.

| File | Family | Weights | Source |
|------|--------|---------|--------|
| `roboto-v51-latin-400.ttf` | Roboto | 400 | [Google Fonts — Roboto](https://fonts.google.com/specimen/Roboto) |
| `roboto-v51-latin-500.ttf` | Roboto | 500 | same |
| `roboto-v51-latin-700.ttf` | Roboto | 700 | same |
| `roboto-mono-v31-latin-400.ttf` | Roboto Mono | 400 | [Google Fonts — Roboto Mono](https://fonts.google.com/specimen/Roboto+Mono) |
| `roboto-mono-v31-latin-500.ttf` | Roboto Mono | 500 | same |
| `Datatype-wdth-wght.woff2` | Datatype | variable (wdth, wght) | [Datatype](https://github.com/franktisellano/datatype) — cellular sparklines in `/devices` grid |

**License:** Apache License 2.0 for Roboto families; **SIL Open Font License 1.1** for Datatype (see [datatype repo](https://github.com/franktisellano/datatype)).

**Subset:** Latin script only (Google’s “latin” subset). For broader Unicode coverage in offline deployments, replace these files with additional subsets from the same families and extend `static/css/terra-fonts.css` with matching `@font-face` rules.
