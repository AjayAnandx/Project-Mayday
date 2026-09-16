import os
from pathlib import Path

from backend.core.component_store import get_component_store
from backend.core.project_store import get_project_store
from backend.core.config import load_config


def store_component(name: str, code: str, description: str = "", framework: str = "react", tags: str = "", replace: bool = False) -> str:
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    store = get_component_store()
    result = store.store_component(name, code, description, framework, tag_list, replace)
    return result["message"]


def list_stored_components(framework: str = "", tag: str = "") -> str:
    store = get_component_store()
    results = store.list_components(framework or None, tag or None)
    if not results:
        return "No stored components found."
    lines = [f"Found {len(results)} components:"]
    for c in results:
        tag_str = f" [{', '.join(c['tags'])}]" if c.get("tags") else ""
        lines.append(f"  - {c['name']} ({c['framework']}) v{c['version']}{tag_str}: {c.get('description', '')}")
    return "\n".join(lines)


def get_stored_component(name: str) -> str:
    store = get_component_store()
    comp = store.get_component(name)
    if not comp:
        return f"Component '{name}' not found."
    return f"--- {comp['name']} (v{comp.get('version', 1)}) ---\n{comp['code']}"


import re as _re_slug


def _slugify_scaffold(name: str) -> str:
    # Unified with project_store._slugify: collapses non-alnum to single "-"
    s = name.lower().strip()
    s = _re_slug.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def scaffold_ui_project(name: str, description: str = "", components: str = "", animation: str = "") -> str:
    store = get_component_store()
    project_store = get_project_store()
    cfg_pdir = load_config().get("data", {}).get("projects_dir", "")
    proj_dir = Path(cfg_pdir) if cfg_pdir else Path(__file__).resolve().parent.parent.parent / "projects"
    slug = _slugify_scaffold(name)
    project_path = proj_dir / slug

    comp_list = [c.strip() for c in components.split(",") if c.strip()] if components else []
    component_codes = []
    for comp_name in comp_list:
        comp = store.get_component(comp_name)
        if comp:
            code = comp.get("code", "")
            # B2: reject stub components at scaffold time (defense in depth)
            if "will be injected here" in code or code.strip().startswith("// Source code from"):
                return f"Component '{comp_name}' is a stub (// will be injected here). Fetch real source first: getRegistryItem('{comp_name}', includeSource=true) then store_component. Aborting scaffold to keep build green."
            if len(code.strip()) < 200 or ("export" not in code and "import" not in code):
                return f"Component '{comp_name}' code looks incomplete (len={len(code)}). Re-fetch via getRegistryItem before scaffold."
            component_codes.append((comp["name"], code))

    existing_project = project_store.find_project_by_name(name)
    if not existing_project:
        project_store.create_project(name)

    os.makedirs(project_path, exist_ok=True)
    vite_dir = project_path
    all_files = []

    index_content = "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\" />\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n  <title>" + name + "</title>\n</head>\n<body>\n  <div id=\"root\"></div>\n  <script type=\"module\" src=\"/src/main.tsx\"></script>\n</body>\n</html>"
    (vite_dir / "index.html").write_text(index_content, encoding="utf-8")
    all_files.append("index.html")

    src_dir = vite_dir / "src"
    os.makedirs(src_dir, exist_ok=True)

    main_content = "import React from 'react'\nimport ReactDOM from 'react-dom/client'\nimport App from './App'\nimport './index.css'\n\nReactDOM.createRoot(document.getElementById('root')!).render(\n  <React.StrictMode>\n    <App />\n  </React.StrictMode>,\n)\n"
    (src_dir / "main.tsx").write_text(main_content, encoding="utf-8")
    all_files.append("src/main.tsx")

    # D3: include canonical @theme tokens so custom classes (bg-midnight etc.) never silently drop
    css_content = "@import \"tailwindcss\";\n@plugin \"tailwindcss-animate\";\n@theme {\n  --color-primary: #000000;\n  --color-secondary: #ffffff;\n  --color-midnight: #0A192F;\n  --color-neon-mint: #00F5D4;\n  --color-soft-slate: #E2E8F0;\n  --color-cargo-bone: #F5F5DC;\n  --color-cargo-charcoal: #1A1A1A;\n  --color-cargo-accent: #FF6B35;\n}\n"
    (src_dir / "index.css").write_text(css_content, encoding="utf-8")
    all_files.append("src/index.css")

    component_src_dir = src_dir / "components"
    os.makedirs(component_src_dir, exist_ok=True)
    written = []
    for cname, ccode in component_codes:
        (component_src_dir / f"{cname}.tsx").write_text(ccode, encoding="utf-8")
        written.append(cname)
        all_files.append(f"src/components/{cname}.tsx")

    imports = "\n".join(f"import {c} from './components/{c}'" for c in written)
    uses = "\n      ".join(f"<{c} />" for c in written)
    app_content = f"""import React from 'react'\n\n{imports}\n\nexport default function App() {{\n  return (\n    <div className="min-h-screen bg-gray-50">\n      {uses}\n    </div>\n  )\n}}\n"""
    (src_dir / "App.tsx").write_text(app_content, encoding="utf-8")
    written.append("App.tsx")
    all_files.append("src/App.tsx")

    pkg = {
        "name": slug,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {"dev": "vite", "build": "tsc --noEmit && vite build", "preview": "vite preview"},
        "dependencies": {"react": "^19.0.0", "react-dom": "^19.0.0", "tailwindcss-animate": "^1.0.0", "motion": "^11.11.17"},
        "devDependencies": {"@types/react": "^19.0.0", "@types/react-dom": "^19.0.0", "@vitejs/plugin-react": "^4.3.0", "tailwindcss": "^4.0.0", "@tailwindcss/vite": "^4.0.0", "typescript": "^5.6.0", "vite": "^6.0.0"},
    }
    (vite_dir / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")
    written.append("package.json")
    all_files.append("package.json")

    tsconfig = """{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false
  },
  "include": ["src"]
}
"""
    (vite_dir / "tsconfig.json").write_text(tsconfig, encoding="utf-8")
    written.append("tsconfig.json")
    all_files.append("tsconfig.json")

    vite_config = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    host: true,
    strictPort: false,
  },
})
"""
    (vite_dir / "vite.config.ts").write_text(vite_config, encoding="utf-8")
    written.append("vite.config.ts")
    all_files.append("vite.config.ts")

    vite_env = "/// <reference types=\"vite/client\" />\n"
    (src_dir / "vite-env.d.ts").write_text(vite_env, encoding="utf-8")
    written.append("vite-env.d.ts")
    all_files.append("src/vite-env.d.ts")

    # A1: atomic 9-file contract assert
    assert len(all_files) >= 8, f"Scaffold must create >=8 files, got {len(all_files)}: {all_files}"
    # Ensure critical invariants are present
    assert (project_path / "src" / "index.css").exists(), "src/index.css missing after scaffold"
    assert (project_path / "vite.config.ts").exists(), "vite.config.ts missing after scaffold"
    lines = [
        f"Scaffolded UI project '{name}' at {project_path}",
        f"Files created ({len(all_files)}): {', '.join(all_files)}",
    ]
    if description:
        lines.append(f"Description: {description}")
    if animation:
        lines.append(f"Animation: {animation}")
    if written:
        lines.append(f"Component files: {', '.join(cname for cname in written)}")
    lines.append(f"\nTo run: cd \"{project_path}\" && npm install && npx vite --port 5174")
    return "\n".join(lines)


import json
